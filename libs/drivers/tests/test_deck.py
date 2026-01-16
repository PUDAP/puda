"""Tests for Deck class to_dict() and to_json() methods."""

import json
from puda_drivers.move.deck import Deck


class TestDeckToDict:
    """Test cases for Deck.to_dict() method."""

    def test_to_dict_empty_deck(self):
        """Test to_dict() on an empty deck (all slots are None)."""
        deck = Deck(rows=2, cols=2)
        result = deck.to_dict()
        
        # Should have all slots
        assert len(result) == 4
        assert result["A1"] is None
        assert result["A2"] is None
        assert result["B1"] is None
        assert result["B2"] is None

    def test_to_dict_with_labware(self):
        """Test to_dict() on a deck with labware loaded."""
        deck = Deck(rows=2, cols=2)
        deck.load_labware("A1", "opentrons_96_tiprack_300ul")
        deck.load_labware("B2", "trash_bin")
        
        result = deck.to_dict()
        
        # Check that loaded labware have their names
        assert result["A1"] == "Opentrons OT-2 96 Tip Rack 300 µL"
        assert result["B2"] == "Trash Bin"
        
        # Check that unloaded slots are None
        assert result["A2"] is None
        assert result["B1"] is None

    def test_to_dict_mixed_slots(self):
        """Test to_dict() with a mix of loaded and empty slots."""
        deck = Deck(rows=3, cols=3)
        deck.load_labware("A1", "opentrons_96_tiprack_300ul")
        deck.load_labware("C3", "polyelectric_8_wellplate_30000ul")
        
        result = deck.to_dict()
        
        # Should have all 9 slots
        assert len(result) == 9
        
        # Check loaded slots
        assert result["A1"] == "Opentrons OT-2 96 Tip Rack 300 µL"
        assert result["C3"] == "Polyelectric 8 Well Plate 30000 µL"
        
        # Check some empty slots
        assert result["A2"] is None
        assert result["B1"] is None
        assert result["B2"] is None
        assert result["C1"] is None

    def test_to_dict_all_slots_filled(self):
        """Test to_dict() when all slots are filled."""
        deck = Deck(rows=2, cols=2)
        deck.load_labware("A1", "opentrons_96_tiprack_300ul")
        deck.load_labware("A2", "trash_bin")
        deck.load_labware("B1", "polyelectric_8_wellplate_30000ul")
        deck.load_labware("B2", "opentrons_96_tiprack_300ul")
        
        result = deck.to_dict()
        
        # All slots should have labware names
        assert result["A1"] == "Opentrons OT-2 96 Tip Rack 300 µL"
        assert result["A2"] == "Trash Bin"
        assert result["B1"] == "Polyelectric 8 Well Plate 30000 µL"
        assert result["B2"] == "Opentrons OT-2 96 Tip Rack 300 µL"
        
        # No None values
        assert None not in result.values()


class TestDeckToJson:
    """Test cases for Deck.to_json() method."""

    def test_to_json_empty_deck(self):
        """Test to_json() on an empty deck."""
        deck = Deck(rows=2, cols=2)
        json_str = deck.to_json()
        
        # Should be valid JSON
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        
        # Should match to_dict() output
        assert parsed == deck.to_dict()
        
        # Should have proper indentation (check for newlines)
        assert "\n" in json_str

    def test_to_json_with_labware(self):
        """Test to_json() on a deck with labware loaded."""
        deck = Deck(rows=2, cols=2)
        deck.load_labware("A1", "opentrons_96_tiprack_300ul")
        deck.load_labware("B2", "trash_bin")
        
        json_str = deck.to_json()
        
        # Should be valid JSON
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        
        # Should match to_dict() output exactly
        assert parsed == deck.to_dict()
        
        # Should contain labware names in the parsed JSON (checking parsed values
        # instead of raw string since JSON serialization may escape Unicode characters)
        assert parsed["A1"] == "Opentrons OT-2 96 Tip Rack 300 µL"
        assert parsed["B2"] == "Trash Bin"

    def test_to_json_matches_to_dict(self):
        """Test that to_json() when parsed matches to_dict() output."""
        deck = Deck(rows=3, cols=3)
        deck.load_labware("A1", "opentrons_96_tiprack_300ul")
        deck.load_labware("B2", "trash_bin")
        deck.load_labware("C3", "polyelectric_8_wellplate_30000ul")
        
        dict_result = deck.to_dict()
        json_str = deck.to_json()
        json_result = json.loads(json_str)
        
        # Should be identical
        assert dict_result == json_result
        
        # Verify structure
        assert json_result["A1"] == "Opentrons OT-2 96 Tip Rack 300 µL"
        assert json_result["B2"] == "Trash Bin"
        assert json_result["C3"] == "Polyelectric 8 Well Plate 30000 µL"
        assert json_result["A2"] is None

    def test_to_json_indentation(self):
        """Test that to_json() has proper indentation (indent=2)."""
        deck = Deck(rows=2, cols=2)
        deck.load_labware("A1", "opentrons_96_tiprack_300ul")
        
        json_str = deck.to_json()
        
        # Check that it has indentation (2 spaces per level)
        lines = json_str.split("\n")
        # First line should be "{"
        assert lines[0].strip() == "{"
        # Second line should have 2 spaces of indentation
        assert lines[1].startswith("  ")
        
        # Verify it's still valid JSON
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

    def test_to_json_round_trip(self):
        """Test that to_json() output can be loaded and matches original."""
        deck = Deck(rows=2, cols=2)
        deck.load_labware("A1", "opentrons_96_tiprack_300ul")
        deck.load_labware("B2", "trash_bin")
        
        original_dict = deck.to_dict()
        json_str = deck.to_json()
        loaded_dict = json.loads(json_str)
        
        # Round trip should preserve all data
        assert loaded_dict == original_dict
        
        # Verify all keys and values match
        for key in original_dict:
            assert key in loaded_dict
            assert loaded_dict[key] == original_dict[key]

