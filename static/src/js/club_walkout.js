/** @odoo-module **/
/**
 * Walkouts (spec §3): rewards waiting in the member's reveal queue are
 * played on their next visit of the club pages, oldest first. Six steps:
 * dark backdrop with the card face down, a light sweep in the tier color,
 * tier / position chips, OVR counting up, name ribbon sliding in, card
 * flipped with "Share" and "Album". Tap to skip. With prefers-reduced-motion
 * only a 300 ms fade. Small rewards (badge levels, milestones) are toasts.
 */
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { armMotifs, playMotifs } from "@pickleball_website/js/card_motif";

const STEP_TIMES = [0, 600, 1200, 1800, 2400, 3000];
const TIER_COLORS = { bronze: "#ec8a4b", silver: "#dfe6f0", gold: "#f7c948", icon: "#b388ff" };

function reducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function markSeen(reveal) {
    return rpc(`/club/api/me/reveals/${reveal.id}/seen`, {}).catch(() => {});
}

function showToast(reveal) {
    let box = document.querySelector(".o_pbw_toasts");
    if (!box) {
        box = document.createElement("div");
        box.className = "o_pbw_toasts";
        box.setAttribute("role", "status");
        document.body.appendChild(box);
    }
    const toast = document.createElement("div");
    toast.className = "o_pbw_toast";
    const icon = document.createElement("i");
    icon.className = "fa fa-star";
    toast.appendChild(icon);
    toast.appendChild(document.createTextNode(reveal.text || _t("New reward")));
    box.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
    markSeen(reveal);
}

function countUp(el, from, to, duration) {
    if (!el || from === to || from === undefined || from === null) {
        return;
    }
    const start = performance.now();
    const step = (now) => {
        const t = Math.min(1, (now - start) / duration);
        el.textContent = Math.round(from + (to - from) * t);
        if (t < 1) {
            requestAnimationFrame(step);
        }
    };
    el.textContent = from;
    requestAnimationFrame(step);
}

export function playWalkout(reveal) {
    return new Promise((resolve) => {
        const reduced = reducedMotion();
        const overlay = document.createElement("div");
        overlay.className = "o_pbw_walkout" + (reduced ? " o_pbw_wo_reduced" : "");
        overlay.setAttribute("role", "dialog");
        overlay.setAttribute("aria-label", _t("New card"));

        const title = document.createElement("div");
        title.className = "o_pbw_wo_title";
        const kind = reveal.kind;
        title.textContent =
            kind === "tier_up"
                ? reveal.payload.first
                    ? _t("Rookie graduated!")
                    : _t("Promoted!")
                : kind === "season"
                ? _t("Season award")
                : kind === "evo"
                ? _t("Evolution complete")
                : _t("New card");

        const stage = document.createElement("div");
        stage.className = "o_pbw_wo_stage";
        const light = document.createElement("div");
        light.className = "o_pbw_wo_light";
        const card = document.createElement("div");
        card.className = "o_pbw_wo_card";
        card.innerHTML = reveal.card_html || "";
        stage.append(card, light);
        armMotifs(card); // the card's motif plays when the card turns over
        const pbCard = card.querySelector(".o_pb_card");
        if (pbCard) {
            const cover = document.createElement("div");
            cover.className = "o_pbw_wo_cover";
            pbCard.appendChild(cover);
        }
        const tier = ["bronze", "silver", "gold", "icon"].find(
            (t) => pbCard && pbCard.classList.contains(`o_pb_card_${t}`)
        );
        overlay.style.setProperty("--wo-color", TIER_COLORS[tier] || TIER_COLORS.gold);

        const actions = document.createElement("div");
        actions.className = "o_pbw_wo_actions";
        const share = document.createElement("a");
        share.className = "btn o_pbw_btn o_pbw_btn_light";
        share.href = reveal.share_url;
        share.setAttribute("download", "");
        share.textContent = _t("Share");
        const album = document.createElement("a");
        album.className = "btn o_pbw_btn o_pbw_btn_dark";
        album.href = reveal.album_url;
        album.textContent = _t("See album");
        actions.append(share, album);
        overlay.append(title, stage, actions);
        document.body.appendChild(overlay);

        const timers = [];
        let done = false;
        const finish = () => {
            if (done) {
                return;
            }
            done = true;
            timers.forEach(clearTimeout);
            overlay.classList.add("o_pbw_wo_dark", "o_pbw_wo_s2", "o_pbw_wo_s3", "o_pbw_wo_s4", "o_pbw_wo_s5",
                "o_pbw_wo_s6");
            playMotifs(card);
        };
        const close = () => {
            overlay.remove();
            markSeen(reveal).then(resolve, resolve);
        };
        overlay.addEventListener("click", (ev) => {
            if (ev.target.closest(".o_pbw_wo_actions")) {
                markSeen(reveal);
                return;
            }
            if (!done) {
                finish(); // first tap: skip to the end
            } else {
                close();
            }
        });
        document.addEventListener(
            "keydown",
            (ev) => {
                if (ev.key === "Escape") {
                    close();
                }
            },
            { once: true }
        );

        if (reduced) {
            requestAnimationFrame(() => overlay.classList.add("o_pbw_wo_dark"));
            done = true;
            return;
        }
        const ovr = card.querySelector(".o_pb_card_ovr b");
        const steps = [
            () => overlay.classList.add("o_pbw_wo_dark"),
            () => overlay.classList.add("o_pbw_wo_s2"),
            () => overlay.classList.add("o_pbw_wo_s3"),
            () => {
                overlay.classList.add("o_pbw_wo_s4");
                countUp(ovr, reveal.old_ovr, reveal.new_ovr, 550);
            },
            () => overlay.classList.add("o_pbw_wo_s5"),
            () => {
                overlay.classList.add("o_pbw_wo_s6");
                playMotifs(card);
                done = true;
            },
        ];
        steps.forEach((fn, i) => timers.push(setTimeout(fn, STEP_TIMES[i])));
    });
}

async function playQueue() {
    const root = document.querySelector(".o_pbw_walkout_root");
    if (!root) {
        return;
    }
    let reveals = [];
    try {
        const response = await fetch("/club/api/me/reveals", { credentials: "same-origin" });
        if (!response.ok) {
            return;
        }
        reveals = await response.json();
    } catch {
        return;
    }
    for (const reveal of reveals) {
        if (reveal.kind === "toast") {
            showToast(reveal);
        } else {
            await playWalkout(reveal);
        }
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", playQueue);
} else {
    playQueue();
}
