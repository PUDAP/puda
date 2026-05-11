"""
Image processing pipeline for colour mixing experiments.

Fixed-geometry approach — no VLM required. The camera is mounted in a fixed
position above the OT-2 deck. All geometric parameters are calibrated once
and stored in ImageConfig; every captured image uses the same values.

Pipeline (applied to every captured image):
    Step 1 — Compute 8 perspective coefficients from src_corners → plate rectangle.
    Step 2 — Apply PIL Image.PERSPECTIVE → flat, undistorted wellplate image.
    Step 3 — Compute grid cell dimensions from the plate image size.
    Step 4 — Slice grid → one ROI patch per well (all 96 wells).
    Step 5 — Save ROI debug overlay (red rectangles + well ID + W×H label).
    Step 6 — Extract median RGB for each requested well by ID.

Standard 96-well plate orientation:
    - Columns 1–12 run left → right in the image.
    - Rows A–H run top → bottom in the image.
    So well A1 is top-left and H12 is bottom-right.

Dependencies:
    pip install numpy Pillow
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont


# ---------------------------------------------------------------------------
# Image configuration dataclass
# ---------------------------------------------------------------------------

@dataclass
class ImageConfig:
    """
    Fixed geometric parameters for one camera-and-plate setup.

    Calibrate these values once for the physical rig; reuse for every image.

    Perspective correction:
        src_corners:  Four wellplate corners in the RAW image, ordered
                      [TL, TR, BR, BL], each as (x, y) in pixels.
                      Measure these from the raw captured photo.
        dst_corners:  Corresponding destination rectangle in the OUTPUT image,
                      ordered [TL, TR, BR, BL]. Typically starts at (0, 0)
                      and spans the full plate_width × plate_height area.
        plate_width:  Width in pixels of the warped output image.
        plate_height: Height in pixels of the warped output image.

    ROI grid (applied to the warped plate image):
        col_num:      Columns in the grid. 12 for a 96-well plate (cols 1–12).
        row_num:      Rows in the grid. 8 for a 96-well plate (rows A–H).
        offset_array: [[x_pad_left, x_pad_right], [y_pad_top, y_pad_bottom]]
                      Pixel inset per grid cell — keeps the ROI inside the well
                      and away from the rim.
    """
    src_corners: list[tuple[int, int]]
    dst_corners: list[tuple[int, int]]
    plate_width: int
    plate_height: int
    col_num: int
    row_num: int
    offset_array: list[list[int]]

    @property
    def output_size(self) -> tuple[int, int]:
        """(width, height) of the PIL perspective transform output."""
        return (self.plate_width, self.plate_height)


# Default calibration for the standard OT-2 camera rig.
# Adjust src_corners if the camera is repositioned.
# Adjust plate_width/plate_height to control warp output resolution.
DEFAULT_CONFIG = ImageConfig(
    src_corners=[(276, 235), (376, 236), (376, 301), (276, 300)],
    dst_corners=[(0, 0), (1800, 0), (1800, 1200), (0, 1200)],
    plate_width=1800,
    plate_height=1200,
    col_num=12,    # columns 1–12, left → right
    row_num=8,     # rows A–H, top → bottom
    offset_array=[[54, 54], [54, 54]],
)


def load_config_override(config_path: str | None = None) -> ImageConfig:
    """
    Load an ImageConfig override from JSON, falling back to DEFAULT_CONFIG.

    Expected JSON keys match ImageConfig fields. If config_path is omitted,
    use env var PUDA_IMAGE_CONFIG when present. Missing file -> DEFAULT_CONFIG.
    """
    path = config_path or os.environ.get("PUDA_IMAGE_CONFIG")
    if not path:
        return DEFAULT_CONFIG
    if not os.path.exists(path):
        return DEFAULT_CONFIG

    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    return ImageConfig(
        src_corners=[tuple(point) for point in data.get("src_corners", DEFAULT_CONFIG.src_corners)],
        dst_corners=[tuple(point) for point in data.get("dst_corners", DEFAULT_CONFIG.dst_corners)],
        plate_width=int(data.get("plate_width", DEFAULT_CONFIG.plate_width)),
        plate_height=int(data.get("plate_height", DEFAULT_CONFIG.plate_height)),
        col_num=int(data.get("col_num", DEFAULT_CONFIG.col_num)),
        row_num=int(data.get("row_num", DEFAULT_CONFIG.row_num)),
        offset_array=[
            [int(value) for value in row]
            for row in data.get("offset_array", DEFAULT_CONFIG.offset_array)
        ],
    )


# ---------------------------------------------------------------------------
# Perspective correction (PIL-based)
# ---------------------------------------------------------------------------

def find_coeffs(
    pa: list[tuple[int, int]],
    pb: list[tuple[int, int]],
) -> list[float]:
    """
    Compute 8 perspective transformation coefficients for PIL Image.PERSPECTIVE.

    Solves the 8×8 linear system that maps source points (pb, raw image) to
    destination points (pa, flat output). Pass the result directly to
    img.transform(..., Image.PERSPECTIVE, coeffs, Image.BICUBIC).

    Args:
        pa: Four points in the OUTPUT image (destination rectangle).
        pb: Four corresponding points in the INPUT image (wellplate corners).

    Returns:
        List of 8 floats for PIL img.transform().
    """
    matrix = []
    for p1, p2 in zip(pa, pb):
        matrix.append([p1[0], p1[1], 1, 0, 0, 0, -p2[0] * p1[0], -p2[0] * p1[1]])
        matrix.append([0, 0, 0, p1[0], p1[1], 1, -p2[1] * p1[0], -p2[1] * p1[1]])
    A = np.array(matrix, dtype=np.float64)
    B = np.array(pb, dtype=np.float64).reshape(8)
    return np.linalg.solve(A, B).tolist()


# ---------------------------------------------------------------------------
# Grid dimensions
# ---------------------------------------------------------------------------

def get_grid_dimensions(
    plate_np: np.ndarray,
    col_num: int,
    row_num: int,
) -> tuple[float, float]:
    """
    Compute the pixel dimensions of one grid cell in the plate image.

    After warping (and optional crop), the plate image is divided into
    row_num × col_num equal cells. This function returns the floating-point
    width and height of each cell.

    Args:
        plate_np: Flat plate image (after warp + optional crop) as NumPy array.
        col_num:  Number of columns in the grid (e.g. 12).
        row_num:  Number of rows in the grid (e.g. 8).

    Returns:
        (cell_w, cell_h) — pixel dimensions of one grid cell (float).
    """
    h, w = plate_np.shape[:2]
    return w / col_num, h / row_num


def _validate_roi_box(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    well_label: str,
) -> None:
    """Fail fast when ROI padding would produce an empty or inverted crop."""
    if x1 >= x2 or y1 >= y2:
        raise ValueError(
            f"Invalid ROI for {well_label}: box ({x1}, {y1}, {x2}, {y2}) is empty. "
            "Check offset_array, crop_box, and output geometry."
        )


# ---------------------------------------------------------------------------
# ROI grid slicing
# ---------------------------------------------------------------------------

def slice_roi_patches(
    plate_np: np.ndarray,
    col_num: int,
    row_num: int,
    offset_array: list[list[int]],
) -> tuple[list[np.ndarray], list[tuple[int, int, int, int]]]:
    """
    Divide the flat plate image into a grid and extract one ROI patch per well.

    Each grid cell is shrunk inward by offset_array to avoid the well rim.
    Patches are returned in row-major order: A1, A2, …, A12, B1, B2, …, H12.

    Args:
        plate_np:     Flat plate image (after warp + optional crop), (H, W, 3).
        col_num:      Number of grid columns (12 for cols 1–12).
        row_num:      Number of grid rows (8 for rows A–H).
        offset_array: [[x_pad_left, x_pad_right], [y_pad_top, y_pad_bottom]].

    Returns:
        patches:   List of ROI arrays in row-major order (96 items for 96-well).
        roi_boxes: List of (x1, y1, x2, y2) for each patch — used by the debug image.
    """
    cell_w, cell_h = get_grid_dimensions(plate_np, col_num, row_num)
    x_pad_l, x_pad_r = offset_array[0]
    y_pad_t, y_pad_b = offset_array[1]

    patches: list[np.ndarray] = []
    roi_boxes: list[tuple[int, int, int, int]] = []

    for row in range(row_num):
        for col in range(col_num):
            x1 = int(cell_w * col) + x_pad_l
            x2 = int(cell_w * (col + 1)) - x_pad_r
            y1 = int(cell_h * row) + y_pad_t
            y2 = int(cell_h * (row + 1)) - y_pad_b
            well_id = f"{chr(ord('A') + row)}{col + 1}"
            _validate_roi_box(x1, y1, x2, y2, well_id)
            patches.append(plate_np[y1:y2, x1:x2])
            roi_boxes.append((x1, y1, x2, y2))

    return patches, roi_boxes


# ---------------------------------------------------------------------------
# Well slot mapping and single-well crop
# ---------------------------------------------------------------------------

def well_to_grid_pos(well_id: str) -> tuple[int, int]:
    """
    Convert a well identifier to its (image_row, image_col) grid position.

    Standard orientation — columns 1–12 run left→right, rows A–H run top→bottom:
        A1  → (row=0, col=0)   top-left
        A12 → (row=0, col=11)  top-right
        H1  → (row=7, col=0)   bottom-left
        H12 → (row=7, col=11)  bottom-right

    Args:
        well_id: Well identifier, e.g. "A1", "B3", "H12".

    Returns:
        (image_row, image_col) zero-based grid indices.

    Raises:
        ValueError: If the format is invalid.
    """
    if len(well_id) < 2 or not well_id[0].isalpha() or not well_id[1:].isdigit():
        raise ValueError(f"Invalid well_id '{well_id}'. Expected format e.g. 'A1'.")
    image_row = ord(well_id[0].upper()) - ord('A')   # A→0 … H→7
    image_col = int(well_id[1:]) - 1                 # 1→0 … 12→11
    return image_row, image_col


def _validate_well_in_bounds(
    well_id: str,
    image_row: int,
    image_col: int,
    col_num: int,
    row_num: int,
) -> None:
    """Validate that a parsed well lies within the configured plate grid."""
    if not (0 <= image_row < row_num):
        last_row = chr(ord("A") + row_num - 1)
        raise ValueError(
            f"Invalid well_id '{well_id}'. Row must be between A and {last_row}."
        )
    if not (0 <= image_col < col_num):
        raise ValueError(
            f"Invalid well_id '{well_id}'. Column must be between 1 and {col_num}."
        )


def well_to_roi_index(well_id: str, col_num: int, row_num: int = 8) -> int:
    """
    Convert a well identifier to its flat index in the patches list.

    Patches are stored in row-major order (A1=0, A2=1, …, A12=11, B1=12, …).

    Args:
        well_id:  Well identifier, e.g. "A1", "B3", "H12".
        col_num:  Number of grid columns (12 for a 96-well plate).
        row_num:  Number of grid rows (8 for a 96-well plate). Default: 8.

    Returns:
        Integer index into the patches list from slice_roi_patches().
    """
    image_row, image_col = well_to_grid_pos(well_id)
    _validate_well_in_bounds(well_id, image_row, image_col, col_num, row_num)
    return image_row * col_num + image_col


def crop_well(
    plate_np: np.ndarray,
    well_id: str,
    col_num: int,
    row_num: int,
    offset_array: list[list[int]],
) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """
    Crop a single named well from the flat plate image.

    Computes the well's pixel bounding box from the grid dimensions, applies
    the offset_array inset, and returns the patch array and its box.

    Args:
        plate_np:     Flat plate image (after warp + optional crop), (H, W, 3).
        well_id:      Well identifier, e.g. "A1", "B3", "H12".
        col_num:      Number of grid columns (12).
        row_num:      Number of grid rows (8).
        offset_array: [[x_pad_left, x_pad_right], [y_pad_top, y_pad_bottom]].

    Returns:
        (patch, (x1, y1, x2, y2)) — the well's ROI array and its bounding box
        in plate_np coordinates.
    """
    cell_w, cell_h = get_grid_dimensions(plate_np, col_num, row_num)
    image_row, image_col = well_to_grid_pos(well_id)
    _validate_well_in_bounds(well_id, image_row, image_col, col_num, row_num)

    x_pad_l, x_pad_r = offset_array[0]
    y_pad_t, y_pad_b = offset_array[1]

    x1 = int(cell_w * image_col) + x_pad_l
    x2 = int(cell_w * (image_col + 1)) - x_pad_r
    y1 = int(cell_h * image_row) + y_pad_t
    y2 = int(cell_h * (image_row + 1)) - y_pad_b
    _validate_roi_box(x1, y1, x2, y2, well_id)

    return plate_np[y1:y2, x1:x2], (x1, y1, x2, y2)


# ---------------------------------------------------------------------------
# ROI debug visualisation
# ---------------------------------------------------------------------------

def save_roi_debug_image(
    plate_np: np.ndarray,
    roi_boxes: list[tuple[int, int, int, int]],
    save_path: str,
    col_num: int,
    row_num: int,
    outline_colour: tuple[int, int, int] = (220, 30, 30),
    outline_width: int = 2,
    font_size: int = 9,
) -> str:
    """
    Draw red rectangles over every ROI patch on the flat plate image and label
    each with its pixel dimensions (W×H) and well ID (e.g. A1).

    Args:
        plate_np:      Flat plate image as NumPy array (H, W, 3) in RGB.
        roi_boxes:     List of (x1, y1, x2, y2) from slice_roi_patches().
        save_path:     File path to save the annotated image.
        col_num:       Number of grid columns (needed to derive well IDs).
        row_num:       Number of grid rows (needed to derive well IDs).
        outline_colour: RGB colour of the rectangle outlines. Default: red.
        outline_width: Border thickness in pixels.
        font_size:     Font size for labels.

    Returns:
        save_path, so the caller can log it.
    """
    debug_pil = Image.fromarray(plate_np.astype(np.uint8))
    draw = ImageDraw.Draw(debug_pil)

    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except (OSError, IOError):
        font = ImageFont.load_default()

    rows = "ABCDEFGH"
    for idx, (x1, y1, x2, y2) in enumerate(roi_boxes):
        row_idx = idx // col_num
        col_idx = idx % col_num
        well_id = f"{rows[row_idx]}{col_idx + 1}"
        patch_w, patch_h = x2 - x1, y2 - y1
        label = f"{well_id} {patch_w}×{patch_h}"

        draw.rectangle([x1, y1, x2, y2], outline=outline_colour, width=outline_width)
        draw.text((x1 + 1, y1 + 1), label, fill=outline_colour, font=font)

    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    save_pil_image(debug_pil, save_path)
    return save_path


def save_pil_image(image: Image.Image, save_path: str) -> None:
    """
    Save an image with higher-quality settings for JPEG outputs.

    Perspective-corrected plate images and ROI debug images are often inspected
    visually, so avoid low-quality default JPEG settings that can make the
    warped image appear soft or blocky.
    """
    suffix = os.path.splitext(save_path)[1].lower()
    if suffix in {".jpg", ".jpeg"}:
        image.save(save_path, quality=95, subsampling=0, optimize=True)
    else:
        image.save(save_path)


# ---------------------------------------------------------------------------
# RGB extraction
# ---------------------------------------------------------------------------

def mean_rgb(patch: np.ndarray) -> tuple[int, int, int]:
    """
    Compute the median RGB of a well ROI patch.

    Uses median instead of mean to suppress outlier pixels (dust, reflections).

    Args:
        patch: ROI patch as NumPy array (H, W, 3) in RGB.

    Returns:
        (R, G, B) median values as integers 0–255.
    """
    return (
        int(np.median(patch[:, :, 0])),
        int(np.median(patch[:, :, 1])),
        int(np.median(patch[:, :, 2])),
    )


def extract_well_rgb(
    patches: list[np.ndarray],
    well_ids: list[str],
    col_num: int,
) -> dict[str, tuple[int, int, int]]:
    """
    Extract the median RGB value for each specified well.

    Args:
        patches:  Full list of ROI patches from slice_roi_patches() — all wells.
        well_ids: List of well identifiers, e.g. ["A1", "A2", "A3"].
        col_num:  Number of grid columns used during slicing (12).

    Returns:
        Dict mapping each well_id to its (R, G, B) median tuple.
    """
    if col_num <= 0:
        raise ValueError("col_num must be positive.")
    if len(patches) % col_num != 0:
        raise ValueError(
            f"Expected patches length to be divisible by col_num, got "
            f"{len(patches)} patches for {col_num} columns."
        )

    row_num = len(patches) // col_num
    rgb_values: dict[str, tuple[int, int, int]] = {}
    for wid in well_ids:
        image_row, image_col = well_to_grid_pos(wid)
        _validate_well_in_bounds(wid, image_row, image_col, col_num, row_num)
        rgb_values[wid] = mean_rgb(patches[image_row * col_num + image_col])
    return rgb_values


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_results(
    rgb_values: dict[str, tuple[int, int, int]],
    min_colour_spread: int = 10,
) -> tuple[bool, list[str]]:
    """
    Validate that extracted RGB values are plausible.

    Checks:
        1. RGB range   — all channel values in 0–255.
        2. Colour spread — at least one channel varies by > min_colour_spread
                          across active wells (confirms mixes were dispensed).

    Args:
        rgb_values:        {well_id: (R, G, B)} from extract_well_rgb().
        min_colour_spread: Minimum inter-well channel range. Default: 10.

    Returns:
        (passed, failures) — passed is True when all checks pass.
    """
    failures: list[str] = []

    for wid, (r, g, b) in rgb_values.items():
        if not (0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255):
            failures.append(f"Well {wid}: RGB ({r},{g},{b}) out of 0–255 range.")

    if len(rgb_values) > 1:
        per_channel = list(zip(*rgb_values.values()))
        for ch in per_channel:
            if (max(ch) - min(ch)) >= min_colour_spread:
                break
        else:
            failures.append(
                f"All active wells have nearly identical colours "
                f"(spread < {min_colour_spread} on every channel). "
                "Check that mixes were actually dispensed."
            )

    return len(failures) == 0, failures


# ---------------------------------------------------------------------------
# Full pipeline entry point
# ---------------------------------------------------------------------------

def run_pipeline(
    image_path: str,
    well_ids: list[str],
    config: ImageConfig = DEFAULT_CONFIG,
    warped_save_path: str | None = None,
    roi_debug_save_path: str | None = None,
) -> dict[str, tuple[int, int, int]]:
    """
    Run the full image processing pipeline for one captured image.

    Steps:
        1. Load raw image and compute perspective coefficients.
        2. Apply PIL Image.PERSPECTIVE → flat warped image.
        3. Compute grid cell dimensions from the warped plate image.
        4. Slice grid into per-well ROI patches (all wells).
        5. Save ROI debug overlay (red rectangles + well ID per cell).
        6. Extract median RGB for each requested well_id.
        7. Validate results.

    Saved files (paths auto-derived from image_path if not supplied):
        <name>_warped.jpg     — full perspective-corrected image.
        <name>_roi_debug.jpg  — debug overlay with red ROI boxes and labels.

    Args:
        image_path:          Path to the raw captured deck image.
        well_ids:            Well IDs to extract RGB for, e.g. ["A1","A2","A3"].
        config:              ImageConfig. Defaults to DEFAULT_CONFIG.
        warped_save_path:    Optional path for the warped image.
        roi_debug_save_path: Optional path for the ROI debug overlay.

    Returns:
        {"A1": (R, G, B), "A2": (R, G, B), ...}

    Raises:
        FileNotFoundError: If image_path does not exist.
        RuntimeError: If RGB validation fails.
    """
    def ensure_parent_dir(path: str) -> None:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)

    base, ext = os.path.splitext(image_path)
    ext = ext or ".jpg"

    # Step 1 & 2: Load → perspective coefficients → warp
    raw_pil = Image.open(image_path).convert("RGB")
    coeffs = find_coeffs(config.dst_corners, config.src_corners)
    warped_pil = raw_pil.transform(config.output_size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    warped_np = np.array(warped_pil)

    if warped_save_path is None:
        warped_save_path = f"{base}_warped{ext}"
    ensure_parent_dir(warped_save_path)
    save_pil_image(warped_pil, warped_save_path)

    # Step 3 & 4: Grid dimensions + ROI slice on the warped image
    plate_np = warped_np
    patches, roi_boxes = slice_roi_patches(
        plate_np, config.col_num, config.row_num, config.offset_array
    )

    # Step 5: ROI debug overlay
    if roi_debug_save_path is None:
        roi_debug_save_path = f"{base}_roi_debug{ext}"
    ensure_parent_dir(roi_debug_save_path)
    save_roi_debug_image(
        plate_np, roi_boxes, roi_debug_save_path, config.col_num, config.row_num
    )

    # Step 6: RGB extraction
    rgb_values = extract_well_rgb(patches, well_ids, config.col_num)

    # Step 7: Validate
    passed, failures = validate_results(rgb_values)
    if not passed:
        raise RuntimeError(
            f"RGB validation failed: {failures}. "
            f"Inspect {roi_debug_save_path} to verify ROI grid alignment."
        )

    return rgb_values
