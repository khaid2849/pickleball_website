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
