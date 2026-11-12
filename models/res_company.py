from odoo import SUPERUSER_ID, fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    pickleball_chat_admin_ids = fields.Many2many(
        'res.users', 'pickleball_chat_admin_user_rel', 'company_id', 'user_id',
        string='Website Chat Admins',
        domain=[('share', '=', False)],
        help='Admins who receive the messages members send from the chat bubble '
             'of the club website (in Discuss). Empty: every Settings administrator.',
    )

    def _get_pickleball_chat_admins(self):
        """Internal users who get the members' website chat messages: the
        configured ones, else every Settings administrator."""
        self.ensure_one()
        company = self.sudo()
        admins = company.pickleball_chat_admin_ids.filtered(lambda user: user.active and not user.share)
        if admins:
            return admins
        bot = self.env.ref('pickleball-team.user_pickleball_ai_bot', raise_if_not_found=False)
        return self.env.ref('base.group_system').sudo().users.filtered(
            lambda user: user.active and not user.share and user.id != SUPERUSER_ID
            and (not bot or user.id != bot.id))
