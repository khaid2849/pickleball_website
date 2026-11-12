{
    'name': 'Pickleball Club Website',
    'version': '18.0.1.15.0',
    'category': 'Website',
    'summary': 'Members-only club website: schedule, player cards, rankings, matches and finance',
    'description': """
Pickleball Club Website
=======================
A sports-style website for the team, in the same flat poster theme as the
member player cards:

- Public club home page (next session, club numbers, top players)
- Members area (login required): dashboard, schedule and session details,
  player cards and profiles, rankings, match results, team finance
- Tournaments (information only): rules, teams, schedule, standings, bracket
- Session page: admins build the matches by dragging players into teams
- Website accounts for members (portal users linked to pickleball.member),
  granted by an admin with the "Grant Website Access" wizard
- Chat bubble for logged-in members: instant answers to frequent questions,
  the team's AI assistant, and a conversation with the admins (Discuss)
- Password change from "Edit my profile", confirmed by email
- Player card gamification: tier progress, walkouts, album and showcase
- Badges, duos, rivals, season leaderboard, weekly challenges, Evolution
- Card share image and a JSON API under /club/api
    """,
    'author': 'Khaid',
    'depends': ['website', 'portal', 'auth_signup', 'mail', 'pickleball-team'],
    'data': [
        'security/club_security.xml',
        'security/ir.model.access.csv',
        'data/website_menu_data.xml',
        'data/mail_template_data.xml',
        'wizard/website_access_wizard_views.xml',
        'views/pickleball_member_views.xml',
        'views/templates_layout.xml',
        'views/templates_components.xml',
        'views/templates_home.xml',
        'views/templates_dashboard.xml',
        'views/templates_schedule.xml',
        'views/templates_players.xml',
        'views/templates_rankings.xml',
        'views/templates_finance.xml',
        'views/templates_register.xml',
        'views/templates_profile.xml',
        'views/templates_tournament.xml',
        'views/templates_chat.xml',
        'views/templates_gamification.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'pickleball-team/static/src/scss/player_card.scss',
            'pickleball-team/static/src/scss/card_motif.scss',
            'pickleball_website/static/src/scss/club.scss',
            'pickleball_website/static/src/scss/tournament.scss',
            'pickleball_website/static/src/scss/match_builder.scss',
            'pickleball_website/static/src/js/session_match_builder.js',
            'pickleball_website/static/src/js/session_match_builder.xml',
            'pickleball_website/static/src/scss/club_chat.scss',
            'pickleball_website/static/src/js/club_chat.js',
            'pickleball_website/static/src/js/club_chat.xml',
            'pickleball_website/static/src/scss/gamification.scss',
            'pickleball_website/static/src/js/card_motif.js',
            'pickleball_website/static/src/js/club_walkout.js',
            'pickleball_website/static/src/js/card_motif_lab.js',
            'pickleball_website/static/src/js/club_showcase.js',
            'pickleball_website/static/src/js/club_flip.js',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'icon': '/pickleball_website/static/description/icon.png',
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
