import re

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestClubRegister(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.member = cls.env['pickleball.member'].create({'name': 'Reg Existing Player'})

    def _register(self, **fields):
        page = self.url_open('/club/register')
        self.assertEqual(page.status_code, 200)
        csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        data = {
            'login': 'reg.player', 'email': 'reg.player@example.com', 'phone': '0901 234 567',
            'password': 'reg-password', 'confirm_password': 'reg-password', 'csrf_token': csrf_token,
        }
        data.update(fields)
        return self.url_open('/club/register', data=data)

    def test_new_player_confirms_email(self):
        response = self._register(is_member='no', name='Reg New Player')
        self.assertIn('/club/pending', response.url)
        member = self.env['pickleball.member'].with_context(active_test=False).search(
            [('name', '=', 'Reg New Player')])
        self.assertEqual(member.website_state, 'pending_email')
        self.assertFalse(member.active, 'unconfirmed sign-ups stay out of the team')
        self.assertEqual(member.user_id.login, 'reg.player')
        self.assertEqual(member.email, 'reg.player@example.com')
        # Logged in, but no members area until the email is confirmed.
        self.assertIn('/club/pending', self.url_open('/club/players').url)

        token = member.sudo().website_signup_token
        self.assertTrue(token)
        self.assertEqual(self.url_open('/club/register/confirm/wrong-token').status_code, 200)
        self.assertEqual(member.website_state, 'pending_email')
        self.url_open(f'/club/register/confirm/{token}')
        member.invalidate_recordset()
        self.assertTrue(member.active)
        self.assertEqual(member.website_state, 'approved')
        self.assertIn(self.env.ref('pickleball_website.group_club_member'), member.user_id.groups_id)
        self.assertEqual(self.url_open('/club/players').status_code, 200)
        self.assertTrue(self.url_open('/club/me').url.endswith('/club/me'))

    def test_existing_member_waits_for_approval(self):
        response = self._register(is_member='yes', member_id=str(self.member.id))
        self.assertIn('/club/pending', response.url)
        self.assertEqual(self.member.website_state, 'pending_approval')
        self.assertEqual(self.member.user_id.login, 'reg.player')
        # Nothing is copied onto the member before approval.
        self.assertFalse(self.member.email)
        self.assertIn('/club/pending', self.url_open('/club/finance').url)
        # Already claimed: not offered to anyone else.
        self.authenticate(None, None)
        self.assertNotIn(f'value="{self.member.id}"', self.url_open('/club/register').text)

        group = self.env.ref('pickleball_website.group_club_member')
        self.assertNotIn(group, self.member.user_id.groups_id, 'no members menus before approval')
        self.member.action_website_approve()
        self.assertEqual(self.member.website_state, 'approved')
        self.assertIn(group, self.member.user_id.groups_id)
        self.assertEqual(self.member.email, 'reg.player@example.com')
        self.assertEqual(self.member.phone, '0901 234 567')
        self.authenticate('reg.player', 'reg-password')
        self.assertEqual(self.url_open('/club/finance').status_code, 200)

    def test_reject_frees_the_member(self):
        self._register(is_member='yes', member_id=str(self.member.id))
        user = self.member.user_id
        self.member.action_website_reject()
        self.assertFalse(self.member.user_id)
        self.assertFalse(self.member.website_state)
        self.assertFalse(user.active)

    def test_invalid_forms_are_refused(self):
        Users = self.env['res.users'].with_context(active_test=False)
        cases = [
            dict(is_member='no', name='Reg X', login='A'),                              # bad username
            dict(is_member='no', name='Reg X', password='short', confirm_password='short'),
            dict(is_member='no', name='Reg X', confirm_password='different-pw'),
            dict(is_member='no', name='Reg X', email='not-an-email'),
            dict(is_member='yes', member_id='0'),                                       # no member picked
            dict(is_member='no', name=''),                                              # no name
            dict(login='admin', is_member='no', name='Reg X'),                          # taken username
        ]
        for fields in cases:
            response = self._register(**fields)
            self.assertIn('/club/register', response.url, fields)
            self.assertIn('invalid-feedback', response.text, fields)
        self.assertFalse(Users.search([('login', '=', 'reg.player')]))

    def test_odoo_signup_is_off(self):
        self.assertEqual(self.env['res.users']._get_signup_invitation_scope(), 'b2b')
