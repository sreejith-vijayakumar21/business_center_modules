# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    bc_team_approval = fields.Boolean(
        string='Approve New Team Members', default=False,
        help="A member that a tenant's administrator adds from the portal waits "
             "for staff approval before joining the contract and receiving their "
             "invitation. When off, they join and are invited at once.")