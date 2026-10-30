# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class BusinessCenterFloor(models.Model):
    """Stores master records for business center floors"""
    
    _name = 'business.center.floor'
    _description = 'A central registry of business center floors'
    _order = 'sequence'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    name = fields.Char(string='Floor Name', required=True)
    sequence = fields.Integer(default=10)
    note = fields.Char(string='Remark')
    space_count = fields.Integer(string='Cabin Space Count', compute='_compute_space_count')
    
    company_id = fields.Many2one(related='center_id.company_id', store=True, string='Company')
    center_id = fields.Many2one('business.center', string='Business Center', required=True,
                                ondelete='cascade', index=True)
    space_ids = fields.One2many('business.center.space', 'floor_id', string='Spaces')
    
    _name_center_uniq = models.Constraint(
        'UNIQUE(name, center_id)',
        'The floor name must be unique per business center!',
    )
    
    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.depends('space_ids')
    def _compute_space_count(self):
        """Count spaces of type 'private_office' (cabins) for this center"""
        
        for rec in self:
            rec.space_count = len(rec.space_ids)
            
    @api.model_create_multi
    def create(self, vals_list):
        """Place each new floor after the last floor of its center, unless a
        sequence was given explicitly. Tracked per center so a batch create
        doesn't hand out the same number twice."""

        next_seq = {}
        for vals in vals_list:
            if 'sequence' in vals:
                continue
            center_id = vals.get('center_id') or self.env.context.get('default_center_id')
            if not center_id:
                continue
            if center_id not in next_seq:
                last = self.search([('center_id', '=', center_id)],
                                   order='sequence desc', limit=1)
                next_seq[center_id] = last.sequence + 10 if last else 10
            vals['sequence'] = next_seq[center_id]
            next_seq[center_id] += 10
        return super().create(vals_list)
            
    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_open_floor_spaces(self):
        """Open the spaces on this floor, pre-filtered in the search panel"""

        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('%(center)s / %(floor)s', center=self.center_id.name, floor=self.name),
            'res_model': 'business.center.space',
            'view_mode': 'kanban,list,form',
            'context': {
                'searchpanel_default_center_id': self.center_id.id,
                'searchpanel_default_floor_id': [self.id],
                'default_center_id': self.center_id.id,
                'default_floor_id': self.id,
            },
        }