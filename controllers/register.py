"""Self sign-up on the club website (/club/register).

Anyone can create an account (username, password, email, optional phone):

- "I'm already a member": they pick their name among the members without an
  account. The account waits for an admin's approval (anyone could pick
  someone else's name); their email/phone are copied onto the member only
  when approved.
- "I'm new": a new member is created, archived until they confirm their
  email with the link we send them.

Until then they can log in, but only see the status page (/club/pending).
"""
import logging
import re

from odoo import Command, _, http
from odoo.exceptions import AccessDenied
from odoo.http import request

_logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
LOGIN_RE = re.compile(r'^[a-z0-9._-]{3,40}$')
MIN_PASSWORD_LENGTH = 8


class ClubRegister(http.Controller):

    def _claimable_members(self):
        """Members someone can sign up as: active, without a website account."""
        return request.env['pickleball.member'].sudo().search(
            [('active', '=', True), ('user_id', '=', False)], order='name')

    def _register_values(self, form=None, errors=None):
        return {
            'form': form or {},
            'errors': errors or {},
            'claimable_members': self._claimable_members(),
            'club_tab': 'register',
            'is_club_member': False,
            'me': request.env['pickleball.member'].sudo(),
        }

    @http.route('/club/register', type='http', auth='public', website=True, sitemap=True,
                methods=['GET', 'POST'])
    def club_register(self, **post):
        if not request.env.user._is_public():
            return request.redirect('/club/me')
        if request.httprequest.method != 'POST':
            return request.render('pickleball_website.club_register', self._register_values())

        form = {key: (post.get(key) or '').strip() for key in (
            'login', 'email', 'phone', 'name', 'is_member', 'member_id')}
        password, confirm = post.get('password') or '', post.get('confirm_password') or ''
        form['login'] = form['login'].lower()
        errors = self._validate(form, password, confirm)
        if errors:
            return request.render('pickleball_website.club_register', self._register_values(form, errors))

        member = self._create_account(form, password)
        # authenticate() checks the password with its own cursor: the new
        # account must be committed first (same as auth_signup's sign-up).
        request.env.cr.commit()
        if member.website_state == 'pending_approval':
            member._website_notify_bot_managers(request.httprequest.host_url)
        try:
            request.session.authenticate(request.db, {
                'login': form['login'], 'password': password, 'type': 'password'})
        except AccessDenied:  # e.g. 2FA policies; they can still log in by hand
            return request.redirect('/web/login?redirect=/club/pending')
        if member.website_state == 'pending_email':
            sent = member._website_send_confirmation_email(request.httprequest.host_url)
            return request.redirect('/club/pending?sent=%d' % int(sent))
        return request.redirect('/club/pending')

    def _validate(self, form, password, confirm):
        errors = {}
        Users = request.env['res.users'].sudo().with_context(active_test=False)
        if not LOGIN_RE.match(form['login']):
            errors['login'] = _('3 to 40 characters: lowercase letters, digits, dots, dashes or underscores.')
        elif Users.search_count([('login', '=ilike', form['login'])]):
            errors['login'] = _('This username is already taken.')
        if len(password) < MIN_PASSWORD_LENGTH:
            errors['password'] = _('At least %s characters.', MIN_PASSWORD_LENGTH)
        elif password != confirm:
            errors['confirm_password'] = _('The two passwords are different.')
        if not EMAIL_RE.match(form['email']):
            errors['email'] = _('Enter a valid email address.')
        elif Users.search_count([('email', '=ilike', form['email'])]):
            errors['email'] = _('An account already uses this email.')
        if form['phone'] and not re.match(r'^[0-9 +().-]{8,20}$', form['phone']):
            errors['phone'] = _('Enter a valid phone number.')
        if form['is_member'] == 'yes':
            member_id = int(form['member_id']) if form['member_id'].isdigit() else 0
            if member_id not in self._claimable_members().ids:
                errors['member_id'] = _('Pick your name in the list.')
        elif form['is_member'] == 'no':
            if len(form['name']) < 2:
                errors['name'] = _('Enter your full name.')
        else:
            errors['is_member'] = _('Tell us whether you are already a member.')
        return errors

    def _create_account(self, form, password):
        """Create the portal user and link (or create) the member."""
        Member = request.env['pickleball.member'].sudo()
        if form['is_member'] == 'yes':
            member = Member.browse(int(form['member_id']))
            name, state = member.name, 'pending_approval'
        else:
            name, state = form['name'], 'pending_email'
        # sudo: public visitors create their own portal account here, after
        # the validation above.
        user = request.env['res.users'].sudo().with_context(no_reset_password=True).create({
            'name': name,
            'login': form['login'],
            'password': password,
            'email': form['email'],
            'phone': form['phone'] or False,
            'lang': request.lang.code,
            'groups_id': [Command.set([request.env.ref('base.group_portal').id])],
        })
        if form['is_member'] == 'yes':
            member.write({'user_id': user.id, 'website_state': state})
        else:
            # Archived until the email is confirmed: unconfirmed sign-ups
            # don't show up in the team.
            member = Member.create({
                'name': name,
                'email': form['email'],
                'phone': form['phone'] or False,
                'user_id': user.id,
                'website_state': state,
                'active': False,
            })
        _logger.info("Club website sign-up: %s (%s) as member %s, %s", user.login, user.id, member.id, state)
        return member

    @http.route('/club/register/confirm/<string:token>', type='http', auth='public', website=True,
                sitemap=False)
    def club_register_confirm(self, token, **kwargs):
        member = request.env['pickleball.member']._website_confirm_signup_token(token)
        return request.render('pickleball_website.club_register_confirmed', {
            'confirmed_member': member,
            'club_tab': 'register',
            'is_club_member': False,
            'me': request.env['pickleball.member'].sudo(),
        })

    @http.route('/club/pending', type='http', auth='user', website=True, sitemap=False,
                methods=['GET', 'POST'])
    def club_pending(self, sent=None, **kwargs):
        member = request.env.user._get_pickleball_member()
        if request.env.user._is_internal() or (member and member.website_state == 'approved'):
            return request.redirect('/club/me')
        if request.httprequest.method == 'POST' and member.website_state == 'pending_email':
            sent = int(member._website_send_confirmation_email(request.httprequest.host_url))
        return request.render('pickleball_website.club_pending', {
            'pending_member': member,
            'email': request.env.user.email,
            'sent': None if sent is None else str(sent) == '1',
            'club_tab': 'pending',
            'is_club_member': False,
            'me': request.env['pickleball.member'].sudo(),
        })
