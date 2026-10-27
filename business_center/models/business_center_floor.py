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