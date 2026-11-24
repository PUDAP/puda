"""Immediate commands stored too long ago (edge was offline) are discarded."""
from __future__ import annotations

import unittest

from processor_fakes import FakeClient, FakeMsg, message, success

from puda.command_processor import CommandProcessor


class StaleImmediateTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_start_is_acked_and_ignored(self) -> None:
        processor = CommandProcessor(FakeClient())
        msg = FakeMsg(message("start", step_number=0), "immediate", age=60)
        await processor.process_immediate(msg, success)
        self.assertTrue(msg.acked)
        self.assertIsNone(processor.run_manager.get_active_run_id())

    async def test_stale_estop_does_not_latch(self) -> None:
        processor = CommandProcessor(FakeClient())
        await processor.process_immediate(FakeMsg(message("estop", step_number=0), "immediate", age=60), success)
        self.assertFalse(processor.is_estopped)

    async def test_fresh_start_runs(self) -> None:
        processor = CommandProcessor(FakeClient())
        await processor.process_immediate(FakeMsg(message("start", step_number=0), "immediate", age=1), success)
        self.assertEqual(processor.run_manager.get_active_run_id(), "run-1")

    async def test_unknown_age_and_disabled_check_run(self) -> None:
        processor = CommandProcessor(FakeClient())
        await processor.process_immediate(FakeMsg(message("start", step_number=0), "immediate", age=None), success)
        self.assertEqual(processor.run_manager.get_active_run_id(), "run-1")

        disabled = CommandProcessor(FakeClient(immediate_max_age=None))
        await disabled.process_immediate(FakeMsg(message("start", step_number=0), "immediate", age=3600), success)
        self.assertEqual(disabled.run_manager.get_active_run_id(), "run-1")


if __name__ == "__main__":
    unittest.main()
