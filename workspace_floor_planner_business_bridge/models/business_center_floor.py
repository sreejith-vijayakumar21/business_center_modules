from odoo import api, fields, models
from odoo.exceptions import UserError


class BusinessCenterFloor(models.Model):
    """Adds floor-level availability counts and the floor layout entry point."""

    _inherit = "business.center.floor"

    floor_plan_ids = fields.One2many("workspace.floor.plan", "bc_floor_id", string="Layouts")
    floor_plan_id = fields.Many2one("workspace.floor.plan", compute="_compute_floor_plan_id", string="Layout")
    has_layout = fields.Boolean(compute="_compute_floor_plan_id")

    office_count = fields.Integer(compute="_compute_unit_counts", string="Offices")
    office_available_count = fields.Integer(compute="_compute_unit_counts", string="Available Offices")
    desk_count = fields.Integer(compute="_compute_unit_counts", string="Desks")
    desk_available_count = fields.Integer(compute="_compute_unit_counts", string="Available Desks")
    meeting_room_count = fields.Integer(compute="_compute_unit_counts", string="Meeting Rooms")
    meeting_room_available_count = fields.Integer(
        compute="_compute_unit_counts", string="Available Meeting Rooms")
    unit_count = fields.Integer(compute="_compute_unit_counts", string="Total Units")
    unit_available_count = fields.Integer(compute="_compute_unit_counts", string="Available Units")

    @api.depends("floor_plan_ids")
    def _compute_floor_plan_id(self):
        for floor in self:
            floor.floor_plan_id = floor.floor_plan_ids[:1]
            floor.has_layout = bool(floor.floor_plan_ids)

    @api.depends("space_ids.state", "space_ids.space_type", "space_ids.is_coworking",
                 "space_ids.is_bookable", "space_ids.desk_ids.state")
    def _compute_unit_counts(self):
        units = self.env["workspace.floor.bc.units"]
        for floor in self:
            offices, desks, rooms = units._floor_units(floor)
            floor.office_count = len(offices)
            floor.office_available_count = len(offices.filtered(lambda s: s.state == "available"))
            floor.desk_count = len(desks)
            floor.desk_available_count = len(desks.filtered(lambda d: d.state == "available"))
            floor.meeting_room_count = len(rooms)
            floor.meeting_room_available_count = len(rooms.filtered(
                lambda r: r.state in ("available", "occupied") and r.is_bookable))
            floor.unit_count = len(offices) + len(desks) + len(rooms)
            floor.unit_available_count = (
                floor.office_available_count + floor.desk_available_count + floor.meeting_room_available_count
            )
    
    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    def write(self, vals):
        """Reordering floors reorders their layouts in the floor planner too."""

        res = super().write(vals)
        if "sequence" in vals and not self.env.context.get("bc_sequence_sync"):
            for floor in self:
                # sudo: only the order number is copied; a Business Center user
                # who may reorder floors is only a viewer in the floor planner.
                floor.floor_plan_ids.sudo().with_context(bc_sequence_sync=True).write(
                    {"sequence": floor.sequence})
        return res

    # ------------------------------------------------------------------
    # MARK: ACTIONS
    # ------------------------------------------------------------------
    def action_open_floor_layout(self):
        """First time: create the layout and open the designer.
        Afterwards: open the live view (totals + coloured layout)."""
        if not self:
            raise UserError(self.env._(
                "Save the business center first: this floor is not saved yet."))
        self.ensure_one()
        plan = self.floor_plan_id
        if not plan:
            plan = self._create_floor_plan()
            return plan.action_open_designer()
        if not plan.object_ids:
            return plan.action_open_designer()
        return plan.action_open_viewer()

    def action_edit_floor_layout(self):
        if not self:
            raise UserError(self.env._(
                "Save the business center first: this floor is not saved yet."))
        self.ensure_one()
        plan = self.floor_plan_id or self._create_floor_plan()
        return plan.action_open_designer()

    def _create_floor_plan(self):
        self.ensure_one()
        Plan = self.env["workspace.floor.plan"]
        if not Plan.has_access("create"):
            raise UserError(self.env._(
                "This floor has no layout yet. Ask a Business Center manager "
                "(Floor Planner administrator) to create it."
            ))
        center = self.center_id
        plan = Plan.create({
            "name": f"{center.code or center.name} / {self.name}",
            "site": center.name,
            "code": self.name,
            "sequence": self.sequence,
            "company_id": center.company_id.id,
            "bc_floor_id": self.id,
        })
        self.env["workspace.floor.bc.layout.generator"]._generate(plan)
        return plan
