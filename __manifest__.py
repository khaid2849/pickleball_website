{
    'name': 'Pickleball Club Website',
    'version': '18.0.1.3.0',
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
- Website accounts for members (portal users linked to pickleball.member),
  granted by an admin with the "Grant Website Access" wizard
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
    ],
    'assets': {
        'web.assets_frontend': [
            'pickleball-team/static/src/scss/player_card.scss',
            'pickleball_website/static/src/scss/club.scss',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'icon': '/pickleball_website/static/description/icon.png',
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
