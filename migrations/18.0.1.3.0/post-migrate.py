from odoo import SUPERUSER_ID, api

from odoo.addons.pickleball_website.hooks import setup_member_access


def migrate(cr, version):
    """1.3.0: members menus only for approved accounts (Club Website Member group)."""
    setup_member_access(api.Environment(cr, SUPERUSER_ID, {}))
