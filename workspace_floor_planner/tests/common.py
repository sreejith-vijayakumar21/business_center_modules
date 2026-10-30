from contextlib import contextmanager
from unittest.mock import patch

from odoo.tests.common import TransactionCase, new_test_user


class FloorPlannerCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env["res.company"].create({"name": "Other Business Center"})
        common = {"company_id": cls.company.id, "company_ids": [cls.company.id]}
        cls.viewer = new_test_user(
            cls.env, login="fp_viewer", groups="workspace_floor_planner.group_floor_planner_viewer", **common)
        cls.designer = new_test_user(
            cls.env, login="fp_designer", groups="workspace_floor_planner.group_floor_planner_user", **common)
        cls.manager = new_test_user(
            cls.env, login="fp_manager", groups="workspace_floor_planner.group_floor_planner_manager", **common)
        cls.plan = cls.env["workspace.floor.plan"].create({
            "name": "Level 1", "canvas_width": 1000, "canvas_height": 800, "company_id": cls.company.id,
        })

    @staticmethod
    def obj(**overrides):
        vals = {
            "client_key": "c1", "object_type": "hot_desk", "name": "D1",
            "x": 10, "y": 20, "width": 50, "height": 40, "rotation": 0,
        }
        vals.update(overrides)
        return vals

    def save(self, plan, objects, user=None, version=None):
        plan = plan.with_user(user) if user else plan
        return plan.fp_save_layout({
            "version": plan.layout_version if version is None else version,
            "objects": objects,
        })


PARTNER_STATUS = {}


@contextmanager
def partner_provider(case):
    """Register the base provider as a 'partner' link provider for tests.

    It behaves exactly like a bridge provider whose business records are
    res.partner, and whose status comes from PARTNER_STATUS.
    """
    Registry = type(case.env["workspace.floor.link.registry"])
    Provider = type(case.env["workspace.floor.link.provider"])

    def statuses(self, records, at=None):
        return {rec.id: PARTNER_STATUS.get(rec.id, "unknown") for rec in records}

    with patch.object(Registry, "_get_provider_models", lambda self: ["workspace.floor.link.provider"]), \
            patch.object(Provider, "_fp_link_key", "partner"), \
            patch.object(Provider, "_fp_link_label", "Partner"), \
            patch.object(Provider, "_fp_target_model", "res.partner"), \
            patch.object(Provider, "_fp_get_statuses", statuses):
        PARTNER_STATUS.clear()
        yield
