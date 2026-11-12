from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pickleball_chat_admin_ids = fields.Many2many(
        related='company_id.pickleball_chat_admin_ids', readonly=False,
    )
