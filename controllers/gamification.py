"""Gamification of the player card on the club website (pickleball-team
docs/gamification-spec.md §13): JSON API under /club/api, and the album,
showcase, season pages, share image and walkouts.

Money is filtered here on the server (§10): the card of another member
never carries an amount the viewer may not see."""
import copy
import json

from werkzeug.exceptions import Forbidden, NotFound

from odoo import fields, http
from odoo.exceptions import ValidationError
from odoo.http import request
from odoo.tools.translate import LazyTranslate

from .club import PickleballClub, apply_preview, demo_card_view, demo_label, demo_players, shift_ovr


def card_motif_codes():
    """Codes of the special cards with a motif (pickleball-team services/card_motif.py)."""
    return ('POTM', 'TOTW', 'IN_FORM', 'IRON_MAN', 'GIANT_SLAYER', 'COMEBACK', 'ROOKIE', 'MONEY_HEIST')

_lt = LazyTranslate(__name__)

TOAST_MESSAGES = {
    'rookie_first_match': _lt('First match played!'),
    'rookie_first_win': _lt('First win!'),
    'rookie_matches': _lt('%(n)s matches played'),
    'rookie_sessions': _lt('%(n)s sessions attended'),
    'rookie_graduated': _lt('Rookie graduated: here is your real card!'),
    'badge_level': _lt('New badge level'),
    'challenge_done': _lt('Weekly challenge done'),
}


def _json(data, status=200):
    return request.make_json_response(data, status=status)


