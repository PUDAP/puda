import unittest

from puda.execution_state import ExecutionState


class ExecutionStateRuntimeStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_is_idle_without_active_execution(self):
        state = ExecutionState()
        self.assertEqual(state.get_runtime_status(), "idle")

    async def test_status_is_busy_while_execution_lock_is_held(self):
        state = ExecutionState()
        self.assertTrue(await state.acquire_lock("run-1"))
        try:
            self.assertEqual(state.get_runtime_status(), "busy")
        finally:
            state.release_lock()
        self.assertEqual(state.get_runtime_status(), "idle")


if __name__ == "__main__":
    unittest.main()
