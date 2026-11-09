"""Tournament pages of the club website: information only (introduction,
rules, teams, schedule, standings, bracket). Tournaments are managed in the
backend (Pickleball > Tournaments) and shown when "Show on Website" is on:
to club members, or to everyone when their visibility is "Everyone".

The labels shown here (rounds, placeholders such as "Winner of match 12")
are built from the tournament structure in this module, so they are
translated with the website (i18n/vi.po)."""
from werkzeug.exceptions import NotFound

from odoo import _, http
from odoo.http import request
from odoo.tools.translate import LazyTranslate

from .club import PickleballClub, labels

_lt = LazyTranslate(__name__)

TOURNAMENT_STATES = {
    'draft': _lt('Coming soon'),
    'open': _lt('Registration open'),
    'ongoing': _lt('Ongoing'),
    'done': _lt('Finished'),
}
FORMATS = {
    'group_knockout': _lt('Group stage + knockout'),
    'round_robin': _lt('Round robin'),
    'knockout': _lt('Single elimination'),
}
PLAY_TYPES = {'singles': _lt('Singles'), 'doubles': _lt('Doubles')}
ROUNDS = {
    'final': _lt('Final'),
    'semi': _lt('Semi-finals'),
    'quarter': _lt('Quarter-finals'),
    'third': _lt('3rd place match'),
}
BEST_OF = {1: _lt('1 game'), 3: _lt('Best of 3'), 5: _lt('Best of 5')}
GROUP_RANKS = {1: _lt('Winner of %s'), 2: _lt('Runner-up of %s'), 3: _lt('3rd of %s')}
RANK_SHORT = {1: _lt('1st'), 2: _lt('2nd'), 3: _lt('3rd')}
TIEBREAKS = {
    'head_to_head': _lt('head-to-head'),
    'point_diff': _lt('point difference'),
    'points_for': _lt('points scored'),
    'game_diff': _lt('game difference'),
    'wins': _lt('wins'),
    'seed': _lt('seed'),
}
TABS = [
    ('overview', _lt('Overview'), 'fa-info-circle'),
    ('teams', _lt('Teams'), 'fa-users'),
    ('schedule', _lt('Schedule'), 'fa-calendar'),
    ('standings', _lt('Standings'), 'fa-list-ol'),
    ('bracket', _lt('Bracket'), 'fa-sitemap'),
]


