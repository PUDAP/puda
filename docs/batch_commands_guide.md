# Using Batch Commands with commands.json

This guide teaches you how to use [`batch_commands.py`](../libs/comms/tests/batch_commands.py) to send multiple commands to a machine by creating a [`commands.json`](../libs/comms/tests/commands.json) file.

## Prerequisites

### 1. Install uv

Install `uv` (a modern, fast Python package and project manager written in Rust) by following the official installation guide:

https://docs.astral.sh/uv/getting-started/installation/

### 2. Configure NATS Client

You can configure NATS server URLs in one of two ways:

**Option 1: Environment Variable (Recommended)**

Set the `NATS_SERVERS` environment variable. If you are connected to the ASUS_B8 network, you can either:

**a) Export directly in your shell:**
```bash
export NATS_SERVERS="nats://192.168.50.201:4222,nats://192.168.50.201:4223,nats://192.168.50.201:4224"
```

**b) Or put it in a `.env` file:**
```bash
NATS_SERVERS="nats://192.168.50.201:4222,nats://192.168.50.201:4223,nats://192.168.50.201:4224"
```

Note: If using a `.env` file, make sure your application loads it (e.g., using `python-dotenv` or similar).

**Option 2: Direct Configuration in Code**

Alternatively, you can set the nats servers directly in [`libs/comms/tests/batch_commands.py`](../libs/comms/tests/batch_commands.py) by modifying the `NATS_SERVERS` constant:

```python
NATS_SERVERS = "nats://192.168.50.201:4222,nats://192.168.50.201:4223,nats://192.168.50.201:4224"
```

The environment variable takes precedence over the default constant if both are set.

### 3. Initialize Your Project

Create a new project directory and initialize it with uv:

```bash
uv init --app <project_name>
cd <project_name>
```

### 4. Install Dependencies

Install the required packages:

```bash
uv add puda_drivers puda_comms
```

## Updating Libraries

When the `puda-comms` or `puda-drivers` libraries are updated, you'll need to update your project dependencies to get the latest features and bug fixes.

### Updating with uv

To update the libraries to their latest versions:

```bash
uv sync --upgrade
```

This will:
- Update all dependencies in your `pyproject.toml` to their latest compatible versions
- Update the lock file (`uv.lock`)
- Reinstall packages with the new versions

### Checking Current Versions

To see what versions you currently have installed:

```bash
uv pip list | grep puda
```

Or check your `pyproject.toml` file for the version constraints.

### After Updating

After updating the libraries:

1. **Check for breaking changes**: Review the library changelogs or release notes
2. **Update your code if needed**: Some updates may require changes to your [`batch_commands.py`](../libs/comms/tests/batch_commands.py) or [`commands.json`](../libs/comms/tests/commands.json)
3. **Re-check available commands**: Run `help(First)` again to see if any new commands were added or existing ones changed

## Discovering Available Commands

To find out what commands are available any machine, use Python's built-in `help()` function:

```python
from puda_drivers.machines import First

help(First)
```

This will display all available methods (commands) on the `First` class, including:
- Method names
- Parameter descriptions
- Type hints
- Docstrings

### Example Output

The `help(First)` output will show methods like:
- `load_deck(deck_layout: Dict[str, str])` - Load labware onto the deck
- `attach_tip(slot: str, well: str)` - Attach a tip to the pipette
- `aspirate_from(slot: str, well: str, amount: float, ...)` - Aspirate liquid from a well
- `dispense_to(slot: str, well: str, amount: float, ...)` - Dispense liquid to a well
- `drop_tip(slot: str, well: str, ...)` - Drop the tip into a waste container
- And many more...

## Creating commands.json

The `commands.json` file is a JSON array where each object represents a command to execute. Each command object must have the following structure:

```json
{
  "name": "command_name",
  "params": {
    "param1": "value1",
    "param2": "value2"
  },
  "step_number": 1
}
```

