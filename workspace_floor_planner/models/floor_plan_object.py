# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.


from odoo import api, fields, models

from odoo.addons.workspace_floor_planner.tools.constants import (
    OBJECT_TYPE_CATEGORY,
    OBJECT_TYPE_SELECTION,
)

GEOMETRY_FIELDS = ("x", "y", "width", "height", "rotation")
STYLE_FIELDS = ("fill_color", "border_color", "border_width", "text_color", "font_size", "icon")


class WorkspaceFloorPlanObject(models.Model):
    """One shape on a floor plan.

    Geometry convention: (x, y) is the top-left corner of the *unrotated*
    rectangle, in logical canvas units; ``rotation`` is in degrees clockwise
    around the rectangle's centre.

    A rentable object may reference one business record through
    ``link_key`` (which registered link provider) + ``link_res_id``. These
    two values are untrusted and are always validated by the link registry.
    """

    _name = "workspace.floor.plan.object"
    _description = "Floor Plan Object"
    _order = "plan_id, z_index, id"

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    plan_id = fields.Many2one("workspace.floor.plan", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="plan_id.company_id", store=True, index=True)
    name = fields.Char(string="Label")
    object_type = fields.Selection(OBJECT_TYPE_SELECTION, required=True, default="facility")
    category = fields.Char(compute="_compute_category")

    x = fields.Float(required=True, default=0)
    y = fields.Float(required=True, default=0)
    width = fields.Float(required=True, default=80)
    height = fields.Float(required=True, default=60)
    rotation = fields.Float(default=0)
    z_index = fields.Integer(default=0)

    fill_color = fields.Char(default="#FFFFFF")
    border_color = fields.Char(default="#424242")
    border_width = fields.Float(default=2)
    text_color = fields.Char(default="#212121")
    font_size = fields.Integer(default=14)
    icon = fields.Char()

    link_key = fields.Char(string="Link Provider", index=True, copy=False)
    link_res_id = fields.Integer(string="Linked Record ID", copy=False)

    _link_uniq = models.Constraint(
        "unique (plan_id, link_key, link_res_id)",
        "A business record can only be placed once on the same floor plan.",
    )
    _link_pair = models.Constraint(
        "CHECK ((link_key IS NULL AND COALESCE(link_res_id, 0) = 0)"
        " OR (link_key IS NOT NULL AND link_res_id > 0))",
        "A link needs both a provider and a record.",
    )

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------ 
    @api.depends("object_type")
    def _compute_category(self):
        for obj in self:
            obj.category = OBJECT_TYPE_CATEGORY.get(obj.object_type)

    @api.depends("name", "object_type")
    def _compute_display_name(self):
        labels = dict(self._fields["object_type"]._description_selection(self.env))
        for obj in self:
            obj.display_name = obj.name or labels.get(obj.object_type) or self.env._("Object")

    # ------------------------------------------------------------------------------
    #   MARK: CONSTRAINT/ONCHANGE METHODS
    # ------------------------------------------------------------------------------ 
    @api.constrains(*GEOMETRY_FIELDS, *STYLE_FIELDS, "z_index", "name")
    def _check_values(self):
        validator = self.env["workspace.floor.layout.validator"]
        for obj in self:
            validator._check_object_record(obj)

    @api.constrains("link_key", "link_res_id", "object_type", "plan_id")
    def _check_link(self):
        registry = self.env["workspace.floor.link.registry"]
        for obj in self.filtered("link_key"):
            registry._validate_link(obj.plan_id, obj.object_type, obj.link_key, obj.link_res_id)
    
    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _read_geometry(self):
        self.ensure_one()
        return {fname: self[fname] for fname in GEOMETRY_FIELDS}

    def _read_style(self):
        self.ensure_one()
        return {fname: (self[fname] or False) if fname == "icon" else self[fname] for fname in STYLE_FIELDS}