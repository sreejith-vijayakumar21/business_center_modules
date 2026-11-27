# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


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
    
    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    def write(self, vals):
        """Switching team approval on or off shows or hides its menu."""

        res = super().write(vals)
        if 'bc_team_approval' in vals:
            self._bc_sync_team_approval_group()
        return res

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _bc_sync_team_approval_group(self):
        """Give every internal user the Team Member Approval group while any
        company approves new team members, and take it away when none does,
        the way Odoo's settings toggle a feature's menus."""

        employees = self.env.ref('base.group_user').sudo()
        group = self.env.ref('business_center_portal.group_bc_team_approval').sudo()
        if self.sudo().search_count([('bc_team_approval', '=', True)], limit=1):
            employees._apply_group(group)
        else:
            employees._remove_group(group)