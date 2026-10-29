# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models, Command
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
from odoo.tools import format_date


import logging

_logger = logging.getLogger(__name__)

class BusinessCenterContract(models.Model):
    """Stores master records for business center contracts"""
    
    _name = 'business.center.contract'
    _description = 'A central registry of business center contracts'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'
    
    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    name = fields.Char(string='Contract', required=True, copy=False, readonly=False, 
                       index='trigram', default=lambda self: _('New'))
    date_start = fields.Date(string='Start date', required=True, tracking=True)
    date_end = fields.Date(string='End date', required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('upcoming', 'Upcoming'),
        ('active', 'Running'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled')
    ], default='draft', tracking=True)
    note = fields.Html(string='Terms & Conditions')
    invoice_count = fields.Integer(string='Invoice Count',
                                   compute='_compute_invoice_count')
    auto_renew = fields.Boolean(string='Auto Renew', default=False)
    renewal_increase_pct = fields.Float(
        string='Renewal Rent Increase (%)', tracking=True, default=0.0,
        help="Applied to every leased asset's rent when this contract renews. "
             "New contracts start from the company setting; use 0 to renew at "
             "the same rent.")
    send_expiry_reminder = fields.Boolean(
        string='Send Expiry Reminder', default=True, tracking=True,
        help="Email the tenant before this contract ends, asking whether they "
             "want to renew.")
    expiry_reminder_days = fields.Integer(
        string='Reminder Lead Days',
        default=lambda self: self.env.company.bc_expiry_reminder_days,
        help="Days before the end date the reminder goes out. Defaults to the "
             "company setting; change it here for this tenant only.")
    expiry_reminder_date = fields.Date(
        string='Reminder Due', compute='_compute_expiry_reminder_date',
        store=True, help="Date the reminder is due, derived from the end date "
                         "and the lead days.")
    expiry_reminder_sent_date = fields.Date(
        string='Reminder Sent', readonly=True, copy=False,
        help="Set once the reminder has gone out, so a scheduler does not "
             "send it twice.")
    contract_sent_date = fields.Date(
        string='Agreement Sent', readonly=True, copy=False,
        help="Last date the lease agreement PDF was emailed to the tenant.")
    agreement_state = fields.Selection([
        ('not_sent', 'Not Sent'),
        ('sent', 'Awaiting Signature'),
        ('signed', 'Signed'),
        ('declined', 'Declined'),
    ], string='Agreement', default='not_sent', required=True, tracking=True, copy=False,
        help="Signing status of the lease agreement. Tracked on its own: billing "
             "and occupancy start from the contract start date even while the "
             "signature is pending.")
    signed_by = fields.Char(string='Signed By', tracking=True, copy=False)
    signed_on = fields.Date(string='Signed On', tracking=True, copy=False)
    signature = fields.Image(string='Signature', copy=False, attachment=True,
                             max_width=1024, max_height=1024,
                             help="Signature captured online, printed on the agreement.")
    next_invoice_date = fields.Date(string='Next Invoice Date', tracking=True, 
                                    help="Start of the next rent period to be billed")
    free_hours_monthly = fields.Float(string='Monthly Free Hours', default=0.0, 
                                      tracking=True, help="Meeting-room hours granted to this contract each month. One shared " 
                                      "allowance across every office on the contract, not per office.")
    wallet_balance = fields.Float(string='Wallet Balance', readonly=True, copy=False)
    last_wallet_reset_date = fields.Date(
        string="Last Wallet Reset", readonly=True, copy=False,
        help="Date the monthly allowance was last credited. Guards against "
             "double-crediting and decides whether a cancellation may refund.")
    wallet_seeded = fields.Boolean(
        string='Wallet Seeded', default=False, copy=False,
        help="True once the wallet has been filled for this contract, so "
             "confirming again does not refill it.")
    is_wallet_eligible = fields.Boolean(string='Wallet Eligible', compute='_compute_is_wallet_eligible', 
                                        store=True, help="Only contracts leasing at least one office space receive free " 
                                        "meeting-room hours. Desk-only contracts do not.")
    pending_charge_total = fields.Monetary(string='Pending Charges', currency_field='currency_id', 
                                           compute='_compute_pending_charge_total', store=True, 
                                           help="Meeting-room overage and manual charges accrued but not yet invoiced.")
    deposit_amount = fields.Monetary(string='Security Deposit', currency_field='currency_id', tracking=True,
        help="Refundable deposit agreed for the whole contract. Enter it while "
             "the contract is draft; it is invoiced on confirmation and locked "
             "afterwards.")
    
    signed_attachment_id = fields.Many2one('ir.attachment', string='Signed Copy',
                                           readonly=True, copy=False)
    expiry_reminder_template_id = fields.Many2one(
        'mail.template', string='Reminder Template',
        domain="[('model', '=', 'business.center.contract')]",
        default=lambda self: self.env.ref(
            'business_center.mail_template_contract_expiry_reminder',
            raise_if_not_found=False),
        help="Template used for the reminder. Swap it to change the wording "
             "for a particular tenant.")
    previous_contract_id = fields.Many2one(
        'business.center.contract', string='Renewed From', readonly=True, copy=False,
        help="The contract this one continues.")
    renewal_contract_id = fields.Many2one(
        'business.center.contract', string='Renewed As', readonly=True, copy=False,
        help="The contract that continues this one after its end date.")
    deposit_refund_id = fields.Many2one('account.move', string='Deposit Refund', readonly=True, copy=False,
        groups='business_center.group_bc_manager',
        help="Draft credit note prepared for the deposit when the contract "
             "ended, for staff to settle after deductions.")
    deposit_invoice_id = fields.Many2one('account.move', string='Deposit Invoice', readonly=True, copy=False,
        groups='business_center.group_bc_manager',
        help="Invoice raised for the deposit when the contract was confirmed.")
    charge_ids = fields.One2many('business.center.contract.charge', 'contract_id', string='Accrued Booking')
    booking_ids = fields.One2many('business.center.booking', 'contract_id',
                                  string='Bookings')
    invoice_ids = fields.One2many('account.move', 'bc_contract_id',groups='business_center.group_bc_manager',
                                  string='Invoices')
    partner_id = fields.Many2one('res.partner', required=True, tracking=True, 
                                 domain="[('is_company', '=', True)]")
    contact_ids = fields.Many2many('res.partner', string='Employees')
    currency_id = fields.Many2one('res.currency', string='Currency',
                                  related='company_id.currency_id', store=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)
    leased_asset_ids = fields.One2many('business.center.leased.asset', 'contract_id', string='Leased Assets')
    center_id = fields.Many2one('business.center', string='Business Center', compute='_compute_center_id',
                                store=True, help="Centre this contract's assets belong to. A contract cannot span "
                                "two centres, so the first leased line decides it.")
    
    _name_uniq = models.Constraint('UNIQUE(name)', 'name should be unique')
    _deposit_amount_positive = models.Constraint(
        'CHECK (deposit_amount >= 0)',
        'The security deposit cannot be negative!',
    )   
    
    _NON_DRAFT_EDITABLE_FIELDS = {
        'name', 'note', 'contact_ids', 'auto_renew',
        'send_expiry_reminder', 'expiry_reminder_days', 'expiry_reminder_date',
        'expiry_reminder_sent_date', 'expiry_reminder_template_id',
        'state', 'next_invoice_date', 'message_main_attachment_id',
        'wallet_balance', 'wallet_seeded', 'last_wallet_reset_date',
        'is_wallet_eligible',
        'pending_charge_total', 'center_id',
        'renewal_contract_id', 'renewal_increase_pct', 'deposit_invoice_id',
        'deposit_refund_id', 'contract_sent_date',
        'agreement_state', 'signed_by', 'signed_on', 'signature', 'signed_attachment_id',
    }
    
    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------ 
    @api.model
    def default_get(self, fields_list):
        """Start new contracts from the company's renewal increase.

        Set here rather than as a field default: Odoo also evaluates field
        defaults to fill existing rows during an upgrade, before the company
        column exists, and that query would fail.
        """

        res = super().default_get(fields_list)
        if 'renewal_increase_pct' in fields_list \
                and 'default_renewal_increase_pct' not in self.env.context:
            res['renewal_increase_pct'] = self.env.company.bc_renewal_increase_pct
        return res
      
    def write(self, vals):
        """Only allow status/occupancy updates once the contract has left draft"""

        locked_fields = set(vals) - self._NON_DRAFT_EDITABLE_FIELDS
        if locked_fields:
            non_draft = self.filtered(lambda s: s.state != 'draft')
            if non_draft:
                raise UserError(_(
                    "Contract %(contract)s can only be edited in Draft state. "
                    "Use 'Reset to Draft' first.",
                    contract=non_draft[0].name,
                ))
        return super().write(vals)    
         
    @api.model_create_multi
    def create(self, vals_list):
        """Assigns a unique sequence reference (e.g. CT/2006/00001) to new
        business center contracts at creation time, unless a name was explicitly provided."""
        
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft':
                raise UserError(_(
                    "A contract is created in Draft and confirmed through the "
                    "Confirm action, which seeds the free-hour wallet, sets the "
                    "first invoice date and claims occupancy on its assets."))
            if vals.get('name', _("New")) == _("New"):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'business.center.contract') or _("New")
                
        return super().create(vals_list)
    
    def unlink(self):
        """Release leased assets before deleting so no resource is left
        stuck in 'occupied' state."""
        
        self._sync_leased_occupancy(exclude=self)
        return super().unlink()
    
    def message_post(self, **kwargs):
        """Mark the agreement as sent when it goes out from the composer opened
        by Send Contract (mirrors sale's mark_so_as_sent)."""

        if self.env.context.get('mark_contract_as_sent'):
            self._mark_agreement_sent()
        return super().message_post(**kwargs)
    
    @api.depends('invoice_ids')
    def _compute_invoice_count(self):
        """Count the invoices linked to this contract.

        Counted with sudo: front-desk users have no accounting rights, and
        reading invoice_ids directly would stop them opening the contract.
        Only the number is exposed; the invoices themselves stay protected.
        """

        for rec in self:
            rec.invoice_count = len(rec.sudo().invoice_ids)
            
    @api.depends('date_start', 'date_end', 'expiry_reminder_days')
    def _compute_expiry_reminder_date(self):
        """Date the reminder is due: the end date minus the lead days, but
        never before the contract starts. A contract shorter than the lead
        time is reminded on its first day."""

        for rec in self:
            if rec.date_end and rec.expiry_reminder_days > 0:
                due = rec.date_end - relativedelta(days=rec.expiry_reminder_days)
                rec.expiry_reminder_date = max(due, rec.date_start) if rec.date_start else due
            else:
                rec.expiry_reminder_date = False

    @api.depends('leased_asset_ids.lease_asset_type')
    def _compute_is_wallet_eligible(self):
        """Free meeting-room hours ride on office space. A contract that leases
        only desks gets no wallet at all."""

        for rec in self:
            rec.is_wallet_eligible = any(
                asset.lease_asset_type == 'office'
                for asset in rec.leased_asset_ids
            )
            
    @api.depends('charge_ids.amount', 'charge_ids.state')
    def _compute_pending_charge_total(self):
        """Sum the still-pending charges on this contract. Charges follow the
        contract, not any one leased office — a booking is made against the
        contract as a whole."""

        for rec in self:
            rec.pending_charge_total = sum(
                rec.charge_ids.filtered(lambda c: c.state == 'pending')
                              .mapped('amount'))

    @api.depends('leased_asset_ids.space_id.center_id',
                 'leased_asset_ids.desk_id.space_id.center_id')
    def _compute_center_id(self):
        """Centre of this contract, taken from the first leased line that has a
        resource. _check_single_center guarantees they all agree."""

        for rec in self:
            center = self.env['business.center']
            for asset in rec.leased_asset_ids:
                if asset.space_id:
                    center = asset.space_id.center_id
                    break
                if asset.desk_id:
                    center = asset.desk_id.space_id.center_id
                    break
            rec.center_id = center
    
    @api.ondelete(at_uninstall=False)
    def _unlink_except_live_or_invoiced(self):
        """Only draft or cancelled contracts may be deleted.

        A confirmed contract has claimed occupancy and represents a commitment
        to the tenant, so it is cancelled rather than erased. An expired one is
        the record of a completed tenancy. And once rent has been invoiced the
        contract is referenced by an accounting document, which must keep its
        origin.
        """

        for contract in self:
            if contract.state not in ('draft', 'cancelled'):
                raise UserError(_(
                    "%(contract)s is %(state)s and cannot be deleted. "
                    "Cancel it first — cancelled contracts can be deleted",
                    contract=contract.name,
                    state=dict(self._fields['state'].selection)[contract.state],
                ))
            if contract.invoice_ids:
                raise UserError(_(
                    "%(contract)s has been invoiced (%(invoices)s) and cannot "
                    "be deleted. The invoice records it as their origin.",
                    contract=contract.name,
                    invoices=", ".join(contract.invoice_ids.mapped('name')),
                ))
        
    # ------------------------------------------------------------------------------
    #   MARK: CONSTRAINT/ONCHANGE METHODS
    # ------------------------------------------------------------------------------   
    @api.constrains('date_start', 'date_end', 'state')
    def _check_asset_locks_on_date_change(self):
        """Re-validate that each leased asset's lock period still fits the
        contract dates, and that no other live contract holds the same space
        or desk over the new dates."""

        for contract in self:
            if contract.state in ('expired', 'cancelled'):
                continue
            contract.leased_asset_ids._check_lock_period_fits_contract()
            contract.leased_asset_ids._check_no_overlapping_contract()
            
    @api.constrains('free_hours_monthly', 'leased_asset_ids')
    def _check_wallet_requires_office(self):
        """Block free hours on a contract that leases desks only.

        Skipped while the contract has no leased assets at all: an import or
        API create writes the contract before its lines, and the confirm-time
        _seed_wallet zeroes an ineligible contract anyway.
        """

        for contract in self:
            if not contract.leased_asset_ids:
                continue
            if contract.free_hours_monthly and not contract.is_wallet_eligible:
                raise ValidationError(_(
                    "%(contract)s leases desks only, so it cannot carry free "
                    "meeting-room hours. Add an office space, or set Monthly "
                    "Free Hours to 0.",
                    contract=contract.name,
                ))
                
    @api.onchange('leased_asset_ids')
    def _onchange_wallet_eligibility(self):
        """Clear the free-hour allowance the moment the last office leaves the
        contract, so a desk-only contract never carries a hidden entitlement."""

        for contract in self:
            if not contract.is_wallet_eligible and contract.free_hours_monthly:
                contract.free_hours_monthly = 0.0
            
    @api.onchange('date_start', 'date_end')
    def _onchange_contract_dates(self):
        """Shows an inline warning when dates are invalid,
        giving the user immediate feedback before saving."""
        
        if self.date_end and self.date_start and self.date_end < self.date_start:
            return {
                'warning': {
                    'title': 'Invalid End Date',
                    'message': 'Contract end date cannot be before the start date.'
                }
            }
            
    @api.constrains('date_start', 'date_end')
    def _check_date_order(self):
        """The onchange warns in the form, but imports, the API and the portal
        never see it, so the rule needs a server-side twin."""

        for contract in self:
            if contract.date_start and contract.date_end \
                    and contract.date_end < contract.date_start:
                raise ValidationError(_(
                    "%(contract)s ends before it starts.", contract=contract.name))
            
    @api.constrains('renewal_increase_pct')
    def _check_renewal_increase(self):
        """A renewal can raise or lower rent, but never to zero or below."""

        for contract in self:
            if contract.renewal_increase_pct <= -100:
                raise ValidationError(_(
                    "%(contract)s: the renewal rent change must be above -100%%.",
                    contract=contract.name))
                
    @api.onchange('date_start', 'date_end', 'expiry_reminder_days')
    def _onchange_fit_reminder_to_contract(self):
        """Keep the reminder lead time within the contract. A contract shorter
        than the lead days gets its lead days reduced to its own length, so the
        reminder falls on the start date and both fields agree."""

        if not (self.date_start and self.date_end
                and self.date_end >= self.date_start
                and self.send_expiry_reminder):
            return
        term_days = (self.date_end - self.date_start).days
        if self.expiry_reminder_days > term_days:
            self.expiry_reminder_days = term_days
                
    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _check_bc_manager(self):
        """Approvals and money-related actions are for managers only. Checked
        server-side because a hidden button can still be called over RPC."""

        if not self.env.user.has_group('business_center.group_bc_manager'):
            raise UserError(_("Only a Business Center Manager can do this."))
    
    def _sync_leased_occupancy(self, exclude=None):
        """Re-derive occupancy on this contract's spaces and desks from whichever
        ACTIVE contract covers today. Draft/future/expired contracts never win, so
        confirming a future contract won't steal 'current' from the live one, and
        resetting/cancelling one contract won't free a resource another active
        contract still occupies. `exclude` drops contracts being deleted."""
        
        today = fields.Date.today()
        exclude = exclude or self.env['business.center.contract']
        if not self.leased_asset_ids:
            _logger.info("Occupancy sync: contract %s has no leased assets to sync.",
                         self.name)
            return
        for resource in list(self.leased_asset_ids.mapped('space_id')) \
                + list(self.leased_asset_ids.mapped('desk_id')):
            current = resource.leased_asset_ids.mapped('contract_id').filtered(
                lambda c: c not in exclude and c.state == 'active'
                and c.date_start and c.date_end
                and c.date_start <= today <= c.date_end
            ).sorted('date_start')[:1]
            resource.write({
                'state': 'occupied' if current else 'available',
                'occupant_id': current.partner_id.id if current else False,
                'current_contract_id': current.id if current else False,
                'contract_start_date': current.date_start if current else False,
                'contract_end_date': current.date_end if current else False,
            })
            
    def _seed_wallet(self):
        """Fill the contract's shared free-hour wallet at confirmation.

        Desk-only contracts are stripped of any allowance that was typed in
        before the office line was removed. Otherwise the wallet is filled once
        and `wallet_seeded` stops a re-confirm from topping it back up.
        """

        self.ensure_one()
        if not self.is_wallet_eligible:
            self.write({
                'free_hours_monthly': 0.0,
                'wallet_balance': 0.0,
                'wallet_seeded': False,
                'last_wallet_reset_date': False,
            })
            return
        if self.wallet_seeded:
            return
        self.write({
            'wallet_balance': self.free_hours_monthly,
            'wallet_seeded': True,
            'last_wallet_reset_date': fields.Date.context_today(self),
        })
        
    def _get_billing_period(self):
        """Next calendar-month-aligned period to bill, as (start, end).

        The period never crosses a month boundary: it stops at the last day of
        its own month or at date_end, whichever is earlier. So a contract
        starting 10 Aug bills 10-31 Aug first, and every cycle after that opens
        on the 1st. Returns (False, False) once the contract is billed out.
        """

        self.ensure_one()
        period_start = self.next_invoice_date or self.date_start
        if not period_start or not self.date_end or period_start > self.date_end:
            return False, False
        month_end = period_start + relativedelta(day=31)
        return period_start, min(month_end, self.date_end)

    def _get_proration(self, period_start, period_end):
        """(billed_days, days_in_month, factor) for a period inside one month.

        Both ends are inclusive, so 10-31 Aug is 22 days. A period covering the
        whole month gives factor 1.0 and leaves the rent untouched.
        """

        days_in_month = (period_start + relativedelta(day=31)).day
        billed_days = (period_end - period_start).days + 1
        return billed_days, days_in_month, float(billed_days) / days_in_month
    
    def _get_term_display(self):
        """Contract length in words for the agreement PDF, end date inclusive,
        e.g. 1 Jan - 31 Dec reads '1 year'."""

        self.ensure_one()
        if not (self.date_start and self.date_end):
            return ''
        delta = relativedelta(self.date_end + relativedelta(days=1), self.date_start)
        parts = []
        for value, one, many in ((delta.years, _('year'), _('years')),
                                 (delta.months, _('month'), _('months')),
                                 (delta.days, _('day'), _('days'))):
            if value:
                parts.append('%s %s' % (value, one if value == 1 else many))
        return ', '.join(parts)

    def _get_meeting_room_rates(self):
        """Bookable meeting rooms at this contract's centre with their hourly
        rate and opening hours, for the agreement PDF. Draft rooms are not set
        up yet and withdrawn rooms cannot be booked, so both are left out.
        Sudo so the report renders for any user."""

        self.ensure_one()
        if not self.center_id:
            return []
        rooms = self.env['business.center.space'].sudo().search([
            ('center_id', '=', self.center_id.id),
            ('space_type', '=', 'meeting_room'),
            ('is_bookable', '=', True),
            ('state', '!=', 'draft'),
        ], order='name')
        return [{
            'name': room.display_name,
            'rate': room.hourly_rate,
            'hours': room.operating_hours_display or '',
        } for room in rooms]
        
    def _get_center_address(self):
        """One-line address of the leased premises for the agreement PDF."""

        self.ensure_one()
        center = self.center_id
        if not center:
            return ''
        city_line = ' '.join(p for p in (center.city, center.zip) if p)
        parts = (center.street, center.street2, city_line,
                 center.state_id.name, center.country_id.name)
        return ', '.join(p for p in parts if p)
    
    def _mark_agreement_sent(self):
        """Stamp the send date and, unless already signed, set the agreement to
        Awaiting Signature with one follow-up activity for the sender."""

        today = fields.Date.context_today(self)
        for contract in self:
            vals = {'contract_sent_date': today}
            if contract.agreement_state != 'signed':
                vals['agreement_state'] = 'sent'
            contract.with_context(tracking_disable=True).write(vals)
            if contract.agreement_state == 'sent':
                contract.activity_unlink(['business_center.mail_activity_type_contract_signature'])
                contract.activity_schedule(
                    'business_center.mail_activity_type_contract_signature',
                    user_id=self.env.user.id)

    def _mark_agreement_signed(self, signed_by, signed_on=None, attachment=None, signature=None):
        """Record the signature. Shared by the backend wizard (signed paper
        copy) and the portal Accept & Sign (drawn signature)."""

        self.ensure_one()
        signed_on = signed_on or fields.Date.context_today(self)
        vals = {
            'agreement_state': 'signed',
            'signed_by': signed_by,
            'signed_on': signed_on,
        }
        if attachment:
            vals['signed_attachment_id'] = attachment.id
        if signature:
            vals['signature'] = signature
        self.write(vals)
        self.activity_feedback(
            ['business_center.mail_activity_type_contract_signature'],
            feedback=_("Agreement signed by %s", signed_by))
        self.message_post(
            body=_("Agreement signed by %(name)s on %(date)s.",
                   name=signed_by, date=format_date(self.env, signed_on)),
            attachment_ids=attachment.ids if attachment else [])

    def _reset_agreement(self):
        """A contract sent back to draft will change, so any signature no
        longer matches it. The signed copy stays in the chatter as history."""

        self.ensure_one()
        if self.agreement_state == 'signed':
            self.message_post(body=_(
                "Agreement signed by %s is void after reset to draft; it must be "
                "signed again.", self.signed_by))
        self.activity_unlink(['business_center.mail_activity_type_contract_signature'])
        self.write({
            'agreement_state': 'not_sent',
            'signed_by': False,
            'signed_on': False,
            'signature': False,
            'signed_attachment_id': False,
        })
    
    def _create_deposit_invoice(self):
        """Raise a draft invoice for the security deposit, separate from rent.

        A deposit is held for the tenant and refunded later, not earned, so it
        is billed on its own tax-free line. A renewal keeps the deposit already
        held and only invoices the increase, if there is one.
        """

        self.ensure_one()
        held = self.previous_contract_id.deposit_amount if self.previous_contract_id else 0.0
        due = self.currency_id.round(self.deposit_amount - held)
        if due <= 0 or self.deposit_invoice_id:
            return False
        product = self.env.ref('business_center.product_security_deposit',
                               raise_if_not_found=False)
        if not product:
            raise UserError(_("The Security Deposit product is missing, so the "
                              "deposit for %s could not be invoiced.", self.name))
        label = (_("Security Deposit top-up - %s", self.name) if held
                 else _("Security Deposit - %s", self.name))
        move = self.env['account.move'].with_company(self.company_id).with_context(
            default_move_type='out_invoice'
        ).create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'currency_id': self.currency_id.id,
            'invoice_date': fields.Date.context_today(self),
            'invoice_origin': self.name,
            'bc_contract_id': self.id,
            'invoice_line_ids': [Command.create({
                'product_id': product.id,
                'name': label,
                'quantity': 1.0,
                'price_unit': due,
                'tax_ids': [Command.clear()],
            })],
        })
        self.deposit_invoice_id = move
        return move
    
    def _deposit_received(self):
        """Deposit the tenant has actually paid, across this contract and the
        contracts it renews: only paid deposit invoices count."""

        self.ensure_one()
        total, contract = 0.0, self
        while contract:
            invoice = contract.sudo().deposit_invoice_id
            if invoice.state == 'posted' and invoice.payment_state in ('paid', 'in_payment'):
                total += invoice.amount_total
            contract = contract.previous_contract_id
        return total

    def _create_deposit_refund(self):
        """Prepare the deposit refund when the contract ends.

        A renewed contract keeps its deposit for the successor. An unpaid
        draft deposit invoice is simply cancelled. Otherwise a draft credit
        note for the deposit received is created and a manager is asked to
        settle it, since damages and unpaid dues must be deducted first.
        """

        self.ensure_one()
        if self.deposit_refund_id:
            return False
        if self.renewal_contract_id and self.renewal_contract_id.state != 'cancelled':
            return False
        deposit_invoice = self.sudo().deposit_invoice_id
        if deposit_invoice.state == 'draft':
            deposit_invoice.button_cancel()
        amount = self.currency_id.round(self._deposit_received())
        if amount <= 0:
            return False
        product = self.env.ref('business_center.product_security_deposit',
                               raise_if_not_found=False)
        if not product:
            raise UserError(_("The Security Deposit product is missing, so the "
                              "deposit refund for %s could not be prepared.", self.name))
        refund = self.env['account.move'].sudo().with_company(self.company_id).with_context(
            default_move_type='out_refund'
        ).create({
            'move_type': 'out_refund',
            'partner_id': self.partner_id.id,
            'currency_id': self.currency_id.id,
            'invoice_date': fields.Date.context_today(self),
            'invoice_origin': self.name,
            'bc_contract_id': self.id,
            'invoice_line_ids': [Command.create({
                'product_id': product.id,
                'name': _("Security Deposit refund - %s", self.name),
                'quantity': 1.0,
                'price_unit': amount,
                'tax_ids': [Command.clear()],
            })],
        })
        self.deposit_refund_id = refund
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            summary=_("Settle security deposit"),
            note=_("Inspect the space and check unpaid dues, adjust the draft "
                   "refund %(refund)s if needed, then post it and pay out or "
                   "offset the balance.", refund=refund.display_name),
            user_id=self.create_uid.id,
        )
        return refund
    
    def _create_renewal(self):
        """Create the draft successor of this contract: same term length,
        same assets, employees and free hours, starting the day after this one
        ends, with each asset's rent raised by renewal_increase_pct. Returns
        the existing successor if there already is one."""

        self.ensure_one()
        if self.renewal_contract_id:
            return self.renewal_contract_id
        new_start = self.date_end + relativedelta(days=1)
        term = relativedelta(new_start, self.date_start)
        factor = 1 + self.renewal_increase_pct / 100.0
        renewal = self.with_context(bc_renewal_create=True).copy({
            'state': 'draft',
            'date_start': new_start,
            'date_end': new_start + term - relativedelta(days=1),
            'next_invoice_date': new_start,
            'previous_contract_id': self.id,
            'leased_asset_ids': [(0, 0, {
                'lease_asset_type': asset.lease_asset_type,
                'space_id': asset.space_id.id,
                'desk_id': asset.desk_id.id,
                'monthly_rent_total': self.currency_id.round(
                    asset.monthly_rent_total * factor),
            }) for asset in self.leased_asset_ids],
        })
        self.renewal_contract_id = renewal
        return renewal
    
    def _send_expiry_reminder(self):
        """Post the renewal reminder on this contract's chatter and email it.

        Going through message_post rather than mail.template.send_mail means the
        message is logged against the record and the tenant's reply threads back
        into this contract's chatter instead of landing in someone's personal
        inbox. The tenant is subscribed first so the reply is routed here.
        """

        self.ensure_one()
        template = self.expiry_reminder_template_id
        if not template:
            raise UserError(_(
                "No reminder template is set on %(contract)s, so nothing was "
                "sent. Pick one on the contract.", contract=self.name))
        if not self.partner_id.email:
            raise UserError(_(
                "%(partner)s has no email address, so the reminder could not "
                "be sent.", partner=self.partner_id.display_name))

        recipients = self.partner_id | self.contact_ids.filtered('email')
        self.message_subscribe(partner_ids=self.partner_id.ids)

        body = template._render_field('body_html', self.ids,
                                      compute_lang=True)[self.id]
        subject = template._render_field('subject', self.ids,
                                         compute_lang=True)[self.id]

        self.message_post(
            body=body,
            subject=subject,
            partner_ids=recipients.ids,
            author_id=self.company_id.partner_id.id,
            email_from=self.company_id.email_formatted,
            subtype_xmlid='mail.mt_comment',
            email_layout_xmlid='mail.mail_notification_layout',
        )
        self.expiry_reminder_sent_date = fields.Date.context_today(self)
        
    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_set_confirm(self):
        """Confirm the contract. A contract whose start date has arrived becomes
        Running; one starting later sits in Upcoming until the cron promotes it.
        Confirming requires an allocated space or desk — unfulfilled demand belongs
        in a CRM lead, not an assetless contract."""

        self.ensure_one()
        self._check_bc_manager()
        if not self.leased_asset_ids:
            raise UserError(_(
                "Add at least one leased asset before confirming. If the customer "
                "is waiting for space to free up, track that as a CRM lead instead."))
        if self.is_wallet_eligible and not self.free_hours_monthly:
            raise UserError(_(
                "%(contract)s leases office space, so it needs a monthly "
                "free-hour allowance. Set Monthly Free Hours before confirming.",
                contract=self.name))
        today = fields.Date.today()
        # A migrated contract that started before this month would otherwise be
        # re-invoiced for every past month by the billing cron.
        if not self.next_invoice_date and self.date_start < today.replace(day=1):
            raise UserError(_(
                "%(contract)s started on %(start)s, before this month. Set Next "
                "Invoice Date to the first period not yet billed, otherwise every "
                "month since the start date would be invoiced again.",
                contract=self.name, start=format_date(self.env, self.date_start)))
        # Seed while still in draft — free_hours_monthly is locked afterwards.
        self._seed_wallet()
        vals = {'state': 'active' if self.date_start <= today else 'upcoming'}
        if not self.next_invoice_date:
            vals['next_invoice_date'] = self.date_start
        self.write(vals)
        self._sync_leased_occupancy()
        self._create_deposit_invoice()
        return self.action_send_contract()

    def action_set_cancel(self):
        """Cancel the contract and mark its leased assets as available"""

        self.ensure_one()
        self._check_bc_manager()
        self.state = 'cancelled'
        self._sync_leased_occupancy()
        self._create_deposit_refund()
        self.activity_unlink(['business_center.mail_activity_type_contract_signature'])

    def action_set_draft(self):
        """Reset the contract back to draft """

        self.ensure_one()
        self._check_bc_manager()
        posted = self.invoice_ids.filtered(lambda m: m.state == 'posted')
        if posted:
            raise UserError(_(
                "%(contract)s has already been invoiced (%(invoices)s) and "
                "cannot be reset to draft. Cancel it and create a new contract "
                "instead, issuing a credit note if the invoice was wrong.",
                contract=self.name,
                invoices=", ".join(posted.mapped('name')),
            ))
        live_bookings = self.booking_ids.filtered(lambda b: b.state == 'confirmed')
        if live_bookings:
            raise UserError(_(
                "%(contract)s has confirmed bookings (%(bookings)s) that drew "
                "free hours. Cancel them before resetting, or the wallet would "
                "be refilled while the rooms stay booked.",
                contract=self.name,
                bookings=", ".join(live_bookings.mapped('name')),
            ))
        self.state = 'draft'
        self.wallet_seeded = False
        self._sync_leased_occupancy()
        self._reset_agreement()
        
    def action_send_contract(self):
        """Open the email composer with the lease agreement PDF attached, the
        way a quotation is sent. The template carries the report, so the
        composer renders and attaches the PDF itself."""

        self.ensure_one()
        if self.state not in ('upcoming', 'active'):
            raise UserError(_("Only a confirmed contract can be sent to the tenant."))
        template = self.env.ref(
            'business_center.mail_template_contract_confirmation',
            raise_if_not_found=False)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Lease Agreement'),
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_model': self._name,
                'default_res_ids': self.ids,
                'default_template_id': template.id if template else False,
                'default_composition_mode': 'comment',
                'default_email_layout_xmlid': 'mail.mail_notification_layout',
                'force_email': True,
                'mark_contract_as_sent': True,
            },
        } 
        
    def action_mark_agreement_signed(self):
        """Record a signed paper copy returned by the tenant."""

        self.ensure_one()
        self._check_bc_manager()
        if self.state not in ('upcoming', 'active'):
            raise UserError(_("Only a confirmed contract can be marked as signed."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Record Signed Agreement'),
            'res_model': 'business.center.contract.sign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_contract_id': self.id,
                'default_signed_by': self.partner_id.name,
            },
        }

    def action_mark_agreement_declined(self):
        """The tenant refused the agreement. Staff then reset to draft and
        resend a revised one, or cancel the contract."""

        self.ensure_one()
        self._check_bc_manager()
        if self.agreement_state != 'sent':
            raise UserError(_("Only an agreement awaiting signature can be declined."))
        self.agreement_state = 'declined'
        self.activity_feedback(
            ['business_center.mail_activity_type_contract_signature'],
            feedback=_("Tenant declined the agreement."))       
                
    def _create_rent_invoice(self):
        """Build one draft customer invoice for the next billing period plus any
        pending meeting-room charges, and return the account.move.

        Rent for a partial first or last month is charged pro rata on days. Only
        raises when there is genuinely nothing to bill, so the caller - button or
        cron - decides how that gets reported.
        """

        self.ensure_one()

        period_start, period_end = self._get_billing_period()
        pending = self.charge_ids.filtered(
            lambda c: c.state == 'pending' and c.booking_id.meeting_room_id)
        if not period_start and not pending:
            raise UserError(_("Nothing to invoice: this contract is billed up to "
                              "its end date and has no pending charges."))

        line_specs = []

        if period_start:
            billed_days, days_in_month, factor = self._get_proration(
                period_start, period_end)
            is_partial = billed_days < days_in_month
            for asset in self.leased_asset_ids.filtered(lambda a: a.monthly_rent_total):
                resource = asset.space_id or asset.desk_id
                res_name = resource.display_name or asset.lease_asset_type
                if is_partial:
                    label = _("Rent - %(res)s (%(start)s to %(end)s, %(days)s of "
                              "%(total)s days)") % {
                        'res': res_name,
                        'start': format_date(self.env, period_start),
                        'end': format_date(self.env, period_end),
                        'days': billed_days,
                        'total': days_in_month,
                    }
                    price_unit = self.currency_id.round(
                        asset.monthly_rent_total * factor)
                else:
                    label = _("Monthly Rent - %(res)s (%(start)s to %(end)s)") % {
                        'res': res_name,
                        'start': format_date(self.env, period_start),
                        'end': format_date(self.env, period_end),
                    }
                    price_unit = asset.monthly_rent_total
                line_specs.append(({
                    'product_id': asset.product_id.id,
                    'name': label,
                    'quantity': 1.0,
                    'price_unit': price_unit,
                }, False))

        by_room = {}
        for charge in pending:
            room = charge.booking_id.meeting_room_id
            by_room.setdefault(room.id, self.env['business.center.contract.charge'])
            by_room[room.id] |= charge

        for room_charges in by_room.values():
            room = room_charges[0].booking_id.meeting_room_id
            # One line per room for the exact amount. Billing the hours as the
            # quantity would round them to the unit precision (50 min = 0.83 h)
            # and under-charge against what the booking showed.
            duration = room_charges[0].booking_id._float_to_duration(
                sum(room_charges.mapped('quantity')))
            label = _("Meeting Room - %(room)s (%(duration)s)",
                      room=room.name or _("Charge"), duration=duration)
            vals = {
                'product_id': room.product_id.id,
                'name': label,
                'quantity': 1.0,
                'price_unit': self.currency_id.round(sum(room_charges.mapped('amount'))),
            }
            line_specs.append((vals, room_charges))

        if not line_specs:
            raise UserError(_("Nothing to invoice: no rent or pending charges found."))

        missing = [v['name'] for v, _c in line_specs if not v.get('product_id')]
        if missing:
            raise UserError(_(
                "These lines have no billing product set, so no tax could be "
                "applied:\n- %s\n\nSet the product on the leased asset or the "
                "meeting room before invoicing."
            ) % "\n- ".join(missing))

        fpos = self.env['account.fiscal.position'].with_company(
            self.company_id)._get_fiscal_position(self.partner_id)

        move = self.env['account.move'].with_company(self.company_id).with_context(
            default_move_type='out_invoice'
        ).create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'currency_id': self.currency_id.id,
            'invoice_date': fields.Date.context_today(self),
            'fiscal_position_id': fpos.id,
            'invoice_origin': self.name,
            'bc_contract_id': self.id,
            'invoice_line_ids': [(0, 0, v) for v, _c in line_specs],
        })

        if period_start:
            self.next_invoice_date = period_end + relativedelta(days=1)

        lines_by_name = {}
        for line in move.invoice_line_ids.filtered(
                lambda l: l.display_type == 'product').sorted('id'):
            lines_by_name.setdefault(line.name, []).append(line)

        for vals, charges in line_specs:
            if not charges:
                continue
            candidates = lines_by_name.get(vals['name']) or []
            if not candidates:
                raise UserError(_(
                    "Could not match the invoice line for %(label)s, so its "
                    "charges were not marked as invoiced. Please check the "
                    "invoice before posting.",
                    label=vals['name'],
                ))
            line = candidates.pop(0)
            charges.write({'state': 'invoiced', 'invoice_line_id': line.id})

        return move

    def action_create_invoice(self):
        """Invoice this contract's next period manually and open the result.
        The scheduler does the same thing nightly; this button is for catching up
        or for sweeping the last charges off a finished contract."""

        self.ensure_one()
        self._check_bc_manager()

        if self.state == 'upcoming':
            raise UserError(_(
                "This contract starts on %s and cannot be invoiced yet."
            ) % format_date(self.env, self.date_start))
        if self.state not in ('active', 'expired'):
            raise UserError(_("You can only invoice a running or expired contract."))
        if not self.leased_asset_ids:
            raise UserError(_("This contract has no leased assets to invoice."))
        zero_rent = self.leased_asset_ids.filtered(lambda a: not a.monthly_rent_total)
        if zero_rent:
            raise UserError(_(
                "These leased assets have no monthly rent set and cannot be "
                "invoiced:\n- %s\n\nSet the rent on the contract before invoicing."
            ) % "\n- ".join(
                (a.space_id or a.desk_id).display_name for a in zero_rent))

        move = self._create_rent_invoice()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoice'),
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
    def action_view_invoices(self):
        """Open the invoices raised against this contract"""
        
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoices'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('bc_contract_id', '=', self.id)],
            'context': {'default_move_type': 'out_invoice',
                        'default_bc_contract_id': self.id},
        }
        
    def action_send_expiry_reminder(self):
        """Send the renewal reminder now. Ignores expiry_reminder_sent_date on
        purpose, so staff can resend after a bounce or a wording change."""

        self.ensure_one()
        if self.state != 'active':
            raise UserError(_(
                "Only a running contract can be sent an expiry reminder."))
        self._send_expiry_reminder()
        
    def action_renew(self):
        """Create a draft renewal for staff to review and confirm."""

        self.ensure_one()
        self._check_bc_manager()
        if self.state not in ('active', 'expired'):
            raise UserError(_("Only a running or expired contract can be renewed."))
        renewal = self._create_renewal()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Renewal'),
            'res_model': 'business.center.contract',
            'res_id': renewal.id,
            'view_mode': 'form',
            'target': 'current',
        }
            
    # ------------------------------------------------------------------------------
    #   MARK: SCHEDULER METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _cron_expire_contracts(self):
        """Expire every contract whose end date has passed and release its assets.

        Both active and upcoming contracts are swept. An upcoming contract whose
        end date has gone by is over whether or not the activation cron ever
        promoted it, and leaving it stranded in upcoming keeps its leased assets
        tied up in _check_no_overlapping_contract, so the space cannot be re-let.

        Draft contracts are deliberately left alone: they never called
        _sync_leased_occupancy, so they hold no resource.
        """

        today = fields.Date.today()
        expired_contracts = self.search([
            ('state', 'in', ('active', 'upcoming')),
            ('date_end', '<', today),
        ])
        if not expired_contracts:
            _logger.info("Contract expiry cron: no contracts to expire.")
            return

        stranded = expired_contracts.filtered(lambda c: c.state == 'upcoming')
        if stranded:
            _logger.warning(
                "Contract expiry cron: %s contract(s) ended while still Upcoming "
                "and were never activated: %s",
                len(stranded), ", ".join(stranded.mapped('name')))

        done = self.browse()
        for contract in expired_contracts:
            try:
                with self.env.cr.savepoint():
                    contract.write({'state': 'expired'})
                    contract._sync_leased_occupancy()
                    contract._create_deposit_refund()
                done |= contract
            except Exception:
                _logger.exception(
                    "Contract expiry cron: could not expire %s; its assets may "
                    "still be marked occupied.", contract.name)

        _logger.info(
            "Contract expiry cron: expired %s of %s contract(s): %s",
            len(done), len(expired_contracts), ", ".join(done.mapped('name')))
                
    @api.model
    def _cron_reset_wallets(self):
        """Credit the monthly free-hour allowance on the 1st of every month.

        The wallet period is the calendar month, matching the billing cycle, so
        a contract that started mid-month has no private reset day of its own.
        Runs daily but returns immediately on any other date.
        last_wallet_reset_date blocks a second credit inside the same month if
        the cron is re-run.
        """

        today = fields.Date.today()
        if today.day != 1:
            return

        contracts = self.search([
            ('state', '=', 'active'),
            ('is_wallet_eligible', '=', True),
            ('free_hours_monthly', '>', 0),
            '|', ('last_wallet_reset_date', '=', False),
                 ('last_wallet_reset_date', '<', today),
        ])
        if not contracts:
            _logger.info("Wallet reset cron: no wallets to reset today.")
            return

        for contract in contracts:
            contract.write({
                'wallet_balance': contract.free_hours_monthly,
                'wallet_seeded': True,
                'last_wallet_reset_date': today,
            })

        _logger.info("Wallet reset cron: reset %s wallet(s): %s",
                     len(contracts), ", ".join(contracts.mapped('name')))
        
    @api.model
    def _cron_renew_contracts(self):
        """Renew every running auto-renew contract that ended yesterday.

        Runs just before the expiry cron, so the successor is already running
        when the old contract is expired and its spaces never become available.
        A renewal that cannot be confirmed (for example the space was let to
        someone else) is noted on the contract, which then expires normally.
        """

        today = fields.Date.today()
        due = self.search([
            ('state', '=', 'active'),
            ('auto_renew', '=', True),
            ('renewal_contract_id', '=', False),
            ('date_end', '<', today),
        ])
        if not due:
            _logger.info("Contract renewal cron: nothing to renew today.")
            return

        renewed, failed = self.browse(), []
        for contract in due:
            try:
                with self.env.cr.savepoint():
                    contract._create_renewal().action_set_confirm()
                renewed |= contract
            except Exception as exc:
                failed.append(contract.name)
                _logger.exception("Contract renewal cron: could not renew %s.", contract.name)
                contract.message_post(body=_(
                    "Automatic renewal failed: %s. The contract will expire; "
                    "renew it manually if the tenant is staying.", exc))

        _logger.info("Contract renewal cron: renewed %s of %s contract(s): %s",
                     len(renewed), len(due), ", ".join(renewed.mapped('name')) or "-")
        
    @api.model
    def _cron_activate_upcoming_contracts(self):
        """Promote upcoming contracts whose start date has arrived, and claim
        occupancy on their spaces and desks."""

        today = fields.Date.today()
        due = self.search([('state', '=', 'upcoming'), ('date_start', '<=', today), ('date_end', '>=', today)])
        if not due:
            _logger.info("Contract activation cron: no contracts to activate.")
            return

        due.write({'state': 'active'})
        for contract in due:
            contract._sync_leased_occupancy()

        _logger.info("Contract activation cron: activated %s contract(s): %s",
                     len(due), ", ".join(due.mapped('name')))
        
    @api.model
    def _cron_generate_invoices(self):
        """Raise one draft invoice per contract whose next billing period has opened.

        Runs daily rather than monthly on purpose. A contract that goes live on
        10 Aug is billed that same night for 10-31 Aug only, which puts its
        next_invoice_date on 1 Sep; from then on it is picked up on the 1st along
        with everything else. Expired contracts are swept too, so meeting-room
        overage accrued in a final month still reaches an invoice.

        Each contract bills inside its own savepoint: one missing a product or a
        rent amount fails alone and the rest still go out.
        """

        today = fields.Date.today()
        due = self.search([
            ('state', 'in', ('active', 'expired')),
            '|', ('next_invoice_date', '<=', today),
                 ('pending_charge_total', '>', 0),
        ])
        if not due:
            _logger.info("Billing cron: nothing due today.")
            return

        billed = self.browse()
        failed = []
        for contract in due:
            try:
                with self.env.cr.savepoint():
                    # Bill every period that has already opened, not just the
                    # first. A contract entered late, or one that sat through a
                    # server outage, catches up in a single run.
                    for _attempt in range(24):
                        period_start, period_end = contract._get_billing_period()
                        if not period_start or period_start > today:
                            break
                        has_rent = contract.leased_asset_ids.filtered(
                            lambda a: a.monthly_rent_total)
                        has_charges = contract.charge_ids.filtered(
                            lambda c: c.state == 'pending' and c.booking_id.meeting_room_id)
                        if not has_rent and not has_charges:
                            contract.next_invoice_date = period_end + relativedelta(days=1)
                            continue
                        contract._create_rent_invoice()
                    else:
                        _logger.warning(
                            "Billing cron: %s hit the 24-period catch-up limit; "
                            "it may still owe invoices.", contract.name)
                billed |= contract
            except Exception:
                failed.append(contract.name)
                _logger.exception("Billing cron: could not invoice %s.", contract.name)

        _logger.info("Billing cron: invoiced %s of %s contract(s): %s",
                     len(billed), len(due), ", ".join(billed.mapped('name')) or "-")
        if failed:
            _logger.warning("Billing cron: %s contract(s) failed: %s",
                            len(failed), ", ".join(failed))
            
    @api.model
    def _cron_send_expiry_reminders(self):
        """Email the renewal reminder for every running contract that has reached
        its reminder date.

        expiry_reminder_sent_date is the guard: once set, the contract is out of
        the domain permanently, so a reminder is never sent twice even if the
        cron runs repeatedly or a contract's dates are edited afterwards.

        Each send is wrapped in its own savepoint. A tenant with no email
        address raises, and that must not stop the rest of the batch.
        """

        today = fields.Date.today()
        due = self.search([
            ('state', '=', 'active'),
            ('send_expiry_reminder', '=', True),
            ('expiry_reminder_sent_date', '=', False),
            ('expiry_reminder_date', '!=', False),
            ('expiry_reminder_date', '<=', today),
            ('date_end', '>=', today),
        ])
        if not due:
            _logger.info("Expiry reminder cron: nothing due today.")
            return

        sent = self.browse()
        failed = []
        for contract in due:
            try:
                with self.env.cr.savepoint():
                    contract._send_expiry_reminder()
                sent |= contract
            except Exception:
                failed.append(contract.name)
                _logger.exception(
                    "Expiry reminder cron: could not send for %s.", contract.name)

        _logger.info("Expiry reminder cron: sent %s of %s reminder(s): %s",
                     len(sent), len(due), ", ".join(sent.mapped('name')) or "-")
        if failed:
            _logger.warning("Expiry reminder cron: %s failed: %s",
                            len(failed), ", ".join(failed))