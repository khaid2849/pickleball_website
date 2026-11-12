"""AI tools of the club website chat bubble.

The bubble runs the same AI assistant as the backend widget and the bots.
For a member (portal user), it runs as superuser — portal users have no
access to the pickleball models — so it is limited here to read-only tools
that respect the website's rule on money: a member sees only their own.
Admins (internal users) keep every tool, with their own access rights.
"""
from odoo import fields, models

# pickleball.member id of the website member chatting (0: an admin without
# a member profile). Set on every website turn.
WEBSITE_MEMBER_CONTEXT_KEY = 'pickleball_website_chat_member_id'
# Set for members (not admins): only WEBSITE_MEMBER_TOOLS can run.
WEBSITE_RESTRICTED_CONTEXT_KEY = 'pickleball_website_chat_restricted'

WEBSITE_TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "get_my_profile",
            "description": "The stats of the member chatting on the website: player card (OVR, "
                           "tier), matches, wins, losses, win rate, bet winnings, sessions played, "
                           "ranking position and recent results.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_payments",
            "description": "Money of the member chatting on the website: what they still owe the "
                           "team (per session), what the team owes them, their latest payments and "
                           "the team's bank account to transfer to.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_court_info",
            "description": "Courts the team plays at: address, phone numbers and how many sessions "
                           "were played there, optionally filtered by name. Also says which courts "
                           "the next session uses.",
            "parameters": {
                "type": "object",
                "properties": {"court_name": {"type": "string", "description": "Partial name filter"}},
            },
        },
    },
]
WEBSITE_TOOL_NAMES = {spec['function']['name'] for spec in WEBSITE_TOOL_SPECS}

# What a member may use from the website: read-only, no other member's money
# (list_unpaid_settlements and get_session_details show everyone's debts).
WEBSITE_MEMBER_TOOLS = WEBSITE_TOOL_NAMES | {
    'get_upcoming_session_headcount',
    'get_session_history',
    'get_player_rankings',
    'suggest_time_slots',
    # Live court availability (pickleball_alobo), when installed.
    'search_available_courts',
    'get_court_schedule',
}


class PickleballAiTools(models.AbstractModel):
    _inherit = 'pickleball.ai.tools'

    def _tool_specs(self) -> list:
        specs = super()._tool_specs()
        ctx = self.env.context
        if WEBSITE_MEMBER_CONTEXT_KEY not in ctx:
            return specs
        if ctx.get(WEBSITE_MEMBER_CONTEXT_KEY):
            specs = specs + WEBSITE_TOOL_SPECS
        if ctx.get(WEBSITE_RESTRICTED_CONTEXT_KEY):
            specs = [spec for spec in specs if spec['function']['name'] in WEBSITE_MEMBER_TOOLS]
        return specs

    def execute(self, name: str, arguments: dict, conversation=None) -> dict:
        # Checked here too: the model may call a tool it was not offered.
        if self.env.context.get(WEBSITE_RESTRICTED_CONTEXT_KEY) and name not in WEBSITE_MEMBER_TOOLS:
            return {"error": "permission_denied",
                    "message": "Not available from the club website chat. Members can't change data "
                               "here: suggest the 'Talk to an admin' tab of the chat."}
        return super().execute(name, arguments, conversation=conversation)

    def _website_chat_member(self):
        member_id = self.env.context.get(WEBSITE_MEMBER_CONTEXT_KEY)
        # sudo: reads the member chatting on the website (portal users can't).
        return self.env['pickleball.member'].sudo().browse(member_id).exists() if member_id else None

    def _tool_get_my_profile(self, conversation=None):
        member = self._website_chat_member()
        if not member:
            return {"error": "The person chatting has no member profile."}
        players, _unranked = member._get_ranking('ovr')
        played = self.env['pickleball.session'].sudo().search_count([
            ('participant_ids', 'in', member.ids), ('state', 'in', ('done', 'settled')),
        ])
        return {
            "name": member.name,
            "card_overall": member.card_overall,
            "card_tier": member.card_tier,
            "matches": member.total_matches,
            "wins": member.total_wins,
            "losses": member.total_losses,
            "win_rate_percent": round(member.win_rate, 1),
            "bet_net_vnd": round(member.bet_net_total),
            "sessions_played": played,
            "ovr_rank": (players.ids.index(member.id) + 1) if member in players else None,
            "ranked_players": len(players),
            "recent_results_newest_first": member.card_recent_results or '',
            "profile_url": f"/club/players/{member.id}",
        }

    def _tool_get_my_payments(self, conversation=None):
        member = self._website_chat_member()
        if not member:
            return {"error": "The person chatting has no member profile."}
        ICP = self.env['ir.config_parameter'].sudo()
        paid = member.settlement_ids.filtered(lambda s: s.is_paid and s.amount < 0).sorted(
            lambda s: (s.payment_date or s.session_date or fields.Date.today(), s.id), reverse=True)[:3]
        return {
            "owes_team_vnd": round(member._get_outstanding_debt()),
            "unpaid_sessions": [
                {"session_date": str(s.session_date), "amount_vnd": round(-s.amount)}
                for s in member._get_unpaid_debts()
            ],
            "bank_credit_vnd": round(member.bank_credit),
            "team_owes_member_vnd": round(member.balance) if member.balance > 0.5 else 0,
            "latest_payments": [
                {"session_date": str(s.session_date), "amount_vnd": round(-s.amount),
                 "paid_on": str(s.payment_date or '')}
                for s in paid
            ],
            "team_bank": " ".join(filter(None, [ICP.get_param('pickleball.sepay_bank'),
                                                ICP.get_param('pickleball.sepay_account_number')])),
            "transfer_note": "Write your name in the transfer note: the debt clears automatically.",
            "finance_url": "/club/finance",
        }

    def _tool_get_court_info(self, conversation=None, court_name=None):
        Court = self.env['pickleball.court'].sudo()
        domain = [('name', 'ilike', court_name)] if court_name else []
        courts = Court.search(domain, limit=20)
        if not court_name:
            courts = courts.sorted(lambda court: -court.session_count)[:8]
        next_session = self._get_upcoming_session()
        return {
            "courts": [
                {"name": court.name, "address": court.address or '',
                 "phones": [phone for phone in (court.phone, court.phone2) if phone],
                 "sessions_played_here": court.session_count}
                for court in courts
            ],
            "next_session_courts": next_session._get_courts().mapped('name') if next_session else [],
        }
