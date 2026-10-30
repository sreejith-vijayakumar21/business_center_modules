# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.


from odoo import api, fields, models

from odoo.addons.workspace_floor_planner.tools.constants import STATUS_SELECTION


class WorkspaceFloorStatus(models.Model):
    """Display settings (colour, label) for each normalised status.

    The *codes* are a fixed contract shared with bridge addons; only how they
    look is configurable, so managers can recolour without touching code.
    """

    _name = "workspace.floor.status"
    _description = "Floor Plan Status Display"
    _order = "sequence, id"

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    code = fields.Selection(STATUS_SELECTION, required=True, readonly=True)
    name = fields.Char(required=True, translate=True)
    description = fields.Char(translate=True)
    color = fields.Char(required=True, default="#9E9E9E")
    sequence = fields.Integer(default=10)

    _code_uniq = models.Constraint("unique (code)", "Each status code can only be configured once.")

    # ------------------------------------------------------------------------------
    #   MARK: CONSTRAINT/ONCHANGE METHODS
    # ------------------------------------------------------------------------------ 
    @api.constrains("color")
    def _check_color(self):
        validator = self.env["workspace.floor.layout.validator"]
        for status in self:
            validator._check_color(status.color, self.env._("Status colour"))
            
    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _get_palette(self):
        """Serialisable palette, used by the editor legend."""
        return [
            {
                "code": status.code,
                "name": status.name,
                "description": status.description or "",
                "color": status.color,
            }
            for status in self.search([])
        ]
