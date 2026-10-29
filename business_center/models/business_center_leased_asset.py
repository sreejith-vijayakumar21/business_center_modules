# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.tools import format_date
from odoo.exceptions import ValidationError, UserError

from dateutil.relativedelta import relativedelta


class BusinessCenterLeasedAsset(models.Model):
    """Stores master records for business center leased assets"""
    
    _name = 'business.center.leased.asset'
    _description = 'A central registry of business center leased assets'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'image.mixin']
    
    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    lease_asset_type = fields.Selection([
        ('office', 'Office'),
        ('desk', 'Desk')
    ], required=True, default='office', tracking=True)
    monthly_rent_total = fields.Monetary(
        string='Monthly Rent', compute='_compute_monthly_rent_total', store=True,
        readonly=False, tracking=True,
        help="Rent agreed for this asset. Starts from the space or desk's list "
             "rent when the asset is picked and can be negotiated while the "
             "contract is draft. Later changes to the list rent do not affect "
             "contracts already agreed.")
    color = fields.Integer(string='Tag Color', compute='_compute_color', store=True)
    contract_state = fields.Selection(related='contract_id.state', string='Contract Status',
                                      store=True)
    
    product_id = fields.Many2one('product.product', string='Rent Product',
                                 compute='_compute_product_id', store=True,
                                 help="Service product used on the invoice line for this asset's rent")
    currency_id = fields.Many2one('res.currency', string='Currency',
                                  related='contract_id.company_id.currency_id', store=True)
    company_id = fields.Many2one(related='contract_id.company_id', store=True, string='Company')
    contract_id = fields.Many2one('business.center.contract', string='Contract', ondelete='cascade')
    renewal_of_contract_id = fields.Many2one(
        related='contract_id.previous_contract_id', string='Renewal Of')
    available_space_ids = fields.Many2many('business.center.space', compute='_compute_available_resources')
    available_desk_ids = fields.Many2many('business.center.desk', compute='_compute_available_resources')
    space_id = fields.Many2one('business.center.space', string='Space',
                            domain="[('id', 'in', available_space_ids), ('center_id.state', '=', 'active')]")
    desk_id = fields.Many2one('business.center.desk', string='Desk',
                            domain="[('id', 'in', available_desk_ids),('space_id.center_id.state', '=', 'active')]")
    _CLAIMING_STATES = ('upcoming', 'active')
    
    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.depends('space_id', 'desk_id')
    def _compute_display_name(self):
        """Name the asset after its linked space or desk, or 'New Asset' if unset"""
        
        for rec in self:
            resource = rec.space_id or rec.desk_id
            rec.display_name = resource.display_name if resource else _('New Asset')

    @api.depends('space_id', 'desk_id')
    def _compute_color(self):
        """Assign a stable kanban tag color derived from the linked resource's id"""
        
        for rec in self:
            resource = rec.space_id or rec.desk_id
            rec.color = (resource.id % 11 + 1) if resource else 0
            
    @api.depends('space_id', 'desk_id', 'lease_asset_type')
    def _compute_monthly_rent_total(self):
        """Take the picked space or desk's list rent as the starting point.

        Depends only on which asset is picked, not on its list rent, so
        repricing a space never changes rent on contracts already agreed.
        """

        for rec in self:
            if rec.lease_asset_type == 'office':
                rec.monthly_rent_total = rec.space_id.monthly_rent
            elif rec.lease_asset_type == 'desk':
                rec.monthly_rent_total = rec.desk_id.monthly_rent
            else:
                rec.monthly_rent_total = 0.0
                
    @api.depends(
        'contract_id.date_start', 'contract_id.date_end',
        'contract_id.leased_asset_ids.space_id',
        'contract_id.leased_asset_ids.desk_id',
    )
    def _compute_available_resources(self):
        """Compute the spaces and desks selectable on this line: same center as its
        siblings, and free of any draft/active contract overlapping these dates."""
        
        Space = self.env['business.center.space']
        Desk = self.env['business.center.desk']
        LeasedAsset = self.env['business.center.leased.asset']
        for rec in self:
            start = rec.contract_id.date_start
            end = rec.contract_id.date_end

            # First sibling line with a resource locks the center for the rest.
            locked_center = rec._contract_locked_center()

            base_space_domain = [
                ('space_type', '=', 'office'),
                ('is_coworking', '=', False),
            ]
            base_desk_domain = []
            if locked_center:
                base_space_domain.append(('center_id', '=', locked_center.id))
                base_desk_domain.append(('space_id.center_id', '=', locked_center.id))

            if not (start and end):
                rec.available_space_ids = Space.search(base_space_domain)
                rec.available_desk_ids = Desk.search(base_desk_domain)
                continue

            overlap_domain = [
                ('contract_id.date_start', '<=', end),
                ('contract_id.date_end', '>=', start),
                ('contract_id.state', 'in', ('draft', 'upcoming', 'active')),
            ]
            if rec._origin.id:
                overlap_domain.append(('id', '!=', rec._origin.id))

            overlapping = LeasedAsset.search(overlap_domain)
            busy_space_ids = overlapping.mapped('space_id').ids
            busy_desk_ids = overlapping.mapped('desk_id').ids

            rec.available_space_ids = Space.search(
                base_space_domain + [('id', 'not in', busy_space_ids)]
            )
            rec.available_desk_ids = Desk.search(
                base_desk_domain + [('id', 'not in', busy_desk_ids)]
            )
                
    @api.depends('lease_asset_type')
    def _compute_product_id(self):
        """Default the rent product to the office or desk product for this kind of
        asset. Stays editable, so a manual pick is never overwritten."""

        P = self.env['product.product']
        office = self.env.ref('business_center.product_office_rent',
                              raise_if_not_found=False) or P
        desk = self.env.ref('business_center.product_desk_rent',
                            raise_if_not_found=False) or P
        defaults = office | desk
        for rec in self:
            wanted = office if rec.lease_asset_type == 'office' else desk
            if not rec.product_id or rec.product_id in defaults:
                rec.product_id = wanted
                
    @api.model_create_multi
    def create(self, vals_list):
        """A renewal keeps exactly the assets of the contract it renews, so
        lines can only be added to it while the renewal itself is created."""

        if not self.env.context.get('bc_renewal_create'):
            contract_ids = [v['contract_id'] for v in vals_list if v.get('contract_id')]
            renewals = self.env['business.center.contract'].browse(
                contract_ids).filtered('previous_contract_id')
            if renewals:
                raise UserError(self._renewal_lock_message(renewals[0]))
        return super().create(vals_list)
                
    def write(self, vals):
        """Rent and leased assets are fixed once the contract leaves draft,
        and a renewal's assets are fixed from the start."""

        if {'monthly_rent_total', 'space_id', 'desk_id'} & set(vals):
            locked = self.filtered(
                lambda a: a.contract_id and a.contract_id.state != 'draft')
            if locked:
                raise UserError(_(
                    "%(asset)s is on contract %(contract)s, which is no longer "
                    "draft, so its rent and asset cannot change. Reset the "
                    "contract to draft first.",
                    asset=locked[0].display_name,
                    contract=locked[0].contract_id.name))
        if {'lease_asset_type', 'space_id', 'desk_id'} & set(vals) \
                and not self.env.context.get('bc_renewal_create'):
            renewal_lines = self.filtered(lambda a: a.contract_id.previous_contract_id)
            if renewal_lines:
                raise UserError(self._renewal_lock_message(renewal_lines[0].contract_id))
        return super().write(vals)
                
    @api.ondelete(at_uninstall=False)
    def _unlink_except_live_contract(self):
        """Leased assets are fixed once the contract leaves draft.

        Removing an asset from a running contract would change what is billed
        and silently free an occupied space, so the contract must be reset to
        draft (or cancelled) first.
        """

        for asset in self:
            contract = asset.contract_id
            if contract.previous_contract_id and contract.state == 'draft' \
                    and not self.env.context.get('bc_renewal_create'):
                raise UserError(self._renewal_lock_message(contract))
            if contract.state not in ('draft', 'cancelled'):
                raise UserError(_(
                    "%(asset)s cannot be removed — contract %(contract)s is "
                    "%(state)s. Reset the contract to draft first, or cancel it "
                    "and raise a new one.",
                    asset=asset.display_name,
                    contract=contract.name,
                    state=dict(contract._fields['state'].selection)[contract.state],
                ))
            
    # ------------------------------------------------------------------------------
    #   MARK: CONSTRAINT/ONCHANGE METHODS
    # ------------------------------------------------------------------------------   
    @api.constrains('space_id', 'desk_id')
    def _check_single_center(self):
        """Forbid mixing assets from different business centers on one contract."""
        
        for asset in self:
            contract = asset.contract_id
            centers = set()
            for line in contract.leased_asset_ids:
                if line.space_id:
                    centers.add(line.space_id.center_id.id)
                elif line.desk_id:
                    centers.add(line.desk_id.space_id.center_id.id)
            if len(centers) > 1:
                raise ValidationError(_(
                    "All leased assets on a contract must belong to the same "
                    "business center."
                ))
                
    @api.onchange('lease_asset_type', 'space_id', 'desk_id')
    def _onchange_lease_asset_type(self):
        """Keep only the resource of the line's own type.

        The form only hides the field of the other type, so without this the
        line keeps the old space or desk: it then shows on the list, the
        agreement PDF and invoices, and stays claimed against other contracts.
        Also runs when a resource is picked, so a line saved before this rule
        existed is cleaned as soon as it is edited.
        """

        if self.lease_asset_type == 'office':
            self.desk_id = False
        else:
            self.space_id = False

    @api.constrains('lease_asset_type', 'space_id', 'desk_id')
    def _check_resource_matches_type(self):
        """A line holds exactly one resource, of its own type. Server-side
        twin of the onchange, for imports, the API and the portal."""

        for asset in self:
            if asset.lease_asset_type == 'office' and asset.desk_id:
                raise ValidationError(_(
                    "%(asset)s is an office line but also holds desk %(desk)s. "
                    "An office line can only hold a space.",
                    asset=asset.display_name, desk=asset.desk_id.display_name))
            if asset.lease_asset_type == 'desk' and asset.space_id:
                raise ValidationError(_(
                    "%(asset)s is a desk line but also holds space %(space)s. "
                    "A desk line can only hold a desk.",
                    asset=asset.display_name, space=asset.space_id.display_name))
            
    @api.constrains('space_id', 'desk_id', 'contract_id')
    def _check_lock_period_fits_contract(self):
        """Block saving when an asset's minimum lock period runs past the contract end."""
        
        for asset in self:
            violation = asset._get_lock_violation()
            if not violation:
                continue
            resource, required_end = violation
            raise ValidationError(_(
                "%(asset)s requires a minimum lock of %(qty)s %(unit)s "
                "(until %(needed)s), but the contract ends %(actual)s. "
                "Extend the contract or choose a shorter-lock asset.",
                asset=resource.display_name,
                qty=resource.min_lock_period,
                unit=resource.min_lock_period_unit,
                needed=required_end,
                actual=asset.contract_id.date_end,
            ))

    def _check_no_overlapping_contract(self):
        """A space or desk can only be committed to one tenant at a time.
        Draft contracts don't claim anything, and cancelled/expired ones have
        released it, so only Upcoming and Running block. Dates are inclusive,
        so one contract must end strictly before the next begins."""

        for asset in self:
            contract = asset.contract_id
            resource = asset.space_id or asset.desk_id
            if not resource or contract.state not in self._CLAIMING_STATES:
                continue
            if not (contract.date_start and contract.date_end):
                continue

            domain = [
                ('id', '!=', asset.id),
                ('contract_id', '!=', contract.id),
                ('contract_id.state', 'in', self._CLAIMING_STATES),
                ('contract_id.date_start', '<=', contract.date_end),
                ('contract_id.date_end', '>=', contract.date_start),
            ]
            if asset.space_id:
                domain.append(('space_id', '=', asset.space_id.id))
            else:
                domain.append(('desk_id', '=', asset.desk_id.id))

            clash = self.sudo().search(domain, limit=1)
            if clash:
                raise ValidationError(_(
                    "%(resource)s is already committed to %(other)s "
                    "(%(from_date)s to %(to_date)s). Two contracts cannot hold "
                    "the same space or desk over the same dates.",
                    resource=resource.display_name,
                    other=clash.contract_id.name,
                    from_date=format_date(self.env, clash.contract_id.date_start),
                    to_date=format_date(self.env, clash.contract_id.date_end),
                ))

    @api.constrains('space_id', 'desk_id', 'contract_id')
    def _check_asset_not_double_booked(self):
        """Block attaching a space or desk that another live contract holds."""

        self._check_no_overlapping_contract()
                
    @api.onchange('space_id', 'desk_id')
    def _onchange_warn_lock_period(self):
        """Warn and clear the picked asset in the UI if its lock period exceeds the contract."""
        
        violation = self._get_lock_violation()
        if not violation:
            return
        resource, required_end = violation
        qty = resource.min_lock_period
        unit = resource.min_lock_period_unit
        name = resource.display_name
        contract_end = self.contract_id.date_end
        if self.space_id:
            self.space_id = False
        else:
            self.desk_id = False
        return {'warning': {
            'title': _('Lock Period Too Long'),
            'message': _(
                "%(asset)s needs a %(qty)s-%(unit)s lock (until %(needed)s), "
                "but this contract ends %(actual)s. Pick a different asset "
                "or extend the contract.",
                asset=name, qty=qty, unit=unit,
                needed=required_end, actual=contract_end,
            ),
        }}
        
    @api.onchange('space_id', 'desk_id')
    def _onchange_check_duplicate_asset(self):
        """Warn and clear the picked asset in the UI if it's already on this contract."""
        
        resource = self.space_id or self.desk_id
        if not resource:
            return

        same = self.contract_id.leased_asset_ids.filtered(
            lambda l: (l.space_id or l.desk_id) == resource
        )
        if len(same) > 1:
            name = resource.display_name
            if self.space_id:
                self.space_id = False
            else:
                self.desk_id = False
            return {'warning': {
                'title': _('Duplicate Asset'),
                'message': _(
                    "%(name)s is already on this contract. "
                    "Pick a different space or desk.",
                    name=name,
                ),
            }}
            
    @api.constrains('space_id', 'desk_id')
    def _check_duplicate_asset(self):
        """Block saving when the same space or desk is leased twice on one contract."""
        
        for asset in self:
            resource = asset.space_id or asset.desk_id
            if not resource:
                continue
            duplicates = asset.contract_id.leased_asset_ids.filtered(
                lambda l: l.id != asset.id
                and (l.space_id or l.desk_id) == resource
            )
            if duplicates:
                raise ValidationError(_(
                    "%(name)s is already leased on this contract. "
                    "Each space or desk can only be added once.",
                    name=resource.display_name,
                ))
                
    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _contract_locked_center(self):
        """Center that all leased assets on this contract must share, taken from
        the first sibling line that already has a resource picked. Reads the
        in-memory contract_id.leased_asset_ids, so it works before the contract
        is saved (NewId lines included)"""
        
        self.ensure_one()
        for asset in self.contract_id.leased_asset_ids:
            if asset.space_id:
                return asset.space_id.center_id
            if asset.desk_id:
                return asset.desk_id.space_id.center_id
        return None
    
    def _get_lock_violation(self):
            """Return (resource, required_end) if this asset's lock period
            exceeds the contract window, else None. Pure read, no side effects."""
            
            self.ensure_one()
            resource = self.space_id or self.desk_id
            contract = self.contract_id
            if not (resource and contract and contract.date_start and contract.date_end) or not resource.is_lock_period:
                return None
            unit = resource.min_lock_period_unit
            qty = resource.min_lock_period or 0
            if not unit or qty <= 0:
                return None
            delta_map = {
                'daily': relativedelta(days=qty),
                'weekly': relativedelta(weeks=qty),
                'monthly': relativedelta(months=qty),
                'yearly': relativedelta(years=qty),
            }
            required_end = contract.date_start + delta_map[unit]
            if required_end > contract.date_end:
                return resource, required_end
            return None
        
    def _renewal_lock_message(self, contract):
        """Explain why a renewal's assets cannot be changed."""

        return _(
            "%(contract)s renews %(previous)s, so it keeps the same spaces and "
            "desks; only the rent and deposit can be adjusted. To move, add or "
            "remove assets, create a new contract instead and turn off Auto "
            "Renew on %(previous)s.",
            contract=contract.name,
            previous=contract.previous_contract_id.name)