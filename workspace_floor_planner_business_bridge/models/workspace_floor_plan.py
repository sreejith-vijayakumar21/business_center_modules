from odoo import fields, models


class WorkspaceFloorPlan(models.Model):
    _inherit = "workspace.floor.plan"

    bc_floor_id = fields.Many2one(
        "business.center.floor", string="Business Center Floor",
        index=True, ondelete="set null", copy=False,
        help="The Business Center floor this layout draws. Link pickers only offer units of this floor.",
    )
    bc_center_id = fields.Many2one(related="bc_floor_id.center_id", string="Business Center")

    _bc_floor_uniq = models.Constraint(
        "unique (bc_floor_id)", "A Business Center floor can only have one layout.",
    )

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    def write(self, vals):
        """Dragging layouts in Floor Planner > Floor Plans reorders the
        Business Center floors they draw, so both lists stay in one order."""

        res = super().write(vals)
        if "sequence" in vals and not self.env.context.get("bc_sequence_sync"):
            for plan in self.filtered("bc_floor_id"):
                # sudo: only the order number is copied; a floor planner
                # designer may have no write access on Business Center floors.
                plan.bc_floor_id.sudo().with_context(bc_sequence_sync=True).write(
                    {"sequence": plan.sequence})
        return res