from odoo import SUPERUSER_ID, api

from odoo.addons.pickleball_website.hooks import setup_member_access


def migrate(cr, version):
    """1.2.0: self sign-up, members-only menus."""
    setup_member_access(api.Environment(cr, SUPERUSER_ID, {}))
