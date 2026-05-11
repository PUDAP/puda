---
name: colour-mixing-image-processing
description: Deterministic image processing pipeline using PIL perspective warp, grid-based ROI slicing, and per-well RGB extraction. No VLM required. Calibrate once with ImageConfig; reuse for every captured image.
---

# Image Processing

**Script**: [../scripts/image_processing.py](../scripts/image_processing.py)  
**Dependencies**: `pip install numpy Pillow`

---

## Design

The camera is in a fixed position. All geometry is calibrated once in `ImageConfig` and reused for every image. No VLM or runtime detection is needed.

```
run_pipeline(image_path, well_ids, config)
    │
    ├── Step 1  find_coeffs(dst_corners, src_corners)              →  8 coefficients
    ├── Step 2  PIL Image.PERSPECTIVE transform                    →  warped image
    ├── Step 3  crop_to_wellplate(warped, crop_box)                →  plate image  (skipped if crop_box=None)
    ├── Step 4  get_grid_dimensions(plate, 12, 8)                  →  cell_w, cell_h
    ├── Step 5  slice_roi_patches(plate, 12, 8, offset_array)      →  96 ROI patches
    ├── Step 6  save_roi_debug_image(...)                          →  <name>_roi_debug.jpg
    └── Step 7  extract_well_rgb(patches, well_ids)                →  {well_id: (R,G,B)}
```

**Well orientation** — standard 96-well plate:

```
       col 1   col 2  …  col 12
row A   A1      A2         A12     ← top-left to top-right
row B   B1      B2         B12
 …
row H   H1      H2         H12     ← bottom-left to bottom-right
```

---

## `ImageConfig` — Calibrated Parameters

| Field | Type | Description |
|---|---|---|
| `src_corners` | `list[(x,y)]` × 4 | Wellplate corners in the **raw** image [TL, TR, BR, BL]. Measure from the actual photo. |
| `dst_corners` | `list[(x,y)]` × 4 | Destination rectangle in the **output** image [TL, TR, BR, BL]. Typically `[(0,0),(W,0),(W,H),(0,H)]`. |
| `plate_width` | int | Width in pixels of the warped output image. |
| `plate_height` | int | Height in pixels of the warped output image. |
| `col_num` | int | Grid columns — `12` for plate columns 1–12 (left → right). |
| `row_num` | int | Grid rows — `8` for plate rows A–H (top → bottom). |
| `offset_array` | `[[xl,xr],[yt,yb]]` | Pixel inset per grid cell — keeps ROI inside the well, away from the rim. |

`output_size` is auto-derived as `(plate_width, plate_height)`.

### Default Calibration (`DEFAULT_CONFIG`)

```python
DEFAULT_CONFIG = ImageConfig(
<<<<<<< Updated upstream
    src_corners=[(274, 237), (374, 238), (374, 303), (274, 302)]
=======
    src_corners=[(270, 238), (373, 237), (369, 303), (274, 301)]
>>>>>>> Stashed changes
    dst_corners=[(0, 0), (1800, 0), (1800, 1200), (0, 1200)],
    plate_width=1800,
    plate_height=1200,
    col_num=12,    # columns 1–12, left → right
    row_num=8,     # rows A–H, top → bottom
    offset_array=[[54, 54], [54, 54]],
)
```

---

## Step 1 — Perspective Coefficients

```
find_coeffs(dst_corners, src_corners)  →  8 floats
```

Solves the 8×8 linear system (via `np.linalg.solve`) that maps the four raw plate corners (`src_corners`) to the flat destination rectangle (`dst_corners`). The 8 coefficients define the projective transform passed to PIL.

---

## Step 2 — Perspective Warp

```
raw image  →  PIL Image.PERSPECTIVE(coeffs)  →  flat plate image
```

PIL applies the coefficients with bicubic interpolation (`Image.BICUBIC`). Result: a clean, upright, undistorted view of the wellplate exactly `plate_width × plate_height` pixels. The default configuration now warps to a higher-resolution `1800 × 1200` output so the corrected plate image and ROI patches are much clearer.

Saved as `<name>_warped.jpg`.

---

## Step 3 — Grid Dimensions

```python
cell_w, cell_h = get_grid_dimensions(plate_np, col_num=12, row_num=8)
# e.g. cell_w = 1800/12 = 150.0 px,  cell_h = 1200/8 = 150.0 px
```

