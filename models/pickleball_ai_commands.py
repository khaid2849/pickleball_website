from odoo import models

# Bots whose command replies end with a link to the club website, set in the
# system parameter below as a comma-separated list ("telegram,zalo").
LINK_CHANNELS_PARAM = 'pickleball_website.bot_website_link_channels'
DEFAULT_LINK_CHANNELS = 'telegram,zalo'

# command -> what the member finds on the website (the link always goes to
# the home page of the club website).
FOOTER_TEXTS = {
    'help': "Xem thẻ cầu thủ, lịch, xếp hạng và tài chính của bạn",
    'session': "Xem lịch thi đấu, người tham gia và kết quả",
    'balance': "Xem chi tiết công nợ và lịch sử đóng tiền",
    'qr': "Xem các khoản cần đóng và lịch sử chuyển khoản",
    'unpaid': "Xem chi tiết công nợ của bạn",
    'summary': "Xem chi tiết chia tiền buổi chơi",
    'history': "Xem toàn bộ lịch sử buổi chơi",
    'ranking': "Xem bảng xếp hạng đầy đủ",
    'members': "Xem thẻ cầu thủ của cả đội",
    'member': "Xem hồ sơ và thống kê chi tiết",
}


class PickleballAiCommands(models.AbstractModel):
    _inherit = 'pickleball.ai.commands'

    def _command_footer(self, command, args, member, channel):
        """Point the member to the home page of the club website for more
        details (members without a website account sign up from there)."""
        footer = super()._command_footer(command, args, member, channel)
        text = FOOTER_TEXTS.get(command)
        if footer or not text or not self._website_link_enabled(channel):
            return footer
        member = member.sudo() if member else member
        if member and member.user_id:
            return f"🌐 {text}: {self._club_home_url()}"
        return f"🌐 {text} trên website của đội (tạo tài khoản ngay ở trang chủ): {self._club_home_url()}"

    def _website_link_enabled(self, channel):
        if not channel:
            return False
        channels = self.env['ir.config_parameter'].sudo().get_param(LINK_CHANNELS_PARAM, DEFAULT_LINK_CHANNELS)
        return channel in {name.strip().lower() for name in (channels or '').split(',')}

    def _club_home_url(self):
        """Home page of the club website, e.g. https://khaid.tail18735e.ts.net/"""
        website = self.env['website'].sudo().get_current_website()
        return f"{website.get_base_url().rstrip('/')}/"
