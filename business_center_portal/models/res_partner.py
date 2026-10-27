from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    bc_role = fields.Selection([
        ('employee', 'Tenant Employee'),
        ('admin', 'Tenant Corporate Admin'),
    ], string='Business Center Role',
       help="Role granted to this contact's portal login")
    
    bc_center_ids = fields.Many2many('business.center', string='Business Centres',
                                     compute='_compute_bc_center_ids', search='_search_bc_center_ids', 
                                     help="Centres this contact's company holds an active contract in.")

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.depends('commercial_partner_id')
    def _compute_bc_center_ids(self):
        """Centres this contact's company holds an active contract in.

        Desks are mapped through their space as well as offices: a desk-only
        tenant used to yield an empty set, and four portal record rules key off
        this field, so those tenants saw nothing in the backend at all.
        """
        
        Contract = self.env['business.center.contract'].sudo()
        for partner in self:
            contracts = Contract.search([
                ('partner_id', 'child_of', partner.commercial_partner_id.id),
                ('state', '=', 'active'),
            ])
            partner.bc_center_ids = (
                contracts.mapped('leased_asset_ids.space_id.center_id')
                | contracts.mapped('leased_asset_ids.desk_id.space_id.center_id')
            )

    def _search_bc_center_ids(self, operator, value):
        """Not searchable: the record rules read .ids directly, and a real
        search would mean reversing the contract lookup for every partner."""
        
        return [('id', '=', 0)]

    def _bc_sync_role(self):
        """Keep the portal user's groups in step with the role on the contact."""
        emp = self.env.ref('business_center_portal.group_bc_tenant_employee')
        adm = self.env.ref('business_center_portal.group_bc_tenant_admin')
        for partner in self:
            user = partner.user_ids[:1]
            if not user or not user.share:
                continue
            user.sudo().group_ids = [(3, emp.id), (3, adm.id)]
            if partner.bc_role == 'employee':
                user.sudo().group_ids = [(4, emp.id)]
            elif partner.bc_role == 'admin':
                user.sudo().group_ids = [(4, adm.id)]

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners._bc_sync_role()
        return partners

    def write(self, vals):
        res = super().write(vals)
        if 'bc_role' in vals:
            self._bc_sync_role()
        return res