class ClubGamification(PickleballClub):

    # ── access helpers ────────────────────────────────────────────────────

    def _api_viewer(self):
        """(me, is_admin) or raise Forbidden for the public / pending users."""
        if self._check_club_access():
            raise Forbidden()
        return self._me(), self._is_admin()

    def _api_member(self, member_id):
        member = self._Member.browse(int(member_id)).exists()
        if not member:
            raise NotFound()
        return member

    def _api_owner(self, member_id):
        """The member, if the viewer is that member (or an admin)."""
        me, is_admin = self._api_viewer()
        member = self._api_member(member_id)
        if not is_admin and member != me:
            raise Forbidden()
        return member

    @staticmethod
    def _card_payload(view):
        payload = dict(view)
        payload.pop('theme', None)
        return payload

    # ── JSON API (§13) ────────────────────────────────────────────────────

    @http.route('/club/api/members/<int:member_id>/card', type='http', auth='user', methods=['GET'],
                sitemap=False)
    def api_member_card(self, member_id, **kwargs):
        me, is_admin = self._api_viewer()
        member = self._api_member(member_id)
        return _json(self._card_payload(member._gm_card_view(viewer=me or None, is_admin=is_admin)))

    @http.route('/club/api/members/<int:member_id>/progress', type='http', auth='user', methods=['GET'],
                sitemap=False)
    def api_member_progress(self, member_id, **kwargs):
        return _json(self._api_owner(member_id)._gm_progress())

    @http.route('/club/api/members/<int:member_id>/album', type='http', auth='user', methods=['GET'],
                sitemap=False)
    def api_member_album(self, member_id, **kwargs):
        self._api_viewer()
        album = self._api_member(member_id)._gm_album()
        return _json({
            'owned': album['owned'], 'total': album['total'],
            'sections': [{
                'category': section['category'], 'label': str(section['label']),
                'slots': [{
                    'code': slot['type'].code, 'name': slot['type'].name,
                    'condition': slot['type'].condition or '', 'owned': bool(slot['cards']),
                    'count': len(slot['cards']),
                    'cards': [{'id': c.id, 'period_key': c.period_key, 'earned_at': fields.Datetime.to_string(c.earned_at),
                               'display_ovr': c.display_ovr, 'stats': c.stats, 'active': c.is_active}
                              for c in slot['cards']],
                } for slot in section['slots']],
            } for section in album['sections']],
        })

    @http.route('/club/api/members/<int:member_id>/showcase', type='json', auth='user', methods=['POST', 'PUT'])
    def api_member_showcase(self, member_id, card_instance_id=None, pinned_badges=None, show_finance_publicly=None,
                            **kwargs):
        member = self._api_owner(member_id)
        try:
            member._gm_set_showcase(card_instance_id, pinned_badges, show_finance_publicly)
        except ValidationError as error:
            return {'error': error.args[0]}
        return {'card': self._card_payload(member._gm_card_view(viewer=member, is_admin=self._is_admin()))}

    @http.route('/club/api/members/<int:member_id>/badges', type='http', auth='user', methods=['GET'],
                sitemap=False)
    def api_member_badges(self, member_id, **kwargs):
        self._api_viewer()
        return _json([{'code': row['type'].code, 'name': row['type'].name, 'level': row['level'],
                       'progress': row['progress'], 'next': row['next'], 'pinned': row['pinned']}
                      for row in self._api_member(member_id)._gm_badges()])

    @http.route('/club/api/members/<int:member_id>/duos', type='http', auth='user', methods=['GET'], sitemap=False)
    def api_member_duos(self, member_id, **kwargs):
        self._api_viewer()
        member = self._api_member(member_id)
        return _json([{
            'partner_id': (pair.member_b_id if pair.member_a_id == member else pair.member_a_id).id,
            'name': pair.name, 'matches': pair.matches, 'wins': pair.wins, 'chemistry': pair.chemistry,
            'last5': pair.last5, 'duo_tier': pair.duo_tier,
        } for pair in member._gm_duo_pairs()])

    @http.route('/club/api/members/<int:member_id>/rivals', type='http', auth='user', methods=['GET'],
                sitemap=False)
    def api_member_rivals(self, member_id, **kwargs):
        self._api_viewer()
        member = self._api_member(member_id)
        rows = []
        for rivalry in member._gm_rivals():
            mine, theirs, other = rivalry._score_for(member)
            rows.append({'rival_id': other.id, 'name': other.name, 'wins': mine, 'losses': theirs,
                         'last5': rivalry.last5 or []})
        return _json(rows)

    @http.route('/club/api/members/<int:member_id>/card/share.png', type='http', auth='user', methods=['GET'],
                sitemap=False)
    def api_member_share_png(self, member_id, card=None, **kwargs):
        member = self._api_owner(member_id)
        instance = self._share_card(member, card)
        png = member._render_share_png(card=instance)
        if not png:
            raise NotFound()
        return request.make_response(png, [
            ('Content-Type', 'image/png'),
            ('Content-Disposition', f'attachment; filename="card-{member.id}.png"'),
            ('Cache-Control', 'no-store'),
        ])

    @staticmethod
    def _share_card(member, card_id):
        if not card_id:
            return None
        card = request.env['pickleball.card.instance'].sudo().browse(int(card_id)).exists()
        if not card or (card.member_id != member and member not in (
                card.duo_pair_id.member_a_id | card.duo_pair_id.member_b_id)):
            raise NotFound()
        return card

    @http.route('/club/api/weekly/totw', type='http', auth='user', methods=['GET'], sitemap=False)
    def api_totw(self, week=None, **kwargs):
        self._api_viewer()
        domain = [('type_code', '=', 'TOTW')]
        if week:
            domain.append(('period_key', '=', week))
        cards = request.env['pickleball.card.instance'].sudo().search(domain, order='earned_at desc', limit=None if week else 10)
        return _json([{'week': c.period_key, 'member_id': c.member_id.id, 'name': c.member_id.name,
                       'points': (c.source or {}).get('points'), 'matches': (c.source or {}).get('matches')}
                      for c in cards])

    def _season_payload(self, season, me=None):
        if not season:
            return None
        payload = {'id': season.id, 'code': season.code, 'number': season.number,
                   'start': fields.Date.to_string(season.date_start), 'end': fields.Date.to_string(season.date_end),
                   'state': season.state}
        if me:
            stat = me._gm_season_stat(season)
            payload['me'] = {'xp': stat.xp, 'level': stat.level, 'rank': stat.rank} if stat else None
        return payload

    @http.route('/club/api/seasons/current', type='http', auth='user', methods=['GET'], sitemap=False)
    def api_season_current(self, **kwargs):
        me, _is_admin = self._api_viewer()
        return _json(self._season_payload(request.env['pickleball.season'].sudo()._get_current(), me))

    @http.route('/club/api/seasons/<int:season_id>/leaderboard', type='http', auth='user', methods=['GET'],
                sitemap=False)
    def api_season_leaderboard(self, season_id, **kwargs):
        self._api_viewer()
        season = request.env['pickleball.season'].sudo().browse(season_id).exists()
        if not season:
            raise NotFound()
        return _json([{'rank': s.rank, 'member_id': s.member_id.id, 'name': s.member_id.name, 'xp': s.xp,
                       'level': s.level, 'matches': s.matches, 'wins': s.wins} for s in season.stat_ids])

    @http.route('/club/api/seasons/<int:season_id>/awards', type='http', auth='user', methods=['GET'],
                sitemap=False)
    def api_season_awards(self, season_id, **kwargs):
        self._api_viewer()
        season = request.env['pickleball.season'].sudo().browse(season_id).exists()
        if not season:
            raise NotFound()
        return _json([{'code': c.type_code, 'name': c.card_type_id.name,
                       'member_id': c.member_id.id or False, 'duo': c.duo_pair_id.name or False}
                      for c in season.award_ids if c.type_code != 'SEASON'])

    def _me_or_forbidden(self):
        me, _is_admin = self._api_viewer()
        if not me:
            raise Forbidden()
        return me

    @http.route('/club/api/me/challenges', type='http', auth='user', methods=['GET'], sitemap=False)
    def api_me_challenges(self, week=None, **kwargs):
        me = self._me_or_forbidden()
        return _json([{'code': c.template_code, 'difficulty': c.difficulty, 'label': c.label, 'target': c.target,
                       'progress': c.progress, 'state': c.state} for c in me._gm_challenges(week)])

    @http.route('/club/api/me/evolutions', type='http', auth='user', methods=['GET'], sitemap=False)
    def api_me_evolutions(self, **kwargs):
        me = self._me_or_forbidden()
        evo = me._gm_evolution()
        tracks = request.env['pickleball.evolution.track'].sudo().search([])
        return _json({
            'current': {'track': evo.track_code, 'stage': evo.stage, 'stage_progress': evo.stage_progress,
                        'state': evo.state} if evo else None,
            'tracks': [{'code': t.code, 'name': t.name, 'description': t.description, 'stages': t._stage_labels()}
                       for t in tracks],
        })

    @http.route('/club/api/me/evolutions', type='json', auth='user', methods=['POST'])
    def api_me_start_evolution(self, track_code=None, **kwargs):
        me = self._me_or_forbidden()
        try:
            evo = me._gm_start_evolution(track_code)
        except ValidationError as error:
            return {'error': error.args[0]}
        return {'track': evo.track_code, 'stage': evo.stage}

    def _reveal_payload(self, reveal, me):
        payload = dict(reveal.payload or {})
        data = {'id': reveal.id, 'kind': reveal.kind, 'payload': payload}
        if reveal.kind == 'toast':
            text = str(TOAST_MESSAGES.get(payload.get('message'), ''))
            try:
                text = text % payload if '%(' in text else text
            except (KeyError, TypeError, ValueError):
                pass
            if payload.get('badge'):
                badge = request.env['pickleball.badge.type'].sudo().search([('code', '=', payload['badge'])], limit=1)
                text = f"{text}: {badge.name} {'★' * int(payload.get('level') or 1)}"
            if payload.get('template'):
                template = request.env['pickleball.challenge.template'].sudo().search(
                    [('code', '=', payload['template'])], limit=1)
                text = f"{text}: {template._label(payload.get('target') or '')}"
            data['text'] = text
            return data
        card = reveal.card_instance_id
        if reveal.kind == 'tier_up' or card.category == 'tier':
            card = request.env['pickleball.card.instance']  # empty: the current tier card, whatever the showcase
        elif not card:
            card = None  # the showcase card
        view = me._gm_card_view(card=card, viewer=me)
        data['card_html'] = str(request.env['ir.ui.view']._render_template(
            'pickleball_website.player_card', dict(self._values('none'), member=me, card=view, motif_size='lg')))
        data['old_ovr'] = payload.get('old_ovr')
        data['new_ovr'] = payload.get('new_ovr') or view['ovr']
        data['share_url'] = f'/club/api/members/{me.id}/card/share.png' + (f'?card={card.id}' if card else '')
        data['album_url'] = f'/club/players/{me.id}/album'
        return data

    @http.route('/club/api/me/reveals', type='http', auth='user', methods=['GET'], sitemap=False)
    def api_me_reveals(self, **kwargs):
        me = self._me_or_forbidden()
        return _json([self._reveal_payload(reveal, me) for reveal in me._gm_reveals()[:20]])

    @http.route('/club/api/me/reveals/<int:reveal_id>/seen', type='json', auth='user', methods=['POST'])
    def api_me_reveal_seen(self, reveal_id, **kwargs):
        me = self._me_or_forbidden()
        reveal = request.env['pickleball.reveal'].sudo().browse(reveal_id).exists()
        if not reveal or reveal.member_id != me:
            raise NotFound()
        reveal.seen_at = reveal.seen_at or fields.Datetime.now()
        return {'ok': True}

    @http.route('/club/api/admin/gamification/settings', type='json', auth='user', methods=['POST', 'PATCH'])
    def api_admin_settings(self, config=None, **kwargs):
        if not request.env.user.has_group('base.group_system'):
            raise Forbidden()
        if config is not None:
            settings = request.env['pickleball.gamification.settings'].create(
                {'config_text': json.dumps(config)})
            settings.action_save()
        return {'config': request.env.company.sudo().pickleball_gm_config or {}}

    @http.route('/club/api/admin/gamification/rebuild', type='json', auth='user', methods=['POST'])
    def api_admin_rebuild(self, **kwargs):
        if not request.env.user.has_group('base.group_system'):
            raise Forbidden()
        return {'stats': request.env['pickleball.gamification']._gm_rebuild()}

    # ── Pages ─────────────────────────────────────────────────────────────

    @http.route('/club/players/<int:member_id>/album', type='http', auth='user', website=True, sitemap=False)
    def club_album(self, member_id, **kwargs):
        denied = self._check_club_access()
        if denied:
            return denied
        player = self._api_member(member_id)
        me = self._me()
        values = self._values('players', player=player, album=player._gm_album(), is_owner=player == me,
                              duos=player._gm_duo_pairs())
        return request.render('pickleball_website.club_album', values)

    @http.route('/club/cards', type='http', auth='user', website=True, sitemap=False)
    def club_cards(self, **kwargs):
        """Every card of the game, by category (members only: visitors get a
        teaser on the home page). Tap a card to flip it: how to earn it.
        Members see the cards on their own player card and which ones they own."""
        denied = self._check_club_access()
        if denied:
            return denied
        me = self._me()
        Card = request.env['pickleball.card.instance'].sudo()
        types = request.env['pickleball.card.type'].sudo().search([])
        today = fields.Date.context_today(request.env.user)
        owned = {}
        if me:
            member = me
            base = me._gm_card_view(card=Card, finance=False)
            for card in Card.search([('member_id', '=', me.id)]) | Card.search(
                    [('duo_pair_id', 'in', me._gm_duo_pairs().ids)]):
                owned.setdefault(card.card_type_id.id, Card)
                owned[card.card_type_id.id] |= card
        else:  # admins without a member profile
            member = demo_players()[1]
            base = demo_card_view(member)
        labels = dict(types._fields['category']._description_selection(request.env))
        sections = []
        # tier steps shown at their OVR: 2 above the step's minimum (the
        # lowest step, from 0: 5 below the next one)
        tier_from = [t._gm_back_info()['ovr_from'] for t in types if t.category == 'tier']
        next_from = dict(zip(tier_from, tier_from[1:]))
        for category in ('tier', 'special', 'season', 'evo', 'duo'):
            items = []
            for card_type in types.filtered(lambda t, cat=category: t.category == cat):
                info = card_type._gm_back_info()
                view = copy.deepcopy(base)
                if info['ovr_from'] is not None:
                    low = info['ovr_from'] or max(next_from.get(0, 60) - 5, 1)
                    shift_ovr(view, min(99, low + 2))
                apply_preview(view, card_type._gm_preview(today.month), demo_label(card_type, today), member=member)
                cards = owned.get(card_type.id, Card)
                items.append({'type': card_type, 'card': view, 'info': info, 'owned': len(cards),
                              'last': max(cards.mapped('earned_at')).date() if cards else None})
            if items:
                sections.append({'category': category, 'label': labels[category], 'items': items})
        values = self._values('cards', sections=sections, card_member=member, owned_count=len(owned),
                              total_count=len(types))
        return request.render('pickleball_website.club_cards', values)

    # ── Card motif lab (admins): every special card's motif, all sizes ─────

    MOTIF_SAMPLE_DATA = {
        'POTM': {'month': 11},
        'IN_FORM': {'streak': 5},
        'GIANT_SLAYER': {'ovr_gap': 8},
        'ROOKIE': {'matches': 3},
    }

    def _motif_lab_cards(self):
        """One sample card per special card with a motif (sample players,
        sample data), with and without the optional data."""
        types = request.env['pickleball.card.type'].sudo().search([('code', 'in', list(card_motif_codes()))])
        by_code = {card_type.code: card_type for card_type in types}
        today = fields.Date.context_today(request.env.user)
        players = demo_players()
        cards = []
        for index, code in enumerate(card_motif_codes()):
            card_type = by_code.get(code)
            if not card_type:
                continue
            player = players[index % len(players)]
            view = demo_card_view(player, card_type._gm_preview(11), demo_label(card_type, today))
            sample = self.MOTIF_SAMPLE_DATA.get(code, {})
            data = dict(view.get('motif_data') or {})
            if 'streak' in sample:
                data.update(streak=sample['streak'], streak_label=str(_lt("%s wins in a row")) % sample['streak'])
            if 'ovr_gap' in sample:
                data.update(ovr_gap=sample['ovr_gap'], gap_label=f"\u2212{sample['ovr_gap']} OVR")
            if 'matches' in sample:
                data.update(matches=sample['matches'], target=10,
                            rookie_label=str(_lt("%(matches)s/%(target)s matches")) % {
                                'matches': sample['matches'], 'target': 10})
            if 'month' in sample:
                data['month'] = sample['month']
            view['motif_data'] = data
            # without the optional data: what a card shows when it is missing
            bare = dict(view, motif_data={key: value for key, value in data.items() if key in ('ovr', 'serial')})
            cards.append({'code': code, 'type': card_type, 'member': player, 'card': view, 'bare': bare})
        return cards

    # Icon samples: three members (three skies, three hues), the first one
    # drawn again (same card), and a lost Icon
    MOTIF_LAB_ICONS = [
        ('ICON_A', 9101, 1, False), ('ICON_B', 9102, 2, False), ('ICON_C', 9103, 3, False),
        ('ICON_A2', 9101, 1, False), ('ICON_LOST', 9102, 2, True),
    ]

    def _motif_lab_icons(self):
        icon_type = request.env['pickleball.card.type'].sudo().search([('code', '=', 'ICON')], limit=1)
        if not icon_type:
            return []
        gm = request.env['pickleball.gamification'].sudo()
        players = demo_players()
        cards = []
        for index, (code, member_id, number, former) in enumerate(self.MOTIF_LAB_ICONS):
            player = players[index % len(players)]
            view = demo_card_view(player, icon_type._gm_preview(), ovr=91)
            data = {'member_id': member_id, 'earned_at': '2026-11-12', 'icon_number': number, 'former': former,
                    'engraving': f'ICON · #{number:02d} · 12.11.2026'}
            view.update(motif_code='ICON', motif_data=data, style=gm._gm_icon_style(data))
            label = ' · '.join(filter(None, [f'Member {member_id}', 'lost Icon' if former else '',
                                             'drawn again' if code == 'ICON_A2' else '']))
            cards.append({'code': code, 'type': icon_type, 'member': player, 'card': view, 'bare': view,
                          'label': label, 'former': former})
        return cards

    @http.route('/club/dev/card-motifs', type='http', auth='user', website=True, sitemap=False)
    def club_card_motif_lab(self, **kwargs):
        if not self._is_admin():
            raise NotFound()
        icons = self._motif_lab_icons()
        cards = self._motif_lab_cards()
        Views = request.env['ir.ui.view']
        for item in cards + icons:
            html = Views._render_template('pickleball_website.player_card', dict(
                self._values('none'), member=item['member'], card=item['card'], no_photo=True, motif_size='lg'))
            icon = item['code'].startswith('ICON')
            item['reveal'] = json.dumps({
                'id': 0, 'kind': 'tier_up' if icon else 'card',
                'payload': {'old_code': 'GOLD_I', 'new_code': 'ICON'} if icon else {}, 'card_html': str(html),
                'old_ovr': max(item['card']['ovr'] - 3, 1), 'new_ovr': item['card']['ovr'],
                'share_url': f"/club/dev/card-motifs/{item['code']}.png", 'album_url': '/club/dev/card-motifs',
            })
        values = self._values('none', lab_cards=cards, lab_icons=icons,
                              stress=[(cards + icons[:3])[i % (len(cards) + 3)] for i in range(48)])
        return request.render('pickleball_website.club_card_motif_lab', values)

    @http.route('/club/dev/card-motifs/<string:code>.png', type='http', auth='user', sitemap=False)
    def club_card_motif_png(self, code, size='share', **kwargs):
        if not self._is_admin():
            raise NotFound()
        samples = self._motif_lab_cards() + self._motif_lab_icons()
        item = next((card for card in samples if card['code'] == code), None)
        if not item:
            raise NotFound()
        png = request.env['pickleball.gamification'].sudo()._gm_view_png(item['card'], share=size == 'share')
        if not png:
            raise NotFound()
        return request.make_response(png, [('Content-Type', 'image/png'), ('Cache-Control', 'no-store')])

    @http.route('/club/me/showcase', type='http', auth='user', website=True, sitemap=False, methods=['GET', 'POST'])
    def club_showcase(self, **post):
        denied = self._check_club_access()
        if denied:
            return denied
        me = self._me()
        if not me:
            return request.redirect('/club/players')
        error = saved = None
        if request.httprequest.method == 'POST':
            badges = request.httprequest.form.getlist('badges')
            try:
                me._gm_set_showcase(post.get('card_id') or False, badges, bool(post.get('show_finance_publicly')))
                saved = True
            except ValidationError as exc:
                error = exc.args[0]
        mode = me.showcase_mode or 'auto'
        if mode == 'card' and not me.showcase_card_id:
            mode = 'auto'
        selected = str(me.showcase_card_id.id) if mode == 'card' else ('tier' if mode == 'tier' else '')
        options = me._gm_showcase_options()
        # One card per choice, rendered here: the page shows the picked one.
        previews = {'': me._gm_card_view(viewer=me, showcase_mode='auto'),
                    'tier': me._gm_card_view(viewer=me, showcase_mode='tier')}
        for section in options:
            for instance in section['cards']:
                previews[str(instance.id)] = me._gm_card_view(card=instance, viewer=me)
        values = self._values('me', options=options, previews=previews, selected=selected,
                              tier_label=previews['tier']['tier_label'],
                              badges=[row for row in me._gm_badges() if row['level']], error=error, saved=saved)
        return request.render('pickleball_website.club_showcase', values)

    @http.route(['/club/season', '/club/season/<int:season_id>'], type='http', auth='user', website=True,
                sitemap=False)
    def club_season(self, season_id=None, **kwargs):
        denied = self._check_club_access()
        if denied:
            return denied
        Season = request.env['pickleball.season'].sudo()
        season = Season.browse(season_id).exists() if season_id else Season._get_current()
        gm = request.env['pickleball.gamification']
        values = self._values(
            'season', season=season, seasons=Season.search([]),
            next_season=gm.sudo()._gm_season() if not season else None,
            season_start=gm.sudo()._gm_config()['season_start'],
            awards=season.award_ids.filtered(lambda c: c.type_code != 'SEASON') if season else [],
            my_stat=self._me()._gm_season_stat(season) if self._me() and season else None,
        )
        return request.render('pickleball_website.club_season', values)

    @http.route('/club/me/evolution', type='http', auth='user', website=True, sitemap=False, methods=['POST'])
    def club_start_evolution(self, track_code=None, **post):
        denied = self._check_club_access()
        if denied:
            return denied
        me = self._me()
        if me and track_code:
            try:
                me._gm_start_evolution(track_code)
            except ValidationError:
                pass
        return request.redirect('/club/me#o_pbw_evolution')
