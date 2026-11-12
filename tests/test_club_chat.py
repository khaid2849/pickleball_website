import importlib
import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, tagged
from odoo.tests.common import JsonRpcException

from ..models.pickleball_ai_tools import WEBSITE_MEMBER_CONTEXT_KEY, WEBSITE_RESTRICTED_CONTEXT_KEY
from .test_club_website import ClubDataMixin

# The module's technical name has a dash: no regular import.
_adapter_base = importlib.import_module('odoo.addons.pickleball-team.services.ai_adapter_base')
AIAdapterResponse = _adapter_base.AIAdapterResponse
AIToolCall = _adapter_base.AIToolCall


class FakeAdapter:
    """Scripted LLM: calls the given tools first, then answers. Records the
    tools it was offered and the tool results it got back."""

    def __init__(self, tool_calls=(), answer='Fake answer'):
        self.tool_calls = list(tool_calls)
        self.answer = answer
        self.offered = []
        self.results = {}

    def chat(self, messages, tools=None):
        self.offered = [spec['function']['name'] for spec in tools or []]
        for message in messages:
            if message['role'] == 'tool':
                self.results[message['name']] = json.loads(message['content'])
        if self.tool_calls:
            name, arguments = self.tool_calls.pop(0)
            return AIAdapterResponse(tool_calls=[AIToolCall(id=f'call_{name}', name=name, arguments=arguments)])
        return AIAdapterResponse(content=self.answer)


