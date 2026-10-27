# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BusinessCenter(models.Model):
    """Stores master records for business centers"""
    
    _name = 'business.center'
    _description = 'A central registry of business centers'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'image.mixin']

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    name = fields.Char(string='Building/Center Name', required=True , tracking=True)
    code = fields.Char(string='Code', required=True, copy=False, readonly=False, 
                       index='trigram', default=lambda self: _('New'))
    state = fields.Selection([
        ('no_active', 'Not Active'),
        ('active', 'Active'),
        ('maintenance', 'Maintenance')
    ], required=True, default='active', tracking=True, group_expand=True)
    image_1920 = fields.Image()
    street = fields.Char()
    street2 = fields.Char()
    city = fields.Char()
    zip = fields.Char()
    email = fields.Char(string='Email', required=True)
    phone_number = fields.Char(string='Phone Number')
    notes = fields.Html(string='Internal Notes')
    space_count = fields.Integer(string='Space Count', compute='_compute_space_count')
    desk_count = fields.Integer(string='Desk Count', compute='_compute_desk_count')
    contract_count = fields.Integer(string='Contract Count', compute='_compute_contract_count')
    meeting_room_count = fields.Integer(string='Meeting Room Count', compute='_compute_meeting_room_count')
    occupancy_rate = fields.Float(string='Occupancy Rate', compute='_compute_occupancy_rate')
    space_sequence_next = fields.Integer(string='Next Space Number', default=1, copy=False)
    
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    state_id = fields.Many2one('res.country.state', string='State/Province')
    country_id = fields.Many2one('res.country', string='Country')
    manager_id = fields.Many2one('res.users', string='Manager', tracking=True, required=True)
    floor_ids = fields.One2many('business.center.floor', 'center_id', string='Floors')
    space_ids = fields.One2many('business.center.space', 'center_id', string='Spaces')
    attachment_ids = fields.Many2many('ir.attachment', string='Images')
    gallery_attachment_ids = fields.Many2many('ir.attachment', related='attachment_ids', string="Gallery", readonly=True)
    
    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        'Code must be unique per company.',
    )
    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    
    @api.depends('space_ids.space_type','space_ids.is_coworking')
    def _compute_space_count(self):
        """Count spaces of type 'private_office' (cabins) for this center"""
        
        for rec in self:
            rec.space_count = len(
                rec.space_ids.filtered(lambda s: s.space_type == 'office' and not s.is_coworking))
    
    @api.depends('space_ids.desk_count')
    def _compute_desk_count(self):
        """count desks connected to this business center"""
        
        for rec in self:
            rec.desk_count = sum(rec.space_ids.mapped('desk_count'))
            
    @api.depends('space_ids.space_type')
    def _compute_meeting_room_count(self):
        """count meeting rooms connected to this business center"""
        
        for rec in self:
            rec.meeting_room_count = len(
                rec.space_ids.filtered(lambda s: s.space_type == 'meeting_room'))
    
    @api.depends('space_ids.state', 'space_ids.space_type', 'space_ids.is_coworking',
                'space_ids.desk_ids.state', 'desk_count', 'space_count')
    def _compute_occupancy_rate(self):
        """Compute the occupancy percentage of the whole center"""
         
        for rec in self:
            total_units = rec.desk_count + rec.space_count

            # occupied offices (private, non-coworking)
            occupied_offices = len(rec.space_ids.filtered(
                lambda s: s.space_type == 'office' and not s.is_coworking
                        and s.state == 'occupied'
            ))
            # occupied desks (separate model, reached through spaces)
            occupied_desks = len(rec.space_ids.mapped('desk_ids').filtered(
                lambda d: d.state == 'occupied'
            ))

            occupied = occupied_offices + occupied_desks
            rec.occupancy_rate = (occupied / total_units) * 100 if total_units else 0.0
                
    @api.depends('space_ids.current_contract_id', 'space_ids.desk_ids.current_contract_id')
    def _compute_contract_count(self):
        """Count the distinct active contracts tied to this center's spaces and desks"""

        for rec in self:
            contracts = rec.space_ids.mapped('current_contract_id')
            contracts |= rec.space_ids.mapped('desk_ids.current_contract_id')
            rec.contract_count = len(contracts)
    
    @api.model_create_multi
    def create(self, vals_list):
        """Assigns a unique sequence reference (e.g. BC-01) to new
        business centers at creation time, unless a name was explicitly provided."""
        
        for vals in vals_list:
            if vals.get('code', _("New")) == _("New"):
                vals['code'] = self.env['ir.sequence'].sudo().next_by_code(
                    'business.center') or _("New")
        return super().create(vals_list)
    
    @api.ondelete(at_uninstall=False)
    def _unlink_except_occupied_children(self):
        """Refuse deletion while any space or desk in this center is occupied.

        Queried directly rather than relying on the children's own delete
        guards: `ondelete='cascade'` removes them at SQL level, so their
        `@api.ondelete` methods never run.
        """

        for center in self:
            spaces = center.space_ids.filtered(lambda s: s.state == 'occupied')
            desks = center.space_ids.mapped('desk_ids').filtered(
                lambda d: d.state == 'occupied')
            occupied = spaces.mapped('display_name') + desks.mapped('display_name')
            if occupied:
                raise UserError(_(
                    "%(center)s cannot be deleted — %(names)s still in use. "
                    "Release or cancel the contracts first.",
                    center=center.display_name,
                    names=", ".join(occupied),
                ))
    
    # ------------------------------------------------------------------------------
    #   MARK: CONSTRAINT/ONCHANGE METHODS
    # ------------------------------------------------------------------------------
    @api.onchange('state_id')
    def _onchange_state_id(self):
        """Fill the country from the selected state, and scope the state list
        to the chosen country."""

        if self.state_id:
            self.country_id = self.state_id.country_id
            
    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _next_space_number(self):
        """Return this centre's next space number and advance its counter.

        The row lock serialises concurrent space creation in the same
        centre, so two users can never receive the same number.
        """

        self.ensure_one()
        self.env.cr.execute(
            "SELECT space_sequence_next FROM business_center WHERE id = %s FOR UPDATE",
            (self.id,))
        number = self.env.cr.fetchone()[0] or 1
        self.env.cr.execute(
            "UPDATE business_center SET space_sequence_next = %s WHERE id = %s",
            (number + 1, self.id))
        self.invalidate_recordset(['space_sequence_next'])
        return number
    
    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_set_active(self):
        """set the business center as Active"""
        
        self.write({'state': 'active'})

    def action_set_no_active(self):
        """set the business center as Deactive"""
        
        self.write({'state': 'no_active'})

    def action_set_maintenance(self):
        """set the business center as under Maintenance"""
        
        self.write({'state': 'maintenance'})
    
    def action_open_available_spaces(self):
        """Open the spaces belonging to this specific center"""
        
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cabin Spaces'),
            'res_model': 'business.center.space',
            'view_mode': 'kanban,list,form',
            'domain': [('space_type', '=', 'office'),('is_coworking', '=', False),
                       ('center_id', '=', self.id)]
        }
    
    def action_open_available_desks(self):
        """Open the desks belonging to this specific center"""
        
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Desks'),
            'res_model': 'business.center.desk',
            'view_mode': 'kanban,form',
            'domain': [('center_id', '=', self.id)]
        }
    
    def action_open_available_meeting_rooms(self):
        """Open the meetings rooms belonging to this specific center"""
        
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Meeting rooms'),
            'res_model': 'business.center.space',
            'view_mode': 'kanban,list,form',
            'domain': [('space_type', '=', 'meeting_room'), 
                       ('center_id', '=', self.id)]
        }
        
    def action_open_available_contracts(self):
        """Open the active contracts attached to this center's spaces and desks"""

        self.ensure_one()
        contracts = self.space_ids.mapped('current_contract_id')
        contracts |= self.space_ids.mapped('desk_ids.current_contract_id')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contracts'),
            'res_model': 'business.center.contract',
            'view_mode': 'list,form',
            'domain': [('id', 'in', contracts.ids)],
        }