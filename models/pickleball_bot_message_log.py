from odoo import fields, models


class PickleballBotMessageLog(models.Model):
    _inherit = 'pickleball.bot.message.log'

    source = fields.Selection(
        selection_add=[('website', 'Website Sign-up')],
        ondelete={'website': 'set null'},
    )
