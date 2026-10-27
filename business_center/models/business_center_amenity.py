# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class BusinessCenterAmenity(models.Model):
    """Stores master records for business center amenities"""
    
    _name = 'business.center.amenity'
    _description = 'A central registry of business center amenities'
    
    # ------------------------------------------------------------------------------
    #   MARK: FIELDS 
    # ------------------------------------------------------------------------------
    name = fields.Char(string='Name', required=True)
    icon = fields.Image()
    
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)