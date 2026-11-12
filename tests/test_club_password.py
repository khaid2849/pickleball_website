import re
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.addons.mail.tests.common import MailCase
from odoo.exceptions import AccessDenied, UserError
from odoo.tests import HttpCase, tagged
from odoo.tests.common import JsonRpcException

from .test_club_website import ClubDataMixin


@tagged('post_install', '-at_install')
class TestClubPassword(ClubDataMixin, MailCase, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_club_data()
        credentials = cls._grant(cls.an)
        cls.login, cls.password = credentials[cls.an]
        cls.an.user_id.email = 'an.password@example.com'

    def setUp(self):
        super().setUp()
        self.authenticate(self.login, self.password)

    def _csrf(self, html):
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def _ask(self, current=None, new='new-secret-1', confirm=None):
        """Post the password form (same browser session every time)."""
        page = self.url_open('/club/me/edit')
        self.assertIn('/club/me/password', page.text)
        response = self.url_open('/club/me/password', data={
            'csrf_token': self._csrf(page.text),
            'current_password': self.password if current is None else current,
            'new_password': new,
            'confirm_password': new if confirm is None else confirm,
        })
        self.an.invalidate_recordset()
        return response

    def _password_ok(self, password):
        user = self.an.user_id
        try:
            self.env['res.users'].with_user(user)._check_credentials(
                {'login': user.login, 'password': password, 'type': 'password'}, {'interactive': True})
        except AccessDenied:
            return False
        return True

    def test_change_confirmed_by_email(self):
        with self.mock_mail_gateway():
            response = self._ask()
        self.assertTrue(response.url.endswith('/club/me/edit?password=sent#pbw_password'), response.url)
        self.assertIn('an.password@example.com', response.text)
        member = self.an.sudo()
        token = member.website_password_token
        self.assertTrue(token)
        self.assertNotIn('new-secret-1', member.website_password_hash, 'only the hash is kept')

        self.assertEqual(len(self._mails), 1)
        mail = self._mails[0]
        self.assertEqual(mail['email_to'], ['an.password@example.com'])
        self.assertIn(f'/club/me/password/confirm/{token}', mail['body'])
        # Nothing changes before the confirmation.
        self.assertTrue(self._password_ok(self.password))

        # Opening the link only shows a button (mail scanners follow links).
        page = self.url_open(f'/club/me/password/confirm/{token}')
        self.assertIn(f'action="/club/me/password/confirm/{token}"', page.text)
        self.assertTrue(self._password_ok(self.password))

        with self.mock_mail_gateway():
            done = self.url_open(f'/club/me/password/confirm/{token}', data={'csrf_token': self._csrf(page.text)})
        self.assertEqual(done.status_code, 200)
        self.assertIn('/club/me', done.text, 'still logged in on this browser')
        self.assertTrue(self._password_ok('new-secret-1'))
        self.assertFalse(self._password_ok(self.password))
        self.assertFalse(member.website_password_token)
        self.assertEqual(len(self._mails), 1, 'the member is told their password changed')
        self.assertIn('changed', self._mails[0]['subject'])

        # The link works only once.
        self.assertIn('fa-chain-broken', self.url_open(f'/club/me/password/confirm/{token}').text)

    def test_wrong_current_password(self):
        with self.mock_mail_gateway():
            response = self._ask(current='not-my-password')
        self.assertIn('alert alert-danger', response.text)
        self.assertRegex(response.text, r'name="current_password"[^>]*is-invalid', 'the field is flagged')
        self.assertFalse(self.an.sudo().website_password_token)
        self.assertFalse(self._mails)

    def test_too_many_wrong_passwords(self):
        for _attempt in range(5):
            self._ask(current='nope')
        # Even the right password is refused for a while.
        with self.mock_mail_gateway():
            response = self._ask()
        self.assertIn('alert alert-danger', response.text)
        self.assertFalse(self.an.sudo().website_password_token)
        self.assertFalse(self._mails)

    def test_invalid_new_password(self):
        for new, confirm in (('short', 'short'), ('new-secret-1', 'new-secret-2'), (None, None)):
            response = self._ask(new=self.password if new is None else new, confirm=confirm)
            self.assertIn('alert alert-danger', response.text)
            self.assertFalse(self.an.sudo().website_password_token)

    def test_email_not_sent_forgets_the_request(self):
        with patch.object(type(self.an), '_website_send_mail', return_value=False):
            response = self._ask()
        self.assertIn('alert alert-danger', response.text)
        self.assertFalse(self.an.sudo().website_password_token)
        self.assertTrue(self._password_ok(self.password))

    def test_expired_link(self):
        with self.mock_mail_gateway():
            self._ask()
        member = self.an.sudo()
        token = member.website_password_token
        member.website_password_expiry = fields.Datetime.now() - timedelta(minutes=1)
        self.authenticate(None, None)
        page = self.url_open(f'/club/me/password/confirm/{token}')
        self.assertIn('fa-chain-broken', page.text)
        self.assertTrue(self._password_ok(self.password))

    # ── Odoo's own ways are closed to members ──────────────────────────────

    def test_portal_security_page_redirects_members(self):
        response = self.url_open('/my/security')
        self.assertIn('/club/me/edit', response.url)
        # A posted form doesn't change anything either.
        self.url_open('/my/security', data={
            'csrf_token': self._csrf(self.url_open('/club/me/edit').text),
            'old': self.password, 'new1': 'direct-change-1', 'new2': 'direct-change-1',
        })
        self.assertTrue(self._password_ok(self.password))

    def test_change_password_rpc_refused_for_members(self):
        with self.assertRaises(UserError):
            self.env['res.users'].with_user(self.an.user_id).change_password(self.password, 'direct-change-1')
        # Same over RPC, as the logged-in member.
        with self.assertRaises(JsonRpcException):
            self.make_jsonrpc_request('/web/dataset/call_kw/res.users/change_password', {
                'model': 'res.users', 'method': 'change_password',
                'args': [self.password, 'direct-change-1'], 'kwargs': {},
            })
        self.assertTrue(self._password_ok(self.password))

    def test_other_users_keep_odoo_password_change(self):
        portal = self.env['res.users'].create({
            'name': 'Pw Stranger', 'login': 'pw_stranger', 'password': 'pw-stranger-1',
            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.assertFalse(portal._pickleball_password_by_email())
        self.assertTrue(self.env['res.users'].with_user(portal).change_password('pw-stranger-1', 'pw-stranger-2'))
        self.authenticate('pw_stranger', 'pw-stranger-2')
        self.assertTrue(self.url_open('/my/security').url.endswith('/my/security'))
        self.assertFalse(self.env.ref('base.user_admin')._pickleball_password_by_email())
