# Measurement plotting

### Plotter

```python
from plotter import (
    plot_measurement,   # Main entry point (auto-routes to correct plotter)
    plot_cv,            # CV forward/backward scatter
    plot_ocv,           # OCV time series
    plot_nyquist,       # PEIS Nyquist plot
    plot_ca,            # CA current vs time
    plot_default,       # Generic scatter of first 2 columns
    get_data_summary,   # Summary statistics
)

# Examples
path = plot_measurement(run_id, "CV")
path = plot_measurement(run_id, "PEIS")  # Routes to nyquist
summary = get_data_summary(run_id)
```

## Supported Data Types

| Type | Status | Plot Function |
|------|--------|---------------|
| CV | ✅ Full | `plot_cv` (forward/backward scatter) |
| OCV | ✅ Full | `plot_ocv` (time series) |
| CA | ✅ Full | `plot_ca` (current vs time) |
| PEIS | ✅ Full | `plot_nyquist` (Z_real vs -Z_imag) |
| GEIS | ✅ Ready | Generic fallback |
