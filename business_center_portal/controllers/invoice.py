# -*- coding: utf-8 -*-
from odoo import http
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.account.controllers.portal import PortalAccount

TENANT_ADMIN_GROUP = 'business_center_portal.group_bc_tenant_admin'


class BusinessCenterInvoicePortal(PortalAccount):
    """Read-only invoice history for the Tenant Corporate Admin.

    Odoo's ``account`` module already ships the /my/invoices list page, the
    /my/invoices/<id> detail page and their templates.  We do not rebuild
    them.  What this controller adds is the business-center policy on top:

      * only a Tenant Corporate Admin may open those pages,
      * a tenant only ever sees customer invoices and credit notes,
      * the vendor-bill filters are taken out of the Filter By dropdown.

    Nothing here grants write access: the account.move record rule stays
    read-only, so the pages are view/download only.
    """

    # ------------------------------------------------------------------
    #   MARK: HELPERS
    # ------------------------------------------------------------------
    def _bc_is_tenant_admin(self):
        return request.env.user.has_group(TENANT_ADMIN_GROUP)

    def _bc_invoice_access_denied(self):
        """Send a portal user who is not a corporate admin back to /my.

        ``user.share`` is True for portal/public logins only, so an internal
        user browsing the portal is never blocked by this.
        """
        user = request.env.user
        if user.share and not self._bc_is_tenant_admin():
            return request.redirect('/my')
        return False

    # ------------------------------------------------------------------
    #   MARK: OVERRIDDEN PORTAL HOOKS
    # ------------------------------------------------------------------
    def _get_invoices_domain(self, m_type=None):
        """A tenant is a customer, so only customer invoices are relevant.

        This also feeds the ``invoice_count`` shown on the home tile, so the
        number and the list always agree.
        """
        domain = super()._get_invoices_domain(m_type)
        if request.env.user.share:
            domain &= Domain('move_type', 'in', ('out_invoice', 'out_refund'))
        return domain

    def _get_account_searchbar_filters(self):
        """Drop the vendor-bill filters; a tenant never receives bills here."""
        filters = super()._get_account_searchbar_filters()
        if request.env.user.share:
            filters.pop('bills', None)
            filters.pop('invoices', None)
        return filters

    # ------------------------------------------------------------------
    #   MARK: ROUTES
    # ------------------------------------------------------------------
    @http.route()
    def portal_my_invoices(self, page=1, date_begin=None, date_end=None,
                           sortby=None, filterby=None, **kw):
        """The invoice history list page (URL and auth inherited from account)."""
        denied = self._bc_invoice_access_denied()
        if denied:
            return denied
        # An old bookmark such as ?filterby=bills would raise a KeyError now
        # that the filter is gone, so fall back to 'all'.
        if filterby and filterby not in self._get_account_searchbar_filters():
            filterby = 'all'
        return super().portal_my_invoices(
            page=page, date_begin=date_begin, date_end=date_end,
            sortby=sortby, filterby=filterby, **kw)

    @http.route()
    def portal_my_invoice_detail(self, invoice_id, access_token=None,
                                 report_type=None, download=False, **kw):
        """One invoice: rendered report, download, communication history.

        A shared link carrying an access_token keeps working as usual; the
        group check only applies to a logged-in portal user browsing /my.
        """
        if not access_token:
            denied = self._bc_invoice_access_denied()
            if denied:
                return denied
        return super().portal_my_invoice_detail(
            invoice_id, access_token=access_token,
            report_type=report_type, download=download, **kw)