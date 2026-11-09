# Header elements of a fresh website that make no sense for the club (a
# "Contact Us" button, a search bar, a placeholder phone number). Turning
# them off is what the website editor's header options do.
_UNUSED_HEADER_VIEWS = (
    'website.header_call_to_action',
    'website.header_search_box',
    'website.header_text_element',
)


def setup_languages(env):
    """Vietnamese (default) and English on every website, with the
    translations of all installed modules loaded for Vietnamese. The website
    language selector shows up once a website has two languages."""
    vietnamese = env['res.lang']._activate_lang('vi_VN')
    english = env.ref('base.lang_en')
    env['ir.module.module'].search([('state', '=', 'installed')])._update_translations(['vi_VN'])
    for website in env['website'].search([]):
        website.language_ids |= vietnamese | english
        website.default_lang_id = vietnamese
        # Visitors get the public user's language when they have no
        # language cookie yet: without this, the site opens in English.
        website.user_id.sudo().lang = vietnamese.code
        # The default "Home" menu, in both languages.
        for menu in env['website.menu'].search([('website_id', '=', website.id), ('url', '=', '/')]):
            menu.with_context(lang='en_US').name = 'Home'
            menu.with_context(lang='vi_VN').name = 'Trang chủ'


MEMBER_MENU_URLS = ('/club/schedule', '/club/players', '/club/rankings', '/club/matches', '/club/finance')


MEMBER_MENU_XMLIDS = (
    'pickleball_website.menu_club_schedule',
    'pickleball_website.menu_club_players',
    'pickleball_website.menu_club_rankings',
    'pickleball_website.menu_club_matches',
    'pickleball_website.menu_club_finance',
)


def sync_menu_names(env):
    """Odoo copies the menus of the default main menu into each website once;
    later data updates only change the originals. Copy their names (in both
    languages) onto the websites' menus. Migrations and install hooks run
    before Odoo loads the module's .po files, so load them first."""
    if env['res.lang']._lang_get('vi_VN'):
        env['ir.module.module'].search([('name', '=', 'pickleball_website')])._update_translations(
            ['vi_VN'], overwrite=True)
    for xmlid in MEMBER_MENU_XMLIDS:
        original = env.ref(xmlid, raise_if_not_found=False)
        if not original:
            continue
        copies = env['website.menu'].search([('url', '=', original.url), ('website_id', '!=', False)])
        for lang in ('en_US', 'vi_VN'):
            copies.with_context(lang=lang).name = original.with_context(lang=lang).name


def setup_member_access(env):
    """Visitors only see the home page; accounts are created with the club
    sign-up page, so Odoo's own /web/signup (open to anyone in "b2c") is
    turned off. Accounts granted before sign-up approval existed are
    approved."""
    member_group = env.ref('pickleball_website.group_club_member')
    logged_in = member_group | env.ref('base.group_user')
    # One menu at a time, with 2-item link commands: website.menu.write
    # appends its own (3-item) command to the list it is given, then fails
    # on it for the next record.
    for menu in env['website.menu'].search([('url', 'in', MEMBER_MENU_URLS)]):
        # Portal users (set by 1.2.0) include accounts still waiting for approval.
        menu.write({'group_ids': [(3, env.ref('base.group_portal').id)]})
        menu.write({'group_ids': [(4, group.id) for group in logged_in]})
    sync_menu_names(env)
    env['ir.config_parameter'].sudo().set_param('auth_signup.invitation_scope', 'b2b')
    Member = env['pickleball.member'].with_context(active_test=False)
    Member.search([('user_id', '!=', False), ('website_state', '=', False)]).write({'website_state': 'approved'})
    Member.search([('user_id', '!=', False)])._sync_club_member_group()


def post_init_hook(env):
    """Turn the default website into the club site: the club home page as
    "/", a club name instead of the placeholder, no generic "Contact us"
    page nor placeholder header elements, Vietnamese + English."""
    for xmlid in _UNUSED_HEADER_VIEWS:
        view = env.ref(xmlid, raise_if_not_found=False)
        if view:
            view.active = False
    for website in env['website'].search([]):
        vals = {'homepage_url': '/club'}
        if website.name in ('My Website', 'Website'):
            vals['name'] = 'The Paddy Shack'
        website.write(vals)
        env['website.menu'].search([('website_id', '=', website.id), ('url', '=', '/contactus')]).unlink()
    setup_languages(env)
    setup_member_access(env)