@tagged('post_install', '-at_install')
class TestClubChat(ClubDataMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_club_data()
        credentials = cls._grant(cls.an | cls.binh)
        cls.an_login, cls.an_password = credentials[cls.an]
        cls.binh_login, cls.binh_password = credentials[cls.binh]
        cls.chat_admin = cls.env['res.users'].create({
            'name': 'Chat Admin', 'login': 'chat_admin', 'password': 'chat_admin_pw',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.env.company.pickleball_chat_admin_ids = cls.chat_admin
        Provider = cls.env['pickleball.ai.provider']
        Provider.search([('is_active', '=', True)]).write({'is_active': False})
        cls.provider = Provider.create({'name': 'Fake', 'model': 'fake', 'is_active': True})
        cls.next_session = cls.env['pickleball.session'].create({
            'date': fields.Date.today() + timedelta(days=3),
            'time_start': 19.0, 'time_end': 21.0,
            'court_id': cls.court.id,
            'booker_id': cls.an.id,
            'participant_ids': [(6, 0, (cls.an | cls.chi).ids)],
        })

    def _rpc(self, route, **params):
        return self.make_jsonrpc_request(route, params)

    def _fake_ai(self, adapter):
        return patch.object(type(self.provider), 'get_adapter', return_value=adapter)

    # ── Bubble on the pages ─────────────────────────────────────────────────

    def test_bubble_only_for_logged_in_members(self):
        self.assertNotIn('pickleball_website.club_chat', self.url_open('/club').text)
        self.authenticate(self.an_login, self.an_password)
        self.assertIn('pickleball_website.club_chat', self.url_open('/club/me').text)
        self.authenticate('chat_admin', 'chat_admin_pw')
        self.assertIn('pickleball_website.club_chat', self.url_open('/club/players').text)

    def test_portal_user_without_member_is_refused(self):
        portal = self.env['res.users'].create({
            'name': 'Chat Stranger', 'login': 'chat_stranger', 'password': 'chat_stranger_pw',
            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.assertFalse(portal._pickleball_website_chat_enabled())
        self.authenticate('chat_stranger', 'chat_stranger_pw')
        with self.assertRaises(JsonRpcException):
            self._rpc('/club/chat/init')

    # ── Frequently asked questions ──────────────────────────────────────────

    def test_init_lists_questions_and_admins(self):
        self.authenticate(self.an_login, self.an_password)
        info = self._rpc('/club/chat/init')
        self.assertEqual(info['faqs'][0]['key'], 'next_session')
        self.assertTrue(info['admin_chat'])
        self.assertEqual(info['admin_names'], ['Chat Admin'])
        self.assertTrue(info['ai_enabled'])

    def test_faq_next_session(self):
        self.authenticate(self.binh_login, self.binh_password)
        answer = self._rpc('/club/chat/faq', key='next_session')
        self.assertIn('Web Court', answer['text'])
        self.assertIn('19:00', answer['text'])
        self.assertIn(f'/club/schedule/{self.next_session.id}', [a['url'] for a in answer['actions']])

    def test_faq_my_debt_shows_only_my_money(self):
        debt = self.binh._get_outstanding_debt()
        self.assertGreater(debt, 0)
        self.authenticate(self.binh_login, self.binh_password)
        answer = self._rpc('/club/chat/faq', key='my_debt')
        self.assertIn(f'{round(debt):,}'.replace(',', '.'), answer['text'])
        for other in (self.an, self.chi, self.dung):
            self.assertNotIn(other.name, answer['text'])
        self.assertEqual(answer['actions'][0]['url'], '/club/finance')

    def test_every_faq_answers(self):
        self.authenticate(self.an_login, self.an_password)
        for faq in self._rpc('/club/chat/init')['faqs']:
            answer = self._rpc('/club/chat/faq', key=faq['key'])
            self.assertTrue(answer['text'], faq['key'])
        unknown = self._rpc('/club/chat/faq', key='_private')
        self.assertTrue(unknown['text'])
        self.assertEqual(unknown['actions'], [], 'no private method is called')

    def test_faq_for_admin_without_member(self):
        self.authenticate('chat_admin', 'chat_admin_pw')
        self.assertFalse(self._rpc('/club/chat/init')['admin_chat'])
        self.assertTrue(self._rpc('/club/chat/faq', key='my_debt')['text'])
        self.assertTrue(self._rpc('/club/chat/admin/messages')['disabled'])

    # ── AI assistant ────────────────────────────────────────────────────────

    def test_ai_member_tools_are_read_only_and_private(self):
        adapter = FakeAdapter(tool_calls=[
            ('get_my_payments', {}),
            ('create_draft_session', {'court_name': 'Web Court', 'date': '2026-12-01', 'time_start': '19:00',
                                      'time_end': '21:00', 'booker_name': 'Web Trần Bình'}),
        ])
        self.authenticate(self.binh_login, self.binh_password)
        with self._fake_ai(adapter):
            result = self._rpc('/club/chat/ask', message='Tôi nợ bao nhiêu?')
        self.assertEqual(result['text'], 'Fake answer')
        self.assertIn('get_my_profile', adapter.offered)
        for hidden in ('list_unpaid_settlements', 'get_session_details', 'create_draft_session', 'update_session'):
            self.assertNotIn(hidden, adapter.offered)
        self.assertEqual(adapter.results['get_my_payments']['owes_team_vnd'], round(self.binh._get_outstanding_debt()))
        self.assertEqual(adapter.results['create_draft_session']['error'], 'permission_denied')
        self.assertFalse(self.env['pickleball.session'].search([('date', '=', '2026-12-01')]))

        conversation = self.env['pickleball.ai.conversation'].browse(result['conversation_id'])
        self.assertEqual((conversation.source, conversation.user_id), ('website', self.binh.user_id))
        history = self._rpc('/club/chat/ai_history', conversation_id=conversation.id)['messages']
        self.assertEqual([m['role'] for m in history], ['user', 'assistant'])

        # Another member can't read or continue that conversation.
        self.authenticate(self.an_login, self.an_password)
        self.assertFalse(self._rpc('/club/chat/ai_history', conversation_id=conversation.id)['messages'])
        with self._fake_ai(FakeAdapter()):
            other = self._rpc('/club/chat/ask', message='hi', conversation_id=conversation.id)
        self.assertNotEqual(other['conversation_id'], conversation.id)

    def test_ai_admin_keeps_every_tool(self):
        adapter = FakeAdapter()
        self.authenticate('chat_admin', 'chat_admin_pw')
        with self._fake_ai(adapter):
            self._rpc('/club/chat/ask', message='Ai chưa đóng tiền?')
        self.assertIn('list_unpaid_settlements', adapter.offered)
        self.assertNotIn('get_my_profile', adapter.offered, 'no member profile for this admin')

    def test_ai_tool_specs_context(self):
        Tools = self.env['pickleball.ai.tools']
        restricted = Tools.with_context(**{WEBSITE_MEMBER_CONTEXT_KEY: self.an.id,
                                           WEBSITE_RESTRICTED_CONTEXT_KEY: True})
        names = {spec['function']['name'] for spec in restricted._tool_specs()}
        self.assertIn('get_my_payments', names)
        self.assertNotIn('list_unpaid_settlements', names)
        self.assertNotIn('get_my_payments', {spec['function']['name'] for spec in Tools._tool_specs()},
                         'the bots and the backend widget keep their tools')
        profile = restricted.execute('get_my_profile', {})
        self.assertEqual(profile['name'], self.an.name)

    def test_ai_hourly_limit(self):
        self.env['ir.config_parameter'].set_param('pickleball_website.chat_ai_hourly_limit', '1')
        self.authenticate(self.an_login, self.an_password)
        with self._fake_ai(FakeAdapter()):
            self.assertIn('text', self._rpc('/club/chat/ask', message='one'))
            self.assertIn('error', self._rpc('/club/chat/ask', message='two'))

    def test_ai_not_configured(self):
        self.provider.is_active = False
        self.authenticate(self.an_login, self.an_password)
        self.assertFalse(self._rpc('/club/chat/init')['ai_enabled'])
        self.assertIn('error', self._rpc('/club/chat/ask', message='hello'))

    # ── Talk to an admin ────────────────────────────────────────────────────

    def test_talk_to_admin(self):
        self.authenticate(self.an_login, self.an_password)
        self.assertEqual(self._rpc('/club/chat/admin/messages')['messages'], [])
        sent = self._rpc('/club/chat/admin/send', text='Cho em <b>đăng ký</b> buổi tới')['message']
        self.assertTrue(sent['mine'])
        self.assertEqual(sent['text'], 'Cho em <b>đăng ký</b> buổi tới', 'members send text, not HTML')

        channel = self.an.website_chat_channel_id
        self.assertEqual(channel.channel_type, 'group')
        self.assertEqual(channel.channel_member_ids.partner_id,
                         self.an.user_id.partner_id | self.chat_admin.partner_id)
        message = channel.message_ids.filtered(lambda m: m.message_type == 'comment')
        self.assertEqual(message.author_id, self.an.user_id.partner_id)

        # The admin answers from Discuss.
        channel.with_user(self.chat_admin).message_post(
            body='OK, đã thêm bạn', message_type='comment', subtype_xmlid='mail.mt_comment')
        new = self._rpc('/club/chat/admin/messages', after_id=sent['id'])['messages']
        self.assertEqual([(m['text'], m['mine'], m['author']) for m in new],
                         [('OK, đã thêm bạn', False, 'Chat Admin')])

        # Another member never sees it.
        self.authenticate(self.binh_login, self.binh_password)
        self.assertEqual(self._rpc('/club/chat/admin/messages')['messages'], [])

    def test_admins_added_later_join_the_conversation(self):
        self.an._website_chat_post('Hello')
        channel = self.an.website_chat_channel_id
        other_admin = self.env['res.users'].create({
            'name': 'Chat Admin 2', 'login': 'chat_admin_2',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        self.env.company.pickleball_chat_admin_ids |= other_admin
        self.an._website_chat_post('Still there?')
        self.assertIn(other_admin.partner_id, channel.channel_member_ids.partner_id)
        self.assertEqual(self.an.website_chat_channel_id, channel, 'one conversation per member')

    def test_admin_chat_flood_and_empty(self):
        self.authenticate(self.an_login, self.an_password)
        self.assertIn('error', self._rpc('/club/chat/admin/send', text='   '))
        with patch('odoo.addons.pickleball_website.models.pickleball_member_chat.CHAT_FLOOD_LIMIT', 2):
            self._rpc('/club/chat/admin/send', text='1')
            self._rpc('/club/chat/admin/send', text='2')
            self.assertIn('error', self._rpc('/club/chat/admin/send', text='3'))

    def test_default_chat_admins_are_settings_admins(self):
        self.env.company.pickleball_chat_admin_ids = False
        admins = self.env.company._get_pickleball_chat_admins()
        self.assertIn(self.env.ref('base.user_admin'), admins)
        self.assertNotIn(self.chat_admin, admins)
