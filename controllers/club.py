"""Club website: a public home page and the members' area (/club/...).

Members log in with portal accounts (pickleball.member.user_id). Portal
users have no access rights on the pickleball models, so every page reads
with sudo() here and only renders what the viewer is allowed to see:

- everyone in the members' area: schedule, players, rankings and results;
- money (debts, settlements, bank transfers): a member sees only their own,
  admins (internal users) see the whole team's.

Texts are English in the code and translated with i18n/vi.po; the website
is Vietnamese by default, English under /en.
"""
from types import SimpleNamespace

from werkzeug.exceptions import Forbidden, NotFound

from odoo import _, fields, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

PLAYED_STATES = ('done', 'settled')
UPCOMING_STATES = ('draft', 'confirmed')

SESSIONS_PER_PAGE = 12
MATCH_SESSIONS_PER_PAGE = 5

WEEKDAYS = (_lt('Monday'), _lt('Tuesday'), _lt('Wednesday'), _lt('Thursday'),
            _lt('Friday'), _lt('Saturday'), _lt('Sunday'))
MONTHS = (_lt('Jan'), _lt('Feb'), _lt('Mar'), _lt('Apr'), _lt('May'), _lt('Jun'),
          _lt('Jul'), _lt('Aug'), _lt('Sep'), _lt('Oct'), _lt('Nov'), _lt('Dec'))
SESSION_STATES = {
    'draft': _lt('Open'),
    'confirmed': _lt('Confirmed'),
    'done': _lt('Played'),
    'settled': _lt('Settled'),
}
EXPENSE_TYPES = {
    'court': _lt('Court rental'),
    'ball': _lt('Balls'),
    'water': _lt('Water & drinks'),
    'equipment': _lt('Equipment'),
    'other': _lt('Other'),
}
EXPENSE_ICONS = {
    'court': 'fa-th-large', 'ball': 'fa-circle', 'water': 'fa-tint',
    'equipment': 'fa-wrench', 'other': 'fa-tag',
}
PLAY_STYLES = {
    'all': _lt('All-court player'),
    'dink': _lt('Dinker'),
    'power': _lt('Power hitter'),
    'net': _lt('Net player'),
    'def': _lt('Defender'),
}
TRANSFER_STATES = {
    'unmatched': _lt('Checking'),
    'matched': _lt('Received'),
    'ignored': _lt('Ignored'),
}
TIERS = [('icon', 'Icon'), ('gold', 'Gold'), ('silver', 'Silver'), ('bronze', 'Bronze')]
PLAYER_SORTS = [('ovr', 'OVR'), ('name', _lt('Name')), ('matches', _lt('Matches')), ('winrate', _lt('Win rate'))]
RANKING_SORTS = [('ovr', 'OVR'), ('winrate', _lt('Win rate')), ('wins', _lt('Wins')), ('bet', _lt('Bet winnings'))]
PAIR_SORTS = [('rating', _lt('Rating')), ('winrate', _lt('Win rate')), ('wins', _lt('Wins')),
              ('matches', _lt('Matches')), ('bet', _lt('Bet winnings'))]
PAIR_SORT_KEYS = {
    'rating': lambda p: (-p.score, -p.wins, -p.matches),
    'winrate': lambda p: (-p.win_rate, -p.matches),
    'wins': lambda p: (-p.wins, -p.score),
    'matches': lambda p: (-p.matches, -p.score),
    'bet': lambda p: (-p.bet_net, -p.score),
}


# ── Formatting helpers (also passed to the templates) ─────────────────────────

def vnd(amount, signed=False):
    """150000 -> '150.000đ' (signed: '+150.000đ' / '-150.000đ')."""
    value = round(amount or 0)
    text = f'{abs(value):,}đ'.replace(',', '.')
    if signed and value:
        return ('+' if value > 0 else '-') + text
    return ('-' + text) if value < 0 else text


