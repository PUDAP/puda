"""Command lifecycle for the machine edge: parse, validate, execute, ack, respond."""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Awaitable, Callable

from nats.aio.msg import Msg

from .models import (
    CommandResponse,
    CommandResponseCode,
    CommandResponseStatus,
    ImmediateCommand,
    MachineState,
    MessageType,
    NATSMessage,
    _get_current_timestamp,
)
from .run_manager import RunManager

if TYPE_CHECKING:
    from .edge_nats_client import EdgeNatsClient

logger = logging.getLogger(__name__)

KEEP_ALIVE_INTERVAL = 25  # seconds

CommandHandler = Callable[[NATSMessage], Awaitable[CommandResponse]]


def _ok() -> CommandResponse:
    return CommandResponse(status=CommandResponseStatus.SUCCESS)


def _error(code: CommandResponseCode, message: str) -> CommandResponse:
    return CommandResponse(
        status=CommandResponseStatus.ERROR,
        code=code,
        message=message,
    )


class CommandProcessor:
    """Owns run/pause state and the queue + immediate command protocol.

    Transport (JetStream, response subjects, KV state) stays on EdgeNatsClient.
    """

    def __init__(self, client: EdgeNatsClient):
        self._client = client
        self.run_manager = RunManager(machine_id=client.machine_id)
        self._pause_lock = asyncio.Lock()
        self._is_paused = False

    @asynccontextmanager
    async def _keep_message_alive(self, msg: Msg, interval: int = KEEP_ALIVE_INTERVAL):
        """Reset the JetStream redelivery timer while a handler runs."""
        async def _heartbeat():
            while True:
                await asyncio.sleep(interval)
                try:
                    await msg.in_progress()
                    logger.debug("Reset redelivery timer via keep-alive")
                except Exception:
                    break

        task = asyncio.create_task(_heartbeat())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _publish_command_response(
        self,
        msg: Msg,
        response: CommandResponse,
        subject: str,
    ) -> None:
        """Publish a RESPONSE-typed copy of the original command to JetStream."""
        js = self._client.js
        if not js:
            return
        try:
            original = NATSMessage.model_validate_json(msg.data)
            header = original.header.model_copy(
                update={
                    "message_type": MessageType.RESPONSE,
                    "timestamp": _get_current_timestamp(),
                }
            )
            payload = original.model_copy(update={"header": header, "response": response})
            await js.publish(subject=subject, payload=payload.model_dump_json().encode())
            logger.info("Published command response to JetStream: %s", payload.model_dump_json())
        except Exception as e:
            logger.error("Error publishing command response: %s", e)

    async def _respond_queue(
        self,
        msg: Msg,
        response: CommandResponse,
        *,
        ack: bool = False,
        term: bool = False,
        complete_run_id: str | None = None,
    ) -> None:
        if term:
            await msg.term()
        elif ack:
            await msg.ack()
        if complete_run_id is not None:
            await self.run_manager.complete_run(complete_run_id)
        await self._publish_command_response(msg, response, self._client.response_queue)

    async def process_queue(self, msg: Msg, handler: CommandHandler) -> None:
        """Parse -> validate -> handle -> ack/nak/term a queued command."""
        run_id = None
        step_number = None
        command = None
        try:
            message = NATSMessage.model_validate_json(msg.data)
            run_id = message.header.run_id
            step_number = message.command.step_number if message.command else None
            command = message.command.name if message.command else None

            async with self._pause_lock:
                if self._is_paused:
                    await self._respond_queue(
                        msg,
                        _error(CommandResponseCode.MACHINE_PAUSED, "Machine paused"),
                    )
                    return

            if run_id is None:
                await self._respond_queue(
                    msg,
                    _error(CommandResponseCode.EXECUTION_ERROR, "Command requires run_id"),
                    ack=True,
                )
                return

            if not await self.run_manager.validate_run_id(run_id):
                if self.run_manager.get_active_run_id() is None:
                    err = _error(
                        CommandResponseCode.RUN_ID_MISMATCH,
                        "Send START command to start a run before sending commands",
                    )
                else:
                    err = _error(
                        CommandResponseCode.RUN_ID_MISMATCH,
                        f"Run ID mismatch: expected active run, got {run_id}",
                    )
                await self._respond_queue(msg, err, ack=True)
                return

            async with self._keep_message_alive(msg):
                response = await handler(message)

            if response.status == CommandResponseStatus.SUCCESS:
                await msg.ack()
            elif response.status == CommandResponseStatus.ERROR:
                await self.run_manager.complete_run(run_id)
                await msg.term()
            await self._publish_command_response(msg, response, self._client.response_queue)

        except asyncio.CancelledError:
            logger.info(
                "Handler execution cancelled: run_id=%s, step_number=%s, command=%s",
                run_id, step_number, command,
            )
            await self._respond_queue(
                msg,
                _error(CommandResponseCode.COMMAND_CANCELLED, "Command cancelled"),
                ack=True,
                complete_run_id=run_id,
            )
        except json.JSONDecodeError as e:
            logger.error("JSON Decode Error. Terminating message.")
            await self._respond_queue(
                msg,
                _error(CommandResponseCode.JSON_DECODE_ERROR, f"JSON decode error: {e}"),
                term=True,
                complete_run_id=run_id,
            )
        except Exception as e:
            logger.error("Handler failed (terminating message): %s", e)
            await self._respond_queue(
                msg,
                _error(CommandResponseCode.EXECUTION_ERROR, str(e)),
                term=True,
                complete_run_id=run_id,
            )

    async def process_immediate(self, msg: Msg, handler: CommandHandler) -> None:
        """Process immediate commands (start, pause, cancel, resume, etc.)."""
        try:
            message = NATSMessage.model_validate_json(msg.data)
            await msg.ack()
            if message.command is None:
                logger.error("Received message with no command")
                return

            command_name = message.command.name.lower()
            run_id = message.header.run_id
            response = await self._dispatch_immediate(command_name, run_id, message, handler)
            await self._publish_command_response(msg, response, self._client.response_immediate)
        except json.JSONDecodeError as e:
            logger.error("JSON Decode Error in immediate command: %s", e)
            await self._fail_immediate(msg, CommandResponseCode.JSON_DECODE_ERROR, f"JSON decode error: {e}")
        except Exception as e:
            logger.error("Error processing immediate command: %s", e)
            await self._fail_immediate(msg, CommandResponseCode.EXECUTION_ERROR, str(e))

    async def _fail_immediate(self, msg: Msg, code: CommandResponseCode, message: str) -> None:
        await self._publish_command_response(
            msg, _error(code, message), self._client.response_immediate
        )
        await self._client.publish_state({"state": MachineState.ERROR, "run_id": None})

    async def _dispatch_immediate(
        self,
        command_name: str,
        run_id: str | None,
        message: NATSMessage,
        handler: CommandHandler,
    ) -> CommandResponse:
        match command_name:
            case ImmediateCommand.START:
                return await self._immediate_start(run_id)
            case ImmediateCommand.COMPLETE:
                return await self._immediate_complete(run_id)
            case ImmediateCommand.PAUSE:
                return await self._immediate_pause(message, handler)
            case ImmediateCommand.RESUME:
                return await self._immediate_resume(handler, message)
            case ImmediateCommand.RESET:
                return await self._immediate_reset(handler, message)
            case ImmediateCommand.CANCEL:
                return await self._immediate_cancel(run_id, handler, message)
            case _:
                return _error(
                    CommandResponseCode.UNKNOWN_COMMAND,
                    f"Unknown immediate command: {command_name}",
                )

    async def _immediate_start(self, run_id: str | None) -> CommandResponse:
        if not run_id:
            return _error(CommandResponseCode.MISSING_RUN_ID, "START command requires RUN_ID")
        if not await self.run_manager.start_run(run_id):
            return _error(
                CommandResponseCode.RUN_ID_MISMATCH,
                f"cannot start, {self.run_manager.get_active_run_id()} is currently running",
            )
        await self._client.publish_state({"state": MachineState.IDLE, "run_id": run_id})
        return _ok()

    async def _immediate_complete(self, run_id: str | None) -> CommandResponse:
        if not run_id:
            return _error(CommandResponseCode.MISSING_RUN_ID, "COMPLETE command requires RUN_ID")
        if not await self.run_manager.complete_run(run_id):
            return _error(CommandResponseCode.RUN_ID_MISMATCH, f"Run {run_id} not active")
        await self._client.publish_state({"state": MachineState.IDLE, "run_id": None})
        return _ok()

    async def _immediate_pause(self, message: NATSMessage, handler: CommandHandler) -> CommandResponse:
        async with self._pause_lock:
            if not self._is_paused:
                self._is_paused = True
                logger.info("Queue paused")
                await self._client.publish_state(
                    {"state": MachineState.PAUSED, "run_id": message.header.run_id}
                )
        return await handler(message)

    async def _immediate_resume(self, handler: CommandHandler, message: NATSMessage) -> CommandResponse:
        async with self._pause_lock:
            if self._is_paused:
                self._is_paused = False
                logger.info("Queue resumed")
                await self._client.publish_state({"state": MachineState.IDLE, "run_id": None})
        return await handler(message)

    async def _immediate_reset(self, handler: CommandHandler, message: NATSMessage) -> CommandResponse:
        await self.run_manager.clear_run()
        logger.info("Resetting machine")
        response = await handler(message)
        if response.status == CommandResponseStatus.SUCCESS:
            await self._client.publish_state({"state": MachineState.IDLE, "run_id": None})
            logger.info("Machine reset")
        else:
            await self._client.publish_state({"state": MachineState.ERROR, "run_id": None})
            logger.error("Machine reset failed: %s", response.message)
        return response

    async def _immediate_cancel(
        self,
        run_id: str | None,
        handler: CommandHandler,
        message: NATSMessage,
    ) -> CommandResponse:
        if not run_id:
            return _error(CommandResponseCode.MISSING_RUN_ID, "CANCEL command requires RUN_ID")
        logger.info("Cancelling all commands with run_id: %s", run_id)
        await self.run_manager.complete_run(run_id)
        await self._client.publish_state({"state": MachineState.IDLE, "run_id": None})
        return await handler(message)
