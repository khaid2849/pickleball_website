from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _get_translation_frontend_modules_name(cls):
        """Translate the texts of the website's JS components (chat bubble,
        match builder): only the listed modules' translations reach the
        frontend."""
        return super()._get_translation_frontend_modules_name() + ['pickleball_website']
