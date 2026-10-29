# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BusinessCenterDesk(models.Model):
    """Stores master records for business center desks"""
    
    _name = 'business.center.desk'
    _description = 'A central registry of business center desks'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    
    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    name = fields.Char(string='Name', required=True, copy=False, readonly=False, 
                       index='trigram', default=lambda self: _('New'))
    row_label = fields.Char(string='Seat Rows')
    position = fields.Integer(string='Position')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('available', 'Available'),
        ('occupied', 'Occupied'),
        ('maintenance', 'Maintenance')
    ], required=True, default='draft', tracking=True, group_expand=True)
    min_lock_period = fields.Integer(string='Minimum Lock Period', default=1)
    min_lock_period_unit = fields.Selection([
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly')
    ], default='monthly', tracking=True, group_expand=True)
    is_lock_period = fields.Boolean(string="Lock Period", default=True)
    monthly_rent = fields.Monetary(string='Per Seat Monthly rent', currency_field='currency_id', tracking=True)
    active = fields.Boolean(default=True)
    desk_contract_count = fields.Integer(string='Contract Count', compute='_compute_desk_contract_count')
    contract_start_date = fields.Date(string='Start Date')
    contract_end_date = fields.Date(string='End Date')
    contract_period_display = fields.Char(string="Contract Period", compute="_compute_contract_period_display")
    
    contract_ids = fields.Many2many('business.center.contract', string='Contracts',
                                    compute='_compute_contract_ids', store=True)
    space_id = fields.Many2one('business.center.space', required=True, ondelete='cascade', index=True,
                               domain="[('is_coworking', '=', True)]")
    center_id = fields.Many2one('business.center', related='space_id.center_id', store=True)
    floor_id = fields.Many2one('business.center.floor', related='space_id.floor_id', store=True)
    occupant_id = fields.Many2one('res.partner', copy=False, tracking=True)
    current_contract_id = fields.Many2one('business.center.contract', copy=False, string='Contract')
    currency_id = fields.Many2one('res.currency', string='Currency')
    company_id = fields.Many2one('res.company', related='center_id.company_id', store=True)
    leased_asset_ids = fields.One2many('business.center.leased.asset', 'desk_id', string='Leased Asset Lines')

    _name_space_uniq = models.Constraint(
        'UNIQUE(name, space_id)',
         'The desk name must be unique per coworking space!'
    )
    _monthly_rent_positive = models.Constraint(
        'CHECK (monthly_rent >= 0)',
         'Monthly rent cannot be negative!'
    )
    _NON_DRAFT_EDITABLE_FIELDS = {
        'state', 'occupant_id', 'current_contract_id',
        'contract_start_date', 'contract_end_date',
        'message_main_attachment_id', 'active',
    }

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    def write(self, vals):
        """Only allow status/occupancy updates once the desk has left draft,
        and refuse archiving a desk that is occupied or on a live contract"""

        locked_fields = set(vals) - self._NON_DRAFT_EDITABLE_FIELDS
        if locked_fields:
            non_draft = self.filtered(lambda s: s.state != 'draft')
            if non_draft:
                raise UserError(_(
                    "Desk %(desk)s can only be edited in Draft state. "
                    "Use 'Reset to Draft' first.",
                    desk=non_draft[0].name,
                ))
        if 'active' in vals and not vals['active']:
            busy = self.filtered(lambda d: d.state == 'occupied' or d.leased_asset_ids.filtered(
                lambda a: a.contract_id.state in ('draft', 'upcoming', 'active')))
            if busy:
                raise UserError(_(
                    "Desk %s is occupied or part of a live contract and "
                    "cannot be archived.", busy[0].name))
        res = super().write(vals)
        if {'state', 'active'} & set(vals):
            self.mapped('space_id')._sync_coworking_state()
        return res
    
    def unlink(self):
        """Removing a desk can change whether its coworking space still has a
        free seat, so re-derive the space's status afterwards."""

        spaces = self.mapped('space_id')
        res = super().unlink()
        spaces.exists()._sync_coworking_state()
        return res
    
    @api.model_create_multi
    def create(self, vals_list):
        """Assigns a unique sequence reference (e.g. BC01/F1/DA2) to new
        business center desks at creation time, unless a name was explicitly provided."""

        for vals in vals_list:
            if vals.get('name', _("New")) == _("New"):
                space_id = vals.get('space_id') or self.env.context.get('default_space_id')
                space = self.env['business.center.space'].browse(space_id)
                center = space.center_id
                floor = space.floor_id
                row_label = vals.get('row_label') or ''
                position = vals.get('position')
                position = str(position) if position else ''
                sequence = 'D' + row_label + position
                parts = [part for part in (center.code, floor.name, sequence) if part]
                vals['name'] = '/'.join(parts)
        return super().create(vals_list)
    
    @api.model
    def search_panel_select_multi_range(self, field_name, **kwargs):
        """Odoo 19 web client sends group_domain=None for a grouped many2one
        filter with counters when no value is ticked; normalise it so the
        domain AND does not crash."""

        if kwargs.get('group_domain') is None:
            kwargs['group_domain'] = []
        return super().search_panel_select_multi_range(field_name, **kwargs)
    
    @api.ondelete(at_uninstall=False)
    def _unlink_except_live_contract(self):
        """Prevent deleting a desk while it still belongs to a draft or active contract"""
        
        for rec in self:
            live = rec.leased_asset_ids.filtered(
                lambda a: a.contract_id.state in ('draft', 'upcoming', 'active')
            )
            if live:
                raise UserError(_(
                    "Desk %(desk)s is part of contract(s) %(contracts)s. "
                    "Cancel or amend the contract before deleting the space.",
                    desk=rec.name,
                    contracts=", ".join(live.mapped('contract_id.name')),
                ))
            
    @api.depends('leased_asset_ids')
    def _compute_desk_contract_count(self):
        """Count the leased asset lines (contracts) tied to this desk"""
        
        for rec in self:
            rec.desk_contract_count = len(rec.leased_asset_ids)

    @api.depends('leased_asset_ids.contract_id')
    def _compute_contract_ids(self):
        """Gather all contracts linked to this desk through its leased asset lines"""
        
        for rec in self:
            rec.contract_ids = rec.leased_asset_ids.mapped('contract_id')
            
    @api.depends('contract_start_date', 'contract_end_date')
    def _compute_contract_period_display(self):
        """Build a readable 'start - end' label from the contract dates"""
        
        for space in self:
            start = space.contract_start_date
            end = space.contract_end_date
            if start and end:
                space.contract_period_display = "%s - %s" % (
                    start.strftime('%-d/%-m/%Y'),
                    end.strftime('%-d/%-m/%Y'),
                )
            else:
                space.contract_period_display = False
        
    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_set_maintenance(self):
        """Put the desk under maintenance"""
        
        self.write({'state': 'maintenance'})

    def action_set_occupied(self):
        """Mark the desk as occupied, refusing if no active contract is linked"""
        
        for rec in self:
            if not rec.current_contract_id:
                raise UserError(_(
                    "Space %s cannot be marked as occupied without an active contract.",
                    rec.name))
        self.write({'state': 'occupied'})
        
    def action_set_draft(self):
        """Reset the desk to draft, refusing while a live contract holds it.

        Writing state alone would leave occupant_id and current_contract_id
        pointing at a running contract while the space vanished from every
        'occupied' filter — the kanban, the occupancy rate, and the centre's
        delete guard.
        """

        for rec in self:
            if rec.current_contract_id.state in ('upcoming', 'active'):
                raise UserError(_(
                    "%(desk)s is held by contract %(contract)s. Cancel or "
                    "amend the contract before resetting the space.",
                    desk=rec.display_name,
                    contract=rec.current_contract_id.name,
                ))
        self.write({'state': 'draft'})
        
    def action_set_available(self):
        """Mark the desk as available, only once its coworking space is open"""

        for rec in self:
            if rec.space_id.state != 'available':
                raise UserError(_(
                    "%(desk)s cannot be made available while its space "
                    "%(space)s is not available. Set the space Available first.",
                    desk=rec.display_name,
                    space=rec.space_id.display_name,
                ))
        self.write({'state': 'available'})
        
    def action_open_desk_contracts(self):
        """Open the list of contracts that lease this desk"""
        
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contracts'),
            'res_model': 'business.center.contract',
            'view_mode': 'list,form',
            'domain': [('leased_asset_ids.desk_id', 'in', self.id)],
            'context': {'list_view_ref': False},
            'order': 'state asc',

        }