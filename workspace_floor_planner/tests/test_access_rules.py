from odoo.exceptions import AccessError
from odoo.tests.common import new_test_user, tagged

from .common import FloorPlannerCase


@tagged("post_install", "-at_install")
class TestAccessRules(FloorPlannerCase):
    def test_viewer_reads_but_cannot_save(self):
        layout = self.plan.with_user(self.viewer).fp_load_layout()
        self.assertFalse(layout["plan"]["can_edit"])
        with self.assertRaises(AccessError):
            self.save(self.plan, [self.obj()], user=self.viewer)

    def test_designer_edits_layout_but_cannot_create_plans(self):
        self.save(self.plan, [self.obj()], user=self.designer)
        self.assertEqual(len(self.plan.object_ids), 1)
        self.assertTrue(self.plan.with_user(self.designer).fp_load_layout()["plan"]["can_edit"])
        with self.assertRaises(AccessError):
            self.env["workspace.floor.plan"].with_user(self.designer).create({"name": "Nope"})
        with self.assertRaises(AccessError):
            self.plan.with_user(self.designer).unlink()

    def test_manager_creates_multiple_plans(self):
        Plan = self.env["workspace.floor.plan"].with_user(self.manager)
        plans = Plan.create([{"name": "Ground"}, {"name": "First"}])
        self.assertEqual(len(plans), 2)
        self.assertFalse(plans[0].fp_load_layout()["objects"], "a new plan starts blank")

    def test_status_colours_manager_only(self):
        status = self.env.ref("workspace_floor_planner.status_available")
        with self.assertRaises(AccessError):
            status.with_user(self.designer).color = "#000000"
        status.with_user(self.manager).color = "#00FF00"

    def test_company_isolation(self):
        foreign = self.env["workspace.floor.plan"].create({
            "name": "Other site", "company_id": self.other_company.id,
        })
        visible = self.env["workspace.floor.plan"].with_user(self.manager).search([])
        self.assertIn(self.plan, visible)
        self.assertNotIn(foreign, visible)
        with self.assertRaises(AccessError):
            foreign.with_user(self.manager).fp_load_layout()

    def test_user_without_group_has_no_access(self):
        outsider = new_test_user(self.env, login="fp_outsider", groups="base.group_user")
        with self.assertRaises(AccessError):
            self.plan.with_user(outsider).fp_load_layout()
