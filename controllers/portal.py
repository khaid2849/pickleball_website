"""Members change their password on the club website only.

Odoo's portal page /my/security changes the password right away; members
are sent to "Edit my profile" instead, where the change is confirmed by
email (the model refuses res.users.change_password for them as well).
"""
from odoo import http
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal


class ClubCustomerPortal(CustomerPortal):

    @http.route()
    def security(self, **post):
        if request.env.user._pickleball_password_by_email():
            return request.redirect('/club/me/edit#pbw_password')
        return super().security(**post)