Divides the warped plate image dimensions by the grid counts to get the floating-point size of each well cell. Used by both `slice_roi_patches` and `crop_well`.

---

## Step 4 — ROI Grid Slicing

```
warped plate image  →  slice_roi_patches(plate, 12, 8, offset_array)  →  96 patches + 96 boxes
```

Each cell is shrunk inward by `offset_array` so the ROI sits inside the well and avoids the rim. Patches are in row-major order: A1, A2, …, A12, B1, …, H12.

### Single-well crop

`crop_well(plate_np, "B3", 12, 8, offset_array)` returns `(patch_array, (x1,y1,x2,y2))` for just that well, without slicing the whole grid.

---

## Step 5 — ROI Debug Image

After slicing, `save_roi_debug_image()` draws a **red rectangle** at every ROI patch and labels it with:
- **Well ID** (e.g. `A1`)

```
┌─────────────────────────────────────────────────────────────┐
│  A1  A2  A3  …  A12                                        │
│  B1  B2  …                                                 │
│  …                                                          │
│  H1  …          H12                                         │
└─────────────────────────────────────────────────────────────┘
```

Saved as `<name>_roi_debug.jpg`.

**When RGB results look wrong, inspect this image first.** Misaligned rectangles mean `src_corners` or `offset_array` need adjusting.

---

## Step 6 — RGB Extraction

```python
rgb_values = extract_well_rgb(patches, well_ids=["A1","A2","A3"], col_num=12)
# → {"A1": (210, 45, 30), "A2": (30, 190, 55), "A3": (20, 40, 200)}
```

Uses **median** per channel to suppress outlier pixels (dust, reflections, bubbles).

---

## Usage

```python
from image_processing import run_pipeline, DEFAULT_CONFIG

rgb_values = run_pipeline(
    image_path="colour-RGB-blue_sample-1.jpg",
    well_ids=["A1", "A2", "A3"],
    config=DEFAULT_CONFIG,
    # optional — auto-derived from image_path if omitted:
    # warped_save_path="colour-RGB-blue_sample-1_warped.jpg",
    # roi_debug_save_path="colour-RGB-blue_sample-1_roi_debug.jpg",
)
# → {"A1": (210, 45, 30), "A2": (30, 190, 55), "A3": (20, 40, 200)}
```

### Saved files per run

| File | Description |
|---|---|
| `<name>_warped.jpg` | Full perspective-corrected image (always saved) |
| `<name>_roi_debug.jpg` | Red ROI rectangles + well ID label at every well |

### Re-calibrating `src_corners`

Open the raw camera photo in any image viewer. Hover over each physical corner of the wellplate and read the `(x, y)` pixel coordinates:

```
src_corners = [
    (x_TL, y_TL),   # top-left  corner of the plate
    (x_TR, y_TR),   # top-right
    (x_BR, y_BR),   # bottom-right
    (x_BL, y_BL),   # bottom-left
]
```

`plate_width` and `plate_height` set the output resolution. The default pipeline uses `1800 × 1200` so the warped image is clearer after perspective correction.

The warped image is used directly for ROI extraction. If alignment changes, recalibrate `src_corners`, `plate_width`, `plate_height`, or `offset_array`.

---

## Validation

`validate_results(rgb_values)` checks:

| Check | Condition | Failure action |
|---|---|---|
| RGB range | All R, G, B in 0–255 | `RuntimeError` |
| Colour spread | At least one channel varies by > 10 across active wells | `RuntimeError` — check dispense completed |

Colour-spread validation only runs when more than one well is requested. A single-well extraction is valid and should not fail just because there is nothing to compare it against.

Invalid well IDs are rejected before extraction. Examples:

- `A0` fails because columns start at `1`
- `A13` fails for a 12-column plate
- `Z1` fails for an 8-row plate

---

## Rules

- Recalibrate `src_corners` whenever the camera is physically moved or refocused.
- Capture **one image per iteration** after all dispenses are complete and the pipette arm is clear.
- `run_pipeline()` always saves the warped image and the ROI debug image every call.
- Warped and ROI debug JPEG outputs are saved with higher-quality settings to reduce visible compression blur.
- Custom save paths can point to new directories; parent folders are created automatically.
- Inspect `<name>_roi_debug.jpg` first when RGB results look wrong.
