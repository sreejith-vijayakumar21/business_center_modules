import math

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import tagged

from .common import FloorPlannerCase


@tagged("post_install", "-at_install")
class TestLayoutSave(FloorPlannerCase):
    def test_save_and_reload_preserves_geometry_and_style(self):
        result = self.save(self.plan, [
            self.obj(rotation=-45, fill_color="#aabbcc", z_index=3, border_width=1.5, font_size=12),
            self.obj(client_key="w", object_type="wall", name="", x=0, y=0, width=300, height=8),
        ])
        self.assertEqual(self.plan.layout_version, 1)
        self.assertEqual(len(result["objects"]), 2)
        desk_id = result["id_map"]["c1"]
        layout = self.plan.fp_load_layout()
        desk = next(o for o in layout["objects"] if o["id"] == desk_id)
        self.assertEqual((desk["x"], desk["y"], desk["width"], desk["height"]), (10, 20, 50, 40))
        self.assertEqual(desk["rotation"], 315, "rotation is normalised to [0, 360)")
        self.assertEqual(desk["fill_color"], "#AABBCC")
        self.assertEqual(desk["z_index"], 3)
        self.assertEqual(desk["category"], "rentable")

    def test_update_and_delete(self):
        result = self.save(self.plan, [self.obj(), self.obj(client_key="c2", name="D2", x=100)])
        d1 = result["id_map"]["c1"]
        result = self.save(self.plan, [{**self.obj(x=200), "id": d1, "client_key": None}])
        self.assertEqual(self.plan.object_ids.ids, [d1])
        self.assertEqual(self.plan.object_ids.x, 200)

    def test_version_conflict(self):
        self.save(self.plan, [self.obj()])
        with self.assertRaises(UserError):
            self.save(self.plan, [self.obj()], version=0)

    def test_rejects_bad_payloads(self):
        bad = [
            self.obj(object_type="spaceship"),
            self.obj(x=math.nan),
            self.obj(width=float("inf")),
            self.obj(width=1),
            self.obj(x=980),                  # 980 + 50 > 1000
            self.obj(y=-5),
            self.obj(fill_color="red"),
            self.obj(fill_color="#12345"),
            self.obj(status="available"),     # client may never send a status
            self.obj(company_id=1),
            self.obj(x="10"),
            self.obj(name="x" * 500),
            self.obj(icon="javascript:alert(1)"),
            self.obj(font_size=1000),
        ]
        for vals in bad:
            with self.subTest(vals=vals), self.assertRaises(ValidationError):
                self.save(self.plan, [vals])
        self.assertFalse(self.plan.object_ids, "nothing is written when validation fails")

    def test_rejects_objects_of_other_plan(self):
        other = self.env["workspace.floor.plan"].create({"name": "Level 2"})
        result = self.save(other, [self.obj()])
        foreign_id = result["id_map"]["c1"]
        with self.assertRaises(ValidationError):
            self.save(self.plan, [{**self.obj(), "id": foreign_id}])
        self.assertEqual(len(other.object_ids), 1)

    def test_rejects_too_many_objects(self):
        objects = [self.obj(client_key=str(i)) for i in range(2001)]
        with self.assertRaises(ValidationError):
            self.save(self.plan, objects)

    def test_atomic_failure_keeps_previous_layout(self):
        self.save(self.plan, [self.obj()])
        before = self.plan.object_ids
        with self.assertRaises(ValidationError):
            self.save(self.plan, [self.obj(client_key="ok"), self.obj(client_key="bad", width=-3)])
        self.assertEqual(self.plan.object_ids, before)

    def test_canvas_cannot_shrink_below_objects(self):
        self.save(self.plan, [self.obj(x=900)])
        with self.assertRaises(ValidationError):
            self.plan.canvas_width = 500

    def test_copy_plan_drops_links_keeps_drawing(self):
        self.save(self.plan, [self.obj()])
        copy = self.plan.copy()
        self.assertEqual(len(copy.object_ids), 1)
        self.assertIn("copy", copy.name)
