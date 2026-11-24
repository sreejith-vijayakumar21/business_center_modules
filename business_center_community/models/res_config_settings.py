# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    bc_community_member_posts = fields.Boolean(
        related='company_id.bc_community_member_posts', readonly=False)
    bc_community_moderation = fields.Boolean(
        related='company_id.bc_community_moderation', readonly=False)
    bc_community_moderator_id = fields.Many2one(
        related='company_id.bc_community_moderator_id', readonly=False)
