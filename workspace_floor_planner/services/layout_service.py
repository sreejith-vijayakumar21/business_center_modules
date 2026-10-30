# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.


from odoo import api, models
from odoo.exceptions import UserError
from odoo.tools import SQL

from odoo.addons.workspace_floor_planner.models.floor_plan_object import (
    GEOMETRY_FIELDS,
    STYLE_FIELDS,
)

PLAN_FIELDS = (
    "name", "code", "site", "floor_level", "canvas_width", "canvas_height", "units_per_meter",
    "grid_size", "show_grid", "snap_to_grid", "status_refresh_interval", "layout_version",
)
OBJECT_WRITE_FIELDS = (
    "name", "object_type", *GEOMETRY_FIELDS, "z_index", *STYLE_FIELDS, "link_key", "link_res_id",
)


class WorkspaceFloorLayoutService(models.AbstractModel):
    """Loads a plan for the editor and saves an edited layout atomically."""

    _name = "workspace.floor.layout.service"
    _description = "Floor Plan Layout Service"

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    @api.model
    def _load(self, plan):
        registry = self.env["workspace.floor.link.registry"]
        names = registry._resolve_names(plan, plan.object_ids)
        return {
            "plan": self._serialize_plan(plan),
            "objects": [self._serialize_object(obj, names) for obj in plan.object_ids],
            "presets": self.env["workspace.floor.object.preset"]._get_palette(),
            "statuses": self.env["workspace.floor.status"]._get_palette(),
            "providers": registry._describe_providers(),
        }

    @api.model
    def _serialize_plan(self, plan):
        data = {fname: plan[fname] for fname in PLAN_FIELDS}
        data.update(
            id=plan.id,
            code=plan.code or "",
            site=plan.site or "",
            can_edit=plan.has_access("write") and self.env["workspace.floor.plan.object"].has_access("create"),
        )
        return data

    @api.model
    def _serialize_object(self, obj, names):
        data = {
            "id": obj.id,
            "name": obj.name or "",
            "object_type": obj.object_type,
            "category": obj.category,
            "z_index": obj.z_index,
            **obj._read_geometry(),
            **obj._read_style(),
            "link_key": obj.link_key or False,
            "link_res_id": obj.link_res_id or False,
            "link_name": False,
            "link_restricted": False,
        }
        if obj.link_key:
            name = names.get(obj.id)
            # Never leak the name of a record the user cannot read.
            data["link_name"] = name or self.env._("Restricted or missing record")
            data["link_restricted"] = name is None
        return data

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    @api.model
    def _save(self, plan, payload):
        """Replace the plan's layout with ``payload``.

        Everything is validated first; then objects are created, updated and
        deleted in the same transaction, so a failure leaves the plan as it
        was. ``payload['version']`` must match the stored version, otherwise
        someone else saved in the meantime and we refuse to overwrite.
        """
        # Lock the plan row so two saves of the same plan are serialised.
        self.env.cr.execute(SQL(
            "SELECT id FROM workspace_floor_plan WHERE id = %s FOR UPDATE", plan.id,
        ))
        plan.invalidate_recordset(["layout_version"])
        clean = self.env["workspace.floor.layout.validator"]._validate_payload(plan, payload)
        if clean["version"] != plan.layout_version:
            raise UserError(self.env._(
                "This floor plan was changed by someone else while you were editing. "
                "Reload it to see their changes (your unsaved changes will be lost).",
            ))

        Object = self.env["workspace.floor.plan.object"]
        existing = {obj.id: obj for obj in plan.object_ids}
        kept_ids = {vals["id"] for vals in clean["objects"] if vals.get("id")}

        # Delete first so a link can move from a removed object to a new one.
        to_delete = plan.object_ids.filtered(lambda o: o.id not in kept_ids)
        to_delete.unlink()

        updates = []
        for vals in clean["objects"]:
            if vals.get("id"):
                obj = existing[vals["id"]]
                changes = self._diff(obj, vals)
                if changes:
                    updates.append((obj, changes, vals))
        # Release links that move between objects before re-assigning them,
        # so swapping two desks' links does not trip the uniqueness rule.
        relinked = Object.browse([
            obj.id for obj, changes, _vals in updates if "link_key" in changes or "link_res_id" in changes
        ])
        if relinked:
            relinked.write({"link_key": False, "link_res_id": False})
        for obj, changes, vals in updates:
            if obj in relinked:
                changes.update(link_key=vals["link_key"], link_res_id=vals["link_res_id"])
            obj.write(changes)

        create_vals, client_keys = [], []
        for vals in clean["objects"]:
            if not vals.get("id"):
                client_keys.append(vals["client_key"])
                create_vals.append({
                    "plan_id": plan.id,
                    **{key: vals[key] for key in OBJECT_WRITE_FIELDS if key in vals},
                })
        created = Object.create(create_vals) if create_vals else Object

        plan.write({**clean["plan"], "layout_version": plan.layout_version + 1})
        result = self._load(plan)
        result["id_map"] = dict(zip(client_keys, created.ids))
        return result

    @api.model
    def _diff(self, obj, vals):
        changes = {}
        for key in OBJECT_WRITE_FIELDS:
            if key not in vals:
                continue
            current = obj[key]
            new = vals[key]
            if isinstance(current, float) and isinstance(new, (int, float)):
                if abs(current - new) > 1e-6:
                    changes[key] = new
            elif (current or False) != (new or False):
                changes[key] = new
        return changes
