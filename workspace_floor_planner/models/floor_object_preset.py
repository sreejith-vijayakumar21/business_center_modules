# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.


from odoo import api, fields, models

from odoo.addons.workspace_floor_planner.tools.constants import (
    OBJECT_TYPE_CATEGORY,
    OBJECT_TYPE_SELECTION,
)


class WorkspaceFloorObjectPreset(models.Model):
    """A palette entry: default size and look for a kind of object.

    New palette items (e.g. "Phone booth") are added as data records, with no
    code change — the editor simply renders whatever presets exist.
    """

    _name = "workspace.floor.object.preset"
    _description = "Floor Plan Palette Preset"
    _order = "sequence, id"

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    object_type = fields.Selection(OBJECT_TYPE_SELECTION, required=True)
    category = fields.Char(compute="_compute_category")
    width = fields.Float(required=True, default=80)
    height = fields.Float(required=True, default=60)
    fill_color = fields.Char(default="#FFFFFF")
    border_color = fields.Char(default="#424242")
    border_width = fields.Float(default=2)
    text_color = fields.Char(default="#212121")
    font_size = fields.Integer(default=14)
    icon = fields.Char(help="Font Awesome icon class, e.g. fa-coffee")
    
    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------ 
    @api.depends("object_type")
    def _compute_category(self):
        for preset in self:
            preset.category = OBJECT_TYPE_CATEGORY.get(preset.object_type)

    # ------------------------------------------------------------------------------
    #   MARK: CONSTRAINT/ONCHANGE METHODS
    # ------------------------------------------------------------------------------   
    @api.constrains("width", "height", "fill_color", "border_color", "text_color",
                    "border_width", "font_size", "icon")
    def _check_values(self):
        validator = self.env["workspace.floor.layout.validator"]
        for preset in self:
            validator._check_style(preset._read_style())
            validator._check_size(preset.width, preset.height)
            
    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _read_style(self):
        self.ensure_one()
        return {
            "fill_color": self.fill_color,
            "border_color": self.border_color,
            "border_width": self.border_width,
            "text_color": self.text_color,
            "font_size": self.font_size,
            "icon": self.icon or False,
        }

    @api.model
    def _get_palette(self):
        return [
            {
                "id": preset.id,
                "name": preset.name,
                "object_type": preset.object_type,
                "category": preset.category,
                "width": preset.width,
                "height": preset.height,
                **preset._read_style(),
            }
            for preset in self.search([])
        ]
