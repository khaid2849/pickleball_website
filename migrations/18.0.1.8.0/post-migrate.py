import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """1.8.0: accounts granted by an admin had no email; they get their
    member's email (it logs in too), unless another account uses it."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    members = env['pickleball.member'].with_context(active_test=False).search(
        [('user_id', '!=', False), ('email', '!=', False)])
    for member in members.filtered(lambda m: not m.user_id.email):
        if member._website_email_taken(member.email):
            _logger.info("Member %s: email not copied to account %s, another account uses it",
                         member.id, member.user_id.login)
        else:
            member.user_id.email = member.email
