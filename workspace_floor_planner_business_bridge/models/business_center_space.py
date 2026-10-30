# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models

from odoo.addons.workspace_floor_planner.tools.constants import OBJECT_TYPE_SELECTION

# Provider keys whose shapes point at spaces, and at desks.
SPACE_LINK_KEYS = ("bc_office", "bc_meeting_room", "bc_coworking")
DESK_LINK_KEYS = ("bc_desk",)


def release_floor_links(env, link_keys, res_ids):
    """Unlink the floor plan shapes drawing records that are being deleted:
    the link is cleared and the label reset to the shape type, so the shape
    shows "Not linked" and can be linked or created again. The layout
    version moves on so an open editor reloads instead of saving the old
    link back."""

    if not res_ids:
        return
    shapes = env["workspace.floor.plan.object"].sudo().search([
        ("link_key", "in", link_keys),
        ("link_res_id", "in", list(res_ids)),
    ])
    if not shapes:
        return
    labels = dict(OBJECT_TYPE_SELECTION)
    for shape in shapes:
        shape.write({
            "link_key": False,
            "link_res_id": False,
            "name": labels.get(shape.object_type, False),
        })
    for plan in shapes.plan_id:
        plan.layout_version += 1


class BusinessCenterSpace(models.Model):
    """Release the floor plan shapes of deleted spaces and their desks."""

    _inherit = "business.center.space"

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    def unlink(self):
        """Delete the spaces, then release the shapes that drew them. Their
        desks are removed by the database cascade, which skips the desks'
        own unlink, so their shapes are released here too."""

        space_ids, desk_ids = self.ids, self.desk_ids.ids
        res = super().unlink()
        release_floor_links(self.env, SPACE_LINK_KEYS, space_ids)
        release_floor_links(self.env, DESK_LINK_KEYS, desk_ids)
        return res


class BusinessCenterDesk(models.Model):
    """Release the floor plan shapes of deleted desks."""

    _inherit = "business.center.desk"

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    def unlink(self):
        """Delete the desks, then release the shapes that drew them."""

        desk_ids = self.ids
        res = super().unlink()
        release_floor_links(self.env, DESK_LINK_KEYS, desk_ids)
        return res