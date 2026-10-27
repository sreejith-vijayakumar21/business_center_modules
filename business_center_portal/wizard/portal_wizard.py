from odoo import models


class PortalWizardUser(models.TransientModel):
    _inherit = 'portal.wizard.user'

    def action_grant_access(self):
        """Apply the contact's Business Center role once the login exists.

        A contact of a tenant company (one with business center contracts)
        granted access without a role becomes a Tenant Employee, the least
        privileged tenant role, so a forgotten role never falls back to Odoo's
        stock access to all of the company's invoices.
        """
        Contract = self.env['business.center.contract'].sudo()
        untagged_tenants = self.mapped('partner_id').filtered(
            lambda p: not p.bc_role and Contract.search_count(
                [('partner_id', 'child_of', p.commercial_partner_id.id)], limit=1))
        untagged_tenants.write({'bc_role': 'employee'})
        res = super().action_grant_access()
        self.mapped('partner_id')._bc_sync_role()
        return res