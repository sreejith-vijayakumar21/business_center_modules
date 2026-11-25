# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from markupsafe import Markup

from odoo import _, models

INVITE_STATES = ('upcoming', 'active')


class BusinessCenterContract(models.Model):
    """Invites a contract's employees to the portal once it is confirmed."""

    _inherit = 'business.center.contract'

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    def write(self, vals):
        """Employees added to a confirmed contract are invited at once."""

        before = {c.id: c.contact_ids for c in self} if 'contact_ids' in vals else {}
        res = super().write(vals)
        for contract in self.filtered(lambda c: c.id in before and c.state in INVITE_STATES):
            contract._bc_invite_members(contract.contact_ids - before[contract.id])
        return res

    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_set_confirm(self):
        """Confirming the contract invites every employee named on it."""

        res = super().action_set_confirm()
        for contract in self:
            contract._bc_invite_members(contract.contact_ids)
        return res

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _bc_invite_members(self, partners):
        """Invite ``partners`` to the portal and note on the contract who was
        invited and who could not be. Never blocks the contract: a contact
        without an email, or one already in use, is only reported."""

        self.ensure_one()
        new = partners.filtered(lambda p: not p.user_ids)
        if not new:
            return
        skipped = new._bc_grant_portal_access()
        invited = new.filtered(lambda p: p not in skipped)
        lines = []
        if invited:
            lines.append(_("Portal invitation sent to %s.", ", ".join(invited.mapped('name'))))
        for partner, reason in skipped.items():
            lines.append(_("%(name)s was not invited to the portal: %(reason)s",
                           name=partner.name, reason=reason))
        self.message_post(body=Markup('<br/>').join(lines))