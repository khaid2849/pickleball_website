from odoo import SUPERUSER_ID, api

from odoo.addons.pickleball_website.hooks import setup_languages


def migrate(cr, version):
    """1.1.0: the website becomes bilingual (Vietnamese by default, English)."""
    setup_languages(api.Environment(cr, SUPERUSER_ID, {}))
