# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models


class BusinessCenterSearchPanelMixin(models.AbstractModel):
    """Search panel fixes shared by spaces and desks."""

    _name = 'business.center.search.panel.mixin'
    _description = 'Search Panel Helpers for Business Center'

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def search_panel_select_multi_range(self, field_name, **kwargs):
        """Odoo 19 web client sends group_domain=None for a grouped many2one
        filter with counters when no value is ticked, which crashes the
        domain AND. Normalise it to an empty domain."""

        if kwargs.get('group_domain') is None:
            kwargs['group_domain'] = []
        return super().search_panel_select_multi_range(field_name, **kwargs)