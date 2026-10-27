# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class BusinessCenterSpace(models.Model):
    """Stores master records for business center spaces"""
    
    _name = 'business.center.space'
    _description = 'A central registry of business center spaces'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'business.center.time.format.mixin']
    _order = 'floor_id'
    
    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    name = fields.Char(string='Name', required=True, copy=False, readonly=False, 
                       index='trigram', default=lambda self: _('New'))
    space_type = fields.Selection([
        ('office', 'Office'),
        ('meeting_room', 'Meeting Room')
    ], required=True, default='office', tracking=True)
    is_coworking = fields.Boolean(default=False, tracking=True)
    desk_count = fields.Integer(string='Desk Count', compute='_compute_desk_count')
    occupied_desk_count = fields.Integer(string='Occupied Desks', compute='_compute_occupied_desk_count')
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
    contract_start_date = fields.Date(string='Start Date')
    contract_end_date = fields.Date(string='End Date')
    contract_period_display = fields.Char(string="Contract Period", compute="_compute_contract_period_display")
    area_sqm = fields.Float(string='Floor Area')
    capacity = fields.Integer(string='Persons/Seats')
    monthly_rent = fields.Monetary(string='Office Lease Rate', currency_field='currency_id', tracking=True, required=True)
    hourly_rate = fields.Monetary(string='Meeting Room Rate', currency_field='currency_id', tracking=True, required=True)
    is_bookable = fields.Boolean(string='Bookable', store=True, readonly=False, compute='_compute_is_bookable', tracking=True,
        help="Whether this meeting room accepts bookings, untick to withdraw meeting room from the booking list")
    min_booking_hour = fields.Float(string='Start Time', tracking=True, required=True)
    max_booking_hour = fields.Float(string='Close Time', tracking=True, required=True)
    operating_hours_display = fields.Char(string='Operating Hours', compute='_compute_operating_hours_display', 
                                         store=True)
    contract_count = fields.Integer(string='Contract Count', compute='_compute_contract_count')
    image_1920 = fields.Image()
    
    product_id = fields.Many2one('product.product', string='Meeting Room Product', domain="[('type', '=', 'service')]", 
                                 default=lambda self: self.env.ref('business_center.product_meeting_room_hire',
                                                                   raise_if_not_found=False), 
                                 help="Service product used on the invoice line when this room's booking hours are charged.")
    contract_ids = fields.Many2many('business.center.contract', string='Contracts',
                                    compute='_compute_contract_ids', store=True)
    leased_asset_ids = fields.One2many('business.center.leased.asset', 'space_id', string='Leased Asset Lines')
    current_contract_id = fields.Many2one('business.center.contract', string='Current Contract',
                                      copy=False, ondelete='set null', tracking=True)
    desk_ids = fields.One2many('business.center.desk', 'space_id', string='Desks')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    occupant_id = fields.Many2one('res.partner', copy=False, tracking=True)
    center_id = fields.Many2one('business.center', string='Business Center', required=True,
                                ondelete='cascade', index=True)
    floor_id = fields.Many2one('business.center.floor', string='Floor', domain="[('center_id', '=', center_id)]")
    company_id = fields.Many2one('res.company', related='center_id.company_id', store=True)
    amenity_ids = fields.Many2many('business.center.amenity', string='Amenities')
    attachment_ids = fields.Many2many('ir.attachment', string='Images')
    gallery_attachment_ids = fields.Many2many('ir.attachment', related='attachment_ids', string="Gallery", readonly=True)

    _monthly_rent_positive = models.Constraint(
        'CHECK (monthly_rent >= 0)',
        'Monthly rent cannot be negative!',
    )
    _hourly_rate_positive = models.Constraint(
        'CHECK (hourly_rate >= 0)',
        'Hourly rate cannot be negative!',
    )
    _min_lock_period = models.Constraint(
        'CHECK (min_lock_period >= 0)',
        'Minimum Lock Period cannot be negative!'
    )
    _name_center_uniq = models.Constraint(
        'UNIQUE(name, center_id)',
        'The space name must be unique per business center!',
    )
    _NON_DRAFT_EDITABLE_FIELDS = {
        'state', 'occupant_id', 'current_contract_id',
        'contract_start_date', 'contract_end_date',
        'message_main_attachment_id','is_bookable'
    }
    
    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.depends('min_booking_hour', 'max_booking_hour')
    def _compute_operating_hours_display(self):
        """Builds a human-readable operating hours string based operating time.
            For Meeting Rooms, formats time slots in AM/PM notation"""
            
        for rec in self:
                rec.operating_hours_display = (
                    f"{rec._float_to_ampm(rec.min_booking_hour)} – {rec._float_to_ampm(rec.max_booking_hour)}"
                )
    
    @api.depends('desk_ids')
    def _compute_desk_count(self):
        """Count the total number of desks belonging to this space"""
        
        for rec in self:
            rec.desk_count = len(rec.desk_ids)
            
    @api.depends('desk_ids.state')
    def _compute_occupied_desk_count(self):
        """Count the desks in this space that are currently occupied"""
        
        for rec in self:
            rec.occupied_desk_count = len(
                rec.desk_ids.filtered(lambda d: d.state == 'occupied'))
    
    @api.depends('space_type')
    def _compute_is_bookable(self):
        """Mark the space as bookable only when it is a meeting room"""
        
        for rec in self:
            if rec.space_type == 'meeting_room':
                rec.is_bookable = True
            else:
                rec.is_bookable = False
                
    @api.depends('contract_start_date', 'contract_end_date')
    def _compute_contract_period_display(self):
        """Build a readable 'start - end' label from the contract dates"""
        
        for space in self:
            start = space.contract_start_date
            end = space.contract_end_date
            if start and end:
                space.contract_period_display = "%s - %s" % (
                    start.strftime('%b %-d, %Y'),
                    end.strftime('%b %-d, %Y'),
                )
            else:
                space.contract_period_display = False

    @api.depends('leased_asset_ids.contract_id')
    def _compute_contract_ids(self):
        """Gather all contracts linked to this space through its leased asset lines"""
        
        for rec in self:
            rec.contract_ids = rec.leased_asset_ids.mapped('contract_id')
        
    @api.depends('name', 'capacity', 'space_type')
    def _compute_display_name(self):
        """Append the seat capacity to the name for meeting rooms"""
        
        for space in self:
            if space.capacity and space.space_type == 'meeting_room':
                space.display_name = "%s (%s seater)" % (space.name, space.capacity)
            else:
                space.display_name = space.name
        
    @api.depends('leased_asset_ids')
    def _compute_contract_count(self):
        """Count the leased asset lines (contracts) tied to this space"""
        
        
        for rec in self:
            rec.contract_count = len(rec.leased_asset_ids)
            
    def write(self, vals):
        """Only allow status/occupancy updates once the space has left draft"""

        locked_fields = set(vals) - self._NON_DRAFT_EDITABLE_FIELDS
        if locked_fields:
            non_draft = self.filtered(lambda s: s.state != 'draft')
            if non_draft:
                raise UserError(_(
                    "Space %(space)s can only be edited in Draft state. "
                    "Use 'Reset to Draft' first.",
                    space=non_draft[0].name,
                ))
        return super().write(vals)
           
    @api.model_create_multi
    def create(self, vals_list):
        """Assigns a per-centre reference (e.g. BC01/F01/OS0001) to new
        spaces at creation time, unless a name was explicitly provided."""

        for vals in vals_list:
            if vals.get('name', _("New")) == _("New"):
                center = self.env['business.center'].browse(
                    vals.get('center_id') or self.env.context.get('default_center_id'))
                floor = self.env['business.center.floor'].browse(vals.get('floor_id'))
                if not center:
                    continue
                prefix = ('M' if vals.get('space_type') == 'meeting_room'
                          else 'C' if vals.get('is_coworking') else 'O')
                sequence = "%sS%04d" % (prefix, center._next_space_number())
                parts = [part for part in (center.code, floor.name, sequence) if part]
                vals['name'] = '/'.join(parts)
        return super().create(vals_list)
                
    @api.ondelete(at_uninstall=False)
    def _unlink_except_live_contract(self):
        """Prevent deleting a space while it still belongs to a draft or active contract"""
        
        for rec in self:
            live = rec.leased_asset_ids.filtered(
                lambda a: a.contract_id.state in ('draft', 'upcoming', 'active')
            )
            if live:
                raise UserError(_(
                    "Space %(space)s is part of contract(s) %(contracts)s. "
                    "Cancel or amend the contract before deleting the space.",
                    space=rec.name,
                    contracts=", ".join(live.mapped('contract_id.name')),
                ))
            if rec.space_type != 'meeting_room':
                continue
            bookings = self.env['business.center.booking'].search([
                ('meeting_room_id', '=', rec.id),
                ('state', '!=', 'cancelled'),
            ], limit=5)
            if bookings:
                raise UserError(_(
                    "%(room)s has bookings (%(bookings)s) and cannot be "
                    "deleted. Cancel them first.",
                    room=rec.display_name,
                    bookings=", ".join(bookings.mapped('name')),
                ))
                
    # ------------------------------------------------------------------------------
    #   MARK: CONSTRAINT/ONCHANGE METHODS
    # ------------------------------------------------------------------------------  
    @api.constrains('min_booking_hour', 'max_booking_hour')
    def _check_operating_hours(self):
        """A room whose close time precedes its open time rejects every booking."""

        for rec in self:
            if rec.space_type == 'meeting_room' \
                    and rec.max_booking_hour <= rec.min_booking_hour:
                raise ValidationError(_(
                    "%s closes before it opens.", rec.display_name))
                
    @api.constrains('space_type', 'is_coworking')
    def _check_coworking_is_office(self):
        """A coworking space must be an office; meeting rooms cannot be coworking."""

        for rec in self:
            if rec.is_coworking and rec.space_type != 'office':
                raise ValidationError(_(
                    "%s is marked as coworking, so it must be an office. "
                    "Untick Coworking before changing it to a meeting room.",
                    rec.display_name))
                
    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_set_draft(self):
        """Reset the space to draft, refusing while a live contract holds it
        or any of its desks is occupied; free desks go back to draft too.

        Writing state alone would leave occupant_id and current_contract_id
        pointing at a running contract while the space vanished from every
        'occupied' filter — the kanban, the occupancy rate, and the centre's
        delete guard.
        """

        for rec in self:
            if rec.current_contract_id.state in ('upcoming', 'active'):
                raise UserError(_(
                    "%(space)s is held by contract %(contract)s. Cancel or "
                    "amend the contract before resetting the space.",
                    space=rec.display_name,
                    contract=rec.current_contract_id.name,
                ))
            occupied = rec.desk_ids.filtered(lambda d: d.state == 'occupied')
            if occupied:
                raise UserError(_(
                    "%(space)s still has occupied desks (%(desks)s). Release "
                    "them before resetting the space.",
                    space=rec.display_name,
                    desks=", ".join(occupied.mapped('name')),
                ))
        self.write({'state': 'draft'})
        self.desk_ids.filtered(lambda d: d.state != 'draft').write({'state': 'draft'})

    def action_set_maintenance(self):
        """Put the space under maintenance; its available desks follow,
        occupied desks stay with their tenants"""

        self.write({'state': 'maintenance'})
        self.desk_ids.filtered(lambda d: d.state == 'available').write({'state': 'maintenance'})

    def action_set_occupied(self):
        """Mark the space as occupied, refusing if no active contract is linked"""
        
        for rec in self:
            if not rec.current_contract_id:
                raise UserError(_(
                    "Space %s cannot be marked as occupied without an active contract.",
                    rec.name))
        self.write({'state': 'occupied'})
        
    def action_set_available(self):
        """Mark the space as available for new contracts or bookings. A
        coworking space whose desks are all taken goes straight to Occupied."""

        self.write({'state': 'available'})
        self._sync_coworking_state()
        
    def action_toggle_bookable(self):
        """Withdraw a meeting room from booking, or open it back up.

        Separate from state: a room can stay occupied and visible while being
        closed to new bookings — a projector out of order, or a room reserved
        for internal use. Maintenance would be the wrong signal for those.
        """

        for rec in self:
            if rec.space_type != 'meeting_room':
                raise UserError(_(
                    "%s is not a meeting room, so it has no booking status.",
                    rec.display_name))
            rec.is_bookable = not rec.is_bookable
        
    def action_open_contracts(self):
        """Open the list of contracts that lease this space"""
        
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contracts'),
            'res_model': 'business.center.contract',
            'view_mode': 'list,form',
            'domain': [('leased_asset_ids.space_id', 'in', self.id)],
            'context': {'list_view_ref': False},
            'order': 'state asc',
        }
        
    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _sync_coworking_state(self):
        """Derive a coworking space's status from its desks.

        Available while at least one desk can still be leased; Occupied once
        none can. Draft and Maintenance are set deliberately by staff, so they
        are left alone, as are coworking spaces without desks.
        """

        for space in self.filtered(
                lambda s: s.is_coworking and s.state in ('available', 'occupied')):
            desks = space.desk_ids
            if not desks:
                continue
            if any(d.state == 'available' for d in desks):
                target = 'available'
            elif any(d.state == 'occupied' for d in desks):
                target = 'occupied'
            else:
                continue
            if space.state != target:
                space.write({'state': target})