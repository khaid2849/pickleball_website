from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged

from ..models.pickleball_ai_commands import LINK_CHANNELS_PARAM
from ..models.pickleball_member import TelegramClient
from .test_club_website import ClubDataMixin


@tagged('post_install', '-at_install')
class TestBotWebsiteLink(ClubDataMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_club_data()
        cls._grant(cls.an)
        cls.Commands = cls.env['pickleball.ai.commands']
        cls.env['ir.config_parameter'].set_param(LINK_CHANNELS_PARAM, 'telegram')
        cls.home = cls.Commands._club_home_url()

    def _reply(self, text, member=None, channel='telegram', **kwargs):
        return self.Commands.run_command(text, member=member, channel=channel, **kwargs)[0]

    def test_links_to_the_home_page(self):
        """Every command with a link points to the home page of the website."""
        self.assertTrue(self.home.endswith('/'))
        self.assertNotIn('/club', self.home)
        for text in ('/balance', '/qr', '/unpaid', '/history', '/ranking', '/members', '/member',
                     f'/member {self.binh.id}', '/session 10/01/2026', '/summary', '/help',
                     '/nosuchcommand'):  # answered with /help
            reply = self._reply(text, member=self.an)
            last_line = reply.splitlines()[-1]
            self.assertTrue(last_line.startswith('🌐 '), (text, reply))
            self.assertTrue(last_line.endswith(f': {self.home}'), (text, last_line))

    def test_sign_up_hint_without_account(self):
        for member in (self.binh, None):
            last_line = self._reply('/ranking', member=member).splitlines()[-1]
            self.assertIn('tạo tài khoản', last_line)
            self.assertTrue(last_line.endswith(self.home))

    def test_only_enabled_bots(self):
        self.assertNotIn('🌐', self._reply('/ranking', member=self.an, channel='zalo'))
        self.assertNotIn('🌐', self._reply('/ranking', member=self.an, channel=None))
        self.env['ir.config_parameter'].set_param(LINK_CHANNELS_PARAM, 'telegram, zalo')
        self.assertIn('🌐', self._reply('/ranking', member=self.an, channel='zalo'))

    def test_no_link_on_manager_commands(self):
        self.an.is_bot_manager = True
        self.assertNotIn('🌐', self._reply('/paid', member=self.an, is_private=True))

    def test_telegram_reply_has_the_link(self):
        config = self.env['pickleball.ai.telegram.config'].create({
            'name': 'Link Bot', 'bot_token': '1:link', 'is_active': True})
        self.an.is_bot_manager = True
        client = MagicMock()
        config._handle_private_message(config, client, '111', '/ranking', self.an, {})
        text = client.send_message.call_args.args[1]
        self.assertIn(self.home, text)


@tagged('post_install', '-at_install')
class TestDebtReminderWebsiteLink(ClubDataMixin, TransactionCase):
    """The daily debt reminder ends with the link to the club website."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_club_data()   # 10/01 session closed: everyone owes their share
        cls.env['ir.config_parameter'].set_param(LINK_CHANNELS_PARAM, 'telegram')
        cls.env['pickleball.ai.telegram.config'].create({
            'name': 'Reminder Bot', 'bot_token': '1:remind', 'is_active': True,
            'group_chat_id': '-100', 'debt_reminder_enabled': True})
        cls.home = cls.env['pickleball.ai.commands']._club_home_url()

    def _send(self):
        with patch.object(TelegramClient, 'send_message', autospec=True, return_value=True) as send, \
                patch.object(TelegramClient, 'send_photo', autospec=True, return_value=True) as photo:
            self.env['pickleball.settlement']._cron_send_debt_reminder()
        calls = send.call_args_list + photo.call_args_list
        self.assertEqual(len(calls), 1)
        call = calls[0]
        return call.kwargs.get('caption') or call.args[2]

    def test_reminder_links_to_the_website(self):
        text = self._send()
        self.assertTrue(text.startswith('💸 Nhắc đóng tiền'), text)
        last_line = text.splitlines()[-1]
        self.assertTrue(last_line.startswith('🌐 Xem chi tiết công nợ của bạn'), last_line)
        self.assertIn('tạo ngay ở trang chủ', last_line)
        self.assertTrue(last_line.endswith(f': {self.home}'), last_line)

    def test_no_link_when_disabled_for_the_bot(self):
        self.env['ir.config_parameter'].set_param(LINK_CHANNELS_PARAM, 'zalo')
        self.assertNotIn('🌐', self._send())
