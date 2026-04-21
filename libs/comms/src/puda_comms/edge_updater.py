"""
Edge self-update service.

Subscribes to the `puda.{machine_id}.update` subject (core NATS, fire-and-forget)
and, on receipt of a valid NATSMessage, pulls a new version of the edge from
either a git repo or a docker image, then:

1. Publishes a response on `puda.{machine_id}.update.response`.
2. Runs an optional shutdown callback so the machine driver can release serial
   ports, sockets, cameras, etc.
3. Disconnects NATS.
4. Replaces the current process with a fresh interpreter via `os.execv`
   (``restart_mode="exec"``, the default). This works with or without an
   external supervisor and keeps Docker / systemd units alive. Set
   ``restart_mode="exit"`` to instead call ``os._exit(0)`` and rely on an
   external supervisor (docker compose `restart: unless-stopped`, systemd,
   etc.) to relaunch the process.

This module is intentionally decoupled from `EdgeNatsClient`: the client only
owns the subject constants and the NATS transport, while this module owns the
deployment / process-lifecycle concerns.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Awaitable, Callable, Literal, Optional

from nats.aio.msg import Msg

from .edge_nats_client import EdgeNatsClient
from .models import (
    CommandResponse,
    CommandResponseCode,
    CommandResponseStatus,
    MessageType,
    NATSMessage,
)

logger = logging.getLogger(__name__)

UpdateHandler = Callable[[NATSMessage], Awaitable[CommandResponse]]
ShutdownCallback = Callable[[], Awaitable[None]]
RestartMode = Literal["exec", "exit"]


class EdgeUpdater:
    """
    Self-update handler for an edge service.
    
    Composes an `EdgeNatsClient` for transport and owns the update dispatch +
    restart logic. Construct once per edge, register a shutdown callback (so
    serial/socket resources are released before exit), and call `subscribe()`
    after the NATS client is connected.
    """
    
    def __init__(
        self,
        nats_client: EdgeNatsClient,
        shutdown_callback: Optional[ShutdownCallback] = None,
        working_dir: Optional[str] = None,
        restart_mode: RestartMode = "exec",
    ) -> None:
        """
        Args:
            nats_client: Connected `EdgeNatsClient` (used for `nc.subscribe`,
                `publish_log`, `publish_alert`, and `disconnect`).
            shutdown_callback: Optional async callable invoked before the
                process exits so the driver can release resources.
            working_dir: Default working directory for git updates. Falls back
                to `os.getcwd()` when unset and not overridden in params.
            restart_mode: How to apply the update after pulling new code.
                ``"exec"`` (default) replaces the current process image with
                a fresh Python interpreter running ``sys.argv`` via
                ``os.execv``; this works anywhere (bare shell, docker,
                systemd) and does not require an external supervisor.
                ``"exit"`` calls ``os._exit(0)`` and relies on an external
                supervisor to relaunch the process.
        """
        self.nats_client = nats_client
        self._shutdown_callback = shutdown_callback
        self._working_dir = working_dir
        self._restart_mode: RestartMode = restart_mode
        self._handler: Optional[UpdateHandler] = None
        self._sub = None
        self._restarting = False

    @property
    def is_restarting(self) -> bool:
        """True once an update has been applied and the restart sequence has begun."""
        return self._restarting
    
    # -- public API ----------------------------------------------------------
    
    def set_shutdown_callback(self, callback: ShutdownCallback) -> None:
        """Register an async callback invoked before the edge exits for an update."""
        self._shutdown_callback = callback
    
    async def subscribe(self, handler: Optional[UpdateHandler] = None) -> None:
        """
        Subscribe to the update subject on core NATS.
        
        Safe to call again after reconnect; the existing subscription (if any)
        is replaced.
        
        Args:
            handler: Optional async `(NATSMessage) -> CommandResponse`. When
                None, the built-in handler is used (supports git + docker).
        """
        if self.nats_client.nc is None:
            logger.error("NATS not connected; cannot subscribe to update subject")
            return
        
        if handler is not None:
            self._handler = handler
        
        if self._sub is not None:
            try:
                await self._sub.unsubscribe()
            except Exception as e:
                logger.debug("Error unsubscribing previous update sub: %s", e)
            self._sub = None
        
        self._sub = await self.nats_client.nc.subscribe(
            subject=self.nats_client.update,
            cb=self._handle_message,
        )
        logger.info("Subscribed to update subject: %s (core NATS)", self.nats_client.update)
    
    async def unsubscribe(self) -> None:
        """Unsubscribe from the update subject."""
        if self._sub is None:
            return
        try:
            await self._sub.unsubscribe()
        except Exception as e:
            logger.debug("Error unsubscribing update sub: %s", e)
        self._sub = None
    
    # -- message handling ----------------------------------------------------
    
    async def _handle_message(self, msg: Msg) -> None:
        """Core NATS subscription callback for the update subject."""
        try:
            message = NATSMessage.model_validate_json(msg.data)
        except Exception as e:
            logger.error("Failed to parse update message: %s", e)
            return
        
        handler = self._handler or self._default_handler
        logger.info("Received update request: %s", msg.data)
        
        try:
            response = await handler(message)
        except Exception as e:
            logger.error("Update handler raised: %s", e, exc_info=True)
            response = CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_ERROR,
                message=str(e),
            )
        
        await self._publish_response(message, response)
        await self.nats_client.publish_log(
            'INFO' if response.status == CommandResponseStatus.SUCCESS else 'ERROR',
            f'Update {response.status.value}: {response.message or ""}',
        )
        
        if response.status == CommandResponseStatus.SUCCESS:
            asyncio.create_task(self._initiate_restart())
    
    async def _publish_response(self, original: NATSMessage, response: CommandResponse) -> None:
        """Publish update response as a NATSMessage on the update_response subject."""
        nc = self.nats_client.nc
        if nc is None:
            return
        try:
            response_header = original.header.model_copy(
                update={
                    'message_type': MessageType.RESPONSE,
                    'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                }
            )
            response_message = original.model_copy(
                update={'header': response_header, 'response': response}
            )
            await nc.publish(
                subject=self.nats_client.update_response,
                payload=response_message.model_dump_json().encode(),
            )
            logger.info("Published update response: %s", response.status)
        except Exception as e:
            logger.error("Error publishing update response: %s", e)
    
    # -- default handler (git / docker) --------------------------------------
    
    async def _default_handler(self, message: NATSMessage) -> CommandResponse:
        """
        Default update handler: pulls a new version from git or docker based on params.
        
        Expected `command.params`:
            source_type: "git" | "docker"
            ref: git URL (git) or image:tag (docker)
            branch: optional branch name (git only, defaults to "main")
            working_dir: optional path for git repo (defaults to constructor
                `working_dir` or `os.getcwd()`)
        """
        if message.command is None:
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_ERROR,
                message='Update message has no command payload',
            )
        
        params = message.command.params or {}
        source_type = str(params.get('source_type', '')).lower()
        ref = params.get('ref')
        
        if not ref:
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_ERROR,
                message='Update params missing required "ref"',
            )
        
        try:
            if source_type == 'git':
                return await self._handle_git(ref, params)
            if source_type == 'docker':
                return await self._handle_docker(ref)
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.UNKNOWN_COMMAND,
                message=f'Unknown source_type: {source_type!r}. Expected "git" or "docker".',
            )
        except FileNotFoundError as e:
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_ERROR,
                message=f'Required executable not found: {e}',
            )
        except Exception as e:
            logger.error("Unexpected error in default update handler: %s", e, exc_info=True)
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_ERROR,
                message=str(e),
            )
    
    async def _handle_git(self, ref: str, params: dict) -> CommandResponse:
        branch = params.get('branch') or 'main'
        working_dir = params.get('working_dir') or self._working_dir or os.getcwd()
        logger.info("Running git update: ref=%s, branch=%s, cwd=%s", ref, branch, working_dir)
        
        code, out, err = await self._run_subprocess('git', 'fetch', '--all', cwd=working_dir)
        if code != 0:
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_ERROR,
                message=f'git fetch failed: {err.strip() or out.strip()}',
            )
        
        code, out, err = await self._run_subprocess(
            'git', 'reset', '--hard', f'origin/{branch}', cwd=working_dir
        )
        if code != 0:
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_ERROR,
                message=f'git reset failed: {err.strip() or out.strip()}',
            )
        
        sync_code, sync_out, sync_err = await self._run_subprocess('uv', 'sync', cwd=working_dir)
        sync_msg = ''
        if sync_code != 0:
            sync_msg = f' (uv sync warning: {sync_err.strip() or sync_out.strip()})'
            logger.warning("uv sync failed: %s", sync_err.strip() or sync_out.strip())
        
        return CommandResponse(
            status=CommandResponseStatus.SUCCESS,
            message=f'Git updated to origin/{branch}{sync_msg}',
            data={'source_type': 'git', 'ref': ref, 'branch': branch, 'working_dir': working_dir},
        )
    
    async def _handle_docker(self, ref: str) -> CommandResponse:
        logger.info("Running docker pull: image=%s", ref)
        code, out, err = await self._run_subprocess('docker', 'pull', ref)
        if code != 0:
            return CommandResponse(
                status=CommandResponseStatus.ERROR,
                code=CommandResponseCode.EXECUTION_ERROR,
                message=(
                    f'docker pull failed: {err.strip() or out.strip()}. '
                    'Ensure the docker CLI is available and the docker socket is accessible.'
                ),
            )
        return CommandResponse(
            status=CommandResponseStatus.SUCCESS,
            message=f'Docker image {ref} pulled',
            data={'source_type': 'docker', 'ref': ref},
        )
    
    # -- restart -------------------------------------------------------------
    
    async def _initiate_restart(self) -> None:
        """
        Release resources and restart the process with the newly pulled
        code/image.

        ``restart_mode="exec"`` replaces the current process image with a
        fresh Python interpreter running ``sys.argv`` (works everywhere,
        no supervisor required). ``restart_mode="exit"`` hard-exits and
        relies on an external supervisor to relaunch.
        """
        self._restarting = True

        try:
            await self.nats_client.publish_alert(
                alert_type='update_restart',
                severity='info',
                msg='Edge restarting to apply update',
            )
        except Exception as e:
            logger.warning("Failed to publish restart alert: %s", e)

        if self._shutdown_callback is not None:
            try:
                logger.info("Running shutdown callback before restart")
                await self._shutdown_callback()
            except Exception as e:
                logger.error("Shutdown callback failed: %s", e, exc_info=True)

        try:
            await self.nats_client.disconnect()
        except Exception as e:
            logger.warning("Error during NATS disconnect on restart: %s", e)

        if self._restart_mode == "exit":
            logger.warning(
                "Exiting process (restart_mode='exit'); supervisor must relaunch"
            )
            os._exit(0)

        executable = sys.executable or 'python3'
        argv = [executable, *sys.argv]
        logger.warning(
            "Re-executing process to apply update: %s", ' '.join(argv)
        )
        try:
            os.execv(executable, argv)
        except Exception as e:
            logger.error(
                "os.execv failed (%s); falling back to os._exit(0)", e, exc_info=True
            )
            os._exit(0)
    
    # -- helpers -------------------------------------------------------------
    
    @staticmethod
    async def _run_subprocess(*args: str, cwd: Optional[str] = None) -> tuple[int, str, str]:
        """Run a subprocess asynchronously and capture output. Returns (returncode, stdout, stderr)."""
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode(errors='replace') if stdout_bytes else ''
        stderr = stderr_bytes.decode(errors='replace') if stderr_bytes else ''
        return proc.returncode or 0, stdout, stderr
