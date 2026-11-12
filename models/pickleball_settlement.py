from odoo import api, models

from .pickleball_ai_commands import FOOTER_TEXTS


class PickleballSettlement(models.Model):
    _inherit = 'pickleball.settlement'

    @api.model
    def _get_debt_reminder_footer(self, channel):
        """The daily debt reminder points members to the club website, where
        they see the details of their debts (on the bots the website link is
        enabled for, like the command replies)."""
        footer = super()._get_debt_reminder_footer(channel)
        Commands = self.env['pickleball.ai.commands']
        if footer or not Commands._website_link_enabled(channel):
            return footer
        # Posted to the team group: some members have no website account yet.
        return (f"🌐 {FOOTER_TEXTS['unpaid']} trên website của đội "
                f"(chưa có tài khoản thì tạo ngay ở trang chủ): {Commands._club_home_url()}")
