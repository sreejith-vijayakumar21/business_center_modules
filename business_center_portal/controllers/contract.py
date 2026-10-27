# -*- coding: utf-8 -*-
from collections import OrderedDict

from odoo import _, http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager


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

    def _contract_searchbar_sortings(self):
        """The choices in the 'Sort By' dropdown on the contract list."""
        return {
            'date': {'label': _('Start Date'), 'order': 'date_start desc'},
            'name': {'label': _('Reference'), 'order': 'name desc'},
            'state': {'label': _('Status'), 'order': 'state'},
        }

    def _contract_searchbar_filters(self):
        """The choices in the 'Filter By' dropdown on the contract list."""
        return {
            'all': {'label': _('All'), 'domain': []},
            'active': {'label': _('Active'), 'domain': [('state', '=', 'active')]},
            'draft': {'label': _('Draft'), 'domain': [('state', '=', 'draft')]},
            'expired': {'label': _('Expired'), 'domain': [('state', '=', 'expired')]},
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
            filterby = 'all'
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
            'page_name': 'contract',
            'pager': pager,
            'default_url': '/my/contracts',
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby,
            'searchbar_filters': OrderedDict(sorted(searchbar_filters.items())),
            'filterby': filterby,
            'searchbar_inputs': searchbar_inputs,
            'search_in': search_in,
            'search': search,
        })
        return request.render('business_center_portal.portal_my_contracts', values)

    @http.route(['/my/contracts/<int:contract_id>'],
                type='http', auth='user', website=True)
    def portal_my_contract_detail(self, contract_id, access_token=None, **kw):
        """The detail page for one contract."""
        
        if not access_token:
            denied = self._bc_contract_access_denied()
            if denied:
                return denied
        try:
            contract_sudo = self._document_check_access(
                'business.center.contract', contract_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')

        values = {
            'contract': contract_sudo,
            'page_name': 'contract',
        }
        return request.render('business_center_portal.portal_contract_page', values)