import io
import re
from unittest.mock import patch

from PIL import Image

from odoo.tests import HttpCase, tagged

from ..models.pickleball_member import TelegramClient
from .test_club_website import ClubDataMixin


def png_bytes(color='red'):
    buffer = io.BytesIO()
    Image.new('RGB', (40, 40), color).save(buffer, 'PNG')
    return buffer.getvalue()


@tagged('post_install', '-at_install')
class TestClubProfile(ClubDataMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_club_data()
        cls.an.write({'dupr_rating': 3.5, 'bank_holder_name': False})
        cls.binh.write({'bank_account': '0123 456 789', 'bank_holder_name': 'TRAN THI BINH'})
        credentials = cls._grant(cls.an)
        cls.login, cls.password = credentials[cls.an]
        cls.manager = cls.env['pickleball.member'].create({
            'name': 'Prof Captain', 'is_bot_manager': True, 'telegram_chat_id': '55501'})
        cls.env['pickleball.ai.telegram.config'].create({
            'name': 'Prof Bot', 'bot_token': '1:prof', 'is_active': True})

    def setUp(self):
        super().setUp()
        self.telegram_send = self.startPatcher(
            patch.object(TelegramClient, 'send_message', autospec=True, return_value=True))

    def _form(self, **fields):
        data = {
            'name': 'Web Nguyễn Văn An', 'gender': 'male', 'play_style': 'dink', 'jersey_number': '8',
            'email': 'an.new@example.com', 'phone': '0909 111 222',
            'bank_name': '', 'bank_account': '', 'bank_holder_name': '',
        }
        data.update(fields)
        return data

    def _post(self, files=None, **fields):
        self.authenticate(self.login, self.password)
        page = self.url_open('/club/me/edit')
        self.assertEqual(page.status_code, 200)
        data = self._form(**fields)
        data['csrf_token'] = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        response = self.url_open('/club/me/edit', data=data, files=files)
        self.an.invalidate_recordset()
        return response

    def _notices(self):
        return [call.args[2] for call in self.telegram_send.call_args_list if str(call.args[1]) == '55501']

    def test_edit_personal_details(self):
        response = self._post(name='Web An Nguyễn', gender='female', play_style='net', jersey_number='23',
                              files={'photo': ('me.png', png_bytes(), 'image/png')})
        self.assertTrue(response.url.endswith('/club/me/edit?saved=1'), response.url)
        self.assertEqual((self.an.name, self.an.gender, self.an.play_style, self.an.jersey_number),
                         ('Web An Nguyễn', 'female', 'net', 23))
        self.assertEqual((self.an.email, self.an.phone), ('an.new@example.com', '0909 111 222'))
        self.assertTrue(self.an.image_128)
        # The login account follows: the new email logs in too.
        user = self.an.user_id
        self.assertEqual((user.name, user.email, user.partner_id.phone),
                         ('Web An Nguyễn', 'an.new@example.com', '0909 111 222'))
        self.assertEqual(self.env['res.users'].search(self.env['res.users']._get_login_domain('an.new@example.com')),
                         user)
        self.assertFalse(self._notices(), 'no bank change: the bot managers are not bothered')

        self._post(remove_photo='1')
        self.assertFalse(self.an.image_128)

    def test_ratings_and_money_cannot_be_changed(self):
        self._post(dupr_rating='5', telegram_chat_id='42', is_bot_manager='1', notes='hi', active='0',
                   balance='1000000', website_state='approved', user_id='1')
        self.assertEqual(self.an.dupr_rating, 3.5)
        self.assertFalse(self.an.telegram_chat_id)
        self.assertFalse(self.an.is_bot_manager)
        self.assertFalse(self.an.notes)
        self.assertTrue(self.an.active)
        self.assertNotEqual(self.an.user_id.id, 1)

    def test_edit_payment_details(self):
        response = self._post(bank_name='MB', bank_account='9988 7766 55', bank_holder_name='NGUYEN VAN AN',
                              files={'qr': ('qr.png', png_bytes('black'), 'image/png')})
        self.assertIn('saved=1', response.url)
        self.assertEqual((self.an.bank_name, self.an.bank_account, self.an.bank_holder_name),
                         ('MB', '9988 7766 55', 'NGUYEN VAN AN'))
        self.assertTrue(self.an.qr_code)
        self.assertEqual(self.url_open('/club/me/qr').headers['Content-Type'], 'image/png')
        # The bot managers are told: transfers are matched on these.
        notices = self._notices()
        self.assertEqual(len(notices), 1)
        for text in ('Web Nguyễn Văn An', 'MB', '9988 7766 55', 'NGUYEN VAN AN', 'Mã QR'):
            self.assertIn(text, notices[0])

        self.telegram_send.reset_mock()
        self._post(bank_name='MB', bank_account='9988 7766 55', bank_holder_name='NGUYEN VAN AN', remove_qr='1')
        self.assertFalse(self.an.qr_code)
        self.assertEqual(len(self._notices()), 1)
        self.assertEqual(self.url_open('/club/me/qr').status_code, 404)

    def test_bank_identity_of_another_member_is_refused(self):
        for fields, error_field in (
            ({'bank_account': '0123456789'}, 'bank_account'),          # same number as Binh
            ({'bank_holder_name': 'Trần Thị Bình'}, 'bank_holder_name'),  # same name, accents ignored
            ({'bank_holder_name': 'TRAN THI BINH CK'}, 'bank_holder_name'),  # longer name containing hers
            ({'name': 'Tran Thi Binh'}, 'name'),                         # member name used as transfer name
        ):
            response = self._post(**fields)
            self.assertEqual(response.status_code, 200, fields)
            self.assertIn('is-invalid', response.text)
            self.assertRegex(response.text, rf'name="{error_field}"[^>]*is-invalid', fields)
            self.assertFalse(self.an.bank_account, fields)
            self.assertFalse(self.an.bank_holder_name, fields)
            self.assertEqual(self.an.name, 'Web Nguyễn Văn An', fields)
        self.assertFalse(self._notices())

    def test_invalid_values_are_refused(self):
        other = self.env['res.users'].create({
            'name': 'Prof Other', 'login': 'prof.other', 'email': 'prof.other@example.com',
            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        for fields, files in (
            ({'email': other.email.upper()}, None),
            ({'email': 'not-an-email'}, None),
            ({'name': 'A'}, None),
            ({'gender': 'other'}, None),
            ({'jersey_number': '100'}, None),
            ({'bank_account': 'abc123'}, None),
            ({'bank_holder_name': 'AN 123'}, None),
            ({}, {'photo': ('x.svg', svg, 'image/svg+xml')}),
            ({}, {'qr': ('x.png', b'not an image', 'image/png')}),
        ):
            response = self._post(files=files, **fields)
            self.assertEqual(response.status_code, 200, fields or files)
            self.assertIn('is-invalid', response.text, fields or files)
            self.assertNotEqual(self.an.email, 'an.new@example.com', 'nothing saved')
            self.assertFalse(self.an.image_128)
            self.assertFalse(self.an.qr_code)

    def test_unchanged_email_used_by_another_account(self):
        """An account granted by an admin had no email, and someone else signed
        up with the member's email: saving the profile must still work."""
        self.an.email = 'an.shared@example.com'
        self.an.user_id.email = False
        other = self.env['res.users'].create({
            'name': 'Prof Other', 'login': 'prof.other2', 'email': 'an.shared@example.com',
            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        response = self._post(email='an.shared@example.com', jersey_number='12')
        self.assertIn('saved=1', response.url)
        self.assertEqual(self.an.jersey_number, 12)
        self.assertFalse(self.an.user_id.email, "not copied: the other account has it")
        self.assertEqual(other.email, 'an.shared@example.com')
        # Changing to an email another account uses is refused, with the reason listed.
        other.email = 'taken@example.com'
        response = self._post(email='taken@example.com')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.an.email, 'an.shared@example.com')
        self.assertRegex(response.text, r'<li>[^<]+</li>')

    def test_grant_copies_member_email(self):
        self.binh.email = 'binh@example.com'
        self.chi.email = 'an.new@example.com'
        self.env['res.users'].create({
            'name': 'Prof Taken', 'login': 'prof.taken', 'email': 'an.new@example.com',
            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self._grant(self.binh | self.chi)
        self.assertEqual(self.binh.user_id.email, 'binh@example.com')
        self.assertFalse(self.chi.user_id.email, 'another account already uses it')

    def test_access(self):
        self.authenticate(None, None)
        self.assertIn('/web/login', self.url_open('/club/me/edit').url)
        self.assertIn('/web/login', self.url_open('/club/me/qr').url)
        self.env['res.users'].create({
            'name': 'Prof Stranger', 'login': 'prof.stranger', 'password': 'prof.stranger.pw',
            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.authenticate('prof.stranger', 'prof.stranger.pw')
        self.assertEqual(self.url_open('/club/me/edit').status_code, 403)
        self.assertEqual(self.url_open('/club/me/qr').status_code, 404)
        # The dashboard links to it.
        self.authenticate(self.login, self.password)
        self.assertRegex(self.url_open('/club/me').text, r'href="[^"]*/club/me/edit"')
