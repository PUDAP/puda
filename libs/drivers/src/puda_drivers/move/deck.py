# src/puda_drivers/move/deck.py

import json
from puda_drivers.labware import StandardLabware


class Deck:
    """
    Deck class for managing labware layout.
    """
    def __init__(self, rows: int, cols: int):
        """
        Initialize the deck.
        
        Args:
            rows: The number of rows in the deck.
            cols: The number of columns in the deck.
        """
        # A dictionary mapping Slot Names (A1, B4) to Labware Objects
        self.slots = {}
        for row in range(rows):
            for col in range(cols):
                slot = f"{chr(65 + row)}{col + 1}"
                self.slots[slot] = None

    def load_labware(self, slot: str, labware_name: str):
        """
        Load labware into a slot.
        """
        if slot.upper() not in self.slots:
            raise KeyError(f"Slot {slot} not found in deck")
        self.slots[slot.upper()] = StandardLabware(labware_name=labware_name)
    
    def empty_slot(self, slot: str):
        """
        Empty a slot (remove labware from it).
        
        Args:
            slot: Slot name (e.g., 'A1', 'B2')
        
        Raises:
            KeyError: If slot is not found in deck
        """
        if slot.upper() not in self.slots:
            raise KeyError(f"Slot {slot} not found in deck")
        self.slots[slot.upper()] = None
        
    def __str__(self):
        """
        Return a string representation of the deck layout.
        """
        lines = []
        for slot, labware in self.slots.items():
            if labware is None:
                continue
            else:
                lines.append(f"{slot}: {labware.name}")
        return "\n".join(lines)

    def __getitem__(self, key):
        """Allows syntax for: my_deck['B4']"""
        return self.slots[key.upper()]
 
    def to_dict(self) -> dict:
        """
        Return the deck layout as a dictionary.
        """
        deck_data = {}
        for slot, labware in self.slots.items():
            if labware is None:
                deck_data[slot] = None
            else:
                deck_data[slot] = labware.name
        return deck_data

    def to_json(self) -> str:
        """
        Return the deck layout as a JSON string.
        """
        # Re-use the logic from to_dict() so you don't have to update it in two places
        return json.dumps(self.to_dict(), indent=2)
