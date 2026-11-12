from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.tools import email_normalize


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def _get_login_domain(self, login):
        """Log in with the username or the email of the account.

        The username always wins. An email is only used when no account has
        it as username, and it must belong to exactly one account (of this
        website): an ambiguous email logs nobody in.
        """
        domain = super()._get_login_domain(login)
        email = email_normalize(login or '', strict=True)
        if not email:
            return domain
        # sudo: called before anyone is logged in.
        Users = self.sudo()
        if Users.search_count(domain, limit=1):
            return domain
        # Same restrictions as a login by username (e.g. the user's website).
        user_ids = [
            user.id for user in Users.search([('email_normalized', '=', email)])
            if Users.search_count(super()._get_login_domain(user.login) + [('id', '=', user.id)], limit=1)
        ]
        if len(user_ids) == 1:
            return [('id', '=', user_ids[0])]
        return domain

    def _get_pickleball_member(self):
        """The pickleball member this user logs in as (empty recordset if none)."""
        self.ensure_one()
        # sudo: portal users have no access to pickleball.member; this only
        # resolves which member the current user is.
        # Inactive too: a new member stays archived until they confirm their email.
        return self.env['pickleball.member'].sudo().with_context(active_test=False).search(
            [('user_id', '=', self.id)], limit=1)

    def _pickleball_website_chat_enabled(self):
        """Whether the chat bubble of the club website shows for this user:
        admins (internal users) and members whose account is approved."""
        self.ensure_one()
        if self._is_public():
            return False
        if self._is_internal():
            return True
        member = self._get_pickleball_member()
        return bool(member) and member.website_state == 'approved' and member.active

    def _pickleball_password_by_email(self):
        """Whether this user may only change their password from the club
        website ("Edit my profile"), where it is confirmed by email: the
        members' portal accounts. Admins keep Odoo's own ways."""
        self.ensure_one()
        return self._is_portal() and bool(self._get_pickleball_member())

    @api.model
    def change_password(self, old_passwd, new_passwd):
        """Members can't change their password right away (portal's
        /my/security, or an RPC call): it goes through the email confirmation
        of the club website."""
        if self.env.user._pickleball_password_by_email():
            raise UserError(_('Change your password from "Edit my profile" on the club website: '
                              'it is confirmed by email.'))
        return super().change_password(old_passwd, new_passwd)
