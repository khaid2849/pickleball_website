/** @odoo-module **/
/**
 * CardMotif motion (pickleball-team card_motif.scss): the "once" motion
 * plays the first time a card shows up on screen (or in a walkout), the
 * "loop" motion runs only while the card is on screen. Only motifs of size
 * md / lg move; prefers-reduced-motion keeps every card still.
 */
const MOVING = ".o_pb_motif.o_pb_motif_md, .o_pb_motif.o_pb_motif_lg";

function reducedMotion() {
    // o_pb_motion_off: the card motif lab's "reduced motion" switch
    return (
        document.documentElement.classList.contains("o_pb_motion_off") ||
        (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches)
    );
}

let onceObserver = null;
let liveObserver = null;

function observers() {
    if (!onceObserver && "IntersectionObserver" in window) {
        onceObserver = new IntersectionObserver(
            (entries) => {
                for (const entry of entries) {
                    if (entry.isIntersecting && !reducedMotion()) {
                        entry.target.classList.add("is-played");
                        onceObserver.unobserve(entry.target);
                    }
                }
            },
            { threshold: 0.35 }
        );
        liveObserver = new IntersectionObserver((entries) => {
            for (const entry of entries) {
                entry.target.classList.toggle("is-live", entry.isIntersecting && !reducedMotion());
            }
        });
    }
    return onceObserver;
}

/** Watch the moving motifs under `root`: play once when seen, loop while seen. */
export function watchMotifs(root = document) {
    if (reducedMotion() || !observers()) {
        return;
    }
    for (const motif of root.querySelectorAll(MOVING)) {
        if (motif.dataset.pbWatched) {
            continue;
        }
        motif.dataset.pbWatched = "1";
        motif.classList.add("is-armed");
        onceObserver.observe(motif);
        liveObserver.observe(motif);
    }
}

/** Hold the motifs under `root` in their start state (walkout, face down). */
export function armMotifs(root) {
    if (reducedMotion()) {
        return;
    }
    for (const motif of root.querySelectorAll(MOVING)) {
        motif.dataset.pbWatched = "1";
        motif.classList.remove("is-played");
        motif.classList.add("is-armed");
    }
}

/** Play the motifs under `root` now (walkout reveal). */
export function playMotifs(root) {
    if (reducedMotion()) {
        return;
    }
    for (const motif of root.querySelectorAll(MOVING)) {
        motif.classList.add("is-armed", "is-played", "is-live");
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => watchMotifs());
} else {
    watchMotifs();
}

// ── Icon cards: 3D tilt, foil and glitter that follow the pointer ──────────
//
// Only the card being touched or hovered moves (size md / lg); everything
// runs in requestAnimationFrame and will-change is set only meanwhile. On
// touch screens a press-and-hold tilts the card; on a big (lg) card the
// device's tilt sensor takes over once the member allowed it (iOS asks
// for permission on that first hold, never by itself).

const ICON = ".o_pb_card.o_pb_card_motif_icon";
const MAX_TILT = 8; // degrees
const HOLD_MS = 250;

function iconCard(target) {
    const card = target && target.closest && target.closest(ICON);
    if (!card || reducedMotion() || !card.querySelector(".o_pb_motif_md, .o_pb_motif_lg")) {
        return null;
    }
    return card;
}

function shadowOf(card) {
    const host = card.parentElement;
    let shadow = host.querySelector(":scope > .o_pb_tilt_shadow");
    if (!shadow) {
        host.classList.add("o_pbw_tilt_host");
        shadow = document.createElement("span");
        shadow.className = "o_pb_tilt_shadow";
        host.insertBefore(shadow, card);
    }
    return shadow;
}

class Tilt {
    constructor(card) {
        this.card = card;
        this.shadow = shadowOf(card);
        this.glitters = [...card.querySelectorAll(".o_pb_m_glitter")].map((el) => ({
            el,
            x: parseFloat(el.style.getPropertyValue("--gx")) || 0,
            y: parseFloat(el.style.getPropertyValue("--gy")) || 0,
        }));
        this.x = 0.5;
        this.y = 0.5;
        this.frame = null;
        card.classList.remove("o_pb_tilt_release");
        card.classList.add("o_pb_tilting");
        this.shadow.style.opacity = "1";
    }

    /** x, y: 0..1 across the card */
    point(x, y) {
        this.x = Math.min(1, Math.max(0, x));
        this.y = Math.min(1, Math.max(0, y));
        if (!this.frame) {
            this.frame = requestAnimationFrame(() => this.render());
        }
    }