class ClubTournament(PickleballClub):

    @property
    def _Tournament(self):
        return request.env['pickleball.tournament'].sudo()

    def _tournament_domain(self):
        domain = [('website_published', '=', True), ('state', '!=', 'cancel')]
        if not (self._is_admin() or self._me()):
            domain.append(('website_visibility', '=', 'public'))
        return domain

    def _get_tournament(self, tournament_id):
        tournament = self._Tournament.search([('id', '=', tournament_id)] + self._tournament_domain())
        if not tournament:
            raise NotFound()
        return tournament

    def _tournament_values(self, **values):
        is_member = self._is_admin() or bool(self._me())
        values = self._values('tournaments', **values)
        values.update(
            tournament_states=labels(TOURNAMENT_STATES),
            tournament_formats=labels(FORMATS),
            play_types=labels(PLAY_TYPES),
            # Visitors see names only: no photo, no link to the members' area.
            shows_members=is_member,
        )
        if not is_member:
            values['photo_url'] = lambda member: ''
        return values

    # ── Labels ──────────────────────────────────────────────────────────────

    @staticmethod
    def _group_name(group):
        if group.name and group.name != f'Group {group.code}':
            return group.name  # renamed by hand
        return _('Group %s', group.code)

    @staticmethod
    def _round_name(match):
        if match.stage == 'knockout':
            key = match.round_key or ''
            if key in ROUNDS:
                return str(ROUNDS[key])
            return _('Round of %s', key[1:]) if key[1:].isdigit() else key
        return _('Round %s', match.round_number)

    def _source_label(self, tournament, source):
        kind, _sep, rest = (source or '').partition(':')
        if kind == 'group':
            group_id, rank = (int(x) for x in rest.split(':'))
            group = tournament.group_ids.filtered(lambda g: g.id == group_id)
            name = self._group_name(group)
            return str(GROUP_RANKS[rank]) % name if rank in GROUP_RANKS else _('#%(rank)s of %(group)s',
                                                                               rank=rank, group=name)
        if kind == 'wildcard':
            return _('Best next-placed #%s', rest)
        if kind == 'league':
            return _('#%s of the league', rest)
        return ''

    def _slot_label(self, match, side):
        """Team name, or where the team will come from."""
        team = match[f'{side}_id']
        if team:
            return team.name
        source = match[f'{side}_source']
        if source:
            return self._source_label(match.tournament_id, source)
        if match.stage == 'knockout' and match.round_number == 1 and match.round_key != 'third' and match.is_bye:
            return _('Bye')
        feeder, kind = match._feeder(side)
        if feeder:
            if feeder.is_bye:
                other = 'team1' if feeder.team1_source or feeder.team1_id else 'team2'
                return self._slot_label(feeder, other)
            if kind == 'loser':
                return _('Loser of match %s', feeder.number)
            return _('Winner of match %s', feeder.number)
        return _('To be decided')

    def _match_view(self, match):
        """A match as a dict for the templates."""
        games = match.game_ids.sorted('sequence')
        return {
            'match': match,
            'number': match.number,
            'round': self._round_name(match),
            'group': self._group_name(match.group_id) if match.group_id else '',
            'team1': match.team1_id, 'team2': match.team2_id,
            'label1': self._slot_label(match, 'team1'), 'label2': self._slot_label(match, 'team2'),
            'games': [(g.team1_score, g.team2_score) for g in games],
            'games1': match.team1_games, 'games2': match.team2_games,
            'winner': match.winner_side,
            'walkover': match.walkover_winner,
            'state': match.state,
            'date': match.match_date, 'time': match.match_time, 'court': match.court_name,
        }

    def _summary_lines(self, tournament):
        """How the tournament is played, in sentences (the backend twin is
        pickleball.tournament._format_summary_lines)."""
        info = tournament._get_structure()
        if info['teams'] < 2:
            return [_("The teams are not known yet.")]
        lines = []
        legs = tournament.round_robin_legs
        legs_text = _(" (%s legs)", legs) if legs > 1 else ''
        if tournament.format == 'group_knockout':
            sizes = info['groups']
            lines.append(_("%(teams)s teams are drawn into %(groups)s groups of %(sizes)s; every team plays every "
                           "other team of its group%(legs)s.", teams=info['teams'], groups=len(sizes),
                           sizes='/'.join(map(str, sorted(set(sizes)))), legs=legs_text))
            if tournament.wildcard_count:
                lines.append(_("The top %(top)s of each group and the %(wild)s best next-placed teams go "
                               "through to the knockout stage.", top=tournament.qualifiers_per_group,
                               wild=tournament.wildcard_count))
            else:
                lines.append(_("The top %s of each group go through to the knockout stage.",
                               tournament.qualifiers_per_group))
        elif tournament.format == 'round_robin':
            lines.append(_("%(teams)s teams, every team plays every other team%(legs)s.",
                           teams=info['teams'], legs=legs_text))
            if info['knockout_teams']:
                lines.append(_("The top %s of the table play the playoffs.", info['knockout_teams']))
            else:
                lines.append(_("No playoffs: the top of the table is champion."))
        else:
            lines.append(_("%s teams, single elimination: lose once and you're out.", info['teams']))
        if info['rounds']:
            rounds = ' → '.join(str(ROUNDS[key]) if key in ROUNDS else _('Round of %s', key[1:])
                                for key in info['rounds'])
            if tournament.third_place_match and info['bracket'] >= 4:
                rounds += ' (+ %s)' % ROUNDS['third']
            lines.append(_("Knockout: %s.", rounds))
            if info['byes']:
                lines.append(_("%s top-seeded teams get a bye in the first round.", info['byes']))
        if tournament.format != 'knockout':
            points = _("Standings: %(win)s points per win, %(loss)s per loss", win=tournament.points_win,
                       loss=tournament.points_loss)
            tiebreaks = [str(TIEBREAKS[tb]) for tb in tournament._tiebreaks() if tb in TIEBREAKS]
            if tiebreaks:
                points += _("; ties broken by %s", ', '.join(tiebreaks))
            lines.append(points + '.')
        total = info['group_matches'] + info['league_matches'] + info['knockout_matches']
        lines.append(_("%s matches in total.", total))
        return lines

    def _first_stage_column(self, tournament):
        """First column of the bracket: every group (or the league) with its
        table, its matches and where its qualifiers go in the knockout
        stage, so the bracket shows the whole way from the first match to
        the final."""
        # Knockout slot source ('group:<id>:<rank>', 'league:<rank>',
        # 'wildcard:<n>') -> number of the match that team plays first.
        destination = {}
        first_round = tournament._knockout_matches().filtered(
            lambda m: m.round_number == 1 and m.round_key != 'third')
        for match in first_round:
            target = match.next_match_id if match.is_bye else match
            for side in ('team1', 'team2'):
                if match[f'{side}_source']:
                    destination[match[f'{side}_source']] = target.number
        if not destination:
            return {'first_stage': []}
        blocks = []
        for table in tournament._get_standings_tables():
            group = table['group']
            if group:
                matches, prefix = group.match_ids, f'group:{group.id}:'
                title = self._group_name(group)
            else:
                matches, prefix = tournament.match_ids.filtered(lambda m: m.stage == 'league'), 'league:'
                title = _('League table')
            exits = [(str(RANK_SHORT[rank]) if rank in RANK_SHORT else _('#%s', rank), destination[prefix + str(rank)])
                     for rank in range(1, len(table['rows']) + 1) if prefix + str(rank) in destination]
            blocks.append({
                'title': title,
                'rows': table['rows'],
                'played': any(m.state == 'done' for m in matches),
                'matches': [self._match_view(m) for m in matches.sorted(lambda m: (m.round_number, m.number))],
                'exits': exits,
            })
        wildcards = [(_('Best next-placed #%s', source.split(':')[1]), number)
                     for source, number in sorted(destination.items()) if source.startswith('wildcard:')]
        return {
            'first_stage': blocks,
            'first_stage_name': _('Group stage') if tournament.format == 'group_knockout' else _('League'),
            'wildcard_exits': wildcards,
        }

    def _match_format(self, tournament):
        rows = []
        game = _("Games to %(points)s, win by %(win_by)s",
                 points=tournament.game_points, win_by=tournament.win_by)
        if tournament.format != 'knockout':
            label = _('Group matches') if tournament.format == 'group_knockout' else _('League matches')
            rows.append((label, str(BEST_OF.get(int(tournament.best_of), ''))))
        if tournament._knockout_matches() or tournament._get_structure()['rounds']:
            rows.append((_('Knockout matches'), str(BEST_OF.get(int(tournament.knockout_best_of), ''))))
            rows.append((_('Final'), str(BEST_OF.get(int(tournament.final_best_of), ''))))
        return game, rows

    # ── Pages ───────────────────────────────────────────────────────────────

    @http.route('/club/tournaments', type='http', auth='public', website=True, sitemap=False)
    def club_tournaments(self, **kwargs):
        tournaments = self._Tournament.search(self._tournament_domain(), order='date_start desc, id desc')
        values = self._tournament_values(
            ongoing=tournaments.filtered(lambda t: t.state == 'ongoing'),
            upcoming=tournaments.filtered(lambda t: t.state in ('draft', 'open')).sorted('date_start'),
            finished=tournaments.filtered(lambda t: t.state == 'done'),
        )
        return request.render('pickleball_website.club_tournaments', values)

    @http.route('/club/tournaments/<int:tournament_id>', type='http', auth='public', website=True, sitemap=False)
    def club_tournament(self, tournament_id, tab='overview', **kwargs):
        tournament = self._get_tournament(tournament_id)
        matches = tournament.match_ids.filtered(lambda m: m.state != 'bye')
        knockout = tournament._knockout_matches()
        tabs = [(key, str(label), icon) for key, label, icon in TABS
                if (key != 'standings' or tournament.format != 'knockout')
                and (key not in ('schedule', 'standings', 'bracket') or tournament.match_ids)
                and (key != 'bracket' or knockout)]
        tab = tab if tab in {t[0] for t in tabs} else 'overview'
        values = self._tournament_values(
            tournament=tournament, current_tab=tab, tabs=tabs,
            group_name=self._group_name,
            podium=[(1, tournament.champion_id), (2, tournament.runner_up_id), (3, tournament.third_place_id)],
        )
        if tab == 'overview':
            game_format, best_of_rows = self._match_format(tournament)
            upcoming = matches.filtered(lambda m: m.state == 'scheduled').sorted(
                lambda m: (not m.match_date, m.match_date or tournament.date_start, m.match_time, m.number))
            values.update(
                summary_lines=self._summary_lines(tournament), game_format=game_format,
                best_of_rows=best_of_rows,
                next_matches=[self._match_view(m) for m in upcoming[:4]],
                done_count=len(matches.filtered(lambda m: m.state == 'done')),
                total_count=len(matches),
            )
        elif tab == 'teams':
            values['teams'] = tournament.team_ids.sorted(lambda t: (t.group_id.sequence, not t.seed, t.seed, t.name))
        elif tab == 'schedule':
            ordered = matches.sorted(
                lambda m: (not m.match_date, m.match_date or tournament.date_start, m.match_time, m.number))
            days = []
            for match in ordered:
                if not days or days[-1]['date'] != match.match_date:
                    days.append({'date': match.match_date, 'matches': []})
                days[-1]['matches'].append(self._match_view(match))
            values['days'] = days
        elif tab == 'standings':
            values['tables'] = [dict(table, title=self._group_name(table['group']) if table['group']
                                     else _('League table'))
                                for table in tournament._get_standings_tables()]
            values['qualifiers'] = tournament.qualifiers_per_group
        elif tab == 'bracket':
            rounds = []
            main = knockout.filtered(lambda m: m.round_key != 'third')
            for number in sorted(set(main.mapped('round_number'))):
                in_round = main.filtered(lambda m: m.round_number == number).sorted('bracket_position')
                rounds.append({'name': self._round_name(in_round[0]),
                               'matches': [self._match_view(m) for m in in_round]})
            values['rounds'] = rounds
            third = knockout.filtered(lambda m: m.round_key == 'third')
            values['third'] = self._match_view(third) if third else None
            values.update(self._first_stage_column(tournament))
        return request.render('pickleball_website.club_tournament', values)

    @http.route('/club/tournaments/<int:tournament_id>/banner', type='http', auth='public', website=True,
                sitemap=False)
    def club_tournament_banner(self, tournament_id, **kwargs):
        tournament = self._get_tournament(tournament_id)
        if not tournament.image:
            raise NotFound()
        stream = request.env['ir.binary']._get_image_stream_from(tournament, 'image')
        return stream.get_response(max_age=86400)
