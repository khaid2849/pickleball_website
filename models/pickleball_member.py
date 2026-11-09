import secrets
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

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
        so nobody can overwrite a member's details by claiming their name)."""
        for member in self:
            if not member.user_id:
                raise UserError(_('%s has no website account to approve.', member.name))
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
        confirm_url = f"{base_url.rstrip('/')}/club/register/confirm/{token}"
        template = self.env.ref('pickleball_website.mail_template_website_signup_confirm').sudo()
        mail_id = template.with_context(confirm_url=confirm_url).send_mail(
            self.id, force_send=True, raise_exception=False,
            email_values={'email_to': self.user_id.email, 'recipient_ids': []},
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
