# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models

# Corporate admins see their company's posted customer invoices, tenant
# employees see none, and every other portal user keeps Odoo's stock rule.
INVOICE_RULE_DOMAIN = """(
    [('state', 'not in', ('cancel', 'draft')),
     ('move_type', 'in', ('out_invoice', 'out_refund')),
     ('partner_id', 'child_of', [user.commercial_partner_id.id])]
    if user.has_group('business_center_portal.group_bc_tenant_admin')
    else [('id', '=', False)]
    if user.has_group('business_center_portal.group_bc_tenant_employee')
    else [('state', 'not in', ('cancel', 'draft')),
          ('move_type', 'in', ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')),
          ('partner_id', 'child_of', [user.commercial_partner_id.id])])"""

INVOICE_LINE_RULE_DOMAIN = """(
    [('parent_state', 'not in', ('cancel', 'draft')),
     ('move_id.move_type', 'in', ('out_invoice', 'out_refund')),
     ('move_id.partner_id', 'child_of', [user.commercial_partner_id.id])]
    if user.has_group('business_center_portal.group_bc_tenant_admin')
    else [('id', '=', False)]
    if user.has_group('business_center_portal.group_bc_tenant_employee')
    else [('parent_state', 'not in', ('cancel', 'draft')),
          ('move_id.move_type', 'in', ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')),
          ('move_id.partner_id', 'child_of', [user.commercial_partner_id.id])])"""


class IrRule(models.Model):
    _inherit = 'ir.rule'

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _bc_apply_portal_invoice_rules(self):
        """Narrow account's portal invoice rules for business center tenants.

        Those rules are noupdate in account, so redefining them in XML is
        skipped on upgrade. Writing them here runs on every install and
        upgrade of this module, and their noupdate flag stays set, so an
        upgrade of account does not reset them.
        """

        for xmlid, domain in (
            ('account.account_invoice_rule_portal', INVOICE_RULE_DOMAIN),
            ('account.account_invoice_line_rule_portal', INVOICE_LINE_RULE_DOMAIN),
        ):
            rule = self.env.ref(xmlid, raise_if_not_found=False)
            if rule and rule.domain_force != domain:
                rule.sudo().write({'domain_force': domain})