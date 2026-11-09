from odoo.http import request

from odoo.addons.website.controllers.main import Website


class ClubWebsite(Website):

    def _login_redirect(self, uid, redirect=None):
        """Members land on their club dashboard after logging in (instead of
        the generic /my portal page)."""
        if not redirect:
            user = request.env['res.users'].sudo().browse(uid)
            if not user._is_internal() and user._get_pickleball_member():
                redirect = '/club/me'
        return super()._login_redirect(uid, redirect=redirect)
