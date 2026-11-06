# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, fields, models
from odoo.exceptions import UserError


class BusinessCenterServiceMixin(models.AbstractModel):
    """Taking a rentable asset (space or desk) out of service and back.

    An asset may only leave service (Draft or Maintenance) while nobody
    holds it: each model says what holds it through
    _bc_upcoming_commitments. Leaving service records who, when and why,
    and gives that person a to-do until the asset is available again.
    """

    _name = 'business.center.service.mixin'
    _description = 'Business Center Asset Service Tracking'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    out_of_service_since = fields.Datetime(string='Out of Service Since', readonly=True, copy=False)
    out_of_service_reason = fields.Char(string='Out of Service Reason', readonly=True, copy=False)
    out_of_service_by_id = fields.Many2one('res.users', string='Taken Out of Service By',
                                           readonly=True, copy=False)

    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_open_out_of_service_wizard(self):
        """Ask why the asset leaves service before resetting it to Draft or
        putting it under Maintenance (from the button's context)."""

        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Take Out of Service'),
            'res_model': 'business.center.out.of.service.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_asset_ref': '%s,%s' % (self._name, self.id),
                'default_target_state': self.env.context.get('bc_target_state', 'draft'),
            },
        }

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _bc_upcoming_commitments(self):
        """Names of the running or upcoming contracts and current or future
        bookings holding this asset. Models override it."""

        return []

    def _bc_check_no_commitments(self):
        """Refuse to take an asset out of service while someone holds it."""

        for rec in self:
            items = rec._bc_upcoming_commitments()
            if items:
                shown = ", ".join(items[:5])
                if len(items) > 5:
                    shown = _("%(shown)s and %(count)s more", shown=shown, count=len(items) - 5)
                raise UserError(_(
                    "%(asset)s is held by %(items)s. Move or cancel them first; "
                    "to stop new bookings meanwhile, withdraw it from booking.",
                    asset=rec.display_name, items=shown))

    def _bc_take_out_of_service(self, reason):
        """Record who took the asset out of service, when and why, and give
        them a to-do until it is available again."""

        activity_type = self.env.ref('business_center.mail_activity_type_back_in_service',
                                     raise_if_not_found=False)
        self.write({
            'out_of_service_since': fields.Datetime.now(),
            'out_of_service_reason': reason,
            'out_of_service_by_id': self.env.uid,
        })
        for rec in self:
            rec.message_post(body=_("Taken out of service: %s", reason))
            if activity_type:
                rec.activity_schedule(
                    activity_type_id=activity_type.id,
                    summary=_("Make %s available again", rec.display_name),
                    note=reason,
                    user_id=self.env.uid,
                )

    def _bc_back_in_service(self):
        """Clear the out-of-service record and close its to-do."""

        out = self.filtered('out_of_service_since')
        if not out:
            return
        out.activity_feedback(['business_center.mail_activity_type_back_in_service'],
                              feedback=_("Available again"))
        out.write({
            'out_of_service_since': False,
            'out_of_service_reason': False,
            'out_of_service_by_id': False,
        })
