"""Independent PUDA NATS subscriptions and acknowledged, batched persistence."""

import asyncio
import logging
import signal
import sys

import nats
from nats.js.api import (
    AckPolicy,
    ConsumerConfig,
    DeliverPolicy,
    RetentionPolicy,
    StreamConfig,
)
from nats.js.errors import NotFoundError
from puda import e2e

from storage import ClickHouse, Config, to_row, timestamp_ns as timestamp_ns

log = logging.getLogger("clickhouse_logger")
RESPONSE_STREAMS = {
    "RESPONSE_QUEUE": "puda.*.cmd.response.queue",
    "RESPONSE_IMMEDIATE": "puda.*.cmd.response.immediate",
}
RESPONSE_CONSUMERS = {
    "RESPONSE_QUEUE": "clickhouse_logger_responses_queue",
    "RESPONSE_IMMEDIATE": "clickhouse_logger_responses_immediate",
}


class Subscriber:
    def __init__(self, config):
        self.config = config
        self.sink = ClickHouse(config)
        self.nc = None
        self.js = None
        self.queue = asyncio.Queue(maxsize=config.max_ack_pending)
        self.key_lock = asyncio.Lock()

    async def sync_keyring(self):
        if not self.config.encrypted:
            return
        async with self.key_lock:
            try:
                kv = await self.js.key_value(e2e.KEYRING_BUCKET)
            except NotFoundError:
                return
            try:
                entry = await kv.get(e2e.KEYRING_KEY)
            except NotFoundError:
                e2e.drop_previous()
                return
            plain = e2e.open_payload(
                e2e.kv_aad(e2e.KEYRING_BUCKET, e2e.KEYRING_KEY), entry.value
            )
            e2e.adopt_record(plain)

    async def watch_keys(self):
        while True:
            await asyncio.sleep(2)
            try:
                await self.sync_keyring()
            except Exception:
                log.error("Keyring refresh failed; retaining current keys")
                await asyncio.sleep(8)

    async def ensure_streams(self):
        for stream, subject in RESPONSE_STREAMS.items():
            try:
                info = await self.js.stream_info(stream)
            except NotFoundError:
                # Shared response streams only. Never create/consume command WorkQueues.
                await self.js.add_stream(
                    config=StreamConfig(
                        name=stream,
                        subjects=[subject],
                        retention=RetentionPolicy.LIMITS,
                        max_age=86400,
                    )
                )
            else:
                if (
                    subject not in (info.config.subjects or [])
                    or info.config.retention not in (
                        RetentionPolicy.LIMITS, RetentionPolicy.INTEREST
                    )
                ):
                    raise ValueError(
                        "Response stream requires the expected subject and Limits or Interest retention"
                    )
                # Existing retention/age belongs to the broker operator, not this backend.
            durable = RESPONSE_CONSUMERS[stream]
            try:
                info = await self.js.consumer_info(stream, durable)
            except NotFoundError:
                await self.js.add_consumer(
                    stream,
                    config=ConsumerConfig(
                        durable_name=durable,
                        deliver_group=durable,
                        deliver_subject=f"puda.logger.clickhouse.deliver.{stream.lower()}",
                        filter_subject=subject,
                        ack_policy=AckPolicy.EXPLICIT,
                        deliver_policy=DeliverPolicy.ALL,
                        ack_wait=120,
                        max_deliver=-1,
                        max_ack_pending=self.config.max_ack_pending,
                    ),
                )
            else:
                c = info.config
                if (
                    c.deliver_group != durable
                    or c.filter_subject != subject
                    or not c.deliver_subject
                    or c.ack_policy != AckPolicy.EXPLICIT
                    or c.max_deliver != -1
                    or c.ack_wait < 120
                    or c.max_ack_pending != self.config.max_ack_pending
                ):
                    raise ValueError(
                        "Incompatible ClickHouse response consumer; review broker configuration"
                    )

    async def receive(self, msg):
        await self.queue.put((msg, False))

    async def receive_response(self, msg):
        await self.queue.put((msg, True))

    async def subscribe(self):
        limits = dict(
            pending_msgs_limit=self.config.max_ack_pending,
            pending_bytes_limit=64 * 1024 * 1024,
        )
        subscriptions = []
        for subject, group in (
            ("puda.*.cmd.queue", "clickhouse_logger_cmd_requests"),
            ("puda.*.cmd.immediate", "clickhouse_logger_cmd_requests"),
            ("puda.*.tlm.health", "clickhouse_logger_telemetry"),
            ("puda.*.tlm.stream.>", "clickhouse_logger_telemetry_stream"),
        ):
            subscriptions.append(
                await self.nc.subscribe(subject, queue=group, cb=self.receive, **limits)
            )
        for stream, subject in RESPONSE_STREAMS.items():
            durable = RESPONSE_CONSUMERS[stream]
            subscriptions.append(
                await self.js.subscribe(
                    subject,
                    stream=stream,
                    durable=durable,
                    queue=durable,
                    cb=self.receive_response,
                    manual_ack=True,
                    **limits,
                )
            )
        return subscriptions

    async def finish(self, msg, action):
        try:
            if action == "nak":
                await msg.nak(delay=5)
            else:
                await getattr(msg, action)()
        except Exception:
            # A failed ACK can redeliver an already persisted row.
            log.error("NATS acknowledgment failed")

    async def process_batch(self, batch):
        rows, responses = [], []
        for msg, jetstream in batch:
            try:
                try:
                    plain = e2e.open_payload(msg.subject, msg.data)
                except e2e.E2EError:
                    await self.sync_keyring()
                    plain = e2e.open_payload(msg.subject, msg.data)
            except Exception:
                log.error("Message decryption failed; retrying response if durable")
                if jetstream:
                    await self.finish(msg, "nak")
                continue
            try:
                rows.append(to_row(msg.subject, plain))
            except (ValueError, KeyError, TypeError, OverflowError, RecursionError):
                log.error("Invalid message discarded; terminating response if durable")
                if jetstream:
                    await self.finish(msg, "term")
                continue
            if jetstream:
                responses.append(msg)
        if not rows:
            return
        try:
            # Synchronous client-batched inserts; confirm HTTP success before ACK.
            await asyncio.to_thread(self.sink.write, rows)
        except Exception:
            log.error(
                "ClickHouse batch write failed; durable responses retry; core traffic may be lost"
            )
            for msg in responses:
                await self.finish(msg, "nak")
            return
        for msg in responses:
            await self.finish(msg, "ack")

    async def worker(self):
        while True:
            batch = [await self.queue.get()]
            deadline = asyncio.get_running_loop().time() + self.config.batch_interval
            try:
                while len(batch) < self.config.batch_size:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        batch.append(
                            await asyncio.wait_for(self.queue.get(), remaining)
                        )
                    except TimeoutError:
                        break
                await self.process_batch(batch)
            finally:
                for _ in batch:
                    self.queue.task_done()

    async def run(self):
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)

        async def on_error(_):
            log.error(
                "NATS error; check broker availability and subscription pending limits"
            )

        async def on_closed():
            stop.set()

        tasks = []
        try:
            await asyncio.to_thread(self.sink.check)
            self.nc = await nats.connect(
                servers=self.config.servers,
                **self.config.connect_options,
                name="puda-clickhouse-logger",
                max_reconnect_attempts=-1,
                error_cb=on_error,
                closed_cb=on_closed,
            )
            self.js = self.nc.jetstream()
            await self.ensure_streams()
            await self.sync_keyring()
            worker = asyncio.create_task(self.worker())
            tasks.append(worker)
            if self.config.encrypted:
                tasks.append(asyncio.create_task(self.watch_keys()))
            subscriptions = await self.subscribe()
            await self.nc.flush()
            log.info("ClickHouse logger ready")
            waiter = asyncio.create_task(stop.wait())
            tasks.append(waiter)
            done, _ = await asyncio.wait(
                [worker, waiter], return_when=asyncio.FIRST_COMPLETED
            )
            if worker in done:
                await worker
            async with asyncio.timeout(60):
                for subscription in subscriptions:
                    await subscription.drain()
                await self.queue.join()
                await self.nc.drain()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self.nc is not None and not self.nc.is_closed:
                await self.nc.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        config = Config.from_env()
        if "--check-config" in sys.argv:
            return 0
        subscriber = Subscriber(config)
        if "--healthcheck" in sys.argv:
            subscriber.sink.check()
        else:
            asyncio.run(subscriber.run())
    except Exception:
        log.error(
            "ClickHouse logger stopped; check environment, credentials, schema and broker configuration"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
