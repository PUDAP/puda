"""Tests for opentrons_driver.controllers.resources (labware upload & catalogues)."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from opentrons_driver.controllers.resources import (
    BUILTIN_LABWARE,
    MASS_BALANCE_VIAL_30ML,
    MASS_BALANCE_VIAL_50ML,
    get_labware_types,
    get_pipette_types,
    upload_custom_labware,
)


# ---------------------------------------------------------------------------
# Built-in labware definitions
# ---------------------------------------------------------------------------


class TestBuiltinDefinitions:
    def test_30ml_has_required_fields(self):
        d = MASS_BALANCE_VIAL_30ML
        assert d["parameters"]["loadName"] == "mass_balance_vial_30000"
        assert d["namespace"] == "custom_beta"
        assert "A1" in d["wells"]
        assert d["wells"]["A1"]["totalLiquidVolume"] == 30000

    def test_50ml_has_required_fields(self):
        d = MASS_BALANCE_VIAL_50ML
        assert d["parameters"]["loadName"] == "mass_balance_vial_50000"
        assert d["namespace"] == "custom_beta"
        assert d["wells"]["A1"]["totalLiquidVolume"] == 50000

    def test_builtin_map_contains_both(self):
        assert "mass_balance_vial_30000" in BUILTIN_LABWARE
        assert "mass_balance_vial_50000" in BUILTIN_LABWARE


# ---------------------------------------------------------------------------
# upload_custom_labware
# ---------------------------------------------------------------------------


class TestUploadCustomLabware:
    def test_upload_from_dict_success(self, mock_client, make_response):
        fake_resp = make_response(201)
        with patch(
            "opentrons_driver.controllers.resources.OT2HttpClient.post",
            return_value=fake_resp,
        ):
            result = upload_custom_labware(mock_client, MASS_BALANCE_VIAL_30ML)
        assert result["load_name"] == "mass_balance_vial_30000"
        assert result["namespace"] == "custom_beta"
        assert result["already_exists"] is False

    def test_upload_from_json_file(self, mock_client, make_response, tmp_path):
        labware_path = tmp_path / "my_labware.json"
        labware_path.write_text(json.dumps(MASS_BALANCE_VIAL_50ML), encoding="utf-8")

        fake_resp = make_response(200)
        with patch(
            "opentrons_driver.controllers.resources.OT2HttpClient.post",
            return_value=fake_resp,
        ):
            result = upload_custom_labware(mock_client, str(labware_path))
        assert result["load_name"] == "mass_balance_vial_50000"

    def test_already_exists_409_does_not_raise(self, mock_client, make_response):
        fake_resp = make_response(409)
        with patch(
            "opentrons_driver.controllers.resources.OT2HttpClient.post",
            return_value=fake_resp,
        ):
            result = upload_custom_labware(mock_client, MASS_BALANCE_VIAL_30ML)
        assert result["already_exists"] is True

    def test_raises_when_file_not_found(self, mock_client):
        with pytest.raises(FileNotFoundError):
            upload_custom_labware(mock_client, "/nonexistent/file.json")

    def test_raises_on_missing_load_name(self, mock_client):
        bad_def = {
            "namespace": "custom",
            "parameters": {},  # no loadName
            "metadata": {"displayName": "Bad"},
        }
        with pytest.raises(ValueError, match="loadName"):
            upload_custom_labware(mock_client, bad_def)

    def test_raises_on_server_error(self, mock_client, make_response):
        fake_resp = make_response(500, text="Server error")
        with patch(
            "opentrons_driver.controllers.resources.OT2HttpClient.post",
            return_value=fake_resp,
        ):
            with pytest.raises(RuntimeError, match="Failed to upload labware"):
                upload_custom_labware(mock_client, MASS_BALANCE_VIAL_30ML)


# ---------------------------------------------------------------------------
# Resources catalogue
# ---------------------------------------------------------------------------


class TestResources:
    def test_get_labware_types_returns_list(self):
        types = get_labware_types()
        assert isinstance(types, list)
        assert len(types) > 0
        assert "opentrons_96_tiprack_300ul" in types

    def test_get_pipette_types_returns_list(self):
        types = get_pipette_types()
        assert isinstance(types, list)
        assert "p300_single_gen2" in types

    def test_labware_types_are_copies(self):
        types1 = get_labware_types()
        types1.append("rogue_labware")
        assert "rogue_labware" not in get_labware_types()

    def test_pipette_types_are_copies(self):
        types1 = get_pipette_types()
        types1.append("rogue_pipette")
        assert "rogue_pipette" not in get_pipette_types()

    def test_custom_vials_in_labware_types(self):
        types = get_labware_types()
        assert "mass_balance_vial_30000" in types
        assert "mass_balance_vial_50000" in types
