"""Chat bubble of the club website (logged-in members and admins).

Three ways to get an answer:

- frequently asked questions: instant answers built from the data (next
  session, what I owe, courts, rankings, my stats…), no AI call;
- free questions: the team's AI assistant (pickleball-team), limited for
  members to read-only tools that only show their own money;
- "Talk to an admin": a Discuss conversation with the website chat admins.
"""
import importlib
from datetime import timedelta

from werkzeug.exceptions import Forbidden

from odoo import _, fields, http
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools.translate import LazyTranslate

from ..models.pickleball_ai_tools import WEBSITE_MEMBER_CONTEXT_KEY, WEBSITE_RESTRICTED_CONTEXT_KEY
from .club import PLAYED_STATES, SESSION_STATES, PickleballClub, fmt_date, hm, vnd, weekday_name

# The module's technical name has a dash: no regular import.
_team_tools = importlib.import_module('odoo.addons.pickleball-team.models.pickleball_ai_tools')
BOT_ACTOR_CONTEXT_KEY = _team_tools.BOT_ACTOR_CONTEXT_KEY
BOT_CHANNEL_CONTEXT_KEY = _team_tools.BOT_CHANNEL_CONTEXT_KEY

_lt = LazyTranslate(__name__)

# (key, icon, label) of the questions shown when the bubble opens.
FAQS = (
    ('next_session', 'fa-calendar', _lt('When is the next session?')),
    ('my_debt', 'fa-money', _lt('How much do I owe?')),
    ('last_session', 'fa-history', _lt('How did the last session go?')),
    ('courts', 'fa-map-marker', _lt('Court information')),
    ('rankings', 'fa-trophy', _lt('Rankings')),
    ('my_stats', 'fa-bar-chart', _lt('My stats')),
    ('my_sessions', 'fa-list-ul', _lt('My recent sessions')),
)
MEDALS = {1: '🥇', 2: '🥈', 3: '🥉'}
RANKING_TOP = 5
AI_MAX_LENGTH = 1000
# AI questions a member may ask per hour (system parameter, 0 = no limit).
AI_HOURLY_LIMIT_PARAM = 'pickleball_website.chat_ai_hourly_limit'
AI_HOURLY_LIMIT_DEFAULT = 30


