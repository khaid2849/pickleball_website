from odoo import models


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _get_pickleball_member(self):
        """The pickleball member this user logs in as (empty recordset if none)."""
        self.ensure_one()
        # sudo: portal users have no access to pickleball.member; this only
        # resolves which member the current user is.
        # Inactive too: a new member stays archived until they confirm their email.
        return self.env['pickleball.member'].sudo().with_context(active_test=False).search(
            [('user_id', '=', self.id)], limit=1)
