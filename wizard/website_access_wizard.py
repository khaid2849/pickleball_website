import re
import secrets
import unicodedata

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

# No look-alike characters (0/O, 1/l/I) — passwords are read out to members.
_PASSWORD_ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'
_PASSWORD_LENGTH = 8


def _login_slug(name):
    """'Nguyễn Văn Ân' -> 'nguyen.van.an' (ASCII, dots between words)."""
    text = (name or '').replace('đ', 'd').replace('Đ', 'D')
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return '.'.join(re.sub(r'[^A-Za-z0-9]+', ' ', text).lower().split()) or 'member'


def _new_password():
    return ''.join(secrets.choice(_PASSWORD_ALPHABET) for _i in range(_PASSWORD_LENGTH))


class PickleballWebsiteAccessWizard(models.TransientModel):
    _name = 'pickleball.website.access.wizard'
    _description = 'Grant Club Website Access'

    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft')
    line_ids = fields.One2many('pickleball.website.access.wizard.line', 'wizard_id', string='Members')

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if 'line_ids' not in fields_list:
            return values
        members = self.env['pickleball.member'].browse(self.env.context.get('active_ids') or [])
        taken = set()
        lines = []
        for member in members:
            user = member.user_id
            login = user.login if user else self._suggest_login(member.name, taken)
            taken.add(login)
            lines.append(Command.create({
                'member_id': member.id,
                'login': login,
                # Existing accounts keep their password unless one is typed in.
                'password': False if user and user.active else _new_password(),
            }))
        values['line_ids'] = lines
        return values

    @api.model
    def _suggest_login(self, name, taken):
        base = _login_slug(name)
        Users = self.env['res.users'].sudo().with_context(active_test=False)
        login, n = base, 1
        while login in taken or Users.search_count([('login', '=', login)]):
            n += 1
            login = f'{base}{n}'
        return login

    def action_grant(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Select at least one member.'))
        logins = [line.login.strip().lower() for line in self.line_ids]
        duplicates = {login for login in logins if logins.count(login) > 1}
        if duplicates:
            raise UserError(_('The same login is used twice: %s', ', '.join(sorted(duplicates))))
        for line in self.line_ids:
            line._grant()
        self.state = 'done'
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class PickleballWebsiteAccessWizardLine(models.TransientModel):
    _name = 'pickleball.website.access.wizard.line'
    _description = 'Grant Club Website Access — Member'

    wizard_id = fields.Many2one('pickleball.website.access.wizard', required=True, ondelete='cascade')
    member_id = fields.Many2one('pickleball.member', required=True, ondelete='cascade')
    login = fields.Char(required=True, help='What the member types as "Email / Login" on the website.')
    password = fields.Char(help='Leave empty to keep the current password of an existing account.')
    existing_account = fields.Boolean(compute='_compute_existing_account')

    @api.depends('member_id.user_id')
    def _compute_existing_account(self):
        for line in self:
            line.existing_account = bool(line.member_id.user_id)

    def _grant(self):
        """Create (or re-activate/update) the member's portal account."""
        self.ensure_one()
        login = self.login.strip().lower()
        member = self.member_id
        # sudo: creating portal users; this wizard is restricted to
        # Access Rights managers (see ir.model.access.csv).
        Users = self.env['res.users'].sudo().with_context(active_test=False, no_reset_password=True)
        user = member.user_id.sudo()
        clash = Users.search([('login', '=', login), ('id', '!=', user.id)], limit=1)
        if clash:
            raise UserError(_('Login "%(login)s" is already used by %(user)s.', login=login, user=clash.name))
        vals = {'login': login, 'active': True}
        if self.password:
            vals['password'] = self.password
        # The member's email goes on the account (it logs in too), unless
        # another account already uses it.
        if member.email and not user.email and not member._website_email_taken(member.email):
            vals['email'] = member.email
        if user:
            user.write(vals)
            member.sudo().website_state = 'approved'
        else:
            if not self.password:
                raise UserError(_('%s: a password is required for a new account.', member.name))
            vietnamese = self.env['res.lang']._lang_get('vi_VN')
            user = Users.create(dict(
                vals,
                name=member.name,
                lang='vi_VN' if vietnamese and vietnamese.active else self.env.lang,
                groups_id=[Command.set([self.env.ref('base.group_portal').id])],
            ))
            member.sudo().write({'user_id': user.id, 'website_state': 'approved'})
        member.sudo()._sync_club_member_group()