def hm(hours):
    """18.5 -> '18:30'."""
    hours = hours or 0.0
    h, m = int(hours), round((hours - int(hours)) * 60)
    if m == 60:
        h, m = h + 1, 0
    return f'{h:02d}:{m:02d}'


def weekday_name(day):
    return str(WEEKDAYS[day.weekday()]) if day else ''


def month_name(day):
    return str(MONTHS[day.month - 1]) if day else ''


def fmt_date(day):
    return day.strftime('%d/%m/%Y') if day else ''


def short_name(name):
    """Last word of a Vietnamese name ('Nguyễn Văn An' -> 'An'), for tight spots."""
    words = (name or '').split()
    return words[-1] if words else ''


def initials(name):
    words = (name or '?').split()
    return ''.join(word[0] for word in words[-2:]).upper()


# ── Showcase data of the public home page (made up, no real member) ─────────

DEMO_PLAYERS = [
    # name, tier, gender, jersey, style, dupr, ovr, (WIN, FRM, EXP, ATT, BET, PAY), W, L, form
    # First = middle of the sample podium: Gold | Icon | Silver.
    ('Lan Anh', 'icon', 'female', 7, 'dink', 4.10, 88, (86, 92, 89, 99, 81, 99), 46, 12, 'WWWWL'),
    ('Minh Quân', 'gold', 'male', 9, 'power', 3.85, 84, (82, 88, 91, 95, 74, 99), 41, 17, 'WWLWW'),
    ('Đức Huy', 'silver', 'male', 21, 'all', 3.40, 72, (68, 74, 80, 71, 58, 92), 29, 21, 'LWWLW'),
]
DEMO_RANKING = [
    # name, tier, ovr, played, wins, win %, form
    ('Lan Anh', 'icon', 88, 58, 46, 79, 'WWWWL'),
    ('Minh Quân', 'gold', 84, 58, 41, 71, 'WWLWW'),
    ('Đức Huy', 'silver', 72, 50, 29, 58, 'LWWLW'),
    ('Thu Trang', 'silver', 70, 44, 24, 55, 'WLWLW'),
    ('Hoàng Nam', 'bronze', 63, 37, 17, 46, 'LLWWL'),
]


def demo_players():
    """Showcase cards: plain objects with the attributes the player card
    template reads from a member."""
    players = []
    for index, (name, tier, gender, jersey, style, dupr, ovr, stats, wins, losses, form) in enumerate(DEMO_PLAYERS):
        players.append(SimpleNamespace(
            id=-(index + 1), name=name, card_tier=tier, gender=gender, jersey_number=jersey,
            play_style=style, dupr_rating=dupr, card_overall=ovr,
            card_win=stats[0], card_form=stats[1], card_exp=stats[2],
            card_att=stats[3], card_bet=stats[4], card_pay=stats[5],
            total_wins=wins, total_losses=losses, card_recent_results=form,
            balance=0.0, active=True, is_bot_manager=False, telegram_chat_id=False, zalo_chat_id=False,
            image_128=False,
        ))
    return players


def labels(mapping):
    """{key: lazy label} -> {key: label in the current language}."""
    return {key: str(label) for key, label in mapping.items()}


