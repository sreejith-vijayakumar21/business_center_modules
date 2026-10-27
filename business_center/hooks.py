# -*- coding: utf-8 -*-
"""Install-time hooks for the Business Center module."""

import logging

_logger = logging.getLogger(__name__)


def pre_init_hook(env):
    """Enable btree_gist before the tables are created, where permitted.

    The business.center.booking exclusion constraint indexes meeting_room_id
    and booking_date with '=' alongside a numrange with '&&'. GiST has no
    default operator class for integer or date, so the extension has to exist
    before the ALTER TABLE runs - which is why this is a pre_init hook.

    """

    try:
        env.cr.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    except Exception:
        env.cr.rollback()
        _logger.warning(
            "Business Center: could not create the btree_gist extension - the "
            "database user lacks CREATE privilege. If the extension is not "
            "already enabled, the double-booking constraint will not be "
            "created. Ask your database administrator to run: "
            "CREATE EXTENSION IF NOT EXISTS btree_gist;")


def post_init_hook(env):
    """Verify the anti-collision constraint actually landed.

    pre_init_hook runs on install only, so a database that was upgraded
    rather than installed fresh never gets the extension, and PostgreSQL
    refuses the EXCLUDE constraint without raising.
    """
    env.cr.execute("""
        SELECT 1 FROM pg_constraint
        WHERE conname = 'business_center_booking_no_double_booking'
    """)
    if env.cr.fetchone():
        _logger.info(
            "Business Center: double-booking exclusion constraint is in place.")
        return

    _logger.warning(
        "Business Center: the double-booking exclusion constraint is MISSING. "
        "Overlapping bookings can be written straight to the database. Run "
        "CREATE EXTENSION IF NOT EXISTS btree_gist; on this database, resolve "
        "any existing overlaps, then upgrade the module again.")