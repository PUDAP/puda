"""Command lifecycle for the machine edge: parse, validate, execute, ack, respond."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Awaitable, Callable

from nats.aio.msg import Msg
from pydantic import ValidationError

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
RESULT_MEMORY = 64  # queued results remembered by stream sequence


def _stream_seq(msg: Msg) -> int | None:
    """JetStream stream sequence of a delivered message, if known."""
    try:
        return int(msg.metadata.sequence.stream)
    except Exception:
        return None


def _num_delivered(msg: Msg) -> int:
    """How many times JetStream has delivered this message (1 if unknown)."""
    try:
        return int(msg.metadata.num_delivered)
    except Exception:
        return 1

CommandHandler = Callable[[NATSMessage], Awaitable[CommandResponse]]


def _ok() -> CommandResponse:
    return CommandResponse(status=CommandResponseStatus.SUCCESS)


def _error(code: CommandResponseCode, message: str, data: dict | None = None) -> CommandResponse:
    return CommandResponse(
        status=CommandResponseStatus.ERROR,
        code=code,
        message=message,
        data=data,
    )


class CommandProcessor:
    """Owns run/pause state and the queue + immediate command protocol.

    Transport (JetStream, response subjects, KV state) stays on EdgeNatsClient.
    """

    def __init__(self, client: EdgeNatsClient):
        self._client = client
        self.run_manager = RunManager(machine_id=client.machine_id)
        self._pause_lock = asyncio.Lock()
        # Immediate verbs other than estop run one at a time, in arrival order.
        self._immediate_lock = asyncio.Lock()
        # Results of recent queued commands by stream sequence, so a
        # redelivery is answered again instead of run again.
        self._results: dict[int, tuple[str | None, bool]] = {}
        # Stream sequences this edge NAKed on pause; their redelivery may run.
        self._nacked: set[int] = set()
        self._is_paused = False
        # Set by ESTOP, cleared only by a successful RESET.
        self._is_estopped = False
        # Set while queued commands may start: not paused, or estopped (so held
        # and pulled commands are discarded instead of waiting forever).
        self._runnable = asyncio.Event()
        self._runnable.set()
        # The queued command currently executing (name, step_number, run_id,
        # started, aborted), for COMPLETE refusals and COMPLETE --abort.
        self._running: dict | None = None

    @property
    def is_estopped(self) -> bool:
        return self._is_estopped

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    def _update_runnable(self) -> None:
        if self._is_paused and not self._is_estopped:
            self._runnable.clear()
        else:
            self._runnable.set()

    async def wait_until_runnable(self) -> None:
        """Block the queue pull loop while paused; pause holds the queue."""
        await self._runnable.wait()

    @asynccontextmanager
    async def _keep_message_alive(self, msg: Msg, interval: int = KEEP_ALIVE_INTERVAL):
        """Reset the JetStream redelivery timer while a handler runs."""
        async def _heartbeat():
            while True:
                await asyncio.sleep(interval)
                try:
                    await msg.in_progress()
                    logger.debug("Reset redelivery timer via keep-alive")
                except Exception as e:
                    # Disconnected: keep trying, the connection may come back.
                    logger.debug("Keep-alive failed (%s); retrying", e)

        task = asyncio.create_task(_heartbeat())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _response_text(self, msg: Msg, response: CommandResponse, *, any_envelope: bool = False) -> str | None:
        """The RESPONSE-typed copy of the command in *msg*, as JSON text.

        Returns None when the payload cannot be opened, or (unless
        *any_envelope*) when a malformed envelope cannot be correlated.
        """
        try:
            plain = self._client.encryption.open_payload(msg.subject, msg.data)
        except Exception as e:
            logger.error("Cannot open command payload; no response sent: %s", e)
            return None
        try:
            original = NATSMessage.model_validate_json(plain)
        except ValidationError:
            text = self._correlatable_response(plain, response)
            if text is None and any_envelope:
                text = json.dumps({"response": response.model_dump(mode="json")})
            if text is None:
                logger.error("Malformed command cannot be correlated; no response sent")
            return text
        header = original.header.model_copy(
            update={"message_type": MessageType.RESPONSE, "timestamp": _get_current_timestamp()}
        )
        return original.model_copy(update={"header": header, "response": response}).model_dump_json()

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
        text = self._response_text(msg, response)
        if text is None:
            return
        try:
            await js.publish(subject=subject, payload=self._client.encryption.seal(subject, text.encode()))
            logger.info("Published command response to JetStream: %s", text)
        except Exception as e:
            logger.error("Error publishing command response: %s", e)

    async def _publish_queue_result(self, msg: Msg, text: str) -> None:
        """Publish a queued command's response and wait until JetStream stores it.

        Called before the message is acked, so a result is never lost: while
        the broker is unreachable this retries, keeping the message alive, until
        it succeeds. Nats-Msg-Id makes a republished result a duplicate that
        JetStream drops.
        """
        subject = self._client.response_queue
        seq = _stream_seq(msg)
        headers = {"Nats-Msg-Id": f"{self._client.machine_id}:{seq}"} if seq is not None else None
        payload = self._client.encryption.seal(subject, text.encode())
        delay = 0.5
        async with self._keep_message_alive(msg):
            while True:
                js = self._client.js  # None while reconnecting
                if js is not None:
                    try:
                        await js.publish(subject=subject, payload=payload, headers=headers)
                        logger.info("Published command response to JetStream: %s", text)
                        return
                    except Exception as e:
                        logger.warning("Response not stored yet (%s); retrying in %.1fs", e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 5.0)

    async def _reply_immediate(self, msg: Msg, response: CommandResponse) -> None:
        """Answer an immediate request on its reply inbox, then record a copy.

        The reply is what the client waits for. The copy on the
        RESPONSE_IMMEDIATE stream is history for loggers; it is published
        after the reply so it never delays it.
        """
        text = self._response_text(msg, response, any_envelope=True)
        if text is None:
            return
        # Only a full envelope is recorded; loggers and history need the
        # correlation fields.
        record = '"header"' in text
        if msg.reply:
            try:
                await msg.respond(self._client.encryption.seal(msg.reply, text.encode()))
            except Exception as e:
                logger.error("Error replying to immediate command: %s", e)
        js = self._client.js
        subject = self._client.response_immediate
        if js is not None and record:
            try:
                await js.publish(subject=subject, payload=self._client.encryption.seal(subject, text.encode()))
            except Exception as e:
                logger.warning("Could not record immediate response on %s: %s", subject, e)
        logger.info("Answered immediate command: %s", text)

    @staticmethod
    def _correlatable_response(plain: bytes, response: CommandResponse) -> str | None:
        """Echo an envelope that failed validation, if clients can still match it.

        Clients correlate on (run_id, step_number, machine_id), so a response is
        only useful when the payload is a JSON object whose header and command
        carry those fields with usable types.
        """
        try:
            original = json.loads(plain)
        except ValueError:
            return None
        if not isinstance(original, dict):
            return None
        header, command = original.get("header"), original.get("command")
        if not isinstance(header, dict) or not isinstance(command, dict):
            return None
        if not isinstance(header.get("machine_id"), str):
            return None
        if not (header.get("run_id") is None or isinstance(header.get("run_id"), str)):
            return None
        step = command.get("step_number")
        if not isinstance(step, int) or isinstance(step, bool):
            return None
        header = {**header, "message_type": MessageType.RESPONSE.value,
                  "timestamp": _get_current_timestamp()}
        return json.dumps({**original, "header": header,
                           "response": response.model_dump(mode="json")})

    @staticmethod
    def _invalid_envelope(error: ValidationError) -> CommandResponse:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in item['loc']) or '<root>'}: {item['msg']}"
            for item in error.errors()[:5]
        )
        return _error(CommandResponseCode.EXECUTION_ERROR, f"Invalid command envelope: {problems}")

    @staticmethod
    async def _nak_confirmed(msg: Msg) -> None:
        """NAK and wait for the server to confirm it.

        A plain (fire-and-forget) NAK can reach the server after the next pull,
        which then gets a newer command first. A confirmed NAK puts the message
        back at the head of the redelivery queue before anything else is pulled.
        """
        client = getattr(msg, "_client", None)
        if client is not None and msg.reply:
            try:
                await client.request(msg.reply, b"-NAK", timeout=5)
                return
            except Exception as e:
                logger.warning("Confirmed NAK failed (%s); sending a plain NAK", e)
        await msg.nak()

    async def _respond_queue(
        self,
        msg: Msg,
        response: CommandResponse,
        *,
        ack: bool = False,
        term: bool = False,
        complete_run_id: str | None = None,
    ) -> None:
        """Answer a queued command: store the result first, then ack or term.

        If the edge dies in between, the message is redelivered; the result
        record, or the redelivery rule in process_queue, stops it running again.
        """
        if complete_run_id is not None:
            await self.run_manager.complete_run(complete_run_id)
        text = self._response_text(msg, response)
        if text is not None:
            await self._publish_queue_result(msg, text)
        self._remember_result(msg, text, term)
        if term:
            await msg.term()
        elif ack:
            await msg.ack()

    def _remember_result(self, msg: Msg, text: str | None, term: bool) -> None:
        seq = _stream_seq(msg)
        if seq is None:
            return
        self._results[seq] = (text, term)
        while len(self._results) > RESULT_MEMORY:
            self._results.pop(next(iter(self._results)))

    async def process_queue(self, msg: Msg, handler: CommandHandler) -> None:
        """Parse -> validate -> handle -> ack/nak/term a queued command."""
        run_id = None
        step_number = None
        command = None
        seq = _stream_seq(msg)
        if seq is not None and seq in self._results:
            # Redelivered after its result was stored but before the ack took
            # effect: send the same result again (a duplicate JetStream drops)
            # and settle it. It never runs twice.
            text, term = self._results[seq]
            logger.info("Redelivered command (stream seq %s) already answered; not running it again", seq)
            if text is not None:
                await self._publish_queue_result(msg, text)
            await (msg.term() if term else msg.ack())
            return
        try:
            try:
                message = NATSMessage.model_validate_json(
                    self._client.encryption.open_payload(msg.subject, msg.data)
                )
            except ValidationError as e:
                # Malformed: never redeliver, leave the run alone, and answer
                # if the client can still correlate the response.
                logger.error("Malformed queued command (terminating): %s", e)
                await self._respond_queue(msg, self._invalid_envelope(e), term=True)
                return
            run_id = message.header.run_id
            step_number = message.command.step_number if message.command else None
            command = message.command.name if message.command else None

            if self._is_estopped:
                # Discard, do not redeliver: work queued before an estop must
                # not run after the reset.
                await self._respond_queue(
                    msg,
                    _error(
                        CommandResponseCode.MACHINE_ESTOPPED,
                        "Machine emergency stopped; send reset before queuing commands",
                    ),
                    term=True,
                )
                return
            if _num_delivered(msg) > 1 and seq not in self._nacked:
                # Delivered before, with no result on record: this edge lost
                # track of it (it restarted while handling it). The hardware
                # may have acted, so it must not run again.
                logger.error("Redelivered command %s (step %s) has no result; not running it again",
                             command, step_number)
                await self._respond_queue(
                    msg,
                    _error(
                        CommandResponseCode.EXECUTION_ERROR,
                        "Redelivered without a result: the edge restarted while handling this "
                        "command. Outcome unknown; it was not run again",
                    ),
                    term=True,
                    complete_run_id=run_id if self.run_manager.get_active_run_id() == run_id else None,
                )
                return
            self._nacked.discard(seq)
            if self._is_paused:
                # Delivered just as the queue was paused: give it back to the
                # stream unanswered. The pull loop waits for resume, and
                # JetStream redelivers it before newer commands.
                logger.info("Queue paused: returning %s (step %s) to the stream", command, step_number)
                if seq is not None:
                    self._nacked.add(seq)
                await self._nak_confirmed(msg)
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

            running = {"name": command, "step_number": step_number, "run_id": run_id,
                       "started": time.monotonic(), "stopped_by": None}
            self._running = running
            try:
                async with self._keep_message_alive(msg):
                    response = await handler(message)
            finally:
                self._running = None
            if running["stopped_by"] is not None:
                # Answered only now that the driver call has returned, so the
                # next queued command can never overlap it.
                response = _error(
                    CommandResponseCode.COMMAND_CANCELLED,
                    f"Stopped by {running['stopped_by']}",
                    response.data,
                )

            failed = response.status == CommandResponseStatus.ERROR
            await self._respond_queue(
                msg, response, ack=not failed, term=failed, complete_run_id=run_id if failed else None
            )

        except asyncio.CancelledError:
            logger.info(
                "Handler execution cancelled: run_id=%s, step_number=%s, command=%s",
                run_id, step_number, command,
            )
            # Edge shutting down: try briefly to store the result, then stop.
            try:
                await asyncio.wait_for(
                    self._respond_queue(
                        msg,
                        _error(CommandResponseCode.COMMAND_CANCELLED, "Command cancelled"),
                        ack=True,
                        complete_run_id=run_id,
                    ),
                    timeout=5,
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.warning("Shutdown: result of %s (step %s) not stored", command, step_number)
            raise
        except Exception as e:
            logger.error("Handler failed (terminating message): %s", e)
            await self._respond_queue(
                msg,
                _error(CommandResponseCode.EXECUTION_ERROR, str(e)),
                term=True,
                complete_run_id=run_id,
            )

    async def process_immediate(self, msg: Msg, handler: CommandHandler) -> None:
        """Answer an immediate request (start, complete, pause, resume, reset, estop).

        Immediate commands are core NATS request/reply: nothing is stored, so a
        command sent while the edge is offline never arrives (the client sees
        no responders) and nothing stale can replay. Every request with a reply
        inbox gets exactly one reply, including malformed ones.

        Each request runs in its own task. ``estop`` is handled at once; the
        other verbs take turns in arrival order, so a slow driver hook never
        delays an emergency stop.
        """
        try:
            try:
                message = NATSMessage.model_validate_json(
                    self._client.encryption.open_payload(msg.subject, msg.data)
                )
            except ValidationError as e:
                # Malformed: nothing runs, machine state is unchanged.
                logger.error("Malformed immediate command: %s", e)
                await self._reply_immediate(msg, self._invalid_envelope(e))
                return
            if message.command is None:
                logger.error("Received message with no command")
                await self._reply_immediate(
                    msg, _error(CommandResponseCode.EXECUTION_ERROR, "Invalid command envelope: command: missing")
                )
                return
            command_name = message.command.name.lower()
            if command_name == ImmediateCommand.ESTOP:
                response = await self._dispatch_immediate(command_name, message.header.run_id, message, handler)
            else:
                async with self._immediate_lock:
                    response = await self._dispatch_immediate(command_name, message.header.run_id, message, handler)
            await self._reply_immediate(msg, response)
        except Exception as e:
            logger.error("Error processing immediate command: %s", e)
            await self._reply_immediate(msg, _error(CommandResponseCode.EXECUTION_ERROR, str(e)))
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
                return await self._immediate_complete(run_id, message, handler)
            case ImmediateCommand.PAUSE:
                return await self._immediate_pause(message, handler)
            case ImmediateCommand.RESUME:
                return await self._immediate_resume(handler, message)
            case ImmediateCommand.RESET:
                return await self._immediate_reset(handler, message)
            case ImmediateCommand.ESTOP:
                return await self._immediate_estop(handler, message)
            case _:
                return _error(
                    CommandResponseCode.UNKNOWN_COMMAND,
                    f"Unknown immediate command: {command_name}",
                )

    def _estopped_error(self, command: str) -> CommandResponse:
        return _error(
            CommandResponseCode.MACHINE_ESTOPPED,
            f"Machine emergency stopped; send reset before {command}",
        )

    async def _immediate_start(self, run_id: str | None) -> CommandResponse:
        if self._is_estopped:
            return self._estopped_error("start")
        if not run_id:
            return _error(CommandResponseCode.MISSING_RUN_ID, "START command requires RUN_ID")
        if self.run_manager.get_active_run_id() == run_id:
            # Retrying a start whose reply was lost is safe.
            return CommandResponse(status=CommandResponseStatus.SUCCESS, data={"already_started": True})
        if not await self.run_manager.start_run(run_id):
            return _error(
                CommandResponseCode.RUN_ID_MISMATCH,
                f"cannot start, {self.run_manager.get_active_run_id()} is currently running",
            )
        await self._client.publish_state({"state": MachineState.IDLE, "run_id": run_id})
        return _ok()

    @staticmethod
    def _describe_running(running: dict) -> dict:
        return {
            "name": running["name"],
            "step_number": running["step_number"],
            "elapsed_s": round(time.monotonic() - running["started"], 1),
        }

    async def _queued_count(self) -> int | None:
        """Queued commands waiting behind the running one (None if unknown)."""
        counter = getattr(self._client, "pending_queue_count", None)
        if counter is None:
            return None
        try:
            count = await counter()
        except Exception:
            return None
        return max(0, count - (1 if self._running is not None else 0))

    async def _immediate_complete(
        self, run_id: str | None, message: NATSMessage, handler: CommandHandler
    ) -> CommandResponse:
        """End the run. Refused while one of its commands runs unless params.abort.

        With ``abort`` the run ends at once: the running command is marked
        stopped, *handler* starts the driver ``abort`` without waiting for it, and
        the command is answered ``COMMAND_CANCELLED`` when its driver call
        returns. Repeating COMPLETE for a run that already ended succeeds with
        ``already_completed``.
        """
        if not run_id:
            return _error(CommandResponseCode.MISSING_RUN_ID, "COMPLETE command requires RUN_ID")
        params = (message.command.params if message.command else None) or {}
        abort = params.get("abort") is True
        if self.run_manager.get_active_run_id() != run_id:
            if self.run_manager.was_ended(run_id):
                return CommandResponse(
                    status=CommandResponseStatus.SUCCESS, data={"already_completed": True}
                )
            return _error(CommandResponseCode.RUN_ID_MISMATCH, f"Run {run_id} not active")

        running = self._running
        if running is not None and running["run_id"] != run_id:
            running = None
        if running is not None and not abort:
            return _error(
                CommandResponseCode.EXECUTION_LOCKED,
                f"Command {running['name']} (step {running['step_number']}) is running; "
                "wait for it to finish, or complete with abort to stop it",
                {"running": self._describe_running(running), "queued": await self._queued_count()},
            )

        data: dict | None = None
        if abort:
            data = {"aborted": None, "driver_abort": False, "queued": await self._queued_count()}
            if running is not None:
                running["stopped_by"] = "complete --abort"
                data["aborted"] = self._describe_running(running)
                stop = await handler(message)
                data["driver_abort"] = bool((stop.data or {}).get("driver_abort"))

        # An estop handled meanwhile may already have ended the run.
        if self.run_manager.get_active_run_id() == run_id:
            await self.run_manager.complete_run(run_id)
        # busy until an aborted driver call actually returns
        state = MachineState.BUSY if self._running is not None else MachineState.IDLE
        await self._client.publish_state({"state": state, "run_id": None})
        return CommandResponse(status=CommandResponseStatus.SUCCESS, data=data)

    async def _immediate_pause(self, message: NATSMessage, handler: CommandHandler) -> CommandResponse:
        async with self._pause_lock:
            if not self._is_paused:
                self._is_paused = True
                self._update_runnable()
                logger.info("Queue paused")
                await self._client.publish_state(
                    {"state": MachineState.PAUSED, "run_id": self.run_manager.get_active_run_id()}
                )
        return await handler(message)

    async def _immediate_resume(self, handler: CommandHandler, message: NATSMessage) -> CommandResponse:
        if self._is_estopped:
            return self._estopped_error("resume")
        async with self._pause_lock:
            if self._is_paused:
                self._is_paused = False
                self._update_runnable()
                logger.info("Queue resumed")
                state = MachineState.BUSY if self._running is not None else MachineState.IDLE
                await self._client.publish_state(
                    {"state": state, "run_id": self.run_manager.get_active_run_id()}
                )
        return await handler(message)

    async def _immediate_reset(self, handler: CommandHandler, message: NATSMessage) -> CommandResponse:
        await self.run_manager.clear_run()
        logger.info("Resetting machine")
        response = await handler(message)
        if (
            response.status == CommandResponseStatus.ERROR
            and response.code == CommandResponseCode.UNKNOWN_COMMAND
        ):
            logger.info("Driver has no reset command; run_id cleared")
            response = _ok()
        if response.status == CommandResponseStatus.SUCCESS:
            if self._is_estopped:
                self._is_estopped = False
                self._update_runnable()
                logger.warning("Emergency stop cleared by reset")
            await self._client.publish_state({"state": MachineState.IDLE, "run_id": None})
            logger.info("Machine reset")
        else:
            await self._client.publish_state({"state": MachineState.ERROR, "run_id": None})
            logger.error("Machine reset failed: %s", response.message)
        return response

    async def _immediate_estop(self, handler: CommandHandler, message: NATSMessage) -> CommandResponse:
        """Latch the emergency stop, run the driver estop, and end the active run.

        The latch is set before the driver is called so no queued command can start
        in between. It stays set even if the driver estop fails or is missing, and
        is cleared only by a successful RESET.
        """
        self._is_estopped = True
        self._update_runnable()
        if self._running is not None:
            self._running["stopped_by"] = "estop"
        logger.critical("EMERGENCY STOP received (run_id: %s)", message.header.run_id)
        try:
            response = await handler(message)
        finally:
            await self.run_manager.clear_run()
            await self._client.publish_state({"state": MachineState.ESTOPPED, "run_id": None})
        if response.status == CommandResponseStatus.SUCCESS:
            logger.critical("Emergency stop completed by driver")
        else:
            logger.critical("Emergency stop driver call failed: %s", response.message)
        return response
