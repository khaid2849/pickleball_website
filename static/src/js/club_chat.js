/** @odoo-module **/

import { Component, markup, onMounted, onPatched, onWillDestroy, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

const TICK_MS = 5000; // admin replies: checked every tick while the admin tab is open…
const IDLE_TICKS = 9; // …and every 9 ticks (45 s) otherwise, for the unread badge.

function escapeHtml(text) {
    return String(text ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

/** Plain text (from the server or the AI) to safe HTML: **bold** and links. */
function formatText(text) {
    let html = escapeHtml(text);
    html = html.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
    html = html.replace(/(https?:\/\/[^\s<]+[^\s<.,;:!?)])/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
    html = html.replace(/(^|[\s(])(\/club(?:\/[\w\-/]*)?)/g, '$1<a href="$2">$2</a>');
    return markup(html);
}

/**
 * Chat bubble of the club website: frequent questions answered instantly,
 * the team's AI assistant, and a conversation with the admins.
 * Mounted on every page from <owl-component name="pickleball_website.club_chat">.
 */
export class ClubChat extends Component {
    static template = "pickleball_website.ClubChat";
    static props = { userId: Number };

    setup() {
        this.storageKey = (name) => `pbw_chat_${name}_${this.props.userId}`;
        this.nextKey = 1;
        this.state = useState({
            open: false,
            loaded: false,
            tab: "assistant",
            info: null,
            messages: [], // assistant tab: {key, from: 'me'|'bot', text, actions, image, faqs}
            adminMessages: [],
            input: "",
            adminInput: "",
            busy: false,
            sending: false,
            error: "",
            adminError: "",
            unread: 0,
        });
        this.conversationId = Number(this.readStorage("conversation")) || null;
        this.seenAdminId = Number(this.readStorage("seen")) || 0;
        this.lastAdminId = 0;
        this.ticks = 0;
        this.scrollRef = useRef("scroll");
        this.inputRef = useRef("input");
        this.shouldScroll = false;

        onMounted(() => {
            // First unread check a bit after the page load, then on the timer.
            this.firstCheck = setTimeout(() => this.refreshAdmin(), 3000);
            this.timer = setInterval(() => this.onTick(), TICK_MS);
        });
        onPatched(() => {
            if (this.shouldScroll && this.scrollRef.el) {
                this.scrollRef.el.scrollTop = this.scrollRef.el.scrollHeight;
                this.shouldScroll = false;
            }
        });
        onWillDestroy(() => {
            clearTimeout(this.firstCheck);
            clearInterval(this.timer);
        });
    }

    // ── Storage (per-browser convenience only) ───────────────────────────

    readStorage(name) {
        try {
            return window.localStorage.getItem(this.storageKey(name));
        } catch {
            return null;
        }
    }

    writeStorage(name, value) {
        try {
            if (value === null) {
                window.localStorage.removeItem(this.storageKey(name));
            } else {
                window.localStorage.setItem(this.storageKey(name), String(value));
            }
        } catch {
            // Private mode / blocked storage: the chat works without it.
        }
    }

    // ── Getters ──────────────────────────────────────────────────────────

    get faqs() {
        return this.state.info?.faqs || [];
    }

    get canAsk() {
        return Boolean(this.state.info?.ai_enabled);
    }

    get adminNames() {
        return (this.state.info?.admin_names || []).join(", ");
    }

    get askPlaceholder() {
        return this.canAsk ? _t("Ask anything about the team…") : _t("Pick a question above");
    }

    get launcherLabel() {
        return this.state.open ? _t("Close the chat") : _t("Open the chat");
    }

    isLast(message) {
        const messages = this.state.messages;
        return messages.length > 0 && messages[messages.length - 1].key === message.key;
    }

    format(text) {
        return formatText(text);
    }

    // ── Opening ──────────────────────────────────────────────────────────

    async toggle() {
        this.state.open = !this.state.open;
        if (this.state.open && !this.state.loaded) {
            await this.load();
        }
        if (this.state.open) {
            this.markAdminSeen();
            this.scrollDown();
            this.focusInput();
        }
    }

    async load() {
        try {
            this.state.info = await rpc("/club/chat/init", {});
        } catch {
            this.state.error = _t("The chat could not be loaded. Try again later.");
            return;
        }
        this.state.messages = [];
        if (this.conversationId) {
            try {
                const { messages } = await rpc("/club/chat/ai_history", { conversation_id: this.conversationId });
                for (const message of messages) {
                    this.pushMessage(message.role === "user" ? "me" : "bot", message.text);
                }
                if (!messages.length) {
                    this.forgetConversation();
                }
            } catch {
                this.forgetConversation();
            }
        }
        this.pushGreeting();
        this.state.loaded = true;
        if (this.state.info.admin_chat) {
            await this.refreshAdmin();
        }
    }

    pushGreeting() {
        const name = this.state.info?.name || "";
        this.pushMessage(
            "bot",
            this.canAsk
                ? _t("Hi %s! 👋 Pick a question below, or ask me anything about the team.", name)
                : _t("Hi %s! 👋 Pick a question below.", name),
            { faqs: true }
        );
    }

    pushMessage(from, text, extra = {}) {
        this.state.messages.push({
            key: this.nextKey++,
            from,
            text,
            actions: extra.actions || [],
            image: extra.image || "",
            faqs: Boolean(extra.faqs),
            error: Boolean(extra.error),
        });
        this.scrollDown();
    }

    scrollDown() {
        this.shouldScroll = true;
    }

    focusInput() {
        setTimeout(() => this.inputRef.el?.focus(), 50);
    }

    switchTab(tab) {
        this.state.tab = tab;
        if (tab === "admin") {
            this.markAdminSeen();
            this.refreshAdmin();
        }
        this.scrollDown();
        this.focusInput();
    }

    forgetConversation() {
        this.conversationId = null;
        this.writeStorage("conversation", null);
    }

    newConversation() {
        this.forgetConversation();
        this.state.messages = [];
        this.state.error = "";
        this.pushGreeting();
    }

    // ── Assistant ────────────────────────────────────────────────────────

    async askFaq(faq) {
        if (this.state.busy) {
            return;
        }
        this.pushMessage("me", faq.label);
        this.state.busy = true;
        try {
            const answer = await rpc("/club/chat/faq", { key: faq.key });
            this.pushMessage("bot", answer.text, { actions: answer.actions, image: answer.image, faqs: true });
        } catch {
            this.pushMessage("bot", _t("Sorry, I could not answer that right now."), { error: true, faqs: true });
        } finally {
            this.state.busy = false;
        }
    }

    async ask() {
        const message = this.state.input.trim();
        if (!message || this.state.busy || !this.canAsk) {
            return;
        }
        this.state.input = "";
        this.pushMessage("me", message);
        this.state.busy = true;
        try {
            const result = await rpc("/club/chat/ask", {
                message,
                conversation_id: this.conversationId,
            });
            if (result.error) {
                this.pushMessage("bot", result.error, { error: true, faqs: true });
            } else {
                this.conversationId = result.conversation_id;
                this.writeStorage("conversation", result.conversation_id);
                this.pushMessage("bot", result.text, { faqs: true });
            }
        } catch {
            this.pushMessage("bot", _t("Sorry, the assistant is not answering right now. Try again later."), {
                error: true,
                faqs: true,
            });
        } finally {
            this.state.busy = false;
            this.focusInput();
        }
    }

    onInputKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            if (this.state.tab === "admin") {
                this.sendToAdmin();
            } else {
                this.ask();
            }
        }
    }

    // ── Talk to an admin ─────────────────────────────────────────────────

    onTick() {
        if (document.hidden) {
            return;
        }
        this.ticks++;
        const watching = this.state.open && this.state.tab === "admin";
        if (watching || this.ticks % IDLE_TICKS === 0) {
            this.refreshAdmin();
        }
    }

    async refreshAdmin() {
        if (this.adminDisabled || (this.state.loaded && !this.state.info?.admin_chat)) {
            return;
        }
        let messages, disabled;
        try {
            ({ messages, disabled } = await rpc(
                "/club/chat/admin/messages",
                { after_id: this.lastAdminId },
                { silent: true }
            ));
        } catch {
            // e.g. an admin without a member profile: no admin conversation.
            this.adminDisabled = true;
            return;
        }
        this.adminDisabled = Boolean(disabled);
        this.addAdminMessages(messages);
    }

    addAdminMessages(messages) {
        const known = new Set(this.state.adminMessages.map((m) => m.id));
        const fresh = messages.filter((m) => !known.has(m.id));
        if (!fresh.length) {
            return;
        }
        this.state.adminMessages.push(...fresh);
        this.lastAdminId = Math.max(this.lastAdminId, ...fresh.map((m) => m.id));
        if (this.state.open && this.state.tab === "admin") {
            this.markAdminSeen();
            this.scrollDown();
        } else {
            this.state.unread = this.state.adminMessages.filter((m) => !m.mine && m.id > this.seenAdminId).length;
        }
    }

    markAdminSeen() {
        if (!(this.state.open && this.state.tab === "admin")) {
            return;
        }
        this.seenAdminId = Math.max(this.seenAdminId, this.lastAdminId);
        this.writeStorage("seen", this.seenAdminId);
        this.state.unread = 0;
    }

    async sendToAdmin() {
        const text = this.state.adminInput.trim();
        if (!text || this.state.sending) {
            return;
        }
        this.state.sending = true;
        this.state.adminError = "";
        try {
            const result = await rpc("/club/chat/admin/send", { text });
            if (result.error) {
                this.state.adminError = result.error;
            } else {
                this.state.adminInput = "";
                this.addAdminMessages([result.message]);
                this.markAdminSeen();
            }
        } catch {
            this.state.adminError = _t("Your message could not be sent. Try again.");
        } finally {
            this.state.sending = false;
            this.focusInput();
        }
    }

    formatTime(date) {
        if (!date) {
            return "";
        }
        const value = new Date(date.replace(" ", "T") + "Z");
        if (Number.isNaN(value.getTime())) {
            return "";
        }
        const sameDay = value.toDateString() === new Date().toDateString();
        const time = value.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        return sameDay ? time : `${value.toLocaleDateString([], { day: "2-digit", month: "2-digit" })} ${time}`;
    }

    hideImage(ev) {
        ev.target.closest(".o_pbw_chat_image")?.remove();
    }
}

registry.category("public_components").add("pickleball_website.club_chat", ClubChat);
