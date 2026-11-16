# Schemas, device adapters, and custom plotters

### 2. Schema Registry (registry.py)

Maps `(device, command)` → column names, units, plot axes.

```python
from registry import SchemaRegistry, Schema

# Get schema
schema = SchemaRegistry.get("first", "CV")
print(schema.columns)  # ['potential', 'current', 'time', 'extra', 'flag']

# Register new schema
SchemaRegistry.register("mydevice", "CUSTOM", Schema(
    columns=["freq", "magnitude", "phase"],
    units={"freq": "Hz", "magnitude": "dB"},
    primary_x="freq",
    primary_y="magnitude"
))

# Get or create default
schema = SchemaRegistry.get_or_default("unknown", "CV")
```

**Built-in schemas:**

| Device | Command | Columns |
|--------|---------|---------|
| first | CV | potential, current, time, extra, flag |
| first | OCV | potential, current, time, extra, flag |
| first | CA | time, current, voltage, extra, flag |
| first | PEIS | frequency, Z_real, Z_imag, phase, flag |
| biologic | CV | E, I, time, Ewe, flag |
| biologic | PEIS | frequency, Z_real, Z_imag, phase, magnitude |

### 3. Device Adapters (adapters/)

Abstract device-specific data extraction.

```python
from adapters import DeviceAdapter, AdapterRegistry, register_all

register_all()  # Registers first, biologic adapters

# Get adapter for device
adapter = AdapterRegistry.get("biologic")

# Auto-detect device from run
adapter = AdapterRegistry.get_or_default("first")

# Unknown device gets GenericAdapter fallback
adapter = AdapterRegistry.get_or_default("unknown_device")
```

**Adding a new device:**
```python
from adapters import DeviceAdapter, AdapterRegistry

class MyDeviceAdapter(DeviceAdapter):
    @property
    def name(self): return "mydevice"

    def extract_data(self, payload, command):
        # Navigate device-specific payload structure
        data = payload.get("response", {}).get("data", {})
        return pd.DataFrame(data.get("0", []))

AdapterRegistry.register(MyDeviceAdapter())
```

### 4. Plotter Registry (plotter.py)

Pluggable visualization functions.

```python
from plotter import register_plotter, plot_measurement

# Registered plotters: CV, OCV, PEIS, CA
plot_path = plot_measurement(run_id, "CV")  # Auto-routes to correct plotter

# Add custom plotter
@register_plotter("MY_DATA")
def plot_my_data(run_id, **kwargs):
    df = extract_measurement_data(run_id, "MY_DATA")
    plt.plot(df["x"], df["y"])
    return save_plot(...)
```
