"""
Colour-mixing metric helpers.

In the RGBy workflow the optimizer suggests 4D volumes
``(R_vol, G_vol, B_vol, water_vol)``, while colour similarity metrics are
computed from measured RGB camera output.
"""

from __future__ import annotations

import math
from typing import Any



def _srgb_channel_to_linear(channel: int) -> float:
    """Convert one sRGB channel (0-255) to linear RGB (0-1)."""
    c = float(channel) / 255.0
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _rgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """Convert sRGB (D65) to CIE L*a*b*."""
    r_lin = _srgb_channel_to_linear(rgb[0])
    g_lin = _srgb_channel_to_linear(rgb[1])
    b_lin = _srgb_channel_to_linear(rgb[2])

    # Linear RGB -> XYZ (D65), scaled to 0-100.
    x = (0.4124564 * r_lin + 0.3575761 * g_lin + 0.1804375 * b_lin) * 100.0
    y = (0.2126729 * r_lin + 0.7151522 * g_lin + 0.0721750 * b_lin) * 100.0
    z = (0.0193339 * r_lin + 0.1191920 * g_lin + 0.9503041 * b_lin) * 100.0

    # D65 reference white.
    xn, yn, zn = 95.047, 100.0, 108.883

    def f(t: float) -> float:
        delta = 6.0 / 29.0
        if t > delta**3:
            return t ** (1.0 / 3.0)
        return t / (3.0 * delta**2) + 4.0 / 29.0

    fx = f(x / xn)
    fy = f(y / yn)
    fz = f(z / zn)

    l_star = 116.0 * fy - 16.0
    a_star = 500.0 * (fx - fy)
    b_star = 200.0 * (fy - fz)
    return l_star, a_star, b_star


def _delta_e_2000_from_lab(
    lab1: tuple[float, float, float],
    lab2: tuple[float, float, float],
) -> float:
    """Calculate CIEDE2000 Delta E from two Lab tuples."""
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2

    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0
    c_bar_7 = c_bar**7
    g = 0.5 * (1.0 - math.sqrt(c_bar_7 / (c_bar_7 + 25.0**7)))

    a1_prime = (1.0 + g) * a1
    a2_prime = (1.0 + g) * a2
    c1_prime = math.hypot(a1_prime, b1)
    c2_prime = math.hypot(a2_prime, b2)
    c_bar_prime = (c1_prime + c2_prime) / 2.0

    h1_prime = math.degrees(math.atan2(b1, a1_prime)) % 360.0 if c1_prime else 0.0
    h2_prime = math.degrees(math.atan2(b2, a2_prime)) % 360.0 if c2_prime else 0.0

    delta_l_prime = l2 - l1
    delta_c_prime = c2_prime - c1_prime

    if c1_prime == 0.0 or c2_prime == 0.0:
        delta_h_prime = 0.0
    else:
        delta_h_prime = h2_prime - h1_prime
        if delta_h_prime > 180.0:
            delta_h_prime -= 360.0
        elif delta_h_prime < -180.0:
            delta_h_prime += 360.0

    delta_h_term = 2.0 * math.sqrt(c1_prime * c2_prime) * math.sin(
        math.radians(delta_h_prime / 2.0)
    )

    l_bar_prime = (l1 + l2) / 2.0
    if c1_prime == 0.0 or c2_prime == 0.0:
        h_bar_prime = h1_prime + h2_prime
    elif abs(h1_prime - h2_prime) <= 180.0:
        h_bar_prime = (h1_prime + h2_prime) / 2.0
    elif (h1_prime + h2_prime) < 360.0:
        h_bar_prime = (h1_prime + h2_prime + 360.0) / 2.0
    else:
        h_bar_prime = (h1_prime + h2_prime - 360.0) / 2.0

    t = (
        1.0
        - 0.17 * math.cos(math.radians(h_bar_prime - 30.0))
        + 0.24 * math.cos(math.radians(2.0 * h_bar_prime))
        + 0.32 * math.cos(math.radians(3.0 * h_bar_prime + 6.0))
        - 0.20 * math.cos(math.radians(4.0 * h_bar_prime - 63.0))
    )

    delta_theta = 30.0 * math.exp(-(((h_bar_prime - 275.0) / 25.0) ** 2))
    r_c = 2.0 * math.sqrt((c_bar_prime**7) / (c_bar_prime**7 + 25.0**7))
    s_l = 1.0 + (0.015 * ((l_bar_prime - 50.0) ** 2)) / math.sqrt(
        20.0 + ((l_bar_prime - 50.0) ** 2)
    )
    s_c = 1.0 + 0.045 * c_bar_prime
    s_h = 1.0 + 0.015 * c_bar_prime * t
    r_t = -math.sin(math.radians(2.0 * delta_theta)) * r_c

    return math.sqrt(
        (delta_l_prime / s_l) ** 2
        + (delta_c_prime / s_c) ** 2
        + (delta_h_term / s_h) ** 2
        + r_t * (delta_c_prime / s_c) * (delta_h_term / s_h)
    )


def calculate_delta_e_2000(
    mixed: tuple[int, int, int],
    target: tuple[int, int, int],
) -> float:
    """
    Calculate CIEDE2000 Delta E between two RGB colours.

    Args:
        mixed: Measured RGB of the mixed colour (R, G, B), values 0-255.
        target: Target RGB colour (R, G, B), values 0-255.

    Returns:
        Delta E 2000 as a float. 0.0 means a perfect match.
    """
    lab_mixed = _rgb_to_lab(mixed)
    lab_target = _rgb_to_lab(target)
    return _delta_e_2000_from_lab(lab_mixed, lab_target)


def stop_condition_reached(
    iteration: int,
    max_iterations: int,
) -> tuple[bool, str]:
    """
    Check whether the optimization stop condition has been reached.

    Args:
        iteration: Current iteration number (1-indexed).
        max_iterations: Maximum number of iterations allowed.

    Returns:
        (stopped, reason) where stopped is True if the loop should end.
    """
    if iteration >= max_iterations:
        return True, f"Reached maximum iterations ({max_iterations})"
    return False, ""


def validate_rgby_volumes(
    volumes: tuple[float, float, float, float] | list[float],
    total_volume: float,
    *,
    tolerance_ul: float = 1.0,
) -> tuple[bool, str]:
    """
    Validate an RGBy volume vector against total-volume constraint.

    Args:
        volumes: (R_vol, G_vol, B_vol, water_vol) in uL.
        total_volume: Expected total volume in uL.
        tolerance_ul: Allowed absolute sum error in uL.

    Returns:
        (is_valid, reason). reason is empty when valid.
    """
    if len(volumes) != 4:
        return False, f"Expected 4 volumes (R,G,B,water), got {len(volumes)}"

    total = float(sum(volumes))
    if abs(total - total_volume) > tolerance_ul:
        return False, (
            f"Volumes sum to {total:.2f} uL, expected {total_volume:.2f} uL "
            f"(+/-{tolerance_ul:.2f} uL)"
        )

    if any(float(v) < 0 for v in volumes):
        return False, "Volumes must be non-negative."

    return True, ""


if __name__ == "__main__":
    mixed = (200, 100, 50)
    target = (180, 120, 60)
    error = calculate_delta_e_2000(mixed, target)

    print(f"Mixed:         {mixed}")
    print(f"Target:        {target}")
    print(f"Delta E 2000:  {error:.4f}")