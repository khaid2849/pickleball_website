"""A member changes their website password from "Edit my profile".

The new password only applies once the member clicks the link emailed to
their account: whoever borrows an open session can't lock the owner out.
Until then only its hash is kept, next to a one-time token.
"""
import logging
import secrets
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied, UserError

_logger = logging.getLogger(__name__)

# How long the link of the password confirmation email stays valid.
PASSWORD_TOKEN_VALIDITY = timedelta(hours=1)
MIN_PASSWORD_LENGTH = 8


class PickleballMember(models.Model):
    _inherit = 'pickleball.member'

    website_password_token = fields.Char(copy=False, groups='base.group_system')
    website_password_expiry = fields.Datetime(copy=False, groups='base.group_system')
    website_password_hash = fields.Char(copy=False, groups='base.group_system')

    def _website_password_errors(self, current: str, new: str, confirm: str) -> dict:
        """Errors (by field) of a password change asked from the website;
        checks the current password of the member's account."""
        self.ensure_one()
        errors = {}
        if not current:
            errors['current_password'] = _('Enter your current password.')
        if len(new) < MIN_PASSWORD_LENGTH:
            errors['new_password'] = _('At least %s characters.', MIN_PASSWORD_LENGTH)
        elif new != confirm:
            errors['confirm_password'] = _('The two passwords are different.')
        elif current and new == current:
            errors['new_password'] = _('Choose a password different from the current one.')
        if errors:
            return errors

        user = self.sudo().user_id
        if user != self.env.user:
            return {'current_password': _('You can only change your own password.')}
        try:
            # Checked as the user (not sudo): the same check as a login.
            self.env.user._check_credentials(
                {'login': user.login, 'password': current, 'type': 'password'}, {'interactive': True})
        except AccessDenied:
            return {'current_password': _('Your current password is not correct.')}
        if hasattr(user, '_check_password_policy'):  # auth_password_policy installed
            try:
                user._check_password_policy([new])
            except UserError as exc:
                return {'new_password': exc.args[0]}
        return {}

    def _website_request_password_change(self, new_password: str, base_url: str) -> bool:
        """Keep the hash of ``new_password`` and email the confirmation link
        to the member's account. Returns False (and forgets the request) when
        the email could not be sent."""
        self.ensure_one()
        # sudo: portal users can't write members nor read the token fields.
        member = self.sudo()
        token = secrets.token_urlsafe(32)
        member.write({
            'website_password_token': token,
            'website_password_expiry': fields.Datetime.now() + PASSWORD_TOKEN_VALIDITY,
            'website_password_hash': member.user_id._crypt_context().hash(new_password),
        })
        sent = member._website_send_mail(
            'pickleball_website.mail_template_website_password_confirm',
            confirm_url=f"{base_url.rstrip('/')}/club/me/password/confirm/{token}",
            valid_minutes=int(PASSWORD_TOKEN_VALIDITY.total_seconds() // 60),
        )
        if not sent:
            member._website_clear_password_request()
        return sent

    def _website_clear_password_request(self):
        self.sudo().write({
            'website_password_token': False,
            'website_password_expiry': False,
            'website_password_hash': False,
        })

    @api.model
    def _website_password_request(self, token: str):
        """The member whose password change ``token`` confirms (sudo), or an
        empty recordset when the link is unknown or expired."""
        if not token:
            return self.browse()
        # sudo: the confirmation link may be opened without being logged in.
        member = self.sudo().search([('website_password_token', '=', token)], limit=1)
        if not member or not member.user_id or member.website_password_expiry < fields.Datetime.now():
            return self.browse()
        return member

    def _website_apply_password_change(self) -> bool:
        """Apply the confirmed password change: every other session of the
        account is logged out. The member is emailed that it changed."""
        self.ensure_one()
        member = self.sudo()
        user = member.user_id
        password_hash = member.website_password_hash
        if not user or not password_hash:
            return False
        # The hash was made by the account's own crypt context: stored as is.
        user._set_encrypted_password(user.id, password_hash)
        member._website_clear_password_request()
        # Session tokens are cached from the password hash: drop the cache so
        # the sessions opened with the old password are logged out.
        self.env.registry.clear_cache()
        _logger.info("Club website: member %s (user %s) changed their password by email confirmation",
                     member.id, user.id)
        member._website_send_mail('pickleball_website.mail_template_website_password_changed',
                                  changed_at=fields.Datetime.context_timestamp(
                                      member.with_context(tz=user.tz or 'Asia/Ho_Chi_Minh'),
                                      fields.Datetime.now()).strftime('%d/%m/%Y %H:%M'))
        return True