    render() {
        this.frame = null;
        const dx = this.x * 2 - 1; // -1..1
        const dy = this.y * 2 - 1;
        const card = this.card;
        card.style.transform = `perspective(800px) rotateX(${(-dy * MAX_TILT).toFixed(2)}deg) rotateY(${(
            dx * MAX_TILT
        ).toFixed(2)}deg)`;
        card.style.setProperty("--tx", dx.toFixed(3));
        card.style.setProperty("--ty", dy.toFixed(3));
        const foil = card.querySelector(".o_pb_icon_foil i");
        if (foil) {
            foil.style.setProperty("--fx", `${((this.x - 0.5) * 32).toFixed(2)}%`);
            foil.style.setProperty("--fy", `${((this.y - 0.5) * 16).toFixed(2)}%`);
        }
        this.shadow.style.transform = `translate(${(-dx * 10).toFixed(1)}px, ${(-dy * 10).toFixed(1)}px)`;
        // glitter lights up where the foil's band passes (the band runs across x, tilted)
        const band = this.x + (this.y - 0.5) * 0.35;
        for (const g of this.glitters) {
            const distance = Math.abs(g.x + (g.y - 0.5) * 0.35 - band);
            g.el.style.opacity = distance < 0.08 ? (1 - distance / 0.08).toFixed(2) : "0";
        }
    }

    release() {
        if (this.frame) {
            cancelAnimationFrame(this.frame);
        }
        const card = this.card;
        card.classList.add("o_pb_tilt_release");
        card.classList.remove("o_pb_tilting");
        card.style.transform = "";
        card.style.setProperty("--tx", "0");
        card.style.setProperty("--ty", "0");
        const foil = card.querySelector(".o_pb_icon_foil i");
        if (foil) {
            foil.style.removeProperty("--fx");
            foil.style.removeProperty("--fy");
        }
        this.shadow.style.transform = "";
        this.shadow.style.opacity = "0";
        for (const g of this.glitters) {
            g.el.style.opacity = "";
        }
        setTimeout(() => card.classList.remove("o_pb_tilt_release"), 550);
    }
}

let active = null;
let holdTimer = null;
let gyro = null;

function cardPoint(card, ev) {
    const rect = card.getBoundingClientRect();
    return [(ev.clientX - rect.left) / rect.width, (ev.clientY - rect.top) / rect.height];
}

function stop() {
    clearTimeout(holdTimer);
    if (active) {
        active.release();
        active = null;
    }
}

document.addEventListener("pointerover", (ev) => {
    if (ev.pointerType !== "mouse") {
        return;
    }
    const card = iconCard(ev.target);
    if (card && (!active || active.card !== card)) {
        stop();
        active = new Tilt(card);
    }
});
document.addEventListener("pointermove", (ev) => {
    if (active && (ev.pointerType === "mouse" || active.touch)) {
        if (ev.pointerType === "mouse" && !active.card.contains(ev.target)) {
            stop();
            return;
        }
        active.point(...cardPoint(active.card, ev));
    }
});
document.addEventListener("pointerout", (ev) => {
    if (active && ev.pointerType === "mouse" && !active.card.contains(ev.relatedTarget)) {
        stop();
    }
});
// touch: press and hold
document.addEventListener("pointerdown", (ev) => {
    if (ev.pointerType === "mouse") {
        return;
    }
    const card = iconCard(ev.target);
    if (!card) {
        return;
    }
    holdTimer = setTimeout(() => {
        stop();
        active = new Tilt(card);
        active.touch = true;
        active.point(...cardPoint(card, ev));
        if (card.querySelector(".o_pb_motif_lg")) {
            startGyro(card);
        }
    }, HOLD_MS);
});
for (const type of ["pointerup", "pointercancel"]) {
    document.addEventListener(type, (ev) => {
        if (ev.pointerType !== "mouse" && !gyro) {
            stop();
        }
        clearTimeout(holdTimer);
    });
}

/** The phone's tilt moves a big Icon card, once the member allowed it. */
function startGyro(card) {
    const Orientation = window.DeviceOrientationEvent;
    if (!Orientation || gyro) {
        return;
    }
    const listen = () => {
        gyro = (ev) => {
            if (!active || active.card !== card) {
                window.removeEventListener("deviceorientation", gyro);
                gyro = null;
                return;
            }
            // gamma: left / right, beta: front / back (about 45 deg when held)
            active.point(0.5 + (ev.gamma || 0) / 40, 0.5 + ((ev.beta || 45) - 45) / 40);
        };
        window.addEventListener("deviceorientation", gyro);
        // a tap outside the card ends it
        document.addEventListener("pointerdown", (ev) => !card.contains(ev.target) && stopGyro(), { once: true });
    };
    if (typeof Orientation.requestPermission === "function") {
        Orientation.requestPermission()
            .then((state) => state === "granted" && listen())
            .catch(() => {});
    } else {
        listen();
    }
}

function stopGyro() {
    if (gyro) {
        window.removeEventListener("deviceorientation", gyro);
        gyro = null;
    }
    stop();
}
