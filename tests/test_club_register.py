import re
from unittest.mock import patch

from odoo.addons.mail.tests.common import MailCase
from odoo.tests import HttpCase, tagged

from ..models.pickleball_member import TelegramClient


@tagged('post_install', '-at_install')
class TestClubRegister(MailCase, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.member = cls.env['pickleball.member'].create({'name': 'Reg Existing Player'})
        cls.manager = cls.env['pickleball.member'].create({
            'name': 'Reg Captain', 'is_bot_manager': True, 'telegram_chat_id': '987654321'})
        cls.env['pickleball.ai.telegram.config'].create({
            'name': 'Reg Bot', 'bot_token': '123:reg-token', 'is_active': True})

    def setUp(self):
        super().setUp()
        # Never call Telegram for real.
        self.telegram_send = self.startPatcher(
            patch.object(TelegramClient, 'send_message', autospec=True, return_value=False))

    def _register_notified(self, **fields):
        """Sign up; returns the response and the Telegram messages sent, by chat id."""
        self.telegram_send.reset_mock()
        self.telegram_send.return_value = True
        response = self._register(**fields)
        return response, {str(call.args[1]): call.args[2] for call in self.telegram_send.call_args_list}

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
        response, messages = self._register_notified(is_member='no', name='Reg New Player')
        self.assertIn('/club/pending', response.url)
        self.assertFalse(messages, 'new players confirm by email: no approval to ask for')
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
        response, messages = self._register_notified(is_member='yes', member_id=str(self.member.id))
        self.assertIn('/club/pending', response.url)
        self.assertEqual(self.member.website_state, 'pending_approval')
        # The bot managers get a Telegram DM to approve it.
        notice = messages.get('987654321')
        self.assertTrue(notice, 'the bot manager is notified')
        for text in ('reg.player', 'Reg Existing Player', 'reg.player@example.com', '0901 234 567',
                     f'/mail/view?model=pickleball.member&res_id={self.member.id}'):
            self.assertIn(text, notice)
        log = self.env['pickleball.bot.message.log'].search(
            [('chat_id', '=', '987654321'), ('source', '=', 'website')])
        self.assertEqual(log.state, 'sent')
        self.assertEqual(self.member.user_id.login, 'reg.player')
        # Nothing is copied onto the member before approval.
        self.assertFalse(self.member.email)
        self.assertIn('/club/pending', self.url_open('/club/finance').url)
        # Already claimed: not offered to anyone else.
        self.authenticate(None, None)
        self.assertNotIn(f'value="{self.member.id}"', self.url_open('/club/register').text)

        group = self.env.ref('pickleball_website.group_club_member')
        self.assertNotIn(group, self.member.user_id.groups_id, 'no members menus before approval')
        self.telegram_send.reset_mock()
        with self.mock_mail_gateway():
            self.assertTrue(self.member.action_website_approve())
        self.telegram_send.assert_not_called()
        self.assertEqual(self.member.website_state, 'approved')
        self.assertIn(group, self.member.user_id.groups_id)
        # The member is emailed that their account is open (no Telegram to them).
        self.assertEqual(len(self._mails), 1)
        mail = self._mails[0]
        self.assertEqual(mail['email_to'], ['reg.player@example.com'])
        self.assertIn('approved', mail['subject'])
        self.assertIn('reg.player', mail['body'])
        self.assertIn('/web/login?redirect=/club/me', mail['body'])
        # Approving again doesn't email again.
        with self.mock_mail_gateway():
            self.member.action_website_approve()
        self.assertFalse(self._mails)
        self.assertEqual(self.member.email, 'reg.player@example.com')
        self.assertEqual(self.member.phone, '0901 234 567')
        self.authenticate('reg.player', 'reg-password')
        self.assertEqual(self.url_open('/club/finance').status_code, 200)

    def test_approve_warns_when_email_fails(self):
        self._register(is_member='yes', member_id=str(self.member.id))
        with patch.object(type(self.member), '_website_send_mail', return_value=False):
            action = self.member.action_website_approve()
        self.assertEqual(self.member.website_state, 'approved', 'approved even if the email failed')
        self.assertEqual(action['tag'], 'display_notification')
        self.assertIn(self.member.name, action['params']['message'])

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
