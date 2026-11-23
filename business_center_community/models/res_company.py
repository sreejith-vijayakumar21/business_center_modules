# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    bc_community_member_posts = fields.Boolean(
        string='Members Can Post', default=True,
        help="Let members share updates and photos on the community feed. "
             "Turn off to keep the feed for staff posts only.")
    bc_community_moderation = fields.Boolean(
        string='Approve Member Posts First', default=True,
        help="A member's post waits for staff approval before other members "
             "see it. Turn off to publish member posts at once.")
