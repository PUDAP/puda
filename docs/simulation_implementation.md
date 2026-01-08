# Simulation Implementation Guide

## Overview

This guide provides instructions for implementing simulation versions of hardware controllers in the `puda-drivers` library. Simulation classes allow testing and development without physical hardware while preserving all validation logic and checks. This is especially important because we use LLMs to generate commands - simulation ensures that the sequence of commands work without any errors before executing on real hardware.

**Key Simplification**: Simulation classes assume all commands succeed. You don't need to simulate responses or error conditions - just update internal state and log actions. This makes implementation much simpler than trying to replicate hardware behavior exactly.

## Directory Structure

Create simulation classes in a `/sim` folder that mirrors the main structure:

```
libs/drivers/src/puda_drivers/
├── move/
│   └── gcode.py  (real implementation)
├── transfer/liquid/sartorius/
│   └── rLine.py  (real implementation)
├── cv/
│   └── camera.py  (real implementation)
├── machines/
│   └── first.py  (real implementation)
└── sim/  (NEW - all simulation code here)
    ├── move/
    │   └── gcode.py  (SimGCodeController)
    ├── transfer/
    │   └── liquid/
    │       └── sartorius.py  (SimSartoriusController)
    └── machines/
        └── first.py  (SimFirst)
```

## General Principles

1. **Preserve the Interface**: Simulation classes must implement the exact same public API as their real counterparts
2. **Preserve Validation**: All validation logic (axis limits, speed ranges, etc.) must work identically
3. **Preserve Logging**: Use the same logging patterns and messages
4. **Skip Hardware**: Do NOT open serial ports or communicate with hardware
5. **Track State**: Maintain internal state (position, volume, tip status, etc.) just like real controllers
6. **Assume Success**: Commands always succeed - no need to simulate responses or error conditions. Just update state and log.

## Implementation Checklist

For each controller, you need to:

- [ ] Create the simulation class file in the appropriate `/sim` subdirectory
- [ ] Copy the class signature and all public methods from the real implementation
- [ ] Implement `__init__` without hardware initialization
- [ ] Implement `connect()` / `disconnect()` as no-ops (but log appropriately)
- [ ] Implement all public methods with state tracking
- [ ] Preserve all validation logic
- [ ] Preserve all logging statements
- [ ] Add `__init__.py` files to make modules importable
- [ ] Test that simulation classes can be imported and instantiated

**Components to implement:**
1. ✅ SimGCodeController (`sim/move/gcode.py`)
2. ✅ SimSartoriusController (`sim/transfer/liquid/sartorius.py`)
3. ✅ SimFirst (`sim/machines/first.py`) - Uses SimGCodeController and SimSartoriusController

---

## 1. SimGCodeController (`sim/move/gcode.py`)

### Key Requirements

- **Inherit from**: `SerialController` (but override `connect()` to not actually connect)
- **State to Track**:
  - `_current_position`: Position object (x, y, z, a)
  - `_axis_limits`: Dict[str, AxisLimits]
  - `_feed`: Current feed rate
  - `_z_feed`: Z-axis feed rate