class PickleballClub(http.Controller):

    # ── Access & common values ─────────────────────────────────────────────

    def _linked_member(self):
        """The member of the logged-in user (sudo), approved or not."""
        user = request.env.user
        if user._is_public():
            return request.env['pickleball.member'].sudo()
        return user._get_pickleball_member()

    def _me(self):
        """The logged-in member (sudo) when their website account is approved,
        else an empty recordset."""
        member = self._linked_member()
        return member if member.website_state == 'approved' and member.active else member.browse()

    @staticmethod
    def _is_admin():
        """Admins (internal users) see everyone's money; members only theirs."""
        return request.env.user._is_internal()

    def _check_club_access(self):
        """None when the current user may see the members' area, else the
        response to return: the sign-up status page while their account
        waits for email confirmation / approval, else a "members only" page."""
        if self._is_admin() or self._me():
            return None
        if self._linked_member():
            return request.redirect('/club/pending')
        return request.render('pickleball_website.club_no_access', self._values('none'), status=403)

    def _values(self, tab, **values):
        me = self._me()
        is_admin = self._is_admin()

        def sees_money(member):
            """Whether the viewer may see `member`'s debts and payments."""
            return is_admin or bool(me and member and member.id == me.id)

        return dict(
            values,
            club_tab=tab,
            me=me,
            is_admin=is_admin,
            is_club_member=bool(me) or is_admin,
            sees_money=sees_money,
            today=fields.Date.context_today(request.env.user),
            vnd=vnd, hm=hm, weekday_name=weekday_name, month_name=month_name, fmt_date=fmt_date,
            short_name=short_name, initials=initials,
            session_states=labels(SESSION_STATES),
            photo_url=self._photo_url,
        )

    @staticmethod
    def _photo_url(member):
        if not member.image_128:
            return ''
        return f'/club/photo/{member.id}?unique={int(member.write_date.timestamp())}'

    @property
    def _Member(self):
        return request.env['pickleball.member'].sudo()

    @property
    def _Session(self):
        return request.env['pickleball.session'].sudo()

    @property
    def _Bet(self):
        return request.env['pickleball.match.bet'].sudo()

    @property
    def _Settlement(self):
        return request.env['pickleball.settlement'].sudo()

    # ── Data helpers ────────────────────────────────────────────────────────

    def _next_session(self):
        today = fields.Date.context_today(request.env.user)
        return self._Session.search(
            [('date', '>=', today), ('state', 'in', UPCOMING_STATES)],
            order='date asc, time_start asc, id asc', limit=1)

    def _active_members(self):
        return self._Member.search([('active', '=', True)])

    @staticmethod
    def _sort_players(members, key):
        return members._sort_for_ranking(key)

    def _match_rows(self, bets, member=None):
        """Matches as dicts for the scoreboard template. With `member`, adds
        the result and money from that member's point of view."""
        rows = []
        for bet in bets:
            row = {
                'bet': bet,
                'session': bet.session_id,
                'team1': bet.team1_member_ids,
                'team2': bet.team2_member_ids,
                'winner': bet.winner,
                'amount': bet.bet_amount,
            }
            if member:
                side = 'team1' if member in bet.team1_member_ids else 'team2'
                row.update(
                    side=side,
                    partners=(bet[f'{side}_member_ids'] - member),
                    opponents=bet['team2_member_ids' if side == 'team1' else 'team1_member_ids'],
                    won=bet.winner == side,
                    net=bet._get_member_net().get(member.id, 0.0) if bet.winner else 0.0,
                )
            rows.append(row)
        return rows

    def _member_matches(self, member, limit=None):
        return self._Bet.search([
            ('winner', '!=', False),
            '|', ('team1_member_ids', 'in', member.ids), ('team2_member_ids', 'in', member.ids),
        ], order='session_date desc, session_id desc, sequence desc, id desc', limit=limit)

    def _sessions_played(self, member):
        return self._Session.search_count([('participant_ids', 'in', member.ids), ('state', 'in', PLAYED_STATES)])

    def _debtors(self):
        """Members who owe the team, biggest debt first, with their oldest
        unpaid session date (admins only)."""
        owing = self._Member.search([('active', '=', True), ('balance', '<', -0.5)]).sorted('balance')
        return [{
            'member': member,
            'owes': -member.balance,
            'since': member._get_unpaid_debts()[:1].session_date,
        } for member in owing]

    @staticmethod
    def _team_qr_url():
        """Public URL of the team's bank QR image (Settings), or ''."""
        company = request.env.company.sudo()
        if not company.pickleball_payment_qr or not company.pickleball_payment_qr_token:
            return ''
        return f'/pickleball/payment-qr/{company.pickleball_payment_qr_token}.jpg'

    @staticmethod
    def _card_level_rows():
        """Card levels and what it takes to reach them (Configuration >
        Card Levels), lowest first, for the home page."""
        rows = []
        Level = request.env['pickleball.card.level'].sudo()
        for level in Level.search([], order='rank asc'):
            if level.tier == 'bronze':
                text = level.description or _('Getting started')
            else:
                parts = []
                if level.min_overall:
                    parts.append(_('OVR %s and up', level.min_overall))
                if level.min_matches:
                    parts.append(_('%s+ matches', level.min_matches))
                if level.min_win_rate:
                    parts.append(_('%s%% win rate', f'{level.min_win_rate:g}'))
                parts += [f'{label} {level[fname]}+' for fname, label in (
                    ('min_win', 'WIN'), ('min_form', 'FRM'), ('min_exp', 'EXP'), ('min_att', 'ATT'),
                    ('min_bet', 'BET'), ('min_pay', 'PAY')) if level[fname]]
                text = ', '.join(parts) or _('Open to everyone')
                if level.description:
                    text = f'{text} — {level.description}'
            rows.append({'tier': level.tier, 'name': (level.name or '').upper(), 'text': text})
        return rows

    # ── Public home page ────────────────────────────────────────────────────

    @http.route('/club', type='http', auth='public', website=True, sitemap=True)
    def club_home(self, **kwargs):
        if not (self._is_admin() or self._me()):
            # Visitors (and accounts not approved yet) get the showcase home
            # page, with made-up data only: no real member nor number.
            values = self._values('home', demo_players=demo_players(), demo_rows=DEMO_RANKING,
                                  card_levels=self._card_level_rows())
            return request.render('pickleball_website.club_home_public', values)
        members = self._active_members()
        played = self._Session.search([('state', 'in', PLAYED_STATES)])
        last_session = self._Session.search(
            [('state', 'in', PLAYED_STATES), ('match_bet_ids.winner', '!=', False)],
            order='date desc, id desc', limit=1)
        values = self._values(
            'home',
            next_session=self._next_session(),
            top_players=self._sort_players(members.filtered('total_matches'), 'ovr')[:3],
            stats={
                'members': len(members),
                'sessions': len(played),
                'matches': self._Bet.search_count([('winner', '!=', False)]),
                'courts': len(played.court_id),
            },
            last_session=last_session,
            last_matches=self._match_rows(last_session.match_bet_ids.filtered('winner').sorted('sequence')[:4]),
        )
        return request.render('pickleball_website.club_home', values)

    # ── Members' area ───────────────────────────────────────────────────────

    @http.route('/club/me', type='http', auth='user', website=True, sitemap=False)
    def club_dashboard(self, **kwargs):
        denied = self._check_club_access()
        if denied:
            return denied
        me = self._me()
        if not me:  # an admin without a member profile
            return request.redirect('/club/players')
        next_session = self._next_session()
        today = fields.Date.context_today(request.env.user)
        ranking = self._sort_players(self._active_members(), 'ovr').ids
        values = self._values(
            'me',
            next_session=next_session,
            in_next_session=me in next_session.participant_ids,
            my_matches=self._match_rows(self._member_matches(me, limit=5), member=me),
            sessions_played=self._sessions_played(me),
            sessions_this_month=self._Session.search_count([
                ('participant_ids', 'in', me.ids), ('state', 'in', PLAYED_STATES),
                ('date', '>=', today.replace(day=1)),
            ]),
            my_rank=ranking.index(me.id) + 1 if me.id in ranking else 0,
            team_qr_url=self._team_qr_url(),
            my_debt=me._get_outstanding_debt(),
        )
        return request.render('pickleball_website.club_dashboard', values)

    @http.route('/club/schedule', type='http', auth='user', website=True, sitemap=False)
    def club_schedule(self, page=1, **kwargs):
        denied = self._check_club_access()
        if denied:
            return denied
        today = fields.Date.context_today(request.env.user)
        upcoming = self._Session.search(
            [('date', '>=', today), ('state', 'in', UPCOMING_STATES)], order='date asc, time_start asc')
        past_domain = [('state', 'in', PLAYED_STATES)]
        total = self._Session.search_count(past_domain)
        pager = request.website.pager(url='/club/schedule', total=total, page=int(page), step=SESSIONS_PER_PAGE)
        past = self._Session.search(past_domain, order='date desc, time_start desc',
                                    limit=SESSIONS_PER_PAGE, offset=pager['offset'])
        values = self._values('schedule', upcoming=upcoming, past=past, pager=pager)
        return request.render('pickleball_website.club_schedule', values)

    @http.route('/club/schedule/<int:session_id>', type='http', auth='user', website=True, sitemap=False)
    def club_session(self, session_id, **kwargs):
        denied = self._check_club_access()
        if denied:
            return denied
        session = self._Session.browse(session_id).exists()
        if not session:
            raise NotFound()
        settlements = session.settlement_ids
        if not self._is_admin():
            # Members only see their own share of the split.
            settlements = settlements.filtered(lambda s: s.member_id == self._me())
        values = self._values(
            'schedule',
            session=session,
            courts=session._get_courts(),
            matches=self._match_rows(session.match_bet_ids.sorted('sequence')),
            expenses=session.expense_ids,
            expense_icons=EXPENSE_ICONS,
            expense_types=labels(EXPENSE_TYPES),
            settlements=settlements.sorted(lambda s: (s.amount >= 0, s.amount)),
            per_person=(session.total_expense / session.total_player_count) if session.total_player_count else 0.0,
            match_builder_props=self._match_builder_props(session) if self._is_admin() else None,
        )
        return request.render('pickleball_website.club_session', values)

    # ── Match builder (admins): drag players into teams ────────────────────

    def _match_builder_props(self, session):
        """Props of the drag & drop match builder of the session page."""
        bets = session.match_bet_ids.sorted('sequence')
        players = session.participant_ids | bets.team1_member_ids | bets.team2_member_ids
        return {
            'sessionId': session.id,
            'locked': session.state == 'settled',
            'needsRecalc': session.state == 'done',
            'defaultBet': bets[-1:].bet_amount or 0,
            'players': [{
                'id': member.id,
                'name': member.name,
                'short': short_name(member.name),
                'initials': initials(member.name),
                'photo': self._photo_url(member),
                'tier': member.card_tier or 'bronze',
                'ovr': member.card_overall,
                'guest': member not in session.participant_ids,
            } for member in players.sorted(lambda m: (m.name or '').lower())],
            'matches': self._builder_matches(bets),
        }

    @staticmethod
    def _builder_matches(bets):
        return [{
            'id': bet.id,
            'team1': bet.team1_member_ids.ids,
            'team2': bet.team2_member_ids.ids,
            'bet': bet.bet_amount,
            'winner': bet.winner or '',
        } for bet in bets]

    @http.route('/club/schedule/<int:session_id>/matches', type='json', auth='user', website=True,
                methods=['POST'])
    def club_session_save_matches(self, session_id, matches=None, **kwargs):
        """Save the matches of the builder: `matches` is the full list
        (in order), each {id (missing for a new one), team1, team2, bet,
        winner}. Matches of the session left out are deleted."""
        if not self._is_admin():
            raise Forbidden()
        # Admins are internal users: no sudo, their own access rights apply.
        session = request.env['pickleball.session'].browse(session_id).exists()
        if not session:
            raise NotFound()
        if session.state == 'settled':
            raise UserError(_("This session is settled: its matches can't be changed any more."))
        allowed = session.participant_ids | session.match_bet_ids.team1_member_ids | \
            session.match_bet_ids.team2_member_ids
        Bet = request.env['pickleball.match.bet']
        kept = Bet
        try:
            for sequence, item in enumerate(matches or [], start=1):
                team1 = [int(i) for i in item.get('team1') or []]
                team2 = [int(i) for i in item.get('team2') or []]
                if not set(team1 + team2) <= set(allowed.ids):
                    raise UserError(_("Only the players of this session can play its matches."))
                if not team1 or not team2:
                    raise UserError(_("Match %s needs at least one player on each side.", sequence))
                vals = {
                    'sequence': sequence,
                    'team1_member_ids': [fields.Command.set(team1)],
                    'team2_member_ids': [fields.Command.set(team2)],
                    'bet_amount': max(0.0, float(item.get('bet') or 0)),
                    'winner': item.get('winner') if item.get('winner') in ('team1', 'team2') else False,
                }
                bet = session.match_bet_ids.filtered(lambda b: b.id == item.get('id'))
                if bet:
                    bet.write(vals)
                else:
                    bet = Bet.create(dict(vals, session_id=session.id))
                kept |= bet
            (session.match_bet_ids - kept).unlink()
        except (TypeError, ValueError):
            raise UserError(_("Invalid match data."))
        except ValidationError as error:
            raise UserError(error.args[0]) from error
        return {
            'matches': self._builder_matches(session.match_bet_ids.sorted('sequence')),
            'needsRecalc': session.state == 'done',
        }

    @http.route('/club/players', type='http', auth='user', website=True, sitemap=False)
    def club_players(self, sort='ovr', tier=None, **kwargs):
        denied = self._check_club_access()
        if denied:
            return denied
        members = self._active_members()
        if tier in dict(TIERS):
            members = members.filtered(lambda m: m.card_tier == tier)
        sort = sort if sort in dict(PLAYER_SORTS) else 'ovr'
        values = self._values(
            'players', players=self._sort_players(members, sort),
            sort=sort, tier=tier if tier in dict(TIERS) else None,
            sorts=[(key, str(label)) for key, label in PLAYER_SORTS], tiers=TIERS,
        )
        return request.render('pickleball_website.club_players', values)

    @http.route('/club/players/<int:member_id>', type='http', auth='user', website=True, sitemap=False)
    def club_player(self, member_id, **kwargs):
        denied = self._check_club_access()
        if denied:
            return denied
        player = self._Member.browse(member_id).exists()
        if not player:
            raise NotFound()
        ranking = self._sort_players(self._active_members(), 'ovr').ids
        sessions = self._Session.search(
            [('participant_ids', 'in', player.ids), ('state', 'in', PLAYED_STATES)], order='date desc', limit=6)
        values = self._values(
            'players',
            player=player,
            rank=ranking.index(player.id) + 1 if player.id in ranking else 0,
            ranked_count=len(ranking),
            matches=self._match_rows(self._member_matches(player, limit=10), member=player),
            sessions=sessions,
            sessions_played=self._sessions_played(player),
            player_subtitle=' · '.join(filter(None, [
                str(PLAY_STYLES[player.play_style]) if player.play_style in PLAY_STYLES else '',
                f'DUPR {player.dupr_rating:.2f}' if player.dupr_rating else '',
                _('Jersey #%s', player.jersey_number) if player.jersey_number else '',
            ])),
        )
        return request.render('pickleball_website.club_player', values)

    @http.route('/club/rankings', type='http', auth='user', website=True, sitemap=False)
    def club_rankings(self, by='ovr', kind='players', **kwargs):
        denied = self._check_club_access()
        if denied:
            return denied
        if kind == 'pairs':
            return self._club_pair_rankings(by)
        by = by if by in dict(RANKING_SORTS) else 'ovr'
        members = self._active_members()
        players = self._sort_players(members.filtered('total_matches'), by)
        moves_session, moves = players._get_ranking_moves(by)
        values = self._values(
            'rankings',
            players=players,
            moves=moves,
            moves_session=moves_session,
            unranked=members.filtered(lambda m: not m.total_matches),
            by=by, sorts=[(key, str(label)) for key, label in RANKING_SORTS],
            kind='players',
        )
        return request.render('pickleball_website.club_rankings', values)

    def _club_pair_rankings(self, by):
        """Doubles pairs of active members, ranked by their results together."""
        by = by if by in dict(PAIR_SORTS) else 'rating'
        pairs = request.env['pickleball.pair.ranking'].sudo().search([]).filtered(
            lambda p: p.member1_id.active and p.member2_id.active)
        values = self._values(
            'rankings',
            pairs=pairs.sorted(PAIR_SORT_KEYS[by]),
            by=by, sorts=[(key, str(label)) for key, label in PAIR_SORTS],
            kind='pairs',
        )
        return request.render('pickleball_website.club_rankings', values)

    @http.route('/club/matches', type='http', auth='user', website=True, sitemap=False)
    def club_matches(self, page=1, **kwargs):
        denied = self._check_club_access()
        if denied:
            return denied
        domain = [('match_bet_ids.winner', '!=', False)]
        total = self._Session.search_count(domain)
        pager = request.website.pager(url='/club/matches', total=total, page=int(page),
                                      step=MATCH_SESSIONS_PER_PAGE)
        sessions = self._Session.search(domain, order='date desc, id desc',
                                        limit=MATCH_SESSIONS_PER_PAGE, offset=pager['offset'])
        blocks = [{
            'session': session,
            'matches': self._match_rows(session.match_bet_ids.filtered('winner').sorted('sequence')),
        } for session in sessions]
        values = self._values('matches', blocks=blocks, pager=pager)
        return request.render('pickleball_website.club_matches', values)

    @http.route('/club/finance', type='http', auth='user', website=True, sitemap=False)
    def club_finance(self, **kwargs):
        denied = self._check_club_access()
        if denied:
            return denied
        me = self._me()
        Settlement = self._Settlement
        values = {
            'transfer_states': labels(TRANSFER_STATES),
            'team_qr_url': self._team_qr_url(),
            'my_debt': me._get_outstanding_debt() if me else 0.0,
            'my_unpaid': me._get_unpaid_debts() if me else Settlement,
            'my_history': Settlement.search([('member_id', '=', me.id)], order='session_date desc, id desc',
                                            limit=15) if me else Settlement,
            'my_transfers': request.env['pickleball.bank.transaction'].sudo().search(
                [('member_id', '=', me.id)], order='transaction_date desc', limit=10) if me else None,
            'my_paid_total': -sum(Settlement.search([
                ('member_id', '=', me.id), ('is_paid', '=', True), ('amount', '<', 0),
            ]).mapped('amount')) if me else 0.0,
        }
        if self._is_admin():
            # The whole team's money: admins only.
            debtors = self._debtors()
            owed = self._Member.search([('active', '=', True), ('balance', '>', 0.5)]).sorted(
                'balance', reverse=True)
            values.update(
                debtors=debtors,
                owed_members=owed,
                total_owed_to_team=sum(d['owes'] for d in debtors),
                total_owed_by_team=sum(owed.mapped('balance')),
                recent_paid=Settlement.search([('is_paid', '=', True), ('amount', '<', 0)],
                                              order='payment_date desc, id desc', limit=8),
            )
        return request.render('pickleball_website.club_finance', self._values('finance', **values))

    @http.route('/club/photo/<int:member_id>', type='http', auth='user', website=True, sitemap=False)
    def club_photo(self, member_id, **kwargs):
        """Member photos for the members' area (portal users can't read
        pickleball.member through /web/image)."""
        if self._check_club_access():
            raise NotFound()
        member = self._Member.browse(member_id).exists()
        if not member or not member.image_128:
            raise NotFound()
        stream = request.env['ir.binary']._get_image_stream_from(member, 'image_512')
        return stream.get_response(max_age=86400)
