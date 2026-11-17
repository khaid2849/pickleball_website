from odoo.tests import HttpCase, tagged

from .test_club_website import ClubDataMixin


@tagged('post_install', '-at_install')
class TestClubCover(ClubDataMixin, HttpCase):
    """Bình pays An's whole bill of a session (pickleball.session.cover):
    An has nothing to pay, Bình's share includes An's."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('pickleball.sepay_auto_settle', 'False')
        cls._create_club_data()
        credentials = cls._grant(cls.an | cls.binh)
        cls.an_login, cls.an_password = credentials[cls.an]
        cls.binh_login, cls.binh_password = credentials[cls.binh]
        cls.cover_session = cls.env['pickleball.session'].create({
            'date': '2026-02-15',
            'court_id': cls.court.id,
            'booker_id': cls.chi.id,
            'court_fee': 300000,
            'participant_ids': [(6, 0, (cls.an | cls.binh | cls.chi).ids)],
            'cover_ids': [(0, 0, {'member_id': cls.an.id, 'payer_id': cls.binh.id})],
        })
        cls.cover_session.action_confirm()
        cls.cover_session.action_done()

    def test_split(self):
        self.assertEqual(self.cover_session.settlement_ids.member_id, self.binh | self.chi)
        binh = self.cover_session.settlement_ids.filtered(lambda s: s.member_id == self.binh)
        self.assertAlmostEqual(binh.amount, -200000)
        self.assertEqual(binh.covered_member_ids, self.an)
        self.assertEqual(self.cover_session._get_cover_payer(self.an), self.binh)

    def test_session_page(self):
        self.authenticate(self.an_login, self.an_password)
        page = self.url_open(f'/club/schedule/{self.cover_session.id}').text
        self.assertEqual(page.count('o_pbw_cover_row'), 1, "An sees who pays his share")
        self.assertEqual(page.count('o_pbw_settlement_row'), 0)
        self.assertIn(self.binh.name, page)

        self.authenticate(self.binh_login, self.binh_password)
        page = self.url_open(f'/club/schedule/{self.cover_session.id}').text
        self.assertEqual(page.count('o_pbw_settlement_row'), 1)
        self.assertEqual(page.count('o_pbw_cover_row'), 0, "members only see their own line")
        self.assertIn('o_pbw_cover_note', page)
        finance = self.url_open('/club/finance').text
        self.assertIn('o_pbw_cover_note', finance)

    def test_chat(self):
        self.authenticate(self.an_login, self.an_password)
        answer = self.make_jsonrpc_request('/club/chat/faq', {'key': 'last_session'})
        self.assertIn(self.binh.name, answer['text'])
        answer = self.make_jsonrpc_request('/club/chat/faq', {'key': 'my_sessions'})
        self.assertIn(self.binh.name, answer['text'])

        self.authenticate(self.binh_login, self.binh_password)
        answer = self.make_jsonrpc_request('/club/chat/faq', {'key': 'last_session'})
        self.assertIn(self.an.name, answer['text'])
        answer = self.make_jsonrpc_request('/club/chat/faq', {'key': 'my_sessions'})
        self.assertIn(self.an.name, answer['text'])
