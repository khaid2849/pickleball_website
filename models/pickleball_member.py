import importlib
import logging
import re
import secrets
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import email_normalize

# The module's technical name has a dash: no regular import.
TelegramClient = importlib.import_module('odoo.addons.pickleball-team.services.telegram_client').TelegramClient

_logger = logging.getLogger(__name__)

# What members may change on their own profile from the website. Not the card
# ratings, DUPR, money, bot links or admin fields: those stay with the admins.
WEBSITE_PROFILE_FIELDS = (
    'name', 'gender', 'play_style', 'jersey_number', 'phone', 'email', 'image_1920',
    'bank_name', 'bank_account', 'bank_holder_name', 'qr_code',
)
# Sepay matches incoming transfers to members on these: changes are checked
# against the other members and reported to the bot managers.
WEBSITE_BANK_FIELDS = ('bank_name', 'bank_account', 'bank_holder_name', 'qr_code')


def _digits(value):
    return re.sub(r'\D', '', value or '')

# How long the link of the sign-up confirmation email stays valid.
SIGNUP_TOKEN_VALIDITY = timedelta(hours=48)


class PickleballMember(models.Model):
    _inherit = 'pickleball.member'

    user_id = fields.Many2one(
        'res.users',
        string='Website Account',
        copy=False,
        index=True,
        ondelete='set null',
        help='Portal account this member logs in to the club website with: '
             'created by the member on the website, or granted by an admin '
             'with the "Grant Website Access" action.',
    )
    website_login = fields.Char(related='user_id.login', string='Website Login')
    website_state = fields.Selection([
        ('pending_email', 'Email Not Confirmed'),
        ('pending_approval', 'Waiting for Approval'),
        ('approved', 'Approved'),
    ], string='Website Account Status', copy=False, index=True,
        help='Email Not Confirmed: a new person signed up on the website and '
             'has not clicked the link of the confirmation email yet.\n'
             'Waiting for Approval: someone signed up claiming to be this '
             'member; an admin must approve it before they can see the '
             'members area.\n'
             'Approved: the account can use the members area.')
    website_signup_token = fields.Char(copy=False, groups='base.group_system')
    website_signup_token_expiry = fields.Datetime(copy=False, groups='base.group_system')
    has_website_access = fields.Boolean(
        string='Website Access',
        compute='_compute_has_website_access',
        search='_search_has_website_access',
    )

    _sql_constraints = [
        ('user_id_uniq', 'unique(user_id)', 'This website account is already linked to another member.'),
    ]

    @api.depends('user_id.active', 'website_state')
    def _compute_has_website_access(self):
        for member in self:
            member.has_website_access = bool(
                member.user_id and member.user_id.active and member.website_state == 'approved')

    def _search_has_website_access(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise NotImplementedError(_('Unsupported search on Website Access.'))
        has_access = (operator == '=') == value
        domain = [('user_id', '!=', False), ('user_id.active', '=', True), ('website_state', '=', 'approved')]
        return domain if has_access else ['!', '&', '&'] + domain

    @api.constrains('user_id')
    def _check_user_id_is_portal(self):
        for member in self.filtered('user_id'):
            if not member.user_id._is_portal():
                raise ValidationError(_(
                    "%(member)s: the website account must be a portal user (not an internal user).",
                    member=member.name))

    def _sync_club_member_group(self):
        """Approved accounts are in the "Club Website Member" group (it shows
        the members' menus of the website); the others are not."""
        group = self.env.ref('pickleball_website.group_club_member').sudo()
        for member in self.filtered('user_id'):
            user = member.user_id.sudo()
            approved = member.website_state == 'approved' and member.active and user.active
            if approved and group not in user.groups_id:
                user.groups_id = [(4, group.id)]
            elif not approved and group in user.groups_id:
                user.groups_id = [(3, group.id)]

    # ── Admin actions ───────────────────────────────────────────────────────

    def action_open_website_access_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Grant Website Access'),
            'res_model': 'pickleball.website.access.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_model': self._name, 'active_ids': self.ids},
        }

    def action_revoke_website_access(self):
        """Archive the members' portal accounts — they can't log in anymore,
        and granting access again re-activates the same account."""
        self.user_id.sudo().write({'active': False})
        self._sync_club_member_group()
        return True

    def action_website_approve(self):
        """Approve a website sign-up: the member gets the members area, and
        the email/phone given at sign-up are copied onto the member (only now,
        so nobody can overwrite a member's details by claiming their name).
        The member is told by email that their account is open."""
        unsent = self.browse()
        for member in self:
            if not member.user_id:
                raise UserError(_('%s has no website account to approve.', member.name))
            was_pending = member.website_state != 'approved'
            user = member.user_id.sudo()
            vals = {'website_state': 'approved', 'active': True}
            if user.email:
                vals['email'] = user.email
            if user.partner_id.phone:
                vals['phone'] = user.partner_id.phone
            member.write(vals)
            member.sudo().write({'website_signup_token': False, 'website_signup_token_expiry': False})
            user.active = True
            member._sync_club_member_group()
            if was_pending and not member._website_send_mail(
                    'pickleball_website.mail_template_website_signup_approved',
                    login_url=f"{member.get_base_url()}/web/login?redirect=/club/me"):
                unsent |= member
        if unsent:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'sticky': True,
                    'title': _('Approved, but the email was not sent'),
                    'message': _('Could not email %s that their account is approved: check the outgoing '
                                 'mail server (Settings > Technical > Emails).', ', '.join(unsent.mapped('name'))),
                    'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                },
            }
        return True

    def action_website_reject(self):
        """Refuse a website sign-up: the account is archived and unlinked, the
        member is free to be claimed again. A brand-new member who never
        confirmed their email is archived too."""
        for member in self:
            user = member.user_id.sudo()
            new_unconfirmed = member.website_state == 'pending_email'
            member.write({'website_state': False})
            member._sync_club_member_group()
            member.write({'user_id': False})
            user.active = False
            if new_unconfirmed:
                member.active = False
        return True

    # ── Sign-up from the website ────────────────────────────────────────────

    def _website_notify_bot_managers(self, base_url):
        """DM the bot managers on Telegram that a website sign-up waits for
        their approval. Returns how many were notified; never raises (the
        sign-up itself is already saved)."""
        self.ensure_one()
        user = self.user_id.sudo()
        lines = [
            "🔔 Có tài khoản website cần duyệt",
            f"👤 Tên đăng nhập: {user.login}",
            f"🏓 Nhận là thành viên: {self.name}",
            f"📧 Email: {user.email}",
        ]
        if user.partner_id.phone:
            lines.append(f"📞 SĐT: {user.partner_id.phone}")
        if self.phone or self.email:
            lines.append(f"ℹ️ Hồ sơ hiện tại: {' · '.join(filter(None, [self.phone, self.email]))}")
        lines.append(f"👉 Duyệt / từ chối: {base_url.rstrip('/')}/mail/view?model={self._name}&res_id={self.id}")
        return self._website_telegram_bot_managers("\n".join(lines))

    def _website_telegram_bot_managers(self, text):
        """DM ``text`` to the bot managers on Telegram. Returns how many got
        it; never raises (what it reports is already saved)."""
        try:
            # sudo: members/visitors on the website can't read bot settings.
            config = self.env['pickleball.ai.telegram.config'].sudo().search(
                [('is_active', '=', True), ('bot_token', '!=', False)], limit=1)
            managers = self.sudo().search([('is_bot_manager', '=', True), ('telegram_chat_id', '!=', False)])
            if not config or not managers:
                _logger.warning("Club website: no Telegram bot or bot manager to notify about member %s", self.ids)
                return 0
            Log = self.env['pickleball.bot.message.log'].sudo()
            client = Log._wrap_client(TelegramClient(config.bot_token), 'telegram', source='website')
            sent = 0
            for manager in managers:
                if client.send_message(manager.telegram_chat_id, text):
                    sent += 1
                else:
                    _logger.warning("Club website: Telegram notice to bot manager %s failed", manager.id)
            return sent
        except Exception:
            _logger.exception("Club website: failed to notify the bot managers about member %s", self.ids)
            return 0

    def _website_new_signup_token(self):
        self.ensure_one()
        token = secrets.token_urlsafe(32)
        self.sudo().write({
            'website_signup_token': token,
            'website_signup_token_expiry': fields.Datetime.now() + SIGNUP_TOKEN_VALIDITY,
        })
        return token

    def _website_send_confirmation_email(self, base_url):
        """Email the sign-up confirmation link to the member's new account.
        Returns False when the email could not be sent (e.g. no outgoing
        mail server configured)."""
        self.ensure_one()
        token = self._website_new_signup_token()
        return self._website_send_mail(
            'pickleball_website.mail_template_website_signup_confirm',
            confirm_url=f"{base_url.rstrip('/')}/club/register/confirm/{token}")

    def _website_send_mail(self, template_xmlid, **ctx):
        """Send a club website email to the member's account email right
        away; ``ctx`` is given to the template. Returns False when it could
        not be sent (e.g. no outgoing mail server)."""
        self.ensure_one()
        if not self.user_id.email:
            return False
        # sudo: also sent for public visitors signing up.
        template = self.env.ref(template_xmlid).sudo()
        mail_id = template.with_context(**ctx).send_mail(
            self.id, force_send=True, raise_exception=False,
            email_values={'email_to': self.user_id.sudo().email, 'recipient_ids': []},
        )
        mail = self.env['mail.mail'].sudo().browse(mail_id).exists()
        # Sent mails are deleted (auto_delete); failed ones stay in exception.
        return not (mail and mail.state == 'exception')

    @api.model
    def _website_confirm_signup_token(self, token):
        """Confirm a new member's email from the link: the member becomes
        active and their account approved. Returns the member, or an empty
        recordset if the link is unknown or expired."""
        if not token:
            return self.browse()
        member = self.sudo().with_context(active_test=False).search(
            [('website_signup_token', '=', token), ('website_state', '=', 'pending_email')], limit=1)
        if not member or member.website_signup_token_expiry < fields.Datetime.now():
            return self.browse()
        member.write({
            'active': True,
            'website_state': 'approved',
            'website_signup_token': False,
            'website_signup_token_expiry': False,
        })
        member._sync_club_member_group()
        return member

    # ── Profile edited by the member on the website ─────────────────────────

    def _website_email_taken(self, email):
        """Whether another account than this member's already uses ``email``
        (emails log in too, so one account per email)."""
        email = email_normalize(email or '', strict=True)
        if not email:
            return False
        # sudo: checks all the accounts, archived ones too.
        return bool(self.env['res.users'].sudo().with_context(active_test=False).search_count(
            [('email_normalized', '=', email), ('id', '!=', self.user_id.id)], limit=1))

    def _website_bank_identity_errors(self, vals):
        """Errors (by field) when the new bank account number or transfer
        names in ``vals`` would collide with another member's: Sepay could
        then credit someone else's transfer to this member."""
        self.ensure_one()
        errors = {}
        # sudo: compares with the other members, never shown to the user.
        others = self.sudo().search([('id', '!=', self.id)])
        new_digits = _digits(vals.get('bank_account', self.bank_account))
        if new_digits and new_digits != _digits(self.bank_account) \
                and any(_digits(other.bank_account) == new_digits for other in others):
            errors['bank_account'] = _('Another member already uses this account number. Ask the team admin.')

        new = self.new({
            'name': vals.get('name', self.name),
            'bank_holder_name': vals.get('bank_holder_name', self.bank_holder_name),
        })
        added = set(new._get_bank_aliases()) - set(self._get_bank_aliases())
        if added:
            taken = {alias for other in others for alias in other._get_bank_aliases()}
            # A name inside a longer one clashes too: the longest name found
            # in a transfer wins.
            clashes = sorted(alias for alias in added for other in taken
                             if f' {alias} ' in f' {other} ' or f' {other} ' in f' {alias} ')
            if clashes:
                field = 'bank_holder_name' if new.bank_holder_name else 'name'
                errors[field] = _('"%s" is too close to the name another member pays with. '
                                  'Ask the team admin.', ', '.join(clashes))
        return errors

    def _website_update_profile(self, vals):
        """Save the profile a member edited on the website, keep their login
        account in sync and tell the bot managers when the bank details
        changed. ``vals`` must be validated already."""
        self.ensure_one()
        vals = {key: value for key, value in vals.items() if key in WEBSITE_PROFILE_FIELDS}
        member = self.sudo()  # sudo: portal users can't write members; fields are filtered above.
        old_bank = {field: member[field] for field in WEBSITE_BANK_FIELDS if field != 'qr_code'}
        member.write(vals)

        user = member.user_id.sudo()
        if user:
            user_vals = {}
            if 'name' in vals and user.name != vals['name']:
                user_vals['name'] = vals['name']
            if 'email' in vals and email_normalize(user.email or '') != email_normalize(vals['email'] or ''):
                if member._website_email_taken(vals['email']):
                    # Kept unchanged on the member: another account has it.
                    _logger.info("Club website: email of member %s not copied to their account: "
                                 "another account uses it", member.id)
                else:
                    user_vals['email'] = vals['email']
            if 'phone' in vals and user.partner_id.phone != vals['phone']:
                user_vals['phone'] = vals['phone']
            if user_vals:
                user.write(user_vals)

        lines = []
        labels = {'bank_name': '🏦 Ngân hàng', 'bank_account': '🔢 Số TK', 'bank_holder_name': '👤 Chủ TK'}
        for field, label in labels.items():
            if field in vals and (old_bank[field] or '') != (vals[field] or ''):
                lines.append(f"{label}: {old_bank[field] or '—'} → {vals[field] or '—'}")
        if 'qr_code' in vals:
            lines.append("🖼 Mã QR: " + ("đã cập nhật" if vals['qr_code'] else "đã xoá"))
        if lines:
            _logger.info("Club website: member %s changed their bank details: %s", member.id, "; ".join(lines))
            self._website_telegram_bot_managers("\n".join(
                [f"✏️ {member.name} vừa sửa thông tin thanh toán trên website"] + lines))
        return True
