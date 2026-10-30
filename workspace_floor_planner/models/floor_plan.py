# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL

from odoo.addons.workspace_floor_planner.tools.constants import (
    MAX_CANVAS_SIZE,
    MIN_CANVAS_SIZE,
    RENTABLE_TYPES,
)


class WorkspaceFloorPlan(models.Model):
    """One floor of a building.

    The model only stores plan data. Loading, saving, validation, linking and
    status are delegated to dedicated service models
    (``workspace.floor.layout.service`` etc.); the RPC methods below are thin,
    access-checked entry points for the editor and the viewer.
    """

    _name = "workspace.floor.plan"
    _description = "Floor Plan"
    _order = "site, sequence, name, id"
    _check_company_auto = True

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    code = fields.Char(string="Floor Code", help="Short code such as 'L2' or 'B1-03'.")
    site = fields.Char(string="Site / Building")
    floor_level = fields.Integer(string="Floor Level")
    active = fields.Boolean(default=True)
    notes = fields.Text()
    canvas_width = fields.Integer(required=True, default=2000)
    canvas_height = fields.Integer(required=True, default=1200)
    units_per_meter = fields.Float(
        default=50.0,
        help="How many canvas units make one metre. Used to show real-world sizes. "
             "0 = abstract units.")
    grid_size = fields.Integer(default=20)
    show_grid = fields.Boolean(default=True)
    snap_to_grid = fields.Boolean(default=True)
    status_refresh_interval = fields.Integer(
        string="Status Refresh (seconds)", default=0,
        help="Automatically refresh unit statuses in the editor. 0 = manual refresh only.")
    layout_version = fields.Integer(
        default=0, readonly=True, copy=False,
        help="Increased on every layout save; protects against two people "
             "overwriting each other.")
    object_count = fields.Integer(compute="_compute_counts")
    rentable_count = fields.Integer(string="Rentable Units", compute="_compute_counts")
    linked_count = fields.Integer(string="Linked Units", compute="_compute_counts")

    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, index=True)
    object_ids = fields.One2many("workspace.floor.plan.object", "plan_id", string="Objects")

    _canvas_width_range = models.Constraint(
        f"CHECK (canvas_width BETWEEN {MIN_CANVAS_SIZE} AND {MAX_CANVAS_SIZE})",
        f"Canvas width must be between {MIN_CANVAS_SIZE} and {MAX_CANVAS_SIZE} units.",
    )
    _canvas_height_range = models.Constraint(
        f"CHECK (canvas_height BETWEEN {MIN_CANVAS_SIZE} AND {MAX_CANVAS_SIZE})",
        f"Canvas height must be between {MIN_CANVAS_SIZE} and {MAX_CANVAS_SIZE} units.",
    )
    _grid_size_range = models.Constraint(
        "CHECK (grid_size BETWEEN 2 AND 500)",
        "Grid size must be between 2 and 500 units.",
    )
    _refresh_positive = models.Constraint(
        "CHECK (status_refresh_interval = 0 OR status_refresh_interval >= 10)",
        "Status refresh must be 0 (manual) or at least 10 seconds.",
    )
    _scale_positive = models.Constraint(
        "CHECK (units_per_meter >= 0)",
        "Units per metre cannot be negative.",
    )

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.depends("object_ids.object_type", "object_ids.link_res_id")
    def _compute_counts(self):
        """Count all objects, the rentable ones, and the rentable ones linked
        to a business record."""

        for plan in self:
            rentable = plan.object_ids.filtered(lambda o: o.object_type in RENTABLE_TYPES)
            plan.object_count = len(plan.object_ids)
            plan.rentable_count = len(rentable)
            plan.linked_count = len(rentable.filtered("link_res_id"))

    def copy_data(self, default=None):
        """Name copies '<name> (copy)' unless a name is given explicitly."""

        default = dict(default or {})
        vals_list = super().copy_data(default)
        if "name" not in default:
            for plan, vals in zip(self, vals_list):
                vals["name"] = self.env._("%s (copy)", plan.name)
        return vals_list

    def copy(self, default=None):
        """Copy the drawing but never the business links: a link identifies
        one physical unit and must not be duplicated on another plan."""

        new_plans = super().copy(default)
        for plan, new_plan in zip(self, new_plans):
            for obj in plan.object_ids:
                obj.copy({"plan_id": new_plan.id, "link_key": False, "link_res_id": False})
        return new_plans

    # ------------------------------------------------------------------------------
    #   MARK: CONSTRAINT/ONCHANGE METHODS
    # ------------------------------------------------------------------------------
    @api.constrains("canvas_width", "canvas_height")
    def _check_objects_fit_canvas(self):
        """Shrinking a canvas must not leave existing objects outside it."""

        validator = self.env["workspace.floor.layout.validator"]
        for plan in self:
            for obj in plan.object_ids:
                validator._check_bounds(plan, obj._read_geometry(), obj.display_name)

    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_open_designer(self):
        """Open the layout designer for this plan."""

        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "workspace_floor_planner.editor",
            "name": self.display_name,
            "params": {"plan_id": self.id},
            "context": {"active_id": self.id},
            "target": "current",
        }

    def action_open_viewer(self):
        """Open the read-only overview: totals and the colour-coded layout."""

        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "workspace_floor_planner.viewer",
            "name": self.display_name,
            "params": {"plan_id": self.id},
            "context": {"active_id": self.id},
            "target": "current",
        }

    # ------------------------------------------------------------------------------
    #   MARK: RPC ENTRY POINTS
    # ------------------------------------------------------------------------------
    def fp_load_layout(self):
        """Return the plan, its objects, palette, statuses and providers."""

        self.ensure_one()
        self.check_access("read")
        return self.env["workspace.floor.layout.service"]._load(self)

    def fp_save_layout(self, payload):
        """Validate and save the edited layout in one transaction."""

        self.ensure_one()
        self.check_access("write")
        return self.env["workspace.floor.layout.service"]._save(self, payload)

    def fp_get_statuses(self, at=None):
        """Return the live status of every unit, optionally at moment ``at``."""

        self.ensure_one()
        self.check_access("read")
        return self.env["workspace.floor.status.service"]._compute(self, at)

    def fp_search_link_targets(self, link_key, query="", limit=20):
        """Search the business records an object may be linked to."""

        self.ensure_one()
        self.check_access("write")
        return self.env["workspace.floor.link.registry"]._search_targets(
            self, link_key, query, limit)

    def fp_open_linked_record(self, object_id):
        """Return the action opening an object's linked record, or False when
        the object is not on this plan or the record is not accessible."""

        self.ensure_one()
        self.check_access("read")
        obj = self.env["workspace.floor.plan.object"].browse(int(object_id)).exists()
        if not obj or obj.plan_id != self:
            return False
        return self.env["workspace.floor.link.registry"]._get_open_action(obj)

    def fp_prepare_create(self, object_id, link_key):
        """Return the form model, title and defaults for creating the business
        record that an unlinked object on this plan will draw."""

        self.ensure_one()
        self.check_access("write")
        obj = self._fp_own_object(object_id)
        provider = self.env["workspace.floor.link.registry"]._get_provider(link_key)
        label = provider._fp_describe()["label"]
        if obj.link_key:
            raise UserError(self.env._(
                "“%s” is already linked to a record.", obj.display_name))
        if not provider._fp_can_create() or obj.object_type not in provider._fp_object_types:
            raise UserError(self.env._(
                "A %s cannot be created from this object.", label))
        return {
            "res_model": provider._fp_target_model,
            "title": self.env._("New %s", label),
            "context": provider._fp_get_create_context(self, obj),
        }

    def fp_link_created_record(self, object_id, link_key, res_id):
        """Link an object to the record just created from it.

        The link is validated like any other (provider, type, access,
        company), and the layout version moves on so an open editor reloads
        instead of overwriting it.
        """

        self.ensure_one()
        self.check_access("write")
        self.env.cr.execute(SQL(
            "SELECT id FROM workspace_floor_plan WHERE id = %s FOR UPDATE", self.id))
        self.invalidate_recordset(["layout_version"])
        obj = self._fp_own_object(object_id)
        obj.write({"link_key": link_key, "link_res_id": int(res_id)})
        self.write({"layout_version": self.layout_version + 1})
        return True

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _fp_own_object(self, object_id):
        """Return the object ``object_id`` if it is on this plan, else raise a
        clear error asking the user to reload."""

        self.ensure_one()
        obj = self.env["workspace.floor.plan.object"].browse(int(object_id)).exists()
        if not obj or obj.plan_id != self:
            raise UserError(self.env._(
                "This object is no longer on the floor plan. Reload the layout."))
        return obj