### Required Fields

- **`name`** (string): The name of the command (corresponds to a method name on the `First` class)
- **`params`** (object): A dictionary of parameters to pass to the command
- **`step_number`** (integer): The execution step number (used to track progress)

### Example commands.json

For complete examples of `commands.json` files, refer to the [`libs/comms/tests/commands.json`](../libs/comms/tests/commands.json) file, which shows how to structure commands that load a deck, attach a tip, aspirate, dispense, and drop the tip.

## Using Cursor AI to Generate commands.json

You can use Cursor AI to help generate your [`commands.json`](../libs/comms/tests/commands.json) file! Simply:

1. Run `help(First)` in a Python shell or script
2. Copy the output
3. Paste it into Cursor along with a description of what you want to do
4. Ask Cursor to generate the `commands.json` file based on the help output

Example prompt for Cursor:
```
I want to create a commands.json file that:
1. Loads a deck with a tiprack at A3, a wellplate at C2, and trash at C1
2. Attaches a tip from A3, well G8
3. Aspirates 100ul from C2, well A1
4. Dispenses 100ul to C2, well B4
5. Drops the tip in C1, well A1

Here's the help output from First:
[paste help(First) output here]

Generate the commands.json file for me.
```

## Running Batch Commands

Once you have your [`commands.json`](../libs/comms/tests/commands.json) file ready, you can run [`batch_commands.py`](../libs/comms/tests/batch_commands.py):

```bash
python batch_commands.py
```

Or if using uv:

```bash
uv run batch_commands.py
```

### How It Works

The [`batch_commands.py`](../libs/comms/tests/batch_commands.py) script:

1. Loads commands from `commands.json`
2. Converts them to `CommandRequest` objects
3. Sends them sequentially to the machine using `CommandService.send_queue_commands()`
4. Automatically stops on the first error and returns the error response
5. Returns the last successful response if all commands succeed

### Configuration

You can modify these variables in [`libs/comms/tests/batch_commands.py`](../libs/comms/tests/batch_commands.py):

- `COMMANDS_JSON_PATH`: Path to your commands.json file (defaults to `commands.json` in the same directory)
- `MACHINE_ID`: The ID of the machine to send commands to
- `USER_ID`: A unique identifier for the user (auto-generated UUID by default)
- `USERNAME`: The username of the person running the commands
- `RUN_ID`: A unique identifier for this run (auto-generated UUID by default)

### Example Output

When running successfully, you'll see:

```
2024-01-01 12:00:00 - __main__ - INFO - Starting batch command tests with run_id: abc-123-def
2024-01-01 12:00:01 - __main__ - INFO - Sending batch constructed from dicts (5 commands)...
2024-01-01 12:00:10 - __main__ - INFO - Batch commands completed successfully!
```

## Tips

1. **Parameter Names**: Make sure parameter names in `commands.json` match exactly with the method signatures from `help(First)`

2. **Step Numbers**: Use sequential step numbers (1, 2, 3, ...) to track execution order

3. **Error Handling**: If any command fails, the batch stops immediately and returns the error. Check the logs for details

4. **Labware Names**: Use standard labware names like:
   - `"trash_bin"`
   - `"opentrons_96_tiprack_300ul"`
   - `"polyelectric_8_wellplate_30000ul"`

5. **Slot Format**: Deck slots use a format like `"A1"`, `"C2"`, etc. (4x4 grid: A1-D4)

6. **Well Format**: Wells use formats like `"A1"`, `"G8"`, etc., depending on the labware type

## Troubleshooting

- **Command not found**: Verify the command name matches exactly with a method from `help(First)`
- **Parameter errors**: Check that all required parameters are provided and types match
- **Connection errors**: Ensure the machine is running and accessible via NATS. If connected to ASUS_B8, make sure `NATS_SERVERS` is set to `192.168.50.201`
- **Timeout errors**: Some commands may take longer; check if the machine is responsive

