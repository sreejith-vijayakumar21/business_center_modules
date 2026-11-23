# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from urllib.parse import quote

from odoo import _, http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager


LEASE_AGREEMENT_REPORT = 'business_center.report_bc_contract'
CONFIRMED_STATES = ('upcoming', 'active', 'expired')


class BusinessCenterContractPortal(CustomerPortal):
    """Everything the portal needs for showing contracts to a member."""

    def _prepare_home_portal_values(self, counters):
        """Add the number shown on the Contracts tile of the /my page."""
        values = super()._prepare_home_portal_values(counters)
        if 'contract_count' in counters:
            Contract = request.env['business.center.contract']
            values['contract_count'] = (
                Contract.search_count(self._get_contracts_domain())
                if Contract.has_access('read') else 0
            )
        return values

    def _get_contracts_domain(self):
        """Only contracts belonging to this member's company."""
        partner = request.env.user.partner_id.commercial_partner_id
        return [('partner_id', 'child_of', partner.id)]
    
    def _bc_contract_access_denied(self):
        """Contract configuration is Tenant Corporate Admin only (FRD §3).

        ``user.share`` is True for portal logins only, so an internal user
        browsing the portal is never blocked by this.
        """
        user = request.env.user
        if user.share and not user.has_group(
                'business_center_portal.group_bc_tenant_admin'):
            return request.redirect('/my')
        return False
    
    def _bc_get_contract_sudo(self, contract_id):
        """Return (contract_sudo, None) when the visitor may see the contract,
        else (None, redirect response): a tenant admin (or internal user)
        whose record rules give read access."""

        denied = self._bc_contract_access_denied()
        if denied:
            return None, denied
        try:
            return self._document_check_access('business.center.contract', contract_id), None
        except (AccessError, MissingError):
            return None, request.redirect('/my')

    def _contract_searchbar_sortings(self):
        """The choices in the 'Sort By' dropdown on the contract list."""
        return {
            'date': {'label': _('Start Date'), 'order': 'date_start desc'},
            'end': {'label': _('End Date'), 'order': 'date_end asc'},
            'name': {'label': _('Reference'), 'order': 'name desc'},
            'state': {'label': _('Status'), 'order': 'state'},
        }

    def _contract_searchbar_filters(self):
        """The choices in the 'Filter By' dropdown on the contract list.
        Running comes first and is the default: it is what a tenant admin
        acts on."""
        return {
            'active': {'label': _('Running'), 'domain': [('state', '=', 'active')]},
            'upcoming': {'label': _('Upcoming'), 'domain': [('state', '=', 'upcoming')]},
            'draft': {'label': _('Draft'), 'domain': [('state', '=', 'draft')]},
            'expired': {'label': _('Expired'), 'domain': [('state', '=', 'expired')]},
            'all': {'label': _('All'), 'domain': []},
        }

    def _contract_searchbar_inputs(self):
        """The choices in the search box dropdown ('Search in ...')."""
        return {
            'name':    {'input': 'name',    'label': _('Search in Reference')},
            'partner': {'input': 'partner', 'label': _('Search in Tenant')},
            'leased':  {'input': 'leased',  'label': _('Search in Leased Assets')},
            'all':     {'input': 'all',     'label': _('Search in All')},
        }

    def _get_contract_search_domain(self, search_in, search):
        """Turn what the member typed into a filter, based on the field
        they chose to search in."""
        leased_domain = [
            '|',
            ('leased_asset_ids.space_id.name', 'ilike', search),
            ('leased_asset_ids.desk_id.name', 'ilike', search),
        ]
        if search_in == 'name':
            return [('name', 'ilike', search)]
        if search_in == 'partner':
            return [('partner_id.name', 'ilike', search)]
        if search_in == 'leased':
            return leased_domain
        return ['|', '|',
                ('name', 'ilike', search),
                ('partner_id.name', 'ilike', search)] + leased_domain

    @http.route(['/my/contracts', '/my/contracts/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_contracts(self, page=1, sortby=None, filterby=None,
                            search=None, search_in='all', **kw):
        """The list page showing all contracts of the logged-in member."""
        
        denied = self._bc_contract_access_denied()
        if denied:
            return denied
        Contract = request.env['business.center.contract']
        domain = self._get_contracts_domain()

        searchbar_sortings = self._contract_searchbar_sortings()
        if not sortby:
            sortby = 'date'
        order = searchbar_sortings[sortby]['order']

        searchbar_filters = self._contract_searchbar_filters()
        if not filterby:
            filterby = 'active'
        domain += searchbar_filters[filterby]['domain']

        searchbar_inputs = self._contract_searchbar_inputs()
        if search and search_in:
            domain += self._get_contract_search_domain(search_in, search)

        contract_count = Contract.search_count(domain)
        pager = portal_pager(
            url='/my/contracts',
            url_args={'sortby': sortby, 'filterby': filterby,
                      'search': search, 'search_in': search_in},
            total=contract_count,
            page=page,
            step=self._items_per_page,
        )
        contracts = Contract.search(
            domain, order=order, limit=self._items_per_page, offset=pager['offset'])
        request.session['my_contracts_history'] = contracts.ids[:100]

        values = self._prepare_portal_layout_values()
        values.update({
            'contracts': contracts,
            'cards': {contract.id: self._bc_contract_card(contract) for contract in contracts},
            'page_name': 'contract',
            'pager': pager,
            'default_url': '/my/contracts',
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby,
            'searchbar_filters': searchbar_filters,
            'filterby': filterby,
            'searchbar_inputs': searchbar_inputs,
            'search_in': search_in,
            'search': search,
        })
        return request.render('business_center_portal.portal_my_contracts', values)

    @http.route(['/my/contracts/<int:contract_id>'],
                type='http', auth='user', website=True)
    def portal_my_contract_detail(self, contract_id, report_type=None, download=False, **kw):
        """The detail page for one contract, or its lease agreement as a PDF
        (``report_type=pdf``, add ``download=true`` to save it), the same
        way an invoice page serves its report."""

        contract_sudo, redirect = self._bc_get_contract_sudo(contract_id)
        if redirect:
            return redirect

        if report_type in ('html', 'pdf', 'text'):
            # A draft is not an agreement yet: nothing to print.
            if contract_sudo.state not in CONFIRMED_STATES:
                return request.redirect(f'/my/contracts/{contract_id}')
            return self._show_report(
                model=contract_sudo, report_type=report_type,
                report_ref=LEASE_AGREEMENT_REPORT, download=download)

        values = {
            'contract': contract_sudo,
            'card': self._bc_contract_card(contract_sudo),
            'page_name': 'contract',
            'can_download_agreement': contract_sudo.state in CONFIRMED_STATES,
        }
        return request.render('business_center_portal.portal_contract_page', values)

    @http.route(['/my/contracts/<int:contract_id>/signed-agreement'],
                type='http', auth='user', website=True)
    def portal_my_contract_signed_page(self, contract_id, **kw):
        """Show the signed copy inside the portal, the way an invoice page
        shows its document: details and actions on the left, the document
        on the right. Same access rules as the contract page."""

        contract_sudo, redirect = self._bc_get_contract_sudo(contract_id)
        if redirect:
            return redirect

        attachment = contract_sudo.signed_attachment_id
        contract_url = f'/my/contracts/{contract_id}'
        if not attachment:
            return request.redirect(contract_url)

        file_url = f'/my/contracts/{contract_id}/signed-copy'
        mimetype = attachment.mimetype or ''
        values = {
            'contract': contract_sudo,
            'page_name': 'contract',
            'contract_url': contract_url,
            'file_url': file_url,
            'download_url': file_url + '?download=1',
            # Odoo's bundled PDF viewer, opened at page width without its outline.
            'viewer_url': ('/web/static/lib/pdfjs/web/viewer.html?file='
                           + quote(file_url, safe='') + '#pagemode=none&zoom=page-width'),
            'is_pdf': mimetype == 'application/pdf',
            'is_image': mimetype.startswith('image/'),
        }
        return request.render('business_center_portal.portal_contract_signed_page', values)

    @http.route(['/my/contracts/<int:contract_id>/signed-copy'],
                type='http', auth='user')
    def portal_my_contract_signed_copy(self, contract_id, download=False, **kw):
        """Serve the signed copy file: shown in the browser by default (for
        the signed copy page), saved when ``download`` is set."""

        contract_sudo, redirect = self._bc_get_contract_sudo(contract_id)
        if redirect:
            return redirect

        attachment = contract_sudo.signed_attachment_id
        if not attachment:
            return request.redirect(f'/my/contracts/{contract_id}')
        return request.env['ir.binary']._get_stream_from(attachment).get_response(
            as_attachment=bool(download))
        
    # ------------------------------------------------------------------------------
    #   MARK: CARD HELPERS
    # ------------------------------------------------------------------------------
    def _bc_contract_card(self, contract):
        """Values one contract card shows. The facts come from the contract
        model; this only gathers them, plus the wallet bar's percentage.
        Sudo: the visitor already passed the access check on the contract."""

        contract = contract.sudo()
        allowance = contract.free_hours_monthly
        return {
            'assets': contract._bc_asset_summary(),
            'monthly_rent': contract._bc_monthly_rent(),
            'days_left': contract._bc_days_left(),
            'ending_soon': contract._bc_is_ending_soon(),
            'renewal': contract.renewal_contract_id if contract._bc_is_continued()
                       else contract.browse(),
            'wallet_pct': min(100, round(contract.wallet_balance / allowance * 100))
                          if contract.is_wallet_eligible and allowance else 0,
        }