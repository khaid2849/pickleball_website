from odoo.tests import HttpCase, tagged

from .test_club_website import ClubDataMixin


@tagged('post_install', '-at_install')
class TestClubPairRankings(ClubDataMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_club_data()   # An & Bình beat Chi & Dũng
        credentials = cls._grant(cls.an)
        cls.login, cls.password = credentials[cls.an]

    def test_pairs_page(self):
        self.authenticate(self.login, self.password)
        page = self.url_open('/club/rankings?kind=pairs').text
        self.assertIn('o_pbw_pair_cell', page)
        self.assertEqual(page.count('o_pbw_pair_cell'), 2)
        self.assertLess(page.index(self.binh.name), page.index(self.chi.name), 'the winning pair first')
        for by in ('rating', 'winrate', 'wins', 'matches', 'bet', 'nonsense'):
            self.assertEqual(self.url_open(f'/club/rankings?kind=pairs&by={by}').status_code, 200, by)
        players = self.url_open('/club/rankings').text
        self.assertNotIn('o_pbw_pair_cell', players)
        self.assertIn('?kind=pairs', players)

    def test_pairs_need_login(self):
        self.assertIn('/web/login', self.url_open('/club/rankings?kind=pairs').url)
