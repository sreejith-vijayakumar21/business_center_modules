# -*- coding: utf-8 -*-

"""Install-time hooks for the Business Center Portal module."""


def uninstall_hook(env):
    """Put account's portal invoice rules back as they were before install.

    Uninstalling deletes this module's tenant groups, but the domains it wrote
    into account's noupdate portal rules would still name them.
    """

    env['ir.rule']._bc_restore_portal_invoice_rules()