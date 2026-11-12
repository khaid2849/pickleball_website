import re

from odoo.exceptions import UserError
from odoo.tests import Form, HttpCase, TransactionCase, tagged

from ..controllers.club import vnd

MEMBER_PAGES = ['/club/me', '/club/schedule', '/club/players', '/club/rankings', '/club/matches', '/club/finance']


class ClubDataMixin:

    @classmethod
    def _create_club_data(cls):
        Member = cls.env['pickleball.member']
        cls.an = Member.create({'name': 'Web Nguyễn Văn An', 'gender': 'male', 'jersey_number': 8})
        cls.binh = Member.create({'name': 'Web Trần Bình', 'gender': 'female'})
        cls.chi = Member.create({'name': 'Web Lê Chi'})
        cls.dung = Member.create({'name': 'Web Dũng'})
        cls.court = cls.env['pickleball.court'].create({'name': 'Web Court', 'address': '1 Pickle St'})
        cls.play_session = cls.env['pickleball.session'].create({
            'date': '2026-01-10',
            'court_id': cls.court.id,
            'booker_id': cls.an.id,
            'participant_ids': [(6, 0, (cls.an | cls.binh | cls.chi | cls.dung).ids)],
            'court_fee': 400000,
        })
        cls.env['pickleball.match.bet'].create({
            'session_id': cls.play_session.id,
            'team1_member_ids': [(6, 0, (cls.an | cls.binh).ids)],
            'team2_member_ids': [(6, 0, (cls.chi | cls.dung).ids)],
            'bet_amount': 20000,
            'winner': 'team1',
        })
        cls.play_session.action_confirm()
        cls.play_session.action_done()

    @classmethod
    def _grant(cls, members):
        wizard = cls.env['pickleball.website.access.wizard'].with_context(
            active_model='pickleball.member', active_ids=members.ids).create({})
        passwords = {line.member_id: (line.login, line.password) for line in wizard.line_ids}
        wizard.action_grant()
        return passwords


@tagged('post_install', '-at_install')
class TestWebsiteAccess(ClubDataMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_club_data()

    def test_grant_creates_portal_accounts(self):
        credentials = self._grant(self.an | self.binh)
        login, password = credentials[self.an]
        self.assertEqual(login, 'web.nguyen.van.an')
        self.assertEqual(len(password), 8)
        self.assertTrue(self.an.user_id._is_portal())
        self.assertEqual(self.an.user_id.login, login)
        self.assertTrue(self.an.has_website_access)
        self.assertEqual(self.an.user_id._get_pickleball_member(), self.an)
        self.assertIn(self.binh, self.env['pickleball.member'].search([('has_website_access', '=', True)]))

    def test_grant_through_the_form(self):
        """Like the UI: open the wizard from the members list and save it."""
        wizard_form = Form(self.env['pickleball.website.access.wizard'].with_context(
            active_model='pickleball.member', active_ids=(self.an | self.binh).ids))
        self.assertEqual(len(wizard_form.line_ids), 2)
        wizard = wizard_form.save()
        self.assertEqual(wizard.line_ids.member_id, self.an | self.binh)
        wizard.action_grant()
        self.assertTrue(self.an.has_website_access)
        self.assertTrue(self.binh.has_website_access)

    def test_suggested_login_is_unique(self):
        self._grant(self.an)
        twin = self.env['pickleball.member'].create({'name': 'Web Nguyễn Văn An'})
        credentials = self._grant(twin)
        self.assertEqual(credentials[twin][0], 'web.nguyen.van.an2')

    def test_regrant_keeps_account_and_revoke_archives(self):
        self._grant(self.an)
        user = self.an.user_id
        self.an.action_revoke_website_access()
        self.assertFalse(user.active)
        self.assertFalse(self.an.has_website_access)
        # Granting again re-activates the same account, with a new password.
        credentials = self._grant(self.an)
        self.assertTrue(credentials[self.an][1])
        self.assertEqual(self.an.user_id, user)
        self.assertTrue(user.active)

    def test_login_clash_is_refused(self):
        self._grant(self.an)
        wizard = self.env['pickleball.website.access.wizard'].with_context(
            active_model='pickleball.member', active_ids=self.binh.ids).create({})
        wizard.line_ids.login = self.an.user_id.login
        with self.assertRaises(UserError):
            wizard.action_grant()


@tagged('post_install', '-at_install')
class TestClubPages(ClubDataMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_club_data()
        credentials = cls._grant(cls.an)
        cls.login, cls.password = credentials[cls.an]

    def test_public_home(self):
        response = self.url_open('/club')
        self.assertEqual(response.status_code, 200)
        self.assertIn('/web/login?redirect=/club/me', response.text)
        self.assertIn('/club/register', response.text)
        # Showcase data only: no real member, no money, no members' menus.
        for member in self.an | self.binh | self.chi:
            self.assertNotIn(member.name, response.text)
        self.assertNotIn('o_pb_card_debt', response.text)
        for url in MEMBER_PAGES[1:]:
            self.assertNotIn(f'href="{url}"', response.text)

    def test_language_switch(self):
        """Vietnamese by default, English under /en."""
        website = self.env['website'].get_current_website()
        if self.env.ref('base.lang_vi_VN') not in website.language_ids:
            self.skipTest('Vietnamese is not set up on this website')
        self.assertIn('Tạo tài khoản', self.url_open('/vi/club').text)
        self.assertIn('Create my account', self.url_open('/en/club').text)

    def test_members_pages_need_login(self):
        for url in MEMBER_PAGES:
            response = self.url_open(url)
            self.assertIn('/web/login', response.url, url)

    def test_member_sees_all_pages(self):
        self.authenticate(self.login, self.password)
        for url in MEMBER_PAGES + [f'/club/schedule/{self.play_session.id}', f'/club/players/{self.binh.id}']:
            response = self.url_open(url)
            self.assertEqual(response.status_code, 200, url)
        dashboard = self.url_open('/club/me').text
        self.assertIn('Web Nguyễn Văn An', dashboard)
        session_page = self.url_open(f'/club/schedule/{self.play_session.id}').text
        self.assertIn('Web Court', session_page)

    def test_member_sees_only_own_money(self):
        """A member sees their own debts and payments, nobody else's."""
        owing = self.binh | self.chi | self.dung
        self.assertTrue(all(round(member.balance) < 0 for member in owing))
        self.authenticate(self.login, self.password)
        finance = self.url_open('/club/finance').text
        for member in owing:
            self.assertNotIn(member.name, finance)
        players = self.url_open('/club/players').text
        self.assertEqual(players.count('o_pb_card_debt o_pb_card_debt_'), 1, 'only my own card shows money')
        for member in owing:
            self.assertNotIn(vnd(-member.balance), players)
        self.assertNotIn(vnd(-self.binh.balance), self.url_open(f'/club/players/{self.binh.id}').text)
        session_page = self.url_open(f'/club/schedule/{self.play_session.id}').text
        self.assertEqual(session_page.count('o_pbw_settlement_row'), 1, 'only my own share of the split')

    def test_admin_sees_everyone_money(self):
        self.env['res.users'].create({
            'name': 'Web Admin', 'login': 'web.admin', 'password': 'web.admin.pw',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        self.authenticate('web.admin', 'web.admin.pw')
        finance = self.url_open('/club/finance').text
        for member in self.binh | self.chi | self.dung:
            self.assertIn(member.name, finance)
            self.assertIn(vnd(-member.balance), finance)
        session_page = self.url_open(f'/club/schedule/{self.play_session.id}').text
        self.assertEqual(session_page.count('o_pbw_settlement_row'), len(self.play_session.settlement_ids))

    def test_portal_user_without_member_is_refused(self):
        self.env['res.users'].create({
            'name': 'Web Stranger', 'login': 'web.stranger', 'password': 'web.stranger.pw',
            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.authenticate('web.stranger', 'web.stranger.pw')
        self.assertEqual(self.url_open('/club/players').status_code, 403)
        self.assertEqual(self.url_open(f'/club/photo/{self.an.id}').status_code, 404)

    def test_player_cards_link_to_profiles(self):
        self.authenticate(self.login, self.password)
        page = self.url_open('/club/players').text
        self.assertRegex(page, rf'<a (?=[^>]*href="[^"]*/club/players/{self.binh.id}")[^>]*class="o_pbw_card_link o_pbw_card_link_active"')

    def _post_login(self, login, password):
        self.authenticate(None, None)
        page = self.url_open('/web/login')
        csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        return self.url_open('/web/login', data={
            'login': login, 'password': password, 'csrf_token': csrf_token,
        }, allow_redirects=False)

    def test_login_with_email(self):
        self.assertIn('Username or email', self.url_open('/en/web/login').text)
        user = self.an.user_id
        user.email = 'Web.An@Example.com'
        for login in (user.login, 'web.an@example.com', ' WEB.AN@example.com '):
            response = self._post_login(login, self.password)
            self.assertIn(response.status_code, (302, 303), login)
            self.assertTrue(response.headers['Location'].endswith('/club/me'), login)
        self.assertEqual(self._post_login('web.an@example.com', 'wrong-password').status_code, 200)

    def test_login_email_must_be_unique(self):
        Users = self.env['res.users']
        user = self.an.user_id
        user.email = 'web.shared@example.com'
        self.assertEqual(Users._get_login_domain('web.shared@example.com'), [('id', '=', user.id)])
        # Two accounts with the same email: the email logs nobody in.
        self._grant(self.binh)
        self.binh.user_id.email = 'web.shared@example.com'
        self.assertFalse(Users.search(Users._get_login_domain('web.shared@example.com')))
        # The username always wins over an email.
        self.binh.user_id.login = 'web.shared@example.com'
        self.assertEqual(Users.search(Users._get_login_domain('web.shared@example.com')), self.binh.user_id)
        # Archived accounts are not found by their email.
        self.binh.user_id.login = 'web.binh'
        self.binh.user_id.active = False
        self.assertEqual(Users.search(Users._get_login_domain('web.shared@example.com')), user)

    def test_login_lands_on_dashboard(self):
        page = self.url_open('/web/login')
        csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        response = self.url_open('/web/login', data={
            'login': self.login, 'password': self.password, 'csrf_token': csrf_token,
        }, allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertTrue(response.headers['Location'].endswith('/club/me'), response.headers['Location'])
