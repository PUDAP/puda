"""Run metadata retrieval against disposable SQLite databases (no CLI required)."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import extractor


class RunMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "puda.db"
        self.path_patch = patch.object(extractor, "get_db_path", return_value=self.db)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)

    def create_db(self, columns=("steps", "notes")):
        with sqlite3.connect(self.db) as conn:
            extras = "".join(f", {column} TEXT" for column in columns)
            conn.execute("CREATE TABLE run (run_id TEXT PRIMARY KEY, protocol_id TEXT, created_at TEXT" + extras + ")")
            conn.execute("CREATE TABLE command_log (run_id TEXT, step_number INTEGER, command_name TEXT, machine_id TEXT, created_at TEXT)")
            conn.executemany("INSERT INTO run (run_id, protocol_id, created_at) VALUES (?, ?, ?)", [
                ("partial", "protocol", "2026-01-01T00:00:00Z"),
                ("full", "protocol", "2026-01-02T00:00:00Z"),
            ])
            conn.executemany("INSERT INTO command_log VALUES (?, ?, ?, ?, ?)", [
                ("partial", 3, "OCV", "device", "2026-01-01T00:00:02Z"),
                ("partial", 1, "CV", None, "2026-01-01T00:00:01Z"),
            ])
            values = {"steps": "1,3-4", "notes": "[2026-01-01T00:01:00Z] Observed drift. [plot](reports/plot.png)\n[2026-01-01T00:02:00Z] Follow-up: Δ stable."}
            for column in columns:
                conn.execute(f"UPDATE run SET {column}=? WHERE run_id='partial'", (values[column],))
        return values

    def test_run_info_returns_text_and_preserves_command_shape(self):
        values = self.create_db()
        info = extractor.get_run_info("partial")
        self.assertEqual(info, {
            "run_id": "partial", "protocol_id": "protocol", "created_at": "2026-01-01T00:00:00Z",
            **values,
            "commands": [{"step": 1, "name": "CV", "device": "unknown"}, {"step": 3, "name": "OCV", "device": "device"}],
        })
        full = extractor.get_run_info("full")
        self.assertIsNone(full["steps"])
        self.assertIsNone(full["notes"])
        self.assertEqual(full["commands"], [])
        self.assertEqual(extractor.get_run_info("missing"), {})

    def test_listing_returns_metadata_without_changing_commands_or_limits(self):
        values = self.create_db()
        runs = extractor.list_all_runs()
        self.assertEqual([r["run_id"] for r in runs], ["full", "partial"])
        self.assertEqual(runs[1]["steps"], values["steps"])
        self.assertEqual(runs[1]["notes"], values["notes"])
        self.assertCountEqual(runs[1]["commands"], ["CV", "OCV"])
        self.assertEqual(runs[0]["commands"], [])
        self.assertIsNone(runs[0]["steps"])
        self.assertIsNone(runs[0]["notes"])
        self.assertEqual(extractor.list_all_runs(limit=1), runs[:1])
        self.assertEqual(extractor.list_all_runs(limit=0), [])
        self.assertEqual(extractor.get_runs_by_type("CV"), [("partial", 1, "2026-01-01T00:00:01Z")])

    def test_legacy_and_partially_upgraded_schemas_are_read_without_migration(self):
        for columns in ((), ("notes",), ("steps",)):
            with self.subTest(columns=columns):
                self.db.unlink(missing_ok=True)
                values = self.create_db(columns)
                before = self.db.read_bytes()
                info = extractor.get_run_info("partial")
                summary = extractor.list_all_runs()[1]
                for column in ("steps", "notes"):
                    expected = values[column] if column in columns else None
                    self.assertEqual(info[column], expected)
                    self.assertEqual(summary[column], expected)
                self.assertEqual(extractor.get_run_info("missing"), {})
                self.assertEqual(self.db.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
