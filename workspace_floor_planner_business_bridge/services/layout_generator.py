# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import math

from odoo import api, models

# Layout spacing, in canvas units.
MARGIN = 40  # around the floor and between blocks
DESK_W, DESK_H, DESK_GAP = 60, 40, 20
ZONE_PAD, ZONE_HEADER = 30, 40
ROW_WRAP_WIDTH = 1400  # blocks wrap to a new row past this width
PLAN_SCALE = 50.0  # canvas units per metre (plan default)
DEFAULT_SIZES = {"private_office": (200, 150), "meeting_room": (220, 160)}

# Pastel look shared with the floor planner palette.
UNIT_BORDER_COLOR = "#8C93AD"
ZONE_FILL_COLOR, ZONE_BORDER_COLOR = "#EEF3FF", "#9DB4F2"


class BusinessCenterLayoutGenerator(models.AbstractModel):
    """Build a starting layout for a floor from its registered units.

    Every private office, coworking space (as a zone with its desks inside)
    and meeting room is placed in tidy rows and linked to its record, so the
    user only has to drag things into their real position. It never creates
    business records.
    """

    _name = "workspace.floor.bc.layout.generator"
    _description = "Business Center starting layout generator"

    # ------------------------------------------------------------------------------
    #   MARK: LAYOUT GENERATION
    # ------------------------------------------------------------------------------
    @api.model
    def _generate(self, plan):
        """Shelf-pack the floor's blocks in rows, create the objects and fit
        the canvas to the content, leaving room to grow."""

        blocks = self._blocks(plan.bc_floor_id)
        x, y, row_height = MARGIN, MARGIN + 40, 0
        vals_list = [{
            "plan_id": plan.id, "name": plan.bc_floor_id.name, "object_type": "label",
            "x": MARGIN, "y": 20, "width": 300, "height": 40, "font_size": 24,
            "fill_color": "#FFFFFF", "border_color": "#FFFFFF", "border_width": 0, "z_index": 2,
        }]
        widest = 0
        for block_w, block_h, objects in blocks:
            if x > MARGIN and x + block_w + MARGIN > ROW_WRAP_WIDTH:
                x, y, row_height = MARGIN, y + row_height + MARGIN, 0
            for obj in objects:
                vals_list.append({**obj, "plan_id": plan.id, "x": obj["x"] + x, "y": obj["y"] + y})
            widest = max(widest, x + block_w + MARGIN)
            x += block_w + MARGIN
            row_height = max(row_height, block_h)
        canvas_w = max(1200, widest + 200)
        canvas_h = max(800, y + row_height + MARGIN + 200)
        plan.write({"canvas_width": math.ceil(canvas_w), "canvas_height": math.ceil(canvas_h)})
        return self.env["workspace.floor.plan.object"].create(vals_list)

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _blocks(self, floor):
        """Return the floor's blocks as ``(width, height, [object vals])``,
        with object positions relative to their block: offices, then
        coworking zones with their desks, then meeting rooms."""

        blocks = []
        spaces = floor.space_ids.sorted("name")
        for space in spaces.filtered(lambda s: s.space_type == "office" and not s.is_coworking):
            w, h = self._office_size(space, "private_office")
            blocks.append((w, h, [
                self._unit(space.name, "private_office", 0, 0, w, h, "bc_office", space.id),
            ]))
        for space in spaces.filtered("is_coworking"):
            desks = space.desk_ids.sorted("name")
            cols = max(1, math.ceil(math.sqrt(len(desks) or 1)))
            rows = max(1, math.ceil(len(desks) / cols))
            w = 2 * ZONE_PAD + cols * DESK_W + (cols - 1) * DESK_GAP
            h = ZONE_HEADER + ZONE_PAD + rows * DESK_H + (rows - 1) * DESK_GAP
            objects = [{
                "name": space.name, "object_type": "coworking_zone",
                "x": 0, "y": 0, "width": w, "height": h, "z_index": 0,
                "fill_color": ZONE_FILL_COLOR, "border_color": ZONE_BORDER_COLOR,
                "link_key": "bc_coworking", "link_res_id": space.id,
            }]
            for index, desk in enumerate(desks):
                col, row = index % cols, index // cols
                objects.append(self._unit(
                    desk.name, "dedicated_desk",
                    ZONE_PAD + col * (DESK_W + DESK_GAP), ZONE_HEADER + row * (DESK_H + DESK_GAP),
                    DESK_W, DESK_H, "bc_desk", desk.id, font_size=10,
                ))
            blocks.append((w, h, objects))
        for space in spaces.filtered(lambda s: s.space_type == "meeting_room"):
            w, h = self._office_size(space, "meeting_room")
            blocks.append((w, h, [
                self._unit(space.name, "meeting_room", 0, 0, w, h, "bc_meeting_room", space.id),
            ]))
        return blocks

    @api.model
    def _office_size(self, space, object_type):
        """Return a shape size from the recorded floor area (4:3 rectangle,
        clamped to sensible bounds), or the default size for the type."""

        if space.area_sqm and space.area_sqm > 0:
            width = math.sqrt(space.area_sqm * 4 / 3) * PLAN_SCALE
            height = width * 3 / 4
            return max(min(width, 600), 100), max(min(height, 450), 80)
        return DEFAULT_SIZES[object_type]

    @api.model
    def _unit(self, name, object_type, x, y, w, h, link_key, res_id, font_size=20):
        """Return the vals of one rentable shape linked to its record."""

        return {
            "name": (name or "")[:120], "object_type": object_type,
            "x": x, "y": y, "width": w, "height": h, "z_index": 1,
            "border_color": UNIT_BORDER_COLOR, "font_size": font_size,
            "link_key": link_key, "link_res_id": res_id,
        }
