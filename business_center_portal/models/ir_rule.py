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

# Odoo's own domains for the two rules, used on uninstall when the original
# was not saved (databases where this module was installed before this fix).
# Copied exactly from odoo/addons/account/security/account_security.xml (19.0).
STOCK_INVOICE_RULE_DOMAIN = (
    "[('state', 'not in', ('cancel', 'draft')), "
    "('move_type', 'in', ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')), "
    "('partner_id','child_of',[user.commercial_partner_id.id])]")
STOCK_INVOICE_LINE_RULE_DOMAIN = (
    "[('parent_state', 'not in', ('cancel', 'draft')), "
    "('move_id.move_type', 'in', ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')), "
    "('move_id.partner_id','child_of',[user.commercial_partner_id.id])]")

# (rule xmlid, domain this module writes, Odoo's stock domain)
PORTAL_INVOICE_RULES = (
    ('account.account_invoice_rule_portal',
     INVOICE_RULE_DOMAIN, STOCK_INVOICE_RULE_DOMAIN),
    ('account.account_invoice_line_rule_portal',
     INVOICE_LINE_RULE_DOMAIN, STOCK_INVOICE_LINE_RULE_DOMAIN),
)

# ir.config_parameter key holding a rule's domain from before this module.
ORIGINAL_DOMAIN_KEY = 'business_center_portal.original_domain.%s'


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

        The domain found before the first write is saved, so uninstalling
        the module can put it back (see _bc_restore_portal_invoice_rules).
        """

        params = self.env['ir.config_parameter'].sudo()
        for xmlid, domain, _stock in PORTAL_INVOICE_RULES:
            rule = self.env.ref(xmlid, raise_if_not_found=False)
            if not rule or rule.domain_force == domain:
                continue
            key = ORIGINAL_DOMAIN_KEY % xmlid
            if not params.get_param(key) and 'business_center_portal.' not in (rule.domain_force or ''):
                params.set_param(key, rule.domain_force or '[]')
            rule.sudo().write({'domain_force': domain})

    @api.model
    def _bc_restore_portal_invoice_rules(self):
        """Give account's portal invoice rules back the domain they had before
        this module, or Odoo's stock domain if none was saved. Called by the
        uninstall hook: the domains written above check this module's groups,
        which are deleted on uninstall."""

        params = self.env['ir.config_parameter'].sudo()
        for xmlid, _domain, stock in PORTAL_INVOICE_RULES:
            key = ORIGINAL_DOMAIN_KEY % xmlid
            rule = self.env.ref(xmlid, raise_if_not_found=False)
            if rule and 'business_center_portal.' in (rule.domain_force or ''):
                rule.sudo().write({'domain_force': params.get_param(key) or stock})
            params.set_param(key, False)