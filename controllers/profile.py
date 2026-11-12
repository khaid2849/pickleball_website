"""A member edits their own profile on the club website (/club/me/edit).

Personal details, photo and payment details (bank account, QR code) only:
the card ratings, DUPR, money and admin fields stay with the admins.
The password can be changed too: it applies once confirmed by email.
"""
import base64
import re
import time

from werkzeug.exceptions import NotFound

from odoo import _, fields, http
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools import email_normalize
from odoo.tools.image import image_process
from odoo.tools.mimetypes import guess_mimetype

from .club import PLAY_STYLES, PickleballClub, labels
from .register import EMAIL_RE

PHONE_RE = re.compile(r'^[0-9 +().-]{8,20}$')
BANK_ACCOUNT_RE = re.compile(r'^[0-9 .-]{6,30}$')
# Names as banks print them: letters (accents ok), spaces; commas between names.
HOLDER_NAME_RE = re.compile(r'^[^\W\d_]+(?:[ .\'-]+[^\W\d_]+)*(?:\s*,\s*[^\W\d_]+(?:[ .\'-]+[^\W\d_]+)*)*$')
IMAGE_MIMETYPES = ('image/png', 'image/jpeg', 'image/webp', 'image/gif')
MAX_IMAGE_SIZE = 8 * 1024 * 1024
# Wrong current passwords allowed in the window (seconds) of one session.
PASSWORD_MAX_FAILURES = 5
PASSWORD_FAILURE_WINDOW = 15 * 60
TEXT_FIELDS = ('name', 'gender', 'play_style', 'jersey_number', 'phone', 'email',
               'bank_name', 'bank_account', 'bank_holder_name')


class ClubProfile(PickleballClub):

    def _profile_values(self, me, form=None, errors=None, saved=False, password_errors=None, password_sent=False):
        if form is None:
            form = {field: me[field] or '' for field in TEXT_FIELDS}
            form['jersey_number'] = me.jersey_number or ''
        member = me.sudo()  # sudo: the token fields are for the system only
        return self._values(
            'me', form=form, errors=errors or {}, saved=saved,
            play_styles=labels(PLAY_STYLES),
            qr_url=f'/club/me/qr?unique={int(me.write_date.timestamp())}' if me.qr_code else '',
            password_errors=password_errors or {},
            password_sent=password_sent,
            password_pending=bool(member.website_password_token
                                  and member.website_password_expiry > fields.Datetime.now()),
            account_email=member.user_id.email or '',
        )

    @http.route('/club/me/edit', type='http', auth='user', website=True, sitemap=False,
                methods=['GET', 'POST'])
    def club_profile_edit(self, **post):
        denied = self._check_club_access()
        if denied:
            return denied
        me = self._me()
        if not me:  # an admin without a member profile
            return request.redirect('/club/players')
        if request.httprequest.method != 'POST':
            return request.render('pickleball_website.club_profile_edit', self._profile_values(
                me, saved=post.get('saved') == '1', password_sent=post.get('password') == 'sent'))

        form = {field: (post.get(field) or '').strip() for field in TEXT_FIELDS}
        vals, errors = self._validate_profile(me, form, post)
        if not errors:
            errors = me._website_bank_identity_errors(vals)
        if errors:
            return request.render('pickleball_website.club_profile_edit', self._profile_values(me, form, errors))
        me._website_update_profile(vals)
        return request.redirect('/club/me/edit?saved=1')

    def _validate_profile(self, me, form, post):
        """(vals to write, errors by field) from the posted form."""
        errors = {}
        vals = {}
        if not 2 <= len(form['name']) <= 80:
            errors['name'] = _('Enter your full name.')
        vals['name'] = form['name']
        if form['gender'] not in ('male', 'female'):
            errors['gender'] = _('Pick one.')
        vals['gender'] = form['gender']
        if form['play_style'] and form['play_style'] not in PLAY_STYLES:
            errors['play_style'] = _('Pick one.')
        vals['play_style'] = form['play_style'] or False
        if form['jersey_number'] and not (form['jersey_number'].isdigit() and int(form['jersey_number']) <= 99):
            errors['jersey_number'] = _('A number from 0 to 99.')
        vals['jersey_number'] = int(form['jersey_number']) if form['jersey_number'].isdigit() else 0

        if form['phone'] and not PHONE_RE.match(form['phone']):
            errors['phone'] = _('Enter a valid phone number.')
        vals['phone'] = form['phone'] or False
        email = email_normalize(form['email'], strict=True)
        if not EMAIL_RE.match(form['email']) or not email:
            errors['email'] = _('Enter a valid email address.')
        elif email != email_normalize(me.email or '') and me._website_email_taken(email):
            # A new email only: an unchanged one never blocks saving the rest.
            errors['email'] = _('An account already uses this email.')
        vals['email'] = form['email']

        if len(form['bank_name']) > 60:
            errors['bank_name'] = _('60 characters at most.')
        vals['bank_name'] = form['bank_name'] or False
        if form['bank_account'] and not BANK_ACCOUNT_RE.match(form['bank_account']):
            errors['bank_account'] = _('Digits only (6 to 30).')
        vals['bank_account'] = form['bank_account'] or False
        if form['bank_holder_name'] and (len(form['bank_holder_name']) > 120
                                         or not HOLDER_NAME_RE.match(form['bank_holder_name'])):
            errors['bank_holder_name'] = _('Letters only, as on your bank account; separate several names with commas.')
        vals['bank_holder_name'] = form['bank_holder_name'] or False

        for field, upload, remove, size in (('image_1920', 'photo', 'remove_photo', (1920, 1920)),
                                             ('qr_code', 'qr', 'remove_qr', (1024, 1024))):
            image, error = self._read_image(post.get(upload), size)
            if error:
                errors[upload] = error
            elif image:
                vals[field] = image
            elif post.get(remove):
                vals[field] = False
        return vals, errors

    @staticmethod
    def _read_image(upload, size):
        """(base64 image, error) from an uploaded file; (False, None) if none."""
        if not upload or not getattr(upload, 'filename', None):
            return False, None
        data = upload.read(MAX_IMAGE_SIZE + 1)
        if not data:
            return False, None
        if len(data) > MAX_IMAGE_SIZE:
            return False, _('The image is too big (8 MB at most).')
        # Raster images only: no SVG (it could carry scripts).
        if guess_mimetype(data) not in IMAGE_MIMETYPES:
            return False, _('Upload a PNG, JPEG, WebP or GIF image.')
        try:
            data = image_process(data, size=size, verify_resolution=True)
        except (UserError, ValueError):
            return False, _('This image could not be read.')
        return base64.b64encode(data), None

    # ── Password (confirmed by email) ─────────────────────────────────────────

    @http.route('/club/me/password', type='http', auth='user', website=True, sitemap=False, methods=['POST'])
    def club_password_change(self, **post):
        """Ask for a new password: it applies once the member clicks the link
        emailed to their account."""
        denied = self._check_club_access()
        if denied:
            return denied
        me = self._me()
        if not me:  # an admin without a member profile
            return request.redirect('/club/players')
        current = post.get('current_password') or ''
        new = post.get('new_password') or ''
        failures = [stamp for stamp in request.session.get('pbw_password_failures', [])
                    if stamp > time.time() - PASSWORD_FAILURE_WINDOW]
        if len(failures) >= PASSWORD_MAX_FAILURES:
            errors = {'current_password': _('Too many wrong passwords: try again in 15 minutes.')}
        else:
            errors = me._website_password_errors(current, new, post.get('confirm_password') or '')
            if 'current_password' in errors and current:
                failures.append(time.time())
            request.session['pbw_password_failures'] = failures
        if not errors and not me._website_request_password_change(new, request.httprequest.host_url):
            errors = {'new_password': _('The confirmation email could not be sent, so your password was not '
                                        'changed. Try again later or ask the team admin.')}
        if errors:
            return request.render('pickleball_website.club_profile_edit',
                                  self._profile_values(me, password_errors=errors))
        return request.redirect('/club/me/edit?password=sent#pbw_password')

    @http.route('/club/me/password/confirm/<string:token>', type='http', auth='public', website=True,
                sitemap=False, methods=['GET', 'POST'])
    def club_password_confirm(self, token, **post):
        """The link of the confirmation email. Opening it shows a button: a
        mail scanner following the link can't change the password alone."""
        member = request.env['pickleball.member']._website_password_request(token)
        if not member:
            return request.render('pickleball_website.club_password_confirm', self._values('none', state='invalid'))
        if request.httprequest.method != 'POST':
            return request.render('pickleball_website.club_password_confirm',
                                  self._values('none', state='confirm', token=token, member_name=member.name))
        user = member.user_id
        member._website_apply_password_change()
        logged_in = request.session.uid == user.id
        if logged_in:
            # Keep this browser logged in: the other sessions are logged out.
            request.session.session_token = user._compute_session_token(request.session.sid)
        return request.render('pickleball_website.club_password_confirm',
                              self._values('none', state='done', logged_in=logged_in))

    @http.route('/club/me/qr', type='http', auth='user', website=True, sitemap=False)
    def club_my_qr(self, **kwargs):
        """The logged-in member's own payment QR code (for the edit page)."""
        me = self._me()
        if not me or not me.qr_code:
            raise NotFound()
        stream = request.env['ir.binary']._get_stream_from(me, 'qr_code')
        return stream.get_response(max_age=0)
