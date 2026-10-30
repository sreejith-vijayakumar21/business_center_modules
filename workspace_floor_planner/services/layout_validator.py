# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.


import math
import re

from odoo import api, models
from odoo.exceptions import ValidationError

from odoo.addons.workspace_floor_planner.tools import constants as C
from odoo.addons.workspace_floor_planner.tools.geometry import normalize_rotation

_COLOR_RE = re.compile(C.COLOR_PATTERN)
_ICON_RE = re.compile(C.ICON_PATTERN)

# Keys the editor may send for one object, and how to coerce them.
_FLOAT_KEYS = ("x", "y", "width", "height", "rotation", "border_width")
_INT_KEYS = ("z_index", "font_size")
_COLOR_KEYS = ("fill_color", "border_color", "text_color")
ALLOWED_OBJECT_KEYS = frozenset(
    ("id", "client_key", "name", "object_type", "icon", "link_key", "link_res_id")
    + _FLOAT_KEYS + _INT_KEYS + _COLOR_KEYS,
)
ALLOWED_PLAN_KEYS = frozenset(("grid_size", "show_grid", "snap_to_grid"))


class WorkspaceFloorLayoutValidator(models.AbstractModel):
    """Single place that decides whether layout data is acceptable.

    Used by the save service (whole payload, before anything is written) and
    by model constraints (any other write path). It only *validates* and
    *normalises*; it never writes.
    """

    _name = "workspace.floor.layout.validator"
    _description = "Floor Plan Layout Validator"

    # ------------------------------------------------------------------
    # Primitive checks
    # ------------------------------------------------------------------
    @api.model
    def _number(self, value, label, integer=False):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError(self.env._("%(label)s must be a number.", label=label))
        if not math.isfinite(value):
            raise ValidationError(self.env._("%(label)s must be a finite number.", label=label))
        if integer:
            if value != int(value):
                raise ValidationError(self.env._("%(label)s must be a whole number.", label=label))
            return int(value)
        return float(value)

    @api.model
    def _check_color(self, value, label):
        if not isinstance(value, str) or not _COLOR_RE.match(value):
            raise ValidationError(self.env._(
                "%(label)s must be a hex colour like #1A2B3C (got %(value)r).", label=label, value=value,
            ))

    @api.model
    def _check_size(self, width, height):
        if width < C.MIN_OBJECT_SIZE or height < C.MIN_OBJECT_SIZE:
            raise ValidationError(self.env._(
                "Objects must be at least %(min)s units wide and high.", min=C.MIN_OBJECT_SIZE,
            ))

    @api.model
    def _check_style(self, style):
        for key in _COLOR_KEYS:
            if style.get(key):
                self._check_color(style[key], key)
        border = style.get("border_width") or 0
        if not 0 <= border <= C.MAX_BORDER_WIDTH:
            raise ValidationError(self.env._("Border width must be between 0 and %s.", C.MAX_BORDER_WIDTH))
        font = style.get("font_size") or C.MIN_FONT_SIZE
        if not C.MIN_FONT_SIZE <= font <= C.MAX_FONT_SIZE:
            raise ValidationError(self.env._(
                "Font size must be between %(min)s and %(max)s.", min=C.MIN_FONT_SIZE, max=C.MAX_FONT_SIZE,
            ))
        icon = style.get("icon")
        if icon and (not isinstance(icon, str) or not _ICON_RE.match(icon)):
            raise ValidationError(self.env._("Icon must be a Font Awesome class like fa-coffee."))

    @api.model
    def _check_bounds(self, plan, geometry, label):
        """The unrotated rectangle must lie inside the canvas.

        A rotated object's corners may poke slightly outside; that is accepted
        on purpose so rotating a shape near the edge is never blocked.
        """
        self._check_size(geometry["width"], geometry["height"])
        if (
            geometry["x"] < 0
            or geometry["y"] < 0
            or geometry["x"] + geometry["width"] > plan.canvas_width + 1e-6
            or geometry["y"] + geometry["height"] > plan.canvas_height + 1e-6
        ):
            raise ValidationError(self.env._(
                "“%(label)s” is outside the %(w)s × %(h)s canvas.",
                label=label, w=plan.canvas_width, h=plan.canvas_height,
            ))
        if not 0 <= geometry["rotation"] < 360:
            raise ValidationError(self.env._("Rotation must be between 0 and 360 degrees."))

    @api.model
    def _check_object_record(self, obj):
        if obj.name and len(obj.name) > C.MAX_LABEL_LENGTH:
            raise ValidationError(self.env._("Labels are limited to %s characters.", C.MAX_LABEL_LENGTH))
        if not -C.MAX_Z_INDEX <= obj.z_index <= C.MAX_Z_INDEX:
            raise ValidationError(self.env._("Layer order is out of range."))
        self._check_bounds(obj.plan_id, obj._read_geometry(), obj.display_name)
        self._check_style(obj._read_style())

    # ------------------------------------------------------------------
    # Payload validation
    # ------------------------------------------------------------------
    @api.model
    def _validate_payload(self, plan, payload):
        """Validate and normalise an editor save payload.

        Returns ``{"version": int, "plan": {...}, "objects": [vals, ...]}``
        where every object dict only contains known, typed keys. Raises
        ValidationError on the first problem, before anything is written.
        """
        if not isinstance(payload, dict):
            raise ValidationError(self.env._("Invalid layout data."))
        version = self._number(payload.get("version"), self.env._("Layout version"), integer=True)
        objects = payload.get("objects")
        if not isinstance(objects, list):
            raise ValidationError(self.env._("Invalid layout data: objects must be a list."))
        if len(objects) > C.MAX_OBJECTS_PER_PLAN:
            raise ValidationError(self.env._(
                "A floor plan can hold at most %s objects.", C.MAX_OBJECTS_PER_PLAN,
            ))

        existing_ids = set(plan.object_ids.ids)
        seen_ids, seen_keys, seen_links = set(), set(), set()
        clean_objects = []
        for index, raw in enumerate(objects, start=1):
            vals = self._validate_object(plan, raw, index, existing_ids)
            if vals.get("id"):
                if vals["id"] in seen_ids:
                    raise ValidationError(self.env._("Object #%s appears twice.", index))
                seen_ids.add(vals["id"])
            else:
                if vals["client_key"] in seen_keys:
                    raise ValidationError(self.env._("Object #%s has a duplicate client key.", index))
                seen_keys.add(vals["client_key"])
            if vals.get("link_key"):
                link = (vals["link_key"], vals["link_res_id"])
                if link in seen_links:
                    raise ValidationError(self.env._(
                        "“%s”: this business record is already placed on this plan.",
                        vals.get("name") or index,
                    ))
                seen_links.add(link)
            clean_objects.append(vals)

        return {
            "version": version,
            "plan": self._validate_plan_settings(payload.get("plan") or {}),
            "objects": clean_objects,
        }

    @api.model
    def _validate_plan_settings(self, raw):
        if not isinstance(raw, dict) or set(raw) - ALLOWED_PLAN_KEYS:
            raise ValidationError(self.env._("Invalid plan settings."))
        clean = {}
        if "grid_size" in raw:
            grid = self._number(raw["grid_size"], self.env._("Grid size"), integer=True)
            if not 2 <= grid <= 500:
                raise ValidationError(self.env._("Grid size must be between 2 and 500 units."))
            clean["grid_size"] = grid
        for key in ("show_grid", "snap_to_grid"):
            if key in raw:
                clean[key] = bool(raw[key])
        return clean

    @api.model
    def _validate_object(self, plan, raw, index, existing_ids):
        if not isinstance(raw, dict):
            raise ValidationError(self.env._("Object #%s is not valid.", index))
        unknown = set(raw) - ALLOWED_OBJECT_KEYS
        if unknown:
            raise ValidationError(self.env._(
                "Object #%(index)s has unsupported fields: %(fields)s",
                index=index, fields=", ".join(sorted(unknown)),
            ))
        vals = {}
        obj_id = raw.get("id")
        if obj_id:
            obj_id = self._number(obj_id, self.env._("Object id"), integer=True)
            if obj_id not in existing_ids:
                raise ValidationError(self.env._("Object #%s does not belong to this floor plan.", index))
            vals["id"] = obj_id
        else:
            key = raw.get("client_key")
            if not isinstance(key, str) or not 0 < len(key) <= 64:
                raise ValidationError(self.env._("New object #%s needs a client key.", index))
            vals["client_key"] = key

        object_type = raw.get("object_type")
        if object_type not in C.OBJECT_TYPE_CATEGORY:
            raise ValidationError(self.env._(
                "Object #%(index)s has an unknown type %(type)r.", index=index, type=object_type,
            ))
        vals["object_type"] = object_type

        name = raw.get("name") or False
        if name is not False:
            if not isinstance(name, str) or len(name) > C.MAX_LABEL_LENGTH:
                raise ValidationError(self.env._(
                    "Object #%(index)s: the label must be text of at most %(max)s characters.",
                    index=index, max=C.MAX_LABEL_LENGTH,
                ))
            name = name.strip() or False
        vals["name"] = name
        label = name or f"#{index}"

        for key in _FLOAT_KEYS:
            if key in raw:
                vals[key] = self._number(raw[key], f"{label}: {key}")
        for key in _INT_KEYS:
            if key in raw:
                vals[key] = self._number(raw[key], f"{label}: {key}", integer=True)
        for key in _COLOR_KEYS:
            if key in raw:
                self._check_color(raw[key], f"{label}: {key}")
                vals[key] = raw[key].upper()
        if "icon" in raw:
            vals["icon"] = raw["icon"] or False

        for key in ("x", "y", "width", "height"):
            if key not in vals:
                raise ValidationError(self.env._("%(label)s: %(key)s is required.", label=label, key=key))
        vals["rotation"] = normalize_rotation(vals.get("rotation", 0.0))
        if not -C.MAX_Z_INDEX <= vals.get("z_index", 0) <= C.MAX_Z_INDEX:
            raise ValidationError(self.env._("%s: layer order is out of range.", label))
        self._check_bounds(plan, vals, label)
        self._check_style(vals)

        link_key = raw.get("link_key") or False
        link_res_id = raw.get("link_res_id") or False
        if link_key or link_res_id:
            if not isinstance(link_key, str):
                raise ValidationError(self.env._("%s: invalid link.", label))
            link_res_id = self._number(link_res_id, f"{label}: link", integer=True)
            # Provider, record existence, access rights and company are all
            # checked by the registry; nothing from the client is trusted.
            self.env["workspace.floor.link.registry"]._validate_link(plan, object_type, link_key, link_res_id)
        vals["link_key"] = link_key or False
        vals["link_res_id"] = link_res_id or False
        return vals
