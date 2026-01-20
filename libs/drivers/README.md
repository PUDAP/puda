# puda-drivers

Hardware drivers for the PUDA (Physical Unified Device Architecture) platform. This package provides Python interfaces for controlling laboratory automation equipment.

## Features

- **Gantry Control**: Control G-code compatible motion systems (e.g., QuBot)
- **Liquid Handling**: Interface with Sartorius rLINE® pipettes and dispensers
- **Serial Communication**: Robust serial port management with automatic reconnection
- **Logging**: Configurable logging with optional file output to logs folder
- **Cross-platform**: Works on Linux, macOS, and Windows

## Installation

### From PyPI

```bash
pip install puda-drivers
```

## Quick Start

### Logging Configuration

Configure logging for your application with optional file output:

```python
import logging
from puda_drivers.core.logging import setup_logging

# Configure logging with file output enabled
setup_logging(
    enable_file_logging=True,
    log_level=logging.DEBUG,
    logs_folder="logs", # Optional: default to logs
    log_file_name="my_experiment"  # Optional: custom log file name
)

# Or disable file logging (console only)
setup_logging(
    enable_file_logging=False,
    log_level=logging.INFO
)
```

**Logging Options:**
- `enable_file_logging`: If `True`, logs are written to files in the `logs/` folder. If `False`, logs only go to console (default: `False`)
- `log_level`: Logging level constant (e.g., `logging.DEBUG`, `logging.INFO`, `logging.WARNING`, `logging.ERROR`, `logging.CRITICAL`) (default: `logging.DEBUG`)
- `logs_folder`: Name of the folder to store log files (default: `"logs"`)
- `log_file_name`: Custom name for the log file. If `None` or empty, uses timestamp-based name (e.g., `log_20250101_120000.log`). If provided without `.log` extension, it will be added automatically.

When file logging is enabled, logs are saved to timestamped files (unless a custom name is provided) in the `logs/` folder. The logs folder is created automatically if it doesn't exist.

### First Machine Example

The `First` machine integrates motion control, deck management, liquid handling, and camera capabilities:

```python
import time
import logging
from puda_drivers.machines import First
from puda_drivers.core.logging import setup_logging

# Configure logging
setup_logging(
    enable_file_logging=False,
    log_level=logging.DEBUG,
)

# Initialize the First machine
machine = First(
    qubot_port="/dev/ttyACM0",
    sartorius_port="/dev/ttyUSB0",
    camera_index=0,
)

# Start up the machine (connects all controllers, homes gantry, and initializes pipette)
machine.startup()

# Load labware onto the deck
machine.load_deck({
    "C1": "trash_bin",
    "C2": "polyelectric_8_wellplate_30000ul",
    "A3": "opentrons_96_tiprack_300ul",
})

# Start video recording
machine.start_video_recording()

# Perform liquid handling operations
machine.attach_tip(slot="A3", well="G8")
machine.aspirate_from(slot="C2", well="A1", amount=100, height_from_bottom=10.0)
machine.dispense_to(slot="C2", well="B4", amount=100, height_from_bottom=30.0)
machine.drop_tip(slot="C1", well="A1", height_from_bottom=10)

# Stop video recording
machine.stop_video_recording()

# Shutdown the machine (gracefully disconnects all controllers)
machine.shutdown()
```

**Discovering Available Methods**: To explore what methods are available on any class instance, you can use Python's built-in `help()` function:

```python
machine = First()
help(machine)  # See methods for the First machine
help(machine.qubot)  # See GCodeController methods
help(machine.pipette)  # See SartoriusController methods
help(machine.camera)  # See CameraController methods
```

Alternatively, you can read the source code directly in the `src/puda_drivers/` directory.

## Device Support

The following device types are supported:

- **GCode** - G-code compatible motion systems (e.g., QuBot)
- **Sartorius rLINE®** - Electronic pipettes and robotic dispensers
- **Camera** - Webcams and USB cameras for image and video capture

## Logging Best Practices

For production applications, configure logging at the start of your script:

```python
import logging
from puda_drivers.core.logging import setup_logging

# Configure logging first, before initializing devices
setup_logging(
    enable_file_logging=True,
    log_level=logging.INFO,
    log_file_name="experiment"
)

# Now all device operations will be logged
# ... rest of your code
```

This ensures all device communication, movements, and errors are captured in log files for debugging and audit purposes.

## Finding Serial Ports

To discover available serial ports on your system:

```python
from puda_drivers.core import list_serial_ports

# List all available ports
ports = list_serial_ports()
for port, desc, hwid in ports:
    print(f"{port}: {desc} [{hwid}]")

# Filter ports by description
sartorius_ports = list_serial_ports(filter_desc="Sartorius")
```

## Requirements

- Python >= 3.8
- pyserial >= 3.5
- See `pyproject.toml` for full dependency list

## Development

### Setup Development Environment

This package is part of a UV workspace monorepo. First, install `uv` if you haven't already. See the [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/) for platform-specific instructions.

**From the repository root:**

```bash
# Or install dependencies for all workspace packages
uv sync --all-packages
```

This will:
- Create a virtual environment at the repository root (`.venv/`)
- Install all dependencies for all workspace packages
- Install `puda-drivers` and other workspace packages in editable mode automatically

**Using the package:**

```bash
# Run Python scripts with workspace context (recommended, works from anywhere in the workspace)
uv run python your_script.py

# Or activate the virtual environment (from repository root where .venv is located)
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
python your_script.py
```

**Adding dependencies:**

```bash
# From the package directory
cd libs/drivers
uv add some-package

# Or from repository root
uv add --package puda-drivers some-package
```

**Note:** Workspace packages are automatically installed in editable mode, so code changes are immediately available without reinstalling.

### Testing

Run tests using pytest with `uv run`:

```bash
# Run all tests
uv run pytest tests/

# Run a specific test file
uv run pytest tests/test_deck.py

# Run a specific test class
uv run pytest tests/test_deck.py::TestDeckToDict

# Run a specific test function
uv run pytest tests/test_deck.py::TestDeckToDict::test_to_dict_empty_deck

# Run with verbose output
uv run pytest tests/ -v

# Run with coverage report
uv run pytest tests/ --cov=puda_drivers --cov-report=html
```

**Note:** Make sure you're in the `libs/drivers` directory or use the full path to the tests directory when running pytest commands.

### Building and Publishing

```bash
# Build distribution packages
uv build

# cd to puda project root
cd ...

# Publish to PyPI
uv publish
# Username: __token__
# Password: <your PyPI API token>
```

### Version Management

```bash
# Set version explicitly
uv version 0.0.1

# Bump version (e.g., 1.2.3 -> 1.3.0)
uv bump minor
```

## Documentation

- [PyPI Package](https://pypi.org/project/puda-drivers/)
- [GitHub Repository](https://github.com/zhao-bears/puda-drivers)
- [Issue Tracker](https://github.com/zhao-bears/puda-drivers/issues)

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request on GitHub.
