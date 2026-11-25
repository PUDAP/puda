"""header.protocol_version is required and must share the SDK's protocol major."""
import unittest

from pydantic import ValidationError

from puda import PROTOCOL_VERSION
from puda.command_processor import CommandProcessor
from puda.models import MessageHeader, MessageType


def header(**extra) -> dict:
    return {"message_type": MessageType.COMMAND, "user_id": "u", "username": "n", "machine_id": "m", **extra}


class ProtocolVersionTests(unittest.TestCase):
    def test_same_major_is_accepted(self) -> None:
        for version in ("1.0", "1.7", "1.12", PROTOCOL_VERSION):
            self.assertEqual(MessageHeader(**header(protocol_version=version)).protocol_version, version)

    def test_missing_version_is_an_invalid_envelope(self) -> None:
        # The pre-1.0 field name is not accepted either: no backward compatibility.
        for fields in (header(), header(version="1.0")):
            with self.assertRaises(ValidationError) as caught:
                MessageHeader(**fields)
            message = CommandProcessor._invalid_envelope(caught.exception).message
            self.assertIn("Invalid command envelope: protocol_version: Field required", message)

    def test_other_major_is_an_invalid_envelope(self) -> None:
        for version in ("2.0", "0.9", "1", "1.0.0", "v1.0", "1.x", "x", ""):
            with self.assertRaises(ValidationError) as caught:
                MessageHeader(**header(protocol_version=version))
            response = CommandProcessor._invalid_envelope(caught.exception)
            self.assertEqual(response.code, "EXECUTION_ERROR")
            self.assertIn("Invalid command envelope: protocol_version: ", response.message)
            self.assertIn(f"unsupported protocol version {version!r}", response.message)
