"""Built-in schema registry lookups (no CLI or database required)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from registry import SchemaRegistry


class BuiltinSchemaTests(unittest.TestCase):
    def test_first_and_biologic_schemas_are_distinct(self):
        expected = {
            ("first", "CV"): ["potential", "current", "time", "extra", "flag"],
            ("first", "OCV"): ["potential", "current", "time", "extra", "flag"],
            ("first", "CA"): ["time", "current", "voltage", "extra", "flag"],
            ("first", "PEIS"): ["frequency", "Z_real", "Z_imag", "phase", "flag"],
            ("biologic", "CV"): ["E", "I", "time", "Ewe", "flag"],
            ("biologic", "PEIS"): ["frequency", "Z_real", "Z_imag", "phase", "magnitude"],
        }
        for (device, command), columns in expected.items():
            with self.subTest(device=device, command=command):
                schema = SchemaRegistry.get(device, command)
                self.assertIsNotNone(schema)
                self.assertEqual(schema.columns, columns)


if __name__ == "__main__":
    unittest.main()
