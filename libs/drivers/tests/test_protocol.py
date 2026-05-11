"""Tests for opentrons_driver.controllers.protocol."""

from unittest.mock import MagicMock, patch

import pytest

from opentrons_driver.controllers.protocol import (
    Protocol,
    ProtocolCommand,
    _build_location_expr,
    _get_first,
    preprocess_protocol_code,
    upload_protocol,
)
from opentrons_driver.core.http_client import OT2HttpClient


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


class TestGetFirst:
    def test_returns_first_matching_key(self):
        assert _get_first({"b": 2, "a": 1}, ["a", "b"]) == 1

    def test_returns_default_when_no_match(self):
        assert _get_first({"x": 1}, ["a", "b"], default=99) == 99

    def test_returns_none_by_default(self):
        assert _get_first({}, ["a"]) is None


class TestBuildLocationExpr:
    def test_plain_well(self):
        expr = _build_location_expr("tiprack", "'A1'", None, None)
        assert expr == "labware['tiprack']['A1']"

    def test_with_bottom_offset(self):
        expr = _build_location_expr("plate", "'B2'", "bottom", 5)
        assert expr == "labware['plate']['B2'].bottom(5.0)"

    def test_with_top_no_offset(self):
        expr = _build_location_expr("plate", "'A1'", "top", None)
        assert expr == "labware['plate']['A1'].top()"

    def test_dynamic_row_offset(self):
        expr = _build_location_expr("plate", "'A1'", "bottom", "row['offset']")
        assert expr == "labware['plate']['A1'].bottom(row['offset'])"


# ---------------------------------------------------------------------------
# Protocol model
# ---------------------------------------------------------------------------


class TestProtocolToCode:
    def _minimal_protocol(self, commands=None):
        return Protocol(
            protocol_name="Test",
            author="Tester",
            description="Unit test",
            robot_type="OT-2",
            api_level="2.23",
            commands=commands or [],
        )

    def test_generates_metadata(self):
        code = self._minimal_protocol().to_python_code()
        assert '"protocolName": "Test"' in code
        assert '"author": "Tester"' in code

    def test_generates_run_function(self):
        code = self._minimal_protocol().to_python_code()
        assert "def run(protocol: protocol_api.ProtocolContext):" in code
        assert "from opentrons import protocol_api" in code

    def test_load_labware_standard(self):
        cmd = ProtocolCommand(
            command_type="load_labware",
            params={
                "name": "tiprack",
                "labware_type": "opentrons_96_tiprack_300ul",
                "location": "1",
            },
        )
        code = self._minimal_protocol([cmd]).to_python_code()
        assert "protocol.load_labware" in code
        assert "opentrons_96_tiprack_300ul" in code

    def test_load_labware_mass_balance_30ml(self):
        cmd = ProtocolCommand(
            command_type="load_labware",
            params={
                "name": "balance",
                "labware_type": "mass_balance_vial_30000",
                "location": "3",
            },
        )
        code = self._minimal_protocol([cmd]).to_python_code()
        assert "load_labware_from_definition" in code
        assert "mass_balance_vial_30000" in code

    def test_load_instrument(self):
        cmd = ProtocolCommand(
            command_type="load_instrument",
            params={
                "name": "p300",
                "instrument_type": "p300_single_gen2",
                "mount": "right",
                "tip_racks": ["tiprack"],
            },
        )
        code = self._minimal_protocol([cmd]).to_python_code()
        assert "load_instrument" in code
        assert "p300_single_gen2" in code
        assert "mount='right'" in code

    def test_aspirate_command(self):
        cmd = ProtocolCommand(
            command_type="aspirate",
            params={
                "pipette": "p300",
                "volume": 100,
                "labware": "plate",
                "well": "A1",
            },
        )
        code = self._minimal_protocol([cmd]).to_python_code()
        assert "pipettes['p300'].aspirate(100.0" in code

    def test_dispense_command(self):
        cmd = ProtocolCommand(
            command_type="dispense",
            params={
                "pipette": "p300",
                "volume": 100,
                "labware": "plate",
                "well": "B1",
            },
        )
        code = self._minimal_protocol([cmd]).to_python_code()
        assert "pipettes['p300'].dispense(100.0" in code

    def test_drop_tip_command(self):
        cmd = ProtocolCommand(
            command_type="drop_tip",
            params={"pipette": "p300"},
        )
        code = self._minimal_protocol([cmd]).to_python_code()
        assert "pipettes['p300'].drop_tip()" in code

    def test_delay_seconds(self):
        cmd = ProtocolCommand(
            command_type="delay",
            params={"seconds": 5},
        )
        code = self._minimal_protocol([cmd]).to_python_code()
        assert "protocol.delay(seconds=5)" in code

    def test_home_command(self):
        cmd = ProtocolCommand(command_type="home", params={})
        code = self._minimal_protocol([cmd]).to_python_code()
        assert "protocol.home()" in code

    def test_namespace_prefix_stripped(self):
        cmd = ProtocolCommand(
            command_type="load_labware",
            params={
                "name": "plate",
                "labware_type": "custom_beta/mass_balance_vial_30000",
                "location": "5",
            },
        )
        code = self._minimal_protocol([cmd]).to_python_code()
        # Should not have namespace prefix in the resulting code
        assert "custom_beta/" not in code


# ---------------------------------------------------------------------------
# preprocess_protocol_code
# ---------------------------------------------------------------------------


class TestPreprocessProtocolCode:
    def test_strips_markdown_fences(self):
        code = "```python\nfrom opentrons import protocol_api\n```"
        result = preprocess_protocol_code(code)
        assert "```" not in result

    def test_adds_missing_import(self):
        code = "def run(protocol):\n    pass\n"
        result = preprocess_protocol_code(code)
        assert "from opentrons import protocol_api" in result

    def test_does_not_duplicate_import(self):
        code = "from opentrons import protocol_api\ndef run(protocol):\n    pass\n"
        result = preprocess_protocol_code(code)
        assert result.count("from opentrons import protocol_api") == 1

    def test_fixes_df_loc_pattern(self):
        code = "from opentrons import protocol_api\nx = df.loc[i, 'volume']\n"
        result = preprocess_protocol_code(code)
        assert "row['volume']" in result
        assert "df.loc" not in result


# ---------------------------------------------------------------------------
# upload_protocol
# ---------------------------------------------------------------------------


class TestUploadProtocol:
    def test_returns_protocol_id_on_success(self, mock_client, make_response):
        fake_resp = make_response(201, {"data": {"id": "proto-123"}})
        with patch("opentrons_driver.controllers.protocol.requests.post", return_value=fake_resp):
            pid = upload_protocol(mock_client, "from opentrons import protocol_api\n")
        assert pid == "proto-123"

    def test_raises_on_http_error(self, mock_client, make_response):
        fake_resp = make_response(500, text="Internal Server Error")
        with patch("opentrons_driver.controllers.protocol.requests.post", return_value=fake_resp):
            with pytest.raises(RuntimeError, match="Failed to upload protocol"):
                upload_protocol(mock_client, "code")

    def test_raises_when_no_id_returned(self, mock_client, make_response):
        fake_resp = make_response(201, {"data": {}})
        with patch("opentrons_driver.controllers.protocol.requests.post", return_value=fake_resp):
            with pytest.raises(RuntimeError, match="no ID returned"):
                upload_protocol(mock_client, "code")
