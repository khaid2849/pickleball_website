import { Component, onMounted, onWillDestroy, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

const MAX_TEAM_SIZE = 2;

/**
 * Admin tool of the session page: drag players (or tap a player, then a
 * team) into the two sides of a match, set the bet and the winner, save.
 * Mounted from <owl-component name="pickleball_website.session_match_builder">.
 */
export class SessionMatchBuilder extends Component {
    static template = "pickleball_website.SessionMatchBuilder";
    static props = {
        sessionId: Number,
        locked: Boolean,
        needsRecalc: Boolean,
        defaultBet: Number,
        players: Array,
        matches: Array,
        // Gamification: rivalries of the season, pairs that already played together.
        rivals: { type: Array, optional: true },
        partnered: { type: Array, optional: true },
    };

    setup() {
        this.playerById = Object.fromEntries(this.props.players.map((p) => [p.id, p]));
        this.nextKey = 1;
        this.state = useState({
            matches: this.props.matches.map((m) => this.toDraft(m)),
            selected: null, // {playerId, from: {key, side} | null}
            dragOver: null,
            dirty: false,
            saving: false,
            error: "",
            message: "",
            needsRecalc: false,
        });
        this.onBeforeUnload = (ev) => {
            if (this.state.dirty) {
                ev.preventDefault();
                ev.returnValue = "";
            }
        };
        onMounted(() => window.addEventListener("beforeunload", this.onBeforeUnload));
        onWillDestroy(() => window.removeEventListener("beforeunload", this.onBeforeUnload));
    }

    toDraft(match) {
        return {
            key: this.nextKey++,
            id: match.id || false,
            team1: [...(match.team1 || [])],
            team2: [...(match.team2 || [])],
            bet: match.bet || 0,
            winner: match.winner || "",
        };
    }

    // ── Getters ───────────────────────────────────────────────────────────

    /** "Rivalry: A LONG 5–4 KHẢI" for each rival pair on opposite sides. */
    rivalBanners(match) {
        const banners = [];
        for (const rivalry of this.props.rivals || []) {
            const aSide = match.team1.includes(rivalry.a) ? 1 : match.team2.includes(rivalry.a) ? 2 : 0;
            const bSide = match.team1.includes(rivalry.b) ? 1 : match.team2.includes(rivalry.b) ? 2 : 0;
            if (aSide && bSide && aSide !== bSide) {
                const a = this.playerById[rivalry.a];
                const b = this.playerById[rivalry.b];
                banners.push(
                    `${_t("Rivalry")}: ${(a.short || a.name).toUpperCase()} ${rivalry.aWins}–${rivalry.bWins} ${(
                        b.short || b.name
                    ).toUpperCase()}`
                );
            }
        }
        return banners;
    }

    /** Pairs of this session's players who never played on the same side. */
    get freshPairs() {
        const done = new Set(this.props.partnered || []);
        const players = this.props.players.filter((p) => !p.guest);
        const pairs = [];
        for (let i = 0; i < players.length; i++) {
            for (let j = i + 1; j < players.length; j++) {
                const [a, b] = [players[i], players[j]].sort((x, y) => x.id - y.id);
                if (!done.has(`${a.id}-${b.id}`)) {
                    pairs.push(`${a.short || a.name} + ${b.short || b.name}`);
                }
            }
        }
        return pairs.slice(0, 8);
    }

    get players() {
        return this.props.players;
    }

    player(id) {
        return this.playerById[id];
    }

    /** How many draft matches each player is in (for a fair rotation). */
    get playCount() {
        const counts = {};
        for (const match of this.state.matches) {
            for (const id of [...match.team1, ...match.team2]) {
                counts[id] = (counts[id] || 0) + 1;
            }
        }
        return counts;
    }

    matchError(match) {
        if (!match.team1.length || !match.team2.length) {
            return _t("Each side needs at least one player.");
        }
        return "";
    }

    get canSave() {
        return (
            !this.props.locked &&
            this.state.dirty &&
            !this.state.saving &&
            this.state.matches.every((m) => !this.matchError(m))
        );
    }

    isSelected(playerId, from = null) {
        const sel = this.state.selected;
        if (!sel || sel.playerId !== playerId) {
            return false;
        }
        if (!from) {
            return !sel.from;
        }
        return sel.from && sel.from.key === from.key && sel.from.side === from.side;
    }

    // ── Moves ─────────────────────────────────────────────────────────────

    findMatch(key) {
        return this.state.matches.find((m) => m.key === key);
    }

    touch() {
        this.state.dirty = true;
        this.state.error = "";
        this.state.message = "";
    }

    /**
     * Put `playerId` on `side` of match `key`. Coming from a team, the
     * player leaves it (move); from the player list, it's a copy.
     */
    place(playerId, target, from = null) {
        const match = this.findMatch(target.key);
        if (!match || this.props.locked) {
            return;
        }
        const other = target.side === "team1" ? "team2" : "team1";
        if (from) {
            const source = this.findMatch(from.key);
            if (source) {
                source[from.side] = source[from.side].filter((id) => id !== playerId);
            }
        }
        if (match[target.side].includes(playerId)) {
            return;
        }
        if (match[target.side].length >= MAX_TEAM_SIZE) {
            this.state.error = _t("A side has %s players at most.", MAX_TEAM_SIZE);
            // Undo the removal from the source team.
            if (from) {
                const source = this.findMatch(from.key);
                if (source && !source[from.side].includes(playerId)) {
                    source[from.side].push(playerId);
                }
            }
            return;
        }
        match[other] = match[other].filter((id) => id !== playerId);
        match[target.side].push(playerId);
        if (match.winner) {
            match.winner = "";
        }
        this.touch();
    }

    removeFrom(playerId, from) {
        const match = this.findMatch(from.key);
        if (match && !this.props.locked) {
            match[from.side] = match[from.side].filter((id) => id !== playerId);
            this.touch();
        }
    }

    addMatch(firstPlayerId = null) {
        const match = this.toDraft({ bet: this.lastBet() });
        if (firstPlayerId) {
            match.team1.push(firstPlayerId);
        }
        this.state.matches.push(match);
        this.touch();
        return match;
    }

    lastBet() {
        const last = this.state.matches[this.state.matches.length - 1];
        return last ? last.bet : this.props.defaultBet;
    }

    removeMatch(key) {
        this.state.matches = this.state.matches.filter((m) => m.key !== key);
        this.touch();
    }

    moveMatch(key, delta) {
        const index = this.state.matches.findIndex((m) => m.key === key);
        const target = index + delta;
        if (index < 0 || target < 0 || target >= this.state.matches.length) {
            return;
        }
        const matches = [...this.state.matches];
        [matches[index], matches[target]] = [matches[target], matches[index]];
        this.state.matches = matches;
        this.touch();
    }

    swapSides(key) {
        const match = this.findMatch(key);
        [match.team1, match.team2] = [match.team2, match.team1];
        match.winner = match.winner === "team1" ? "team2" : match.winner === "team2" ? "team1" : "";
        this.touch();
    }

    setWinner(match, side) {
        match.winner = match.winner === side ? "" : side;
        this.touch();
    }

    onBetInput(match, ev) {
        const value = parseFloat(ev.target.value);
        match.bet = Number.isFinite(value) && value > 0 ? value : 0;
        this.touch();
    }

    /**
     * New doubles match from the 4 players who played least so far
     * (strongest + weakest vs the two in between, by OVR).
     */
    suggestMatch() {
        const counts = this.playCount;
        const pool = this.players
            .filter((p) => !p.guest)
            .map((p) => ({ p, n: counts[p.id] || 0, r: Math.random() }))
            .sort((a, b) => a.n - b.n || a.r - b.r)
            .slice(0, 4)
            .map((x) => x.p)
            .sort((a, b) => b.ovr - a.ovr);
        if (pool.length < 2) {
            this.state.error = _t("Not enough players for a match.");
            return;
        }
        const match = this.addMatch();
        if (pool.length >= 4) {
            match.team1 = [pool[0].id, pool[3].id];
            match.team2 = [pool[1].id, pool[2].id];
        } else {
            match.team1 = [pool[0].id];
            match.team2 = [pool[1].id];
        }
    }

    // ── Pointer: tap to select, tap a team to place ───────────────────────

    onPlayerClick(playerId, from = null) {
        if (this.props.locked) {
            return;
        }
        this.state.selected = this.isSelected(playerId, from) ? null : { playerId, from };
    }

    onZoneClick(key, side) {
        const sel = this.state.selected;
        if (!sel) {
            return;
        }
        this.place(sel.playerId, { key, side }, sel.from);
        this.state.selected = null;
    }

    onNewMatchClick() {
        const sel = this.state.selected;
        if (sel) {
            if (sel.from) {
                this.removeFrom(sel.playerId, sel.from);
            }
            this.addMatch(sel.playerId);
            this.state.selected = null;
        } else {
            this.addMatch();
        }
    }

    onPoolClick() {
        const sel = this.state.selected;
        if (sel && sel.from) {
            this.removeFrom(sel.playerId, sel.from);
            this.state.selected = null;
        }
    }

    // ── HTML5 drag & drop ─────────────────────────────────────────────────

    onDragStart(ev, playerId, from = null) {
        if (this.props.locked) {
            ev.preventDefault();
            return;
        }
        ev.dataTransfer.effectAllowed = from ? "move" : "copy";
        ev.dataTransfer.setData("text/plain", JSON.stringify({ playerId, from }));
        this.state.selected = null;
    }

    onDragOver(ev, zone) {
        if (this.props.locked) {
            return;
        }
        ev.preventDefault();
        this.state.dragOver = zone;
    }

    onDragLeave(zone) {
        if (this.state.dragOver === zone) {
            this.state.dragOver = null;
        }
    }

    readDrag(ev) {
        ev.preventDefault();
        this.state.dragOver = null;
        try {
            return JSON.parse(ev.dataTransfer.getData("text/plain"));
        } catch {
            return null;
        }
    }

    onDrop(ev, key, side) {
        const data = this.readDrag(ev);
        if (data && data.playerId) {
            this.place(data.playerId, { key, side }, data.from);
        }
    }

    onDropNewMatch(ev) {
        const data = this.readDrag(ev);
        if (data && data.playerId) {
            if (data.from) {
                this.removeFrom(data.playerId, data.from);
            }
            this.addMatch(data.playerId);
        }
    }

    onDropPool(ev) {
        const data = this.readDrag(ev);
        if (data && data.from) {
            this.removeFrom(data.playerId, data.from);
        }
    }

    // ── Save ──────────────────────────────────────────────────────────────

    async save() {
        if (!this.canSave) {
            return;
        }
        this.state.saving = true;
        this.state.error = "";
        try {
            const result = await rpc(`/club/schedule/${this.props.sessionId}/matches`, {
                matches: this.state.matches.map((m) => ({
                    id: m.id,
                    team1: m.team1,
                    team2: m.team2,
                    bet: m.bet,
                    winner: m.winner,
                })),
            });
            this.state.matches = result.matches.map((m) => this.toDraft(m));
            this.state.dirty = false;
            this.state.needsRecalc = result.needsRecalc;
            this.state.message = _t("Matches saved.");
        } catch (error) {
            this.state.error = error?.data?.message || error?.message || _t("The matches could not be saved.");
        } finally {
            this.state.saving = false;
        }
    }

    matchLabel(index) {
        return _t("Match %s", index + 1);
    }
}

registry.category("public_components").add("pickleball_website.session_match_builder", SessionMatchBuilder);
