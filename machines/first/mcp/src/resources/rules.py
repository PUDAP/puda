"""
Rules Resource

Resource that exposes rules and restrictions for the First machine.
"""

import json


async def get_rules_resource() -> str:
    """Returns a JSON object describing rules and restrictions when generating commands for the First machine.

    Returns:
        str: JSON-formatted object containing deck usage rules.
    """
    rules = {
        "available_slots": {
            "description": "Deck slots that can be used",
            "slots": ["A1", "A2", "A3", "A4", "B1", "B2", "B3", "B4", "C1", "C2", "C3", "C4"]
        },
        "command_restrictions": {
            "move_electrode": {
                "description": "Deck slots that cannot be used for move_electrode command",
                "slots": ["A1", "A2", "A3", "A4"]
            }
        },
        "command_dependencies": {
            "attach_tip": {
                "description": "attach_tip must be called before aspirate_from, dispense_to, or drop_tip",
                "required_before": ["aspirate_from", "dispense_to", "drop_tip"]
            }
        }
    }
    
    return json.dumps(rules, indent=2)

