from odoo.tests import HttpCase, tagged

from .test_club_website import ClubDataMixin


@tagged('post_install', '-at_install')
class TestClubRankingMoves(ClubDataMixin, HttpCase):
    """Rank and figure changes since before the latest session with results."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_club_data()   # 10/01: An & Bình beat Chi & Dũng
        cls.em = cls.env['pickleball.member'].create({'name': 'Web Em'})
        # 17/01: Chi & Dũng win twice, Em plays their first match.
        cls.rematch = cls.env['pickleball.session'].create({
            'date': '2026-01-17',
            'court_id': cls.court.id,
            'booker_id': cls.an.id,
            'participant_ids': [(6, 0, (cls.an | cls.binh | cls.chi | cls.dung | cls.em).ids)],
            'court_fee': 400000,
        })
        Bet = cls.env['pickleball.match.bet']
        for sequence in (1, 2):
            Bet.create({
                'session_id': cls.rematch.id,
                'sequence': sequence,
                'team1_member_ids': [(6, 0, (cls.chi | cls.dung).ids)],
                'team2_member_ids': [(6, 0, (cls.an | cls.binh).ids)],
                'bet_amount': 20000,
                'winner': 'team1',
            })
        Bet.create({
            'session_id': cls.rematch.id,
            'sequence': 3,
            'team1_member_ids': [(6, 0, cls.em.ids)],
            'team2_member_ids': [(6, 0, cls.an.ids)],
            'bet_amount': 10000,
            'winner': 'team2',
        })
        cls.rematch.action_confirm()
        cls.rematch.action_done()
        credentials = cls._grant(cls.an)
        cls.login, cls.password = credentials[cls.an]

    def test_stats_before_session(self):
        before = (self.an | self.chi | self.em)._get_stats_before(self.rematch)
        self.assertEqual((before[self.an.id]['total_matches'], before[self.an.id]['total_wins']), (1, 1))
        self.assertEqual(before[self.an.id]['bet_net_total'], 20000)
        self.assertEqual((before[self.chi.id]['total_matches'], before[self.chi.id]['total_wins']), (1, 0))
        self.assertEqual(before[self.chi.id]['win_rate'], 0.0)
        self.assertEqual(before[self.em.id]['total_matches'], 0)
        # Before the rematch, a member's card is what it was right after 10/01.
        self.assertGreater(before[self.an.id]['card_overall'], before[self.chi.id]['card_overall'])
        self.assertLess(self.an.card_overall, before[self.an.id]['card_overall'])
        self.assertGreater(self.chi.card_overall, before[self.chi.id]['card_overall'])

    def test_ranking_moves(self):
        members = self.an | self.binh | self.chi | self.dung | self.em
        players = members.filtered('total_matches')._sort_for_ranking('wins')
        self.assertEqual(players[:2], self.dung | self.chi)
        session, moves = players._get_ranking_moves('wins')
        self.assertEqual(session, self.rematch)
        self.assertEqual(moves[self.dung.id]['rank'], 2)     # 4th -> 2nd
        self.assertEqual(moves[self.chi.id]['rank'], 2)      # 3rd -> 1st
        self.assertEqual(moves[self.an.id]['rank'], -2)      # 1st -> 3rd
        self.assertIsNone(moves[self.em.id]['rank'])         # first match: newcomer
        self.assertEqual(moves[self.dung.id]['win_rate'], 66.7)
        self.assertEqual(moves[self.dung.id]['bet'], 40000)
        self.assertGreater(moves[self.dung.id]['ovr'], 0)
        self.assertLess(moves[self.binh.id]['ovr'], 0)

    def test_rankings_page_shows_moves(self):
        self.authenticate(self.login, self.password)
        page = self.url_open('/club/rankings').text
        self.assertIn('o_pbw_move_up', page)
        self.assertIn('o_pbw_move_down', page)
        self.assertIn('o_pbw_move_new', page)
        self.assertIn('o_pbw_delta_up', page)
        self.assertIn(f'/club/schedule/{self.rematch.id}', page)
        for by in ('ovr', 'winrate', 'wins', 'bet'):
            self.assertEqual(self.url_open(f'/club/rankings?by={by}').status_code, 200, by)
