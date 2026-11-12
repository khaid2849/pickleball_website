from odoo.tests import HttpCase, tagged

from .test_club_website import ClubDataMixin


@tagged('post_install', '-at_install')
class TestClubGamification(ClubDataMixin, HttpCase):
    """Gamification pages and API of the members area (money filtered on
    the server, owner-only endpoints)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_club_data()
        credentials = cls._grant(cls.an | cls.binh)
        cls.an_login, cls.an_password = credentials[cls.an]
        cls.binh_login, cls.binh_password = credentials[cls.binh]
        # An owes the team; Binh owes nothing.
        cls.env['pickleball.settlement'].search([('member_id', 'in', (cls.an | cls.binh).ids)]).write(
            {'is_paid': True})
        cls.env['pickleball.settlement'].create({
            'session_id': cls.play_session.id, 'member_id': cls.an.id, 'amount': -75000})

    def test_card_api_filters_money(self):
        self.authenticate(self.binh_login, self.binh_password)
        card = self.url_open(f'/club/api/members/{self.an.id}/card').json()
        self.assertIsNone(card['finance'], "another member never gets An's debt")
        self.assertNotIn('75', str(card.get('finance')))
        own = self.url_open(f'/club/api/members/{self.binh.id}/card').json()
        self.assertEqual(own['finance']['state'], 'paid')
        self.an.show_finance_publicly = True
        card = self.url_open(f'/club/api/members/{self.an.id}/card').json()
        self.assertEqual(card['finance']['state'], 'owes')

    def test_owner_only_endpoints(self):
        self.authenticate(self.binh_login, self.binh_password)
        self.assertEqual(self.url_open(f'/club/api/members/{self.an.id}/progress').status_code, 403)
        self.assertEqual(self.url_open(f'/club/api/members/{self.an.id}/card/share.png').status_code, 403)
        progress = self.url_open(f'/club/api/members/{self.binh.id}/progress').json()
        self.assertIn('code', progress)
        self.assertEqual(self.url_open('/club/api/me/challenges').status_code, 200)
        self.assertIsInstance(self.url_open('/club/api/me/reveals').json(), list)

    def test_pages_render(self):
        self.authenticate(self.an_login, self.an_password)
        for path in ('/club/me', f'/club/players/{self.binh.id}', f'/club/players/{self.an.id}/album',
                     '/club/me/showcase', '/club/season', '/club/players'):
            response = self.url_open(path)
            self.assertEqual(response.status_code, 200, path)
        album = self.url_open(f'/club/players/{self.an.id}/album').text
        self.assertIn('o_pbw_album_grid', album)
        # the card of An as seen by Binh shows no money row at all
        self.authenticate(self.binh_login, self.binh_password)
        page = self.url_open(f'/club/players/{self.an.id}').text
        self.assertNotIn('o_pb_card_debt_owes', page)

    def test_public_cannot_use_api(self):
        response = self.url_open(f'/club/api/members/{self.an.id}/card', allow_redirects=False)
        self.assertNotEqual(response.status_code, 200, "redirected to the login page")
        self.assertNotIn('finance', response.text)
