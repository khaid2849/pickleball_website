import json

from odoo.tests import HttpCase, tagged

from .test_club_website import ClubDataMixin


@tagged('post_install', '-at_install')
class TestClubTournament(ClubDataMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_club_data()
        credentials = cls._grant(cls.an)
        cls.login, cls.password = credentials[cls.an]
        cls.env['res.users'].create({
            'name': 'Web Admin', 'login': 'web.admin', 'password': 'web.admin.pw',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.tournament = cls.env['pickleball.tournament'].create({
            'name': 'Web Spring Cup', 'date_start': '2026-12-05', 'play_type': 'singles',
            'format': 'group_knockout', 'group_size': 2, 'qualifiers_per_group': 1,
            'website_published': True, 'rules': '<p>Web rule: serve underhand</p>',
        })
        cls.env['pickleball.tournament.team'].create([{
            'tournament_id': cls.tournament.id, 'member_ids': [(6, 0, member.ids)], 'seed': index + 1,
        } for index, member in enumerate(cls.an | cls.binh | cls.chi | cls.dung)])
        cls.tournament.action_generate()
        cls.tournament.action_auto_schedule()

    def _pages(self):
        base = f'/club/tournaments/{self.tournament.id}'
        return [base] + [f'{base}?tab={tab}' for tab in ('teams', 'schedule', 'standings', 'bracket')]

    def test_members_only_tournament(self):
        """Visitors don't see a members-only tournament."""
        self.assertNotIn('Web Spring Cup', self.url_open('/club/tournaments').text)
        self.assertEqual(self.url_open(f'/club/tournaments/{self.tournament.id}').status_code, 404)
        self.authenticate(self.login, self.password)
        self.assertIn('Web Spring Cup', self.url_open('/club/tournaments').text)
        for url in self._pages():
            response = self.url_open(url)
            self.assertEqual(response.status_code, 200, url)
        page = self.url_open(self._pages()[0]).text
        self.assertIn('Web rule: serve underhand', page)
        bracket = self.url_open(self._pages()[4]).text
        self.assertEqual(bracket.count('o_pbw_bmatch_tbd'), 2, "final placeholders before the groups are played")

    def test_public_tournament_hides_photos_and_links(self):
        self.tournament.website_visibility = 'public'
        teams = self.url_open(self._pages()[1]).text
        self.assertIn(self.binh.name, teams)
        self.assertNotIn('/club/players/', teams)
        self.assertNotIn('/club/photo/', teams)
        self.tournament.website_published = False
        self.assertEqual(self.url_open(self._pages()[0]).status_code, 404)

    def test_results_show_in_standings_and_bracket(self):
        for match in self.tournament.match_ids.filtered(lambda m: m.stage == 'group'):
            match.score_summary = '11-3'
        final = self.tournament.match_ids.filtered(lambda m: m.round_key == 'final')
        self.assertTrue(final.team1_id and final.team2_id, "group winners reach the final")
        self.authenticate(self.login, self.password)
        standings = self.url_open(self._pages()[3]).text
        self.assertIn('o_pbw_tstand_q', standings)
        bracket = self.url_open(self._pages()[4]).text
        self.assertIn(final.team1_id.name, bracket)
        # The bracket starts with the group stage: groups, their matches and
        # where their winners go.
        self.assertIn('o_pbw_bround_groups', bracket)
        self.assertEqual(bracket.count('o_pbw_bgroup_match '), 2, "one match in each group of 2")
        self.assertEqual(bracket.count('<i class="fa fa-long-arrow-right"></i> #%s' % final.number), 2,
                         "both group winners go to the final")

    def _save(self, matches):
        response = self.url_open(
            f'/club/schedule/{self.play_session.id}/matches',
            data=json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': {'matches': matches}}),
            headers={'Content-Type': 'application/json'},
        ).json()
        self.env.invalidate_all()
        return response

    def test_match_builder_admin_only(self):
        self.authenticate(self.login, self.password)
        page = self.url_open(f'/club/schedule/{self.play_session.id}').text
        self.assertNotIn('session_match_builder', page)
        result = self._save([])
        self.assertIn('error', result)
        self.assertTrue(self.play_session.match_bet_ids, "a member can't delete the matches")

    def test_match_builder_saves_matches(self):
        """The play session is done (already split): the builder still saves,
        and reminds to recalculate the settlements."""
        self.authenticate('web.admin', 'web.admin.pw')
        page = self.url_open(f'/club/schedule/{self.play_session.id}').text
        self.assertIn('pickleball_website.session_match_builder', page)
        existing = self.play_session.match_bet_ids
        result = self._save([
            {'id': existing.id, 'team1': [self.an.id], 'team2': [self.chi.id], 'bet': 10000, 'winner': 'team2'},
            {'team1': [self.binh.id, self.dung.id], 'team2': [self.an.id, self.chi.id], 'bet': 0, 'winner': ''},
        ])['result']
        self.assertTrue(result['needsRecalc'])
        bets = self.play_session.match_bet_ids.sorted('sequence')
        self.assertEqual(len(bets), 2)
        self.assertEqual(bets[0], existing)
        self.assertEqual(bets[0].team1_member_ids, self.an)
        self.assertEqual(bets[0].winner, 'team2')
        self.assertEqual(bets[1].bet_amount, 0, "friendly match without a bet")
        # A player who isn't in the session is refused, and nothing changes.
        stranger = self.env['pickleball.member'].create({'name': 'Web Outsider'})
        error = self._save([{'team1': [stranger.id], 'team2': [self.an.id], 'bet': 0}])
        self.assertIn('error', error)
        self.assertEqual(len(self.play_session.match_bet_ids), 2)
        # Settled sessions are locked.
        self.play_session.action_settle()
        self.assertIn('error', self._save([]))
        self.assertEqual(len(self.play_session.match_bet_ids), 2)
