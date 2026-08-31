"""
Shared edge client logic for machine NATS edge services.

Provides the EdgeRunner class that encapsulates connect-with-retry, command
validation, handler execution, and the main loop so each machine's edge
main.py stays minimal.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable, Awaitable

from .command import (
    SDK_UPDATE_ERROR,
    build_command_catalog,
    require_command_names,
)
from .edge_nats_client import EdgeNatsClient
from .edge_updater import EdgeUpdater
from .execution_state import ExecutionState
from .models import (
    CommandResponse,
    CommandResponseStatus,
    CommandResponseCode,
    MachineState,
    NATSMessage,
)

logger = logging.getLogger(__name__)


def _normalize_handler_result(result: Any) -> dict | None:
    """
    Convert handler result to a dictionary suitable for JSON serialization.

    Handlers sometimes return enums or other non-dict types, so we normalize
    everything to a dict for JSON. Supports dict, Pydantic model (model_dump),
    objects with to_dict(), or __dict__.
    """
    if result is None:
        return None
    if isinstance(result, dict):
        return result
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if hasattr(result, "to_dict") and callable(result.to_dict):
        return result.to_dict()
    if hasattr(result, "__dict__"):
        return result.__dict__
    return {"result": result}


def _unknown_command(command_name: str) -> CommandResponse:
    logger.error("Unknown or restricted command: %s", command_name)
    return CommandResponse(
        status=CommandResponseStatus.ERROR,
        code=CommandResponseCode.UNKNOWN_COMMAND,
        message=f"Unknown or restricted command: {command_name}",
    )


def _sdk_update_required() -> CommandResponse:
    logger.error(SDK_UPDATE_ERROR)
    return CommandResponse(
        status=CommandResponseStatus.ERROR,
        code=CommandResponseCode.UNKNOWN_COMMAND,
        message=SDK_UPDATE_ERROR,
    )


def _validate_handler(
    driver: Any,
    command_name: str,
    allowed_commands: frozenset[str],
) -> tuple[Any, CommandResponse | None]:
    """
    Validate that a command is decorated with ``@command`` and callable on the driver.

    Returns (handler, error_response). handler is callable or None; error_response is None if valid.
    """
    if not allowed_commands:
        return None, _sdk_update_required()
    if command_name.startswith("_") or command_name not in allowed_commands:
        return None, _unknown_command(command_name)
    handler = getattr(driver, command_name, None)
    if not callable(handler):
        return None, _unknown_command(command_name)
    return handler, None


async def _execute_handler(
    handler: Callable[..., Any],
    params: dict | None,
    kwargs: dict | None = None,
) -> Any:
    """
    Run a synchronous handler in a thread pool so the async wrapper can be cancelled.

    Spreads params as keyword arguments. If kwargs is provided, those are merged
    in (kwargs take precedence on key conflicts).
    """
    params = params if isinstance(params, dict) else {}
    if kwargs:
        params = {**params, **kwargs}
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: handler(**params))


class EdgeRunner:
    """
    Encapsulates the edge service lifecycle: NATS connection, command
    subscription, handler dispatch, and the telemetry main loop.
    """

    def __init__(
        self,
        nats_client: EdgeNatsClient,
        machine_driver: Any,
        telemetry_handler: Callable[[], Awaitable[None]],
        state_handler: Callable[[], dict] | None = None,
    ) -> None:
        """
        Args:
            nats_client: NATS client used to subscribe to commands and publish
                state, logs, and telemetry.
            machine_driver: Driver instance exposing command handlers. Only
                methods marked with ``@command`` are advertised and executed.
                Handlers must raise to indicate failure; a ``False`` return is
                still a successful response (``{"result": false}``).
            telemetry_handler: Async callable run every second to publish
                heartbeat, position, health, etc.; no arguments.
            state_handler: Optional callable returning a dict to merge into
                the state payload (e.g. deck state); if None, only state/run_id
                are published.
        """
        self.nats_client = nats_client
        self.machine_driver = machine_driver
        self.telemetry_handler = telemetry_handler
        self.state_handler = state_handler
        self.nats_client.set_state_handler(state_handler)
        self.allowed_commands = require_command_names(machine_driver)
        logger.info(
            "Remote commands for %s: %s",
            type(machine_driver).__name__,
            ", ".join(sorted(self.allowed_commands)) or "(none)",
        )
        # Manage command execution state
        self.exec_state = ExecutionState()
        self.nats_client.set_runtime_status_handler(self.exec_state.get_runtime_status)
        # Self-update service; release driver resources before process exit
        self.updater = EdgeUpdater(
            nats_client=nats_client,
            shutdown_callback=self._driver_shutdown,
        )

    # -- public API ----------------------------------------------------------

    async def connect(self) -> None:
        """Connect to NATS with infinite retry every 5 seconds."""
        while True:
            if await self.nats_client.connect():
                logger.info("Connected to NATS servers successfully")
                return
            logger.error("Failed to connect to NATS, retrying in 5 seconds...")
            await asyncio.sleep(5)

    async def run(self) -> None:
        """Subscribe to commands and run the main loop."""
        await self._setup_subscriptions()
        # publish commands to KV store (only need to do this once on startup)
        await self._publish_commands()
        # publish initial state so CLI state lookups work before the first command
        await self._publish_state(MachineState.IDLE)
        try:
            await self._run_main_loop()
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        """Publish offline state, release driver resources, and close NATS."""
        logger.info("Shutting down edge runner...")
        try:
            await self._publish_state(MachineState.OFFLINE)
        except Exception as e:
            logger.warning("Failed to publish offline state: %s", e)
        await self._driver_shutdown()
        try:
            await self.nats_client.disconnect()
        except Exception as e:
            logger.warning("Error closing NATS connection: %s", e)
        logger.info("Edge runner shutdown complete")

    # -- subscription / connection -------------------------------------------

    async def _setup_subscriptions(self) -> None:
        await self.nats_client.subscribe_ping()
        await self.nats_client.subscribe_queue(self._handle_execute)
        await self.nats_client.subscribe_immediate(self._handle_immediate)
        await self.updater.subscribe()
    
    async def _driver_shutdown(self) -> None:
        """
        Best-effort cleanup on the machine driver before the edge exits.
        Calls `shutdown` on the driver (if defined) so serial ports, sockets,
        cameras, etc. are released for the next process.
        """
        method = getattr(self.machine_driver, "shutdown", None)
        if not callable(method):
            logger.info("Driver has no shutdown method; skipping")
            return
        try:
            logger.info("Invoking driver.shutdown() before restart")
            result = method()
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            logger.error("Driver shutdown() raised during shutdown: %s", e, exc_info=True)

    async def _ensure_connection(self) -> bool:
        if self.updater.is_restarting:
            # Update in progress; don't fight the teardown by reconnecting.
            await asyncio.sleep(0.5)
            return False
        if self.nats_client.nc is None or self.nats_client.js is None:
            logger.warning("Connection lost, attempting to reconnect...")
            if await self.nats_client.connect():
                await self._setup_subscriptions()
                logger.info("Reconnected and re-subscribed")
                await self._publish_state(MachineState.IDLE)
                return True
            logger.error("Reconnection failed, retrying in 5 seconds...")
            await asyncio.sleep(5)
            return False
        return True

    # -- command handlers ----------------------------------------------------

    async def _handle_execute(self, message: NATSMessage) -> CommandResponse:
        if message.command is None:
            logger.error("Received message with no command")
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_ERROR,
                message="No command in message",
            )

        run_id = message.header.run_id
        command_name = message.command.name
        params = message.command.params or {}
        kwargs = message.command.kwargs

        logger.info("Queue command received: run_id=%s, command_name=%s, params=%s, kwargs=%s", run_id, command_name, params, kwargs)

        if not await self.exec_state.acquire_lock(run_id):
            logger.warning(
                "Cannot execute %s (run_id: %s): another command is running or cancelled",
                command_name,
                run_id,
            )
            await self._publish_state(MachineState.ERROR)
            await self.nats_client.publish_log(
                "ERROR", f"Cannot execute {command_name}: another command is running"
            )
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_LOCKED,
                message=f"Cannot execute {command_name}: another command is running or cancelled",
            )

        try:
            await self._publish_state(MachineState.BUSY, run_id)

            handler, error_response = _validate_handler(
                self.machine_driver, command_name, self.allowed_commands
            )
            if error_response is not None:
                await self._publish_state(MachineState.ERROR, run_id)
                return error_response

            task = asyncio.create_task(_execute_handler(handler, params, kwargs))
            self.exec_state.set_current_task(task)

            try:
                handler_result = await task
            except asyncio.CancelledError:
                logger.info("Handler execution cancelled (run_id: %s)", run_id)
                return CommandResponse(
                    status=CommandResponseStatus.ERROR,
                    code=CommandResponseCode.COMMAND_CANCELLED,
                    message="Command was cancelled",
                )

            await self._publish_state(MachineState.IDLE, run_id)
            await self.nats_client.publish_log("INFO", f"Command {command_name} completed")
            return CommandResponse(
                status=CommandResponseStatus.SUCCESS,
                data=_normalize_handler_result(handler_result),
            )
        except Exception as e:
            logger.error("Execute handler error (recoverable): %s", e, exc_info=True)
            await self._publish_state(MachineState.ERROR, run_id)
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_ERROR,
                message=str(e),
            )
        finally:
            self.exec_state.release_lock()

    async def _handle_immediate(self, message: NATSMessage) -> CommandResponse:
        if message.command is None:
            logger.error("Received immediate message with no command")
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_ERROR,
                message="No command in message",
            )

        command_name = message.command.name
        params = message.command.params or {}
        kwargs = message.command.kwargs
        run_id = message.header.run_id

        try:
            logger.info("Executing immediate command: %s (run_id: %s)", command_name, run_id)
            handler, error_response = _validate_handler(
                self.machine_driver, command_name, self.allowed_commands
            )
            if error_response is not None:
                return error_response
            handler_result = await _execute_handler(handler, params, kwargs)
            logger.info("Immediate command %s completed (run_id: %s)", command_name, run_id)
            return CommandResponse(
                status=CommandResponseStatus.SUCCESS,
                data=_normalize_handler_result(handler_result),
            )
        except Exception as e:
            logger.error("Immediate command handler error: %s", e, exc_info=True)
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_ERROR,
                message=str(e),
            )

    # -- helpers -------------------------------------------------------------

    async def _publish_state(self, state: MachineState, run_id: str | None = None) -> None:
        # only default values here. EdgeNatsClient.publish_state() adds the registered state_handler fields.
        payload: dict[str, Any] = {"state": state, "run_id": run_id}
        await self.nats_client.publish_state(payload)
        
    async def _publish_commands(self) -> None:
        text, catalog = build_command_catalog(self.machine_driver)
        payload: dict[str, Any] = {"commands": text, "catalog": catalog}
        await self.nats_client.publish_commands(payload)

    async def _run_main_loop(self) -> None:
        """Never returns; runs ensure_connection + telemetry_handler every second."""
        while True:
            try:
                if not await self._ensure_connection():
                    continue
                try:
                    await self.telemetry_handler()
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error("Error publishing telemetry: %s", e, exc_info=True)
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.info("Main loop cancelled, shutting down...")
                raise
            except Exception as e:
                logger.error("Unexpected error in main loop: %s", e, exc_info=True)
                await asyncio.sleep(5)
