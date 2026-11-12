"""Chat bubble of the club website: the "Talk to an admin" conversation.

Each member gets one Discuss group conversation with the website chat admins
(Settings > Pickleball Team > Website chat). Members write from the bubble,
admins answer from Discuss in the backend, and the bubble polls the replies.
"""
from datetime import timedelta

from odoo import Command, _, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

# A member can't flood the admins: at most this many messages in this window.
CHAT_FLOOD_LIMIT = 20
CHAT_FLOOD_WINDOW = timedelta(minutes=10)
CHAT_MAX_LENGTH = 2000
CHAT_HISTORY_LIMIT = 50


class PickleballMember(models.Model):
    _inherit = 'pickleball.member'

    website_chat_channel_id = fields.Many2one(
        'discuss.channel', string='Website Chat', copy=False, readonly=True,
        index='btree_not_null', ondelete='set null',
        help='Discuss conversation between this member and the admins, '
             'started from the chat bubble of the club website.',
    )

    def _website_chat_channel(self, create: bool = True):
        """The member's admin conversation (sudo), created on first use, with
        the current chat admins added to it."""
        self.ensure_one()
        # sudo: portal users can't read members nor create Discuss channels;
        # this only ever touches the logged-in member's own conversation.
        member = self.sudo()
        partner = member.user_id.partner_id
        if not partner:
            raise UserError(_('This member has no website account.'))
        admins = self.env.company._get_pickleball_chat_admins()
        channel = member.website_chat_channel_id
        if not channel:
            if not create:
                return channel
            channel = self.env['discuss.channel'].sudo().create({
                'name': _('Website chat: %s', member.name),
                'channel_type': 'group',
                'channel_member_ids': [Command.create({'partner_id': p.id})
                                       for p in partner | admins.partner_id],
            })
            channel._broadcast(channel.channel_member_ids.partner_id.ids)
            member.website_chat_channel_id = channel
            return channel
        missing = (partner | admins.partner_id) - channel.channel_member_ids.partner_id
        if missing:
            # Admins added to the settings later join the existing conversations.
            channel._add_members(partners=missing, post_joined_message=False)
        return channel

    def _website_chat_post(self, text: str):
        """Post ``text`` from the member to their admin conversation."""
        self.ensure_one()
        text = (text or '').strip()
        if not text:
            raise UserError(_('Write a message first.'))
        if len(text) > CHAT_MAX_LENGTH:
            raise UserError(_('Your message is too long (%s characters at most).', CHAT_MAX_LENGTH))
        partner = self.sudo().user_id.partner_id
        channel = self._website_chat_channel()
        recent = self.env['mail.message'].sudo().search_count([
            ('model', '=', 'discuss.channel'), ('res_id', '=', channel.id),
            ('author_id', '=', partner.id), ('message_type', '=', 'comment'),
            ('date', '>=', fields.Datetime.now() - CHAT_FLOOD_WINDOW),
        ])
        if recent >= CHAT_FLOOD_LIMIT:
            raise UserError(_('You sent a lot of messages: wait a few minutes for an admin to answer.'))
        # A plain str body is escaped by message_post (no HTML from members).
        message = channel.message_post(
            author_id=partner.id, body=text,
            message_type='comment', subtype_xmlid='mail.mt_comment',
        )
        return self._website_chat_message_values(message, partner)

    def _website_chat_messages(self, after_id: int = 0) -> list:
        """The latest messages of the member's admin conversation (oldest
        first), only those newer than ``after_id`` when given."""
        self.ensure_one()
        channel = self._website_chat_channel(create=False)
        if not channel:
            return []
        domain = [('model', '=', 'discuss.channel'), ('res_id', '=', channel.id),
                  ('message_type', '=', 'comment')]
        if after_id:
            domain.append(('id', '>', after_id))
        # sudo: the member reads their own conversation only (channel above).
        messages = self.env['mail.message'].sudo().search(domain, order='id desc', limit=CHAT_HISTORY_LIMIT)
        partner = self.sudo().user_id.partner_id
        return [self._website_chat_message_values(message, partner) for message in messages.sorted('id')]

    @staticmethod
    def _website_chat_message_values(message, partner) -> dict:
        text = html2plaintext(message.body or '').strip()
        if message.attachment_ids:
            names = ', '.join(message.attachment_ids.mapped('name'))
            text = f"{text}\n📎 {names}".strip()
        return {
            'id': message.id,
            'text': text,
            'mine': message.author_id == partner,
            'author': message.author_id.name or '',
            'date': fields.Datetime.to_string(message.date),
        }