class ClubChat(PickleballClub):

    def _check_chat_access(self):
        if request.env.user._is_public() or not (self._is_admin() or self._me()):
            raise Forbidden()

    # ── Opening the bubble ──────────────────────────────────────────────────

    @http.route('/club/chat/init', type='json', auth='user', website=True)
    def club_chat_init(self, **kwargs):
        self._check_chat_access()
        me = self._me()
        admins = request.env.company._get_pickleball_chat_admins()
        return {
            'name': me.name if me else request.env.user.name,
            'is_admin': self._is_admin(),
            'faqs': [{'key': key, 'icon': icon, 'label': str(label)} for key, icon, label in FAQS],
            # Admins answer the members from Discuss: no admin tab for them.
            'admin_chat': bool(me) and bool(admins),
            'admin_names': admins.mapped('name')[:3],
            'ai_enabled': bool(request.env['pickleball.ai.provider'].sudo().search_count(
                [('is_active', '=', True)], limit=1)),
        }

    # ── Frequently asked questions ──────────────────────────────────────────

    @http.route('/club/chat/faq', type='json', auth='user', website=True)
    def club_chat_faq(self, key=None, **kwargs):
        self._check_chat_access()
        if key not in {faq[0] for faq in FAQS}:
            return self._answer(_("I don't know this question."))
        return getattr(self, f'_faq_{key}')()

    @staticmethod
    def _answer(text, actions=None, image=''):
        """An answer of the bubble: text lines, links shown as buttons, an image."""
        return {
            'text': text if isinstance(text, str) else '\n'.join(line for line in text if line),
            'actions': [{'label': str(label), 'url': url} for label, url in (actions or [])],
            'image': image or '',
        }

    def _session_title(self, session):
        return _('%(weekday)s %(date)s, %(start)s – %(end)s', weekday=weekday_name(session.date),
                 date=fmt_date(session.date), start=hm(session.time_start), end=hm(session.time_end))

    def _faq_next_session(self):
        session = self._next_session()
        schedule = (_('Schedule'), '/club/schedule')
        if not session:
            return self._answer(_('No session is planned yet: the admins post the next one on the schedule.'),
                                [schedule])
        me = self._me()
        courts = session._get_courts()
        lines = [
            '📅 ' + self._session_title(session),
            '🏟 ' + _('Court: %s', ' + '.join(courts.mapped('name')) or '—'),
            ('📍 ' + courts[:1].address) if courts[:1].address else '',
            '👥 ' + _('%s players registered', session.total_player_count),
        ]
        if session.state == 'draft':
            lines.append('⏳ ' + _('Not confirmed yet.'))
        if me:
            lines.append('✅ ' + _("You're on the list.") if me in session.participant_ids
                         else '🙋 ' + _("You're not on the list yet: tell an admin if you want to play."))
        return self._answer(lines, [(_('Session details'), f'/club/schedule/{session.id}'), schedule])

    def _faq_my_debt(self):
        me = self._me()
        finance = (_('My finance'), '/club/finance')
        if not me:
            return self._answer(_("You have no member profile: the finance page shows the whole team's debts."),
                                [finance])
        debt = me._get_outstanding_debt()
        if debt <= 0.5:
            if me.balance > 0.5:
                return self._answer('💰 ' + _('The team owes you %s.', vnd(me.balance)), [finance])
            return self._answer('✅ ' + _("You don't owe anything: all settled!"), [finance])
        unpaid = me._get_unpaid_debts()
        lines = ['📌 ' + _('You owe the team %s.', vnd(debt))]
        lines += ['• ' + _('Session of %(date)s: %(amount)s', date=fmt_date(s.session_date), amount=vnd(-s.amount))
                  for s in unpaid[:5]]
        if len(unpaid) > 5:
            lines.append('• ' + _('… and %s more sessions', len(unpaid) - 5))
        if me.bank_credit > 0.5:
            lines.append(_('Already received from you: %s', vnd(me.bank_credit)))
        ICP = request.env['ir.config_parameter'].sudo()
        bank = ' '.join(filter(None, [ICP.get_param('pickleball.sepay_bank'),
                                      ICP.get_param('pickleball.sepay_account_number')]))
        if bank:
            lines.append('🏦 ' + _('Transfer to: %s', bank))
        lines.append(_('Write your name in the transfer note: your debt clears automatically.'))
        return self._answer(lines, [finance], image=self._team_qr_url())

    def _faq_last_session(self):
        session = self._Session.search([('state', 'in', PLAYED_STATES)],
                                       order='date desc, time_start desc, id desc', limit=1)
        if not session:
            return self._answer(_('No session has been played yet.'))
        me = self._me()
        players = session.total_player_count
        lines = [
            '🏁 ' + self._session_title(session),
            '🏟 ' + ' + '.join(session._get_courts().mapped('name')),
            '👥 ' + _('%(players)s players · total %(total)s · %(per_person)s per person', players=players,
                      total=vnd(session.total_expense),
                      per_person=vnd(session.total_expense / players) if players else '—'),
        ]
        played = session.match_bet_ids.filtered('winner')
        if played:
            lines.append('🏓 ' + _('%s matches played', len(played)))
        if me and me in session.participant_ids:
            settlement = session.settlement_ids.filtered(lambda s: s.member_id == me)[:1]
            status = _('paid') if settlement.is_paid else _('not paid yet')
            if settlement and settlement.amount < -0.5:
                lines.append('💸 ' + _('Your share: you owe %(amount)s (%(status)s)',
                                       amount=vnd(-settlement.amount), status=status))
            elif settlement and settlement.amount > 0.5:
                lines.append('💰 ' + _('The team pays you back %(amount)s (%(status)s)',
                                       amount=vnd(settlement.amount), status=status))
            mine = self._match_rows(played.filtered(
                lambda bet: me in bet.team1_member_ids or me in bet.team2_member_ids), me)
            if mine:
                wins = len([row for row in mine if row['won']])
                lines.append('🎯 ' + _('Your matches: %(wins)s won, %(losses)s lost',
                                       wins=wins, losses=len(mine) - wins))
        elif me:
            lines.append(_("You didn't play this session."))
        return self._answer(lines, [(_('Session details'), f'/club/schedule/{session.id}')])

    def _faq_courts(self):
        session = self._next_session()
        next_courts = session._get_courts() if session else request.env['pickleball.court'].sudo()
        played = request.env['pickleball.court'].sudo().search([('active', '=', True)]).sorted(
            lambda court: -court.session_count)
        courts = next_courts | (played - next_courts)[:max(3 - len(next_courts), 1)]
        if not courts:
            return self._answer(_('No court is recorded yet.'))
        blocks = []
        for court in courts:
            title = '🏟 ' + court.name
            if court in next_courts:
                title += ' — ' + _('next session')
            lines = [title]
            if court.address:
                lines.append('📍 ' + court.address)
            phones = ' · '.join(filter(None, [court.phone, court.phone2]))
            if phones:
                lines.append('📞 ' + phones)
            lines.append(_('%s sessions played here', court.session_count))
            blocks.append('\n'.join(lines))
        actions = [(_('Next session'), f'/club/schedule/{session.id}')] if session else []
        return self._answer('\n\n'.join(blocks), actions)

    def _faq_rankings(self):
        players, _unranked = self._Member._get_ranking('ovr')
        rankings = (_('Full rankings'), '/club/rankings')
        if not players:
            return self._answer(_('No ranking yet: no match has been recorded.'), [rankings])
        lines = ['🏆 ' + _('Top players (OVR)')]
        for rank, player in enumerate(players[:RANKING_TOP], start=1):
            lines.append(_('%(medal)s %(name)s — OVR %(ovr)s · %(wins)sW-%(losses)sL · %(rate)s',
                           medal=MEDALS.get(rank, f'{rank}.'), name=player.name, ovr=player.card_overall,
                           wins=player.total_wins, losses=player.total_losses,
                           rate=f'{round(player.win_rate)}%'))
        me = self._me()
        if me and me in players:
            lines.append('')
            lines.append('👉 ' + _('You: #%(rank)s of %(total)s (OVR %(ovr)s)', rank=players.ids.index(me.id) + 1,
                                   total=len(players), ovr=me.card_overall))
        elif me:
            lines.append('')
            lines.append(_("You're not ranked yet: play a recorded match first."))
        return self._answer(lines, [rankings])

    def _faq_my_stats(self):
        me = self._me()
        if not me:
            return self._answer(_('Stats are kept for members: you have no player card.'),
                                [(_('Players'), '/club/players')])
        tier = dict(me._fields['card_tier']._description_selection(request.env)).get(me.card_tier, '')
        players, _unranked = self._Member._get_ranking('ovr')
        lines = [
            '⭐ ' + _('OVR %(ovr)s · %(tier)s card', ovr=me.card_overall, tier=tier),
            '🏓 ' + _('%(matches)s matches: %(wins)s won, %(losses)s lost · win rate %(rate)s',
                      matches=me.total_matches, wins=me.total_wins, losses=me.total_losses,
                      rate=f'{round(me.win_rate)}%'),
            '📅 ' + _('%s sessions played', self._sessions_played(me)),
            '💵 ' + _('Bets: %s', vnd(me.bet_net_total, signed=True)),
        ]
        if me in players:
            lines.append('🏆 ' + _('Ranking: #%(rank)s of %(total)s', rank=players.ids.index(me.id) + 1,
                                   total=len(players)))
        if me.card_recent_results:
            lines.append('📈 ' + _('Recent form: %s', ' '.join(me.card_recent_results)))
        # The bot's token-guarded card image (the bubble hides it if it fails).
        image = f'/pickleball/member/{me.id}/card/{me._get_card_token()}.png?v={int(me.write_date.timestamp())}'
        return self._answer(lines, [(_('My profile'), f'/club/players/{me.id}'), (_('My page'), '/club/me')],
                            image=image)

    def _faq_my_sessions(self):
        me = self._me()
        if not me:
            return self._answer(_("You have no member profile: here is the team's schedule."),
                                [(_('Schedule'), '/club/schedule')])
        sessions = self._Session.search([('participant_ids', 'in', me.ids)], order='date desc, id desc', limit=5)
        if not sessions:
            return self._answer(_("You haven't joined a session yet."), [(_('Schedule'), '/club/schedule')])
        states = {key: str(label) for key, label in SESSION_STATES.items()}
        lines = ['🗓 ' + _('Your last %s sessions:', len(sessions))]
        for session in sessions:
            line = f"• {fmt_date(session.date)} — {session.court_id.name or '—'} ({states.get(session.state, '')})"
            share = session.settlement_ids.filtered(lambda s: s.member_id == me)[:1]
            if share and abs(share.amount) > 0.5:
                line += f" · {vnd(share.amount, signed=True)}"
            lines.append(line)
        return self._answer(lines, [(_('Schedule'), '/club/schedule'), (_('My finance'), '/club/finance')])

    # ── AI assistant ────────────────────────────────────────────────────────

    @http.route('/club/chat/ask', type='json', auth='user', website=True)
    def club_chat_ask(self, message='', conversation_id=None, **kwargs):
        self._check_chat_access()
        message = (message or '').strip()
        if not message:
            return {'error': _('Write a question first.')}
        if len(message) > AI_MAX_LENGTH:
            return {'error': _('Your question is too long (%s characters at most).', AI_MAX_LENGTH)}
        user = request.env.user
        me = self._me()
        is_admin = self._is_admin()
        if not request.env['pickleball.ai.provider'].sudo().search_count([('is_active', '=', True)], limit=1):
            return {'error': _('The AI assistant is not set up yet: pick a question above or talk to an admin.')}
        if not is_admin and self._ai_limit_reached(user):
            return {'error': _('You asked a lot of questions this hour: try again later, or talk to an admin.')}

        conversation = request.env['pickleball.ai.conversation']._get_or_create_for_website(
            user, conversation_id=conversation_id)
        ctx = {WEBSITE_MEMBER_CONTEXT_KEY: me.id if me else 0}
        if is_admin:
            # Admins: their own access rights, every tool (as the backend widget).
            orchestrator = request.env['pickleball.ai.orchestrator'].with_context(**ctx)
        else:
            # sudo: portal users can't read the pickleball models. The tools are
            # then limited to the read-only website ones (pickleball.ai.tools in
            # this module), and the session-editing tools see no bot actor.
            orchestrator = request.env['pickleball.ai.orchestrator'].sudo().with_context(**ctx, **{
                WEBSITE_RESTRICTED_CONTEXT_KEY: True,
                BOT_ACTOR_CONTEXT_KEY: 0,
                BOT_CHANNEL_CONTEXT_KEY: 'Website',
            })
        answer = orchestrator.run_turn(conversation, message, identity_hint=self._ai_identity_hint(me, is_admin))
        return {'conversation_id': conversation.id, 'text': answer}

    @http.route('/club/chat/ai_history', type='json', auth='user', website=True)
    def club_chat_ai_history(self, conversation_id=None, **kwargs):
        self._check_chat_access()
        if not conversation_id:
            return {'messages': []}
        # sudo: limited to the user's own website conversation.
        conversation = request.env['pickleball.ai.conversation'].sudo().search([
            ('id', '=', int(conversation_id)), ('user_id', '=', request.env.user.id), ('source', '=', 'website'),
        ], limit=1)
        messages = conversation.message_ids.sorted('id').filtered(
            lambda m: m.role in ('user', 'assistant') and m.content and not m.tool_calls_json)
        return {'messages': [{'role': m.role, 'text': m.content} for m in messages[-30:]]}

    @staticmethod
    def _ai_limit_reached(user):
        limit = int(request.env['ir.config_parameter'].sudo().get_param(
            AI_HOURLY_LIMIT_PARAM, AI_HOURLY_LIMIT_DEFAULT) or 0)
        if limit <= 0:
            return False
        # sudo: counts the user's own questions (portal users can't read them).
        asked = request.env['pickleball.ai.message'].sudo().search_count([
            ('role', '=', 'user'),
            ('conversation_id.user_id', '=', user.id),
            ('conversation_id.source', '=', 'website'),
            ('create_date', '>=', fields.Datetime.now() - timedelta(hours=1)),
        ])
        return asked >= limit

    @staticmethod
    def _ai_identity_hint(me, is_admin):
        common = (
            "Reply in the user's language (Vietnamese by default), short plain text: no markdown "
            "tables or headings. Useful pages of the club website: /club/schedule, /club/rankings, "
            "/club/finance, /club/players, /club/me."
        )
        if is_admin:
            return (f"You are chatting on the club website with {request.env.user.name}, an admin of the "
                    f"team (Odoo internal user) who may use every tool. {common}")
        return (
            f"You are chatting on the club website with {me.name} (pickleball.member id={me.id}), a "
            "logged-in member. 'Me', 'my debt', 'my stats' mean this member: use get_my_profile and "
            "get_my_payments, never ask who they are. On the website a member only sees their own "
            "money: never tell how much another member owes or paid. You can't change any data from "
            "this chat: when they want something changed (join a session, fix a payment…), tell them "
            f"to use the 'Talk to an admin' tab of this chat. {common}"
        )

    # ── Talk to an admin ────────────────────────────────────────────────────

    def _chat_member(self):
        me = self._me()
        if not me:
            raise Forbidden()
        return me

    @http.route('/club/chat/admin/messages', type='json', auth='user', website=True)
    def club_chat_admin_messages(self, after_id=0, **kwargs):
        self._check_chat_access()
        me = self._me()
        if not me:  # an admin: they answer from Discuss
            return {'messages': [], 'disabled': True}
        return {'messages': me._website_chat_messages(after_id=int(after_id or 0))}

    @http.route('/club/chat/admin/send', type='json', auth='user', website=True)
    def club_chat_admin_send(self, text='', **kwargs):
        self._check_chat_access()
        try:
            return {'message': self._chat_member()._website_chat_post(text)}
        except UserError as exc:
            return {'error': exc.args[0]}
