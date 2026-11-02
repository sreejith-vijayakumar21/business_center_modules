# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models


class BusinessCenterContractCharge(models.Model):
    """Accrued charge line (booking overage or manual charge) awaiting invoicing."""

    _name = 'business.center.contract.charge'
    _description = 'Business Center Contract Charge'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    description = fields.Char(string='Description', required=True)
    date = fields.Date(string='Charge Date', required=True,
                       default=fields.Date.context_today)
    quantity = fields.Float(string='Quantity', default=1)
    unit_price = fields.Monetary(string='Unit Price', currency_field='currency_id', tracking=True)
    amount = fields.Monetary(string='Amount', compute='_compute_amount', store=True, 
                             currency_field='currency_id', tracking=True)
    state = fields.Selection([
        ('pending', 'Pending'),
        ('invoiced', 'Invoiced'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='pending')
    
    desk_booking_id = fields.Many2one('business.center.desk.booking', string='Hot Desk Booking',
                                      ondelete='restrict', index=True)
    contract_id = fields.Many2one('business.center.contract', string='Contract',
                                  required=True, ondelete='cascade', index=True)
    booking_id = fields.Many2one('business.center.booking', string='Source Booking',
                                 ondelete='set null')
    invoice_line_id = fields.Many2one('account.move.line', string='Invoice Line',
                                      readonly=True, copy=False)
    currency_id = fields.Many2one('res.currency', string='Currency',
                                  related='contract_id.currency_id', store=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 related='contract_id.company_id', store=True)

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.depends('quantity', 'unit_price')
    def _compute_amount(self):
        """Compute the charge amount as quantity times unit price."""
        
        for rec in self:
            rec.amount = rec.quantity * rec.unit_price
            
    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _bc_invoice_resource(self):
        """The booked resource this charge bills: a hot desk or a meeting room."""

        self.ensure_one()
        return self.desk_booking_id.desk_id or self.booking_id.meeting_room_id

    def _bc_invoice_product(self):
        """The product its invoice line uses."""

        self.ensure_one()
        if self.desk_booking_id:
            return self.env.ref('business_center.product_hot_desk_booking')
        return self.booking_id.meeting_room_id.product_id

    def _bc_invoice_label(self):
        """The kind of charge, shown on the invoice line."""

        self.ensure_one()
        return _("Hot Desk") if self.desk_booking_id else _("Meeting Room")