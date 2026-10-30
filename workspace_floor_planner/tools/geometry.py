"""Pure geometry helpers (no Odoo imports, easy to unit test)."""

import math


def normalize_rotation(degrees):
    """Return the angle folded into [0, 360)."""
    value = math.fmod(float(degrees), 360.0)
    if value < 0:
        value += 360.0
    # fmod(-0.0) can give -0.0, and 359.9999999 should stay below 360.
    return 0.0 if value == 0 or value >= 360.0 else value


def center_of(rect):
    """Centre point of a rect given as a mapping with x, y, width, height."""
    return (rect["x"] + rect["width"] / 2.0, rect["y"] + rect["height"] / 2.0)


def point_in_rotated_rect(point, rect):
    """True when ``point`` lies inside ``rect`` once the rect is rotated.

    The rect is rotated clockwise by ``rect['rotation']`` degrees around its
    centre (same convention as the editor's SVG transform).
    """
    cx, cy = center_of(rect)
    angle = math.radians(-(rect.get("rotation") or 0.0))
    dx, dy = point[0] - cx, point[1] - cy
    # Undo the rotation so the test becomes an axis-aligned one.
    local_x = dx * math.cos(angle) - dy * math.sin(angle)
    local_y = dx * math.sin(angle) + dy * math.cos(angle)
    return abs(local_x) <= rect["width"] / 2.0 and abs(local_y) <= rect["height"] / 2.0