- **Methods to Implement**:
  - `connect()`: Set `_is_connected = True` without opening serial port
  - `disconnect()`: Set `_is_connected = False`
  - `execute()`: Parse commands and update state accordingly (don't send to hardware)
  - `home()`: Reset `_current_position` to (0, 0, 0, 0)
  - `move_absolute()`: Validate limits, update `_current_position`
  - `move_relative()`: Convert to absolute, validate, update position
  - `get_position()`: Return `_current_position` (async, but can be sync in sim)
  - `set_axis_limits()`: Store limits (preserve validation)
  - `get_axis_limits()`: Return stored limits
  - `get_internal_position()`: Return `_current_position.copy()`

### Implementation Notes

- `execute()` can be simplified: **Assume all commands succeed**. You don't need to parse commands or return specific responses. Just log the command and return a simple success indicator (e.g., `"ok"`). For `M114` (get position), return a formatted string based on `_current_position`.
- For `move_absolute()` and `move_relative()`:
  - Call `_validate_move_positions()` (preserve validation)
  - Update `_current_position` immediately (no actual movement)
  - Log the movement as if it happened
  - Skip calling `execute()` - just update state directly
- `_execute_move()` should update position state directly without calling `execute()`
- `_wait_for_move()` should be a no-op (just log)

### Example Structure

```python
from puda_drivers.core.serialcontroller import SerialController
from puda_drivers.core.position import Position
from puda_drivers.move.gcode import AxisLimits
import logging
from typing import Optional, Dict

class SimGCodeController(SerialController):
    """Simulation version of GCodeController."""
    
    # Copy all constants from GCodeController
    DEFAULT_FEEDRATE = 3000
    MAX_FEEDRATE = 3000
    MAX_Z_FEED_RATE = 1000
    TOLERANCE = 0.01
    SAFE_MOVE_HEIGHT = -5
    VALID_AXES = "XYZA"
    
    def __init__(self, port_name=None, baudrate=9600, timeout=30, feed=3000, z_feed=1000):
        # Don't call super().__init__() - we don't want serial port initialization
        # Instead, manually set attributes
        self.port_name = port_name
        self.baudrate = baudrate
        self.timeout = timeout
        self._is_connected = False  # Start disconnected
        self._logger = logging.getLogger(__name__)
        
        # Initialize state
        self._current_position = Position(x=0.0, y=0.0, z=0.0, a=0.0)
        self._feed = feed
        self._z_feed = z_feed
        self._axis_limits = {
            "X": AxisLimits(0, 0),
            "Y": AxisLimits(0, 0),
            "Z": AxisLimits(0, 0),
            "A": AxisLimits(0, 0),
        }
        
        self._logger.info("SimGCodeController initialized (SIMULATION MODE)")
    
    def connect(self):
        """Simulate connection without opening serial port."""
        if self._is_connected:
            self._logger.warning("Already connected")
            return
        self._is_connected = True
        self._logger.info("Simulated connection established")
    
    def disconnect(self):
        """Simulate disconnection."""
        self._is_connected = False
        self._logger.info("Simulated disconnection")
    
    @property
    def is_connected(self):
        return self._is_connected
    
    def execute(self, command: str, value: Optional[str] = None) -> str:
        """Simulate command execution without hardware."""
        # Assume command always succeeds - no need to parse or simulate responses
        # Just log and return "ok" for most commands
        # For M114 (get position), return formatted position string
        self._logger.info("Simulated command: %s", command)
        if "M114" in command.upper():
            # Return position query result
            pos = self._current_position
            return f"X:{pos.x:.1f} Y:{pos.y:.1f} Z:{pos.z:.1f} A:{pos.a:.1f}"
        return "ok"  # All other commands succeed
    
    # ... implement all other methods ...
```

---

## 2. SimSartoriusController (`sim/transfer/liquid/sartorius.py`)

### Key Requirements

- **Inherit from**: `SerialController` (but override `connect()` to not actually connect)
- **State to Track**:
  - `_tip_attached`: bool
  - `_volume`: int (current volume in µL)
  - `_inward_speed`: int (1-6)
  - `_outward_speed`: int (1-6)
  - `_position`: int (current piston position in steps)
- **Methods to Implement**:
  - `connect()`: Set `_is_connected = True` without opening serial port
  - `disconnect()`: Set `_is_connected = False`
  - `initialize()`: Reset state (`_tip_attached = False`, `_volume = 0`)
  - `aspirate(amount)`: Validate amount > 0, update `_volume += amount`, update `_position`
  - `dispense(amount)`: Validate amount > 0, update `_volume -= amount`, update `_position`
  - `eject_tip()`: Set `_tip_attached = False`
  - `set_tip_attached()`: Update `_tip_attached`
  - `is_tip_attached()`: Return `_tip_attached`
  - `get_position()`: Return `_position` (async, but can be sync in sim)
  - `set_inward_speed()` / `get_inward_speed()`: Store/return speed (preserve validation)
  - `set_outward_speed()` / `get_outward_speed()`: Store/return speed (preserve validation)
  - `get_status()`: Return simulated status JSON
  - `get_liquid_level()`: Return simulated liquid level
  - `run_to_position()`: Update `_position` (preserve validation)
  - `run_blowout()`: No-op (just log)

### Implementation Notes

- `execute()` can be simplified: **Assume all commands succeed**. You don't need to parse commands or return specific responses. Just log the command and return a simple success indicator. For query commands (`DP`, `DS`, `DI`, `DO`), return appropriate values based on internal state.
- **Important**: Methods like `aspirate()`, `dispense()`, `initialize()` should update state directly without calling `execute()`. Only implement `execute()` if other code calls it directly.
- Preserve all validation:
  - Speed must be 1-6 (`_validate_speed()`)
  - Amount must be > 0
  - No leading zeros in position values
- Volume tracking: `aspirate()` increases `_volume`, `dispense()` decreases it
- Position tracking: Convert µL to steps using `MICROLITER_PER_STEP = 0.5`

### Example Structure

```python
from puda_drivers.core.serialcontroller import SerialController
import logging
from typing import Optional
import json

class SimSartoriusController(SerialController):
    """Simulation version of SartoriusController."""
    
    # Copy all constants
    DEFAULT_BAUDRATE = 9600
    DEFAULT_TIMEOUT = 10
    MICROLITER_PER_STEP = 0.5
    MIN_SPEED = 1
    MAX_SPEED = 6
    
    def __init__(self, port_name=None, baudrate=9600, timeout=10):
        # Don't call super().__init__() - we don't want serial port initialization
        self.port_name = port_name
        self.baudrate = baudrate
        self.timeout = timeout
        self._is_connected = False
        self._logger = logging.getLogger(__name__)
        
        # Initialize state
        self._tip_attached = False
        self._volume = 0  # µL
        self._position = 0  # steps
        self._inward_speed = 3  # default
        self._outward_speed = 3  # default
        
        self._logger.info("SimSartoriusController initialized (SIMULATION MODE)")
    
    def connect(self):
        """Simulate connection without opening serial port."""
        self._is_connected = True
        self._logger.info("Simulated connection established")
    
    def disconnect(self):
        """Simulate disconnection."""
        self._is_connected = False
        self._logger.info("Simulated disconnection")
    
    def aspirate(self, amount: int):
        """Simulate aspiration - update state without hardware."""
        if amount <= 0:
            raise ValueError(f"Aspiration amount must be positive, got {amount}")
        
        steps = int(amount / self.MICROLITER_PER_STEP)
        self._logger.info("** Aspirating %s uL (RI%s steps) **", amount, steps)
        
        # Update state directly - no need to call execute()
        self._volume += amount
        self._position += steps
        
        self._logger.info("** Aspirated %s uL Successfully **\n", amount)
    
    def execute(self, command: str, value: Optional[str] = None) -> str:
        """Simulate command execution - assume all commands succeed."""
        # Only needed if other code calls execute() directly
        # For most methods, update state directly instead of calling execute()
        self._logger.info("Simulated command: %s", command)
        if command == "DP":  # Get position
            return str(self._position)
        elif command == "DS":  # Get status
            return "1"  # Return a status code
        elif command == "DI":  # Get inward speed
            return str(self._inward_speed)
        elif command == "DO":  # Get outward speed
            return str(self._outward_speed)
        return "ok"  # All other commands succeed
    
    # ... implement all other methods ...
```

---

## 3. SimFirst (`sim/machines/first.py`)

### Key Requirements

- **Inherit from**: No base class (First doesn't inherit from anything)
- **Key Difference**: Use simulation controllers instead of real ones (no camera controller)
- **State**: Same as real First (deck, controllers, constants) - but without camera
- **Methods**: Most methods remain identical - they delegate to simulation controllers. Camera-related methods can be removed or made no-ops.

### Implementation Strategy

**The key insight**: `SimFirst` is almost identical to `First`, except it uses simulation controllers instead of real ones. Most of the logic stays the same since it's coordination logic, not hardware communication. **Note**: Camera functionality is not needed in simulation.

### Implementation Notes

1. **Import simulation controllers** (no camera):
   ```python
   from puda_drivers.sim.move import SimGCodeController
   from puda_drivers.sim.transfer.liquid.sartorius import SimSartoriusController
   ```

2. **In `__init__()`**: Replace controller initialization (skip camera):
   ```python
   # Real First does:
   self.qubot = GCodeController(port_name=qubot_port or self.DEFAULT_QUBOT_PORT)
   self.camera = CameraController(camera_index=camera_index or self.DEFAULT_CAMERA_INDEX)
   
   # SimFirst does:
   self.qubot = SimGCodeController(port_name=qubot_port or self.DEFAULT_QUBOT_PORT)
   # Skip camera initialization - not needed for simulation
   ```

3. **All other methods stay the same**: Since `First` delegates to controllers, and simulation controllers have the same interface, all the coordination logic (`attach_tip()`, `aspirate_from()`, etc.) works without changes.

4. **Preserve all constants**: Copy all class constants (`DEFAULT_AXIS_LIMITS`, `SLOT_ORIGINS`, `CEILING_HEIGHT`, etc.)

5. **Preserve all validation**: All validation logic in `First` methods should remain identical

6. **Preserve logging**: Keep all logging statements

### Example Structure

```python
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Tuple, Type, Union
import numpy as np

from puda_drivers.move import Deck  # Deck is not hardware-specific, use real one
from puda_drivers.core import Position
from puda_drivers.labware import StandardLabware

# Import simulation controllers
from puda_drivers.sim.move import SimGCodeController
from puda_drivers.sim.transfer.liquid.sartorius import SimSartoriusController
from puda_drivers.sim.cv import SimCameraController


class SimFirst:
    """
    Simulation version of First machine class.
    
    Uses simulation controllers instead of real hardware controllers.
    All coordination logic remains identical.
    """
    
    # Copy all constants from First
    DEFAULT_QUBOT_PORT = "/dev/ttyACM0"
    DEFAULT_QUBOT_BAUDRATE = 9600
    DEFAULT_QUBOT_FEEDRATE = 3000
    
    DEFAULT_SARTORIUS_PORT = "/dev/ttyUSB0"
    DEFAULT_SARTORIUS_BAUDRATE = 9600
    
    DEFAULT_CAMERA_INDEX = 0
    
    Z_ORIGIN = Position(x=0, y=0, z=0)
    A_ORIGIN = Position(x=60, y=0, a=0)
    
    DEFAULT_AXIS_LIMITS = {
        "X": (0, 330),
        "Y": (-440, 0),
        "Z": (-140, 0),
        "A": (-175, 0),
    }
    
    CEILING_HEIGHT = 192.2
    TIP_LENGTH = 59
    
    SLOT_ORIGINS = {
        "A1": Position(x=-2, y=-424),
        "A2": Position(x=98, y=-424),
        # ... copy all slot origins ...
    }
    
    def __init__(
        self,
        qubot_port: Optional[str] = None,
        sartorius_port: Optional[str] = None,
        axis_limits: Optional[Dict[str, Tuple[float, float]]] = None,
    ):
        """Initialize SimFirst with simulation controllers (no camera)."""
        # Initialize deck (not hardware-specific)
        self.deck = Deck(rows=4, cols=4)
        
        # Initialize SIMULATION controllers
        self.qubot = SimGCodeController(
            port_name=qubot_port or self.DEFAULT_QUBOT_PORT,
        )
        
        # Set axis limits
        limits = axis_limits or self.DEFAULT_AXIS_LIMITS
        for axis, (min_val, max_val) in limits.items():
            self.qubot.set_axis_limits(axis, min_val, max_val)
        
        # Initialize simulation pipette
        self.pipette = SimSartoriusController(
            port_name=sartorius_port or self.DEFAULT_SARTORIUS_PORT,
        )
        
        # Camera not needed for simulation - skip initialization
        
        # Initialize logger
        self._logger = logging.getLogger(__name__)
        self._logger.info(
            "SimFirst machine initialized (SIMULATION MODE) with qubot_port='%s', sartorius_port='%s'",
            qubot_port or self.DEFAULT_QUBOT_PORT,
            sartorius_port or self.DEFAULT_SARTORIUS_PORT,
        )
    
    # Copy ALL methods from First - they should work identically
    # since they delegate to controllers with the same interface
    
    def startup(self):
        """Start up the machine - same as First (without camera)."""
        self._logger.info("Starting up machine and connecting all controllers")
        self.qubot.connect()
        self.pipette.connect()
        # Camera not needed for simulation
        self._logger.info("All controllers connected successfully")
        
        self._logger.info("Homing gantry...")
        self.qubot.home()
        
        self._logger.info("Initializing pipette...")
        self.pipette.initialize()
        # In simulation, you can skip the sleep or make it very short
        # time.sleep(5)  # Optional: keep for realistic timing, or remove
        self._logger.info("Machine startup complete - ready for operations")
    
    def shutdown(self):
        """Shut down the machine - same as First (without camera)."""
        self._logger.info("Shutting down machine and disconnecting all controllers")
        self.qubot.disconnect()
        self.pipette.disconnect()
        # Camera not needed for simulation
        self._logger.info("Machine shutdown complete")
    
    # ... copy all other methods from First exactly as they are ...
    # attach_tip, drop_tip, aspirate_from, dispense_to, etc.
    # They all work the same because they use self.qubot, self.pipette
    # which are simulation controllers with the same interface
    # 
    # Note: Camera-related methods (capture_image, start_video_recording, etc.)
    # can be removed or made no-ops if not needed
```

### Key Points

1. **Deck stays real**: `Deck` is not hardware-specific, so use the real `Deck` class
2. **Controllers are simulation**: Use `SimGCodeController` and `SimSartoriusController` (no camera needed)
3. **All methods stay the same**: Since simulation controllers have the same interface, all coordination methods (`attach_tip()`, `aspirate_from()`, etc.) work without modification
4. **Camera methods**: Camera-related methods (`capture_image()`, `start_video_recording()`, etc.) can be removed or made no-ops
5. **Optional timing**: You can remove or reduce `time.sleep()` calls in simulation mode for faster testing
6. **Preserve everything else**: All constants, slot origins, position calculations, validation, and logging stay identical

### Testing

```python
from puda_drivers.sim.machines import SimFirst

# Create simulation machine
machine = SimFirst()

# All operations work the same
machine.startup()
machine.load_labware("A1", "Opentrons96TipRack300")
machine.attach_tip("A1", "A1")
machine.aspirate_from("B1", "A1", amount=100)
machine.dispense_to("C1", "A1", amount=100)
machine.shutdown()
```

---

## Testing Checklist

After implementing each simulation class:

1. **Import Test**: Can you import the class?
   ```python
   from puda_drivers.sim.move import SimGCodeController
   ```

2. **Instantiation Test**: Can you create an instance?
   ```python
   controller = SimGCodeController()
   ```

3. **Basic Operations**: Do basic operations work?
   ```python
   controller.connect()
   controller.set_axis_limits("X", 0, 100)
   controller.home()
   pos = controller.move_absolute(Position(x=10, y=20))
   ```

4. **Validation Test**: Do validation errors still occur?
   ```python
   controller.set_axis_limits("X", 0, 100)
   controller.move_absolute(Position(x=150))  # Should raise ValueError
   ```

5. **State Tracking**: Does state update correctly?
   ```python
   controller.home()
   assert controller.get_internal_position().x == 0.0
   controller.move_absolute(Position(x=50))
   assert controller.get_internal_position().x == 50.0
   ```

---

## Creating `__init__.py` Files

Create `__init__.py` files to make modules importable:

**`sim/__init__.py`**:
```python
# Simulation modules
```

**`sim/move/__init__.py`**:
```python
from .gcode import SimGCodeController

__all__ = ["SimGCodeController"]
```

**`sim/transfer/__init__.py`**:
```python
# Transfer simulation modules
```

**`sim/transfer/liquid/__init__.py`**:
```python
# Liquid transfer simulation modules
```

**`sim/transfer/liquid/sartorius/__init__.py`**:
```python
from .sartorius import SimSartoriusController

__all__ = ["SimSartoriusController"]
```

**`sim/machines/__init__.py`**:
```python
from .first import SimFirst

__all__ = ["SimFirst"]
```

---

## Questions?

If you encounter issues or need clarification:

1. Check the real implementation for method signatures and behavior
2. Ensure all validation logic is preserved
3. Ensure all logging statements are preserved
4. Test that simulation classes can be used as drop-in replacements

Remember: The goal is to make simulation classes behave identically to real controllers, except they don't communicate with hardware.

