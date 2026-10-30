import math

from odoo import api, models

MARGIN = 40          # space between blocks and around the floor
DESK_W, DESK_H, DESK_GAP = 60, 40, 20
ZONE_PAD, ZONE_HEADER = 30, 40
DEFAULT_SIZES = {"private_office": (200, 150), "meeting_room": (220, 160)}


class BusinessCenterLayoutGenerator(models.AbstractModel):
    """Builds a starting layout for a floor from its registered units.

    Every private office, coworking space (as a zone with its desks inside)
    and meeting room is placed in tidy rows and linked to its record, so the
    user only has to drag things into their real position. It never creates
    business records.
    """

    _name = "workspace.floor.bc.layout.generator"
    _description = "Business Center starting layout generator"

    @api.model
    def _office_size(self, space, object_type):
        """Use the recorded floor area when there is one (4:3 rectangle)."""
        plan_scale = 50.0  # canvas units per metre (plan default)
        if space.area_sqm and space.area_sqm > 0:
            width = math.sqrt(space.area_sqm * 4 / 3) * plan_scale
            height = width * 3 / 4
            return max(min(width, 600), 100), max(min(height, 450), 80)
        return DEFAULT_SIZES[object_type]

    @api.model
    def _blocks(self, floor):
        """List of blocks: (width, height, [object vals relative to block])."""
        blocks = []
        spaces = floor.space_ids.sorted("name")
        for space in spaces.filtered(lambda s: s.space_type == "office" and not s.is_coworking):
            w, h = self._office_size(space, "private_office")
            blocks.append((w, h, [self._unit(space.name, "private_office", 0, 0, w, h, "bc_office", space.id)]))
        for space in spaces.filtered("is_coworking"):
            desks = space.desk_ids.sorted("name")
            cols = max(1, math.ceil(math.sqrt(len(desks) or 1)))
            rows = max(1, math.ceil(len(desks) / cols))
            w = 2 * ZONE_PAD + cols * DESK_W + (cols - 1) * DESK_GAP
            h = ZONE_HEADER + ZONE_PAD + rows * DESK_H + (rows - 1) * DESK_GAP
            objects = [{
                "name": space.name, "object_type": "coworking_zone",
                "x": 0, "y": 0, "width": w, "height": h, "z_index": 0,
                "fill_color": "#E3F2FD", "border_color": "#1E88E5",
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
            blocks.append((w, h, [self._unit(space.name, "meeting_room", 0, 0, w, h, "bc_meeting_room", space.id)]))
        return blocks

    @api.model
    def _unit(self, name, object_type, x, y, w, h, link_key, res_id, font_size=20):
        return {
            "name": (name or "")[:120], "object_type": object_type,
            "x": x, "y": y, "width": w, "height": h, "z_index": 1,
            "border_color": "#37474F", "font_size": font_size,
            "link_key": link_key, "link_res_id": res_id,
        }

    @api.model
    def _generate(self, plan):
        """Shelf-pack the blocks in rows and create the objects."""
        blocks = self._blocks(plan.bc_floor_id)
        width = 1400  # wrap rows here; the canvas is resized to the content below
        x, y, row_height = MARGIN, MARGIN + 40, 0
        vals_list = [{
            "plan_id": plan.id, "name": plan.bc_floor_id.name, "object_type": "label",
            "x": MARGIN, "y": 20, "width": 300, "height": 40, "font_size": 24,
            "fill_color": "#FFFFFF", "border_color": "#FFFFFF", "border_width": 0, "z_index": 2,
        }]
        widest = 0
        for block_w, block_h, objects in blocks:
            if x > MARGIN and x + block_w + MARGIN > width:
                x, y, row_height = MARGIN, y + row_height + MARGIN, 0
            for obj in objects:
                vals_list.append({**obj, "plan_id": plan.id, "x": obj["x"] + x, "y": obj["y"] + y})
            widest = max(widest, x + block_w + MARGIN)
            x += block_w + MARGIN
            row_height = max(row_height, block_h)
        # Fit the canvas to the content, leaving room to grow.
        canvas_w = max(1200, widest + 200)
        canvas_h = max(800, y + row_height + MARGIN + 200)
        plan.write({"canvas_width": math.ceil(canvas_w), "canvas_height": math.ceil(canvas_h)})
        return self.env["workspace.floor.plan.object"].create(vals_list)
