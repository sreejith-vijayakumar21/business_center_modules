from odoo.tests.common import BaseCase, tagged

from odoo.addons.workspace_floor_planner.tools.geometry import (
    normalize_rotation,
    point_in_rotated_rect,
)


@tagged("post_install", "-at_install")
class TestGeometry(BaseCase):
    def test_normalize_rotation(self):
        self.assertEqual(normalize_rotation(0), 0)
        self.assertEqual(normalize_rotation(360), 0)
        self.assertEqual(normalize_rotation(-90), 270)
        self.assertEqual(normalize_rotation(725), 5)

    def test_point_in_rotated_rect(self):
        rect = {"x": 0, "y": 0, "width": 100, "height": 10, "rotation": 0}
        self.assertTrue(point_in_rotated_rect((90, 5), rect))
        self.assertFalse(point_in_rotated_rect((50, 40), rect))
        rect["rotation"] = 90  # now a vertical bar centred on (50, 5)
        self.assertFalse(point_in_rotated_rect((90, 5), rect))
        self.assertTrue(point_in_rotated_rect((50, 40), rect))
