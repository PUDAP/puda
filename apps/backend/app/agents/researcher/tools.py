"""Tools specific to the researcher agent."""
from typing import Literal


def _detect_device_types(query: str) -> list[Literal["opentron", "biologic", "keithley", "general"]]:
    """Detect which device types the query relates to based on keywords.
    
    Returns a list of detected device types, as a query can involve multiple machines.
    The first machine is treated as an Opentrons machine (liquid handling).
    """
    query_lower = query.lower()
    detected_types = []
    
    # first keywords (includes first machine since it's also a liquid handling machine)
    first_keywords = ["opentron", "opentrons", "pipette", "pipetting", "liquid handling", 
                         "protocol", "labware", "tip", "aspirate", "dispense",
                         "first machine", "first", "gcode", "grbl", "cnc", "positioning"]
    if any(keyword in query_lower for keyword in first_keywords):
        detected_types.append("opentron")
    
    # BioLogic keywords
    biologic_keywords = ["biologic", "electrochemical", "potentiostat", "galvanostat", 
                        "echem", "cv", "cyclic voltammetry", "impedance", "eis"]
    if any(keyword in query_lower for keyword in biologic_keywords):
        detected_types.append("biologic")
    
    # Keithley keywords
    keithley_keywords = ["keithley", "sourcemeter", "source meter", "multimeter", 
                        "voltage", "current", "resistance", "measurement", "smu"]
    if any(keyword in query_lower for keyword in keithley_keywords):
        detected_types.append("keithley")
    
    # If no specific device types detected, return general
    if not detected_types:
        detected_types.append("general")
    
    return detected_types


def research_tool(query: str) -> str:
    """Perform research on a given query.
    
    This tool analyzes the query and routes it to the appropriate device-specific MCP tools
    based on the instructions in instructions.md. It identifies device types (OpenTron,
    BioLogic, Keithley) and provides guidance on which MCP tools to use. A query can
    involve multiple machines, and the first machine is treated as an Opentrons machine.
    
    Args:
        query: The research query or task description
        
    Returns:
        A comprehensive response indicating which MCP tools should be used and
        how to proceed with the device-specific task(s).
    """
    if not query or not query.strip():
        return "Error: Query cannot be empty. Please provide a research question or task description."
    
    device_types = _detect_device_types(query)
    
    # Build response sections for each detected device type
    sections = [f"Research Query: {query}\n"]
    
    if len(device_types) > 1:
        sections.append(f"Device Types Detected: {', '.join(device_types).title()}\n")
    else:
        sections.append(f"Device Type Detected: {device_types[0].title()}\n")
    
    sections.append("\n")
    
    # Add guidance for each detected device type
    if "first" in device_types:
        sections.append(
            "=== First Machine (Liquid Handling) ===\n\n"
            "Recommended MCP Tools:\n"
            "- generate_machine_commands: Convert natural language to OpenTron protocol\n"
            "- run_commands: Run commands on robot\n"
            "- get_machine_status: Check current machine status (for First machine)\n\n"
            "- get_available_labware: Get available labware on the First machine\n"
            "- get_available_commands: Get available commands on the First machine\n"
            
            "Next Steps: Use the appropriate First machine MCP tool based on your specific needs. "
            "For protocol generation from natural language, use 'generate_machine_commands' "
            "for First machine. "
            "After tool execution, provide a comprehensive analysis of the results.\n\n"
        )
    
    if "biologic" in device_types:
        sections.append(
            "=== BioLogic (Electrochemical) ===\n\n"
            "Recommended MCP Tools:\n"
            "- natural_language_to_biologic_protocol: Convert natural language to BioLogic experiment protocol\n"
            "- Other BioLogic-specific tools for experiment control and data analysis\n\n"
            "Next Steps: Use 'natural_language_to_biologic_protocol' or other BioLogic MCP tools "
            "to generate and execute your electrochemical experiment. Ensure proper safety and "
            "operational requirements are met. After execution, analyze and summarize the results.\n\n"
        )
    
    if "keithley" in device_types:
        sections.append(
            "=== Keithley (Electrical Measurements) ===\n\n"
            "Recommended MCP Tools:\n"
            "- Keithley-specific tools for voltage, current, and resistance measurements\n"
            "- Measurement configuration and execution tools\n\n"
            "Next Steps: Use Keithley MCP tools to configure and execute your measurement task. "
            "Ensure proper device connection and safety parameters. After measurement, provide "
            "a detailed analysis of the results.\n\n"
        )
    
    if "general" in device_types and len(device_types) == 1:
        sections.append(
            "=== General/Unspecified ===\n\n"
            "This query doesn't clearly specify a device type. Please clarify which device you "
            "need to work with:\n"
            "- OpenTron/First Machine: For liquid handling and pipetting protocols\n"
            "- BioLogic: For electrochemical experiments\n"
            "- Keithley: For electrical measurements\n\n"
            "Alternatively, if this is a general research question, please rephrase to include "
            "the specific device or task type you need assistance with.\n"
        )
    
    # Add final guidance for multi-device queries
    if len(device_types) > 1 and "general" not in device_types:
        sections.append(
            "=== Multi-Device Workflow ===\n\n"
            "This query involves multiple devices. Coordinate the use of MCP tools for each device "
            "according to the workflow requirements. Ensure proper sequencing and data flow between "
            "devices. After all tool executions, provide a comprehensive analysis that synthesizes "
            "results from all devices.\n"
        )
    
    return "".join(sections)


def analyze_documents_tool(documents: list[str]) -> str:
    """Analyze a collection of documents."""
    # TODO: Implement document analysis
    return "Analysis complete"

