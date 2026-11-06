# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class BusinessCenterSpace(models.Model):
    """Stores master records for business center spaces"""
    
    _name = 'business.center.space'
    _description = 'A central registry of business center spaces'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'business.center.time.format.mixin', 
                'business.center.search.panel.mixin', 'business.center.service.mixin']
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
    space_category = fields.Selection([
        ('private_office', 'Private Office'),
        ('coworking', 'Coworking Space'),
        ('meeting_room', 'Meeting Room'),
    ], string='Category', compute='_compute_space_category', store=True,
        help="Space type with coworking spaces told apart from private offices, "
             "for grouping and filtering.")
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
    area_sqm = fields.Float(string='Floor Area', tracking=True)
    capacity = fields.Integer(string='Persons/Seats', tracking=True)
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
    active = fields.Boolean(default=True, tracking=True,
                        help="Archived spaces are kept for their history (contracts, "
                                "invoices, bookings) but no longer offered anywhere.")
    
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
        # status and occupancy, managed by the contract and booking flows
        'state', 'occupant_id', 'current_contract_id',
        'contract_start_date', 'contract_end_date',
        'message_main_attachment_id', 'is_bookable', 'active',
        'out_of_service_since', 'out_of_service_reason', 'out_of_service_by_id',
        # commercial: applies to new contracts and bookings only
        'monthly_rent', 'hourly_rate', 'product_id',
        'is_lock_period', 'min_lock_period', 'min_lock_period_unit',
        # descriptive
        'capacity', 'area_sqm', 'amenity_ids', 'image_1920', 'attachment_ids',
        # operational, checked against future bookings
        'min_booking_hour', 'max_booking_hour',
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
                
    @api.depends('space_type', 'is_coworking')
    def _compute_space_category(self):
        """Split offices into private offices and coworking spaces, so the
        three kinds of space can be grouped separately."""

        for rec in self:
            if rec.space_type == 'meeting_room':
                rec.space_category = 'meeting_room'
            elif rec.is_coworking:
                rec.space_category = 'coworking'
            else:
                rec.space_category = 'private_office'
                
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
        
    @api.depends('name', 'capacity', 'space_type', 'is_coworking')
    @api.depends_context('bc_show_capacity')
    def _compute_display_name(self):
        """Append the seat capacity, e.g. 'BC01/F0/OS0001 (4 seater)'.

        Always for meeting rooms. For private offices only when the caller
        asks for it with bc_show_capacity (picking a space on a contract),
        so invoice lines, the agreement PDF and other screens keep the
        plain reference.
        """

        show_office = self.env.context.get('bc_show_capacity')
        for space in self:
            is_private_office = space.space_type == 'office' and not space.is_coworking
            if space.capacity and (space.space_type == 'meeting_room'
                                   or (show_office and is_private_office)):
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
        if 'active' in vals and not vals['active']:
            busy = self.filtered(lambda s: s.state == 'occupied' or s._bc_upcoming_commitments()
                                 or s.leased_asset_ids.filtered(lambda a: a.contract_id.state == 'draft'))
            if busy:
                raise UserError(_(
                    "Space %s is occupied, booked or part of a live contract and cannot "
                    "be archived.", busy[0].name))
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
    def _unlink_except_has_history(self):
        """A space with history (contracts, bookings, or desks with contracts)
        keeps its record; archive it instead."""

        for rec in self:
            if rec._bc_has_history():
                raise UserError(_(
                    "%s has contracts or bookings in its history and cannot be "
                    "deleted. Archive it instead to stop using it.", rec.display_name))
                
    # ------------------------------------------------------------------------------
    #   MARK: CONSTRAINT/ONCHANGE METHODS
    # ------------------------------------------------------------------------------  
    @api.constrains('min_booking_hour', 'max_booking_hour')
    def _check_operating_hours(self):
        """Opening hours must make sense, and may not shut out a booking
        already made: future bookings must still fit the new hours."""

        today = fields.Date.context_today(self)
        for rec in self:
            open_h, close_h = rec.min_booking_hour, rec.max_booking_hour
            if (rec.space_type == 'meeting_room' or (rec.is_coworking and close_h)) \
                    and close_h <= open_h:
                raise ValidationError(_("%s closes before it opens.", rec.display_name))
            if not close_h:
                continue  # coworking space open all day
            if rec.space_type == 'meeting_room':
                bookings = self.env['business.center.booking'].sudo().search([
                    ('meeting_room_id', '=', rec.id), ('state', '=', 'confirmed'),
                    ('booking_date', '>=', today)])
            elif rec.is_coworking:
                bookings = self.env['business.center.desk.booking'].sudo().search([
                    ('desk_id.space_id', '=', rec.id),
                    ('state', 'in', ('confirmed', 'checked_in')),
                    ('booking_date', '>=', today)])
            else:
                continue
            outside = bookings.filtered(lambda b: b.start_time < open_h or b.end_time > close_h)
            if outside:
                raise ValidationError(_(
                    "%(space)s has bookings outside the new hours (%(bookings)s). "
                    "Move or cancel them first.",
                    space=rec.display_name, bookings=", ".join(outside[:5].mapped('name'))))
                
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
        """Reset the space to draft, only while nothing holds it (running or
        upcoming contracts, current or future bookings, on it or its desks);
        its desks go back to draft too. Past history is left as it is."""

        self._bc_check_no_commitments()
        self.write({'state': 'draft'})
        self.desk_ids.filtered(lambda d: d.state != 'draft').write({'state': 'draft'})

    def action_set_maintenance(self):
        """Put the space under maintenance, only while nothing holds it; its
        available desks follow."""

        self._bc_check_no_commitments()
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
        coworking space whose desks are all taken goes straight to Occupied.
        Ends any out-of-service period and closes its to-do."""

        self.write({'state': 'available'})
        self._sync_coworking_state()
        self._bc_back_in_service()
        
    def action_toggle_bookable(self):
        """Withdraw a meeting room from booking, or open it back up.

        Separate from state: a room can stay occupied and visible while being
        closed to new bookings — a projector out of order, or a room reserved
        for internal use. Maintenance would be the wrong signal for those.
        Existing bookings continue; the chatter lists them on withdrawal.
        """

        for rec in self:
            if rec.space_type != 'meeting_room':
                raise UserError(_(
                    "%s is not a meeting room, so it has no booking status.",
                    rec.display_name))
            rec.is_bookable = not rec.is_bookable
            if not rec.is_bookable:
                upcoming = rec._bc_upcoming_commitments()
                if upcoming:
                    rec.message_post(body=_(
                        "Withdrawn from booking. Existing bookings continue: %s.",
                        ", ".join(upcoming[:5])))
        
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
                
    def _bc_has_history(self):
        """True when the space was ever on a contract, ever booked (meeting
        rooms), or, for a coworking space, one of its desks has history."""

        self.ensure_one()
        space = self.sudo()
        if space.leased_asset_ids:
            return True
        if space.space_type == 'meeting_room' and self.env['business.center.booking'].sudo().search_count(
                [('meeting_room_id', '=', space.id)], limit=1):
            return True
        return any(desk._bc_has_history() for desk in space.with_context(active_test=False).desk_ids)
    
    def _bc_upcoming_commitments(self):
        """Running or upcoming contracts and current or future bookings that
        hold this space, including those of its desks."""

        self.ensure_one()
        today = fields.Date.context_today(self)
        items = self.sudo().leased_asset_ids.contract_id.filtered(
            lambda c: c.state in ('upcoming', 'active')).mapped('name')
        if self.space_type == 'meeting_room':
            items += self.env['business.center.booking'].sudo().search([
                ('meeting_room_id', '=', self.id), ('state', '=', 'confirmed'),
                ('booking_date', '>=', today)]).mapped('name')
        for desk in self.desk_ids:
            items += desk._bc_upcoming_commitments()
        return items