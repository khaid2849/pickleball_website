from odoo import api, fields, models


class PickleballAiConversation(models.Model):
    _inherit = 'pickleball.ai.conversation'

    source = fields.Selection(
        selection_add=[('website', 'Club Website')],
        ondelete={'website': 'cascade'},
    )

    @api.model
    def _get_or_create_for_website(self, user, conversation_id: int | None = None):
        """The website chat bubble's AI conversation of ``user`` (sudo): the
        given one when it is theirs, else a new one."""
        # sudo: portal users have no access to the AI conversations; the
        # search is limited to the user's own website conversations.
        Conversation = self.sudo()
        if conversation_id:
            conversation = Conversation.search([
                ('id', '=', int(conversation_id)),
                ('user_id', '=', user.id),
                ('source', '=', 'website'),
            ], limit=1)
            if conversation:
                return conversation
        return Conversation.create({'user_id': user.id, 'source': 'website'})
