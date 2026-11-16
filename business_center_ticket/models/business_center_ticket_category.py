# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class BusinessCenterTicketCategory(models.Model):
    """What a ticket is about (internet, facilities, maintenance, ...) and
    who handles that kind of ticket in each centre."""

    _name = 'business.center.ticket.category'
    _description = 'Ticket Category'
    _order = 'sequence, name'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    name = fields.Char(string='Category', required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Char(string='Shown to Members', translate=True,
                              help="One line telling members what to report under this category.")
    assignee_ids = fields.One2many('business.center.ticket.category.assignee', 'category_id',
                                   string='Assignees per Centre')

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _bc_assignee_for(self, center):
        """Who handles this category in ``center``: the person set for that
        centre, else the centre's manager."""

        self.ensure_one()
        line = self.assignee_ids.filtered(lambda a: a.center_id == center)[:1]
        return line.user_id or center.manager_id


class BusinessCenterTicketCategoryAssignee(models.Model):
    """The staff member handling one ticket category in one centre."""

    _name = 'business.center.ticket.category.assignee'
    _description = 'Ticket Category Assignee'
    _order = 'center_id'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    category_id = fields.Many2one('business.center.ticket.category', string='Category',
                                  required=True, ondelete='cascade')
    center_id = fields.Many2one('business.center', string='Business Center', required=True,
                                ondelete='cascade')
    user_id = fields.Many2one('res.users', string='Assigned To', required=True,
                              domain="[('share', '=', False)]")

    _category_center_uniq = models.Constraint(
        'UNIQUE(category_id, center_id)',
        'A category has one assignee per business center.',
    )
