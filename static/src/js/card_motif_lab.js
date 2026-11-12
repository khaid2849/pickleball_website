/** @odoo-module **/
/**
 * Card motif lab (/club/dev/card-motifs, admins): replay the "once" motion,
 * play a card's walkout, switch motion off (as prefers-reduced-motion does)
 * and count the motifs looping on screen.
 */
import { playWalkout } from "@pickleball_website/js/club_walkout";
import { watchMotifs } from "@pickleball_website/js/card_motif";

function replay(root) {
    for (const motif of root.querySelectorAll(".o_pb_motif.o_pb_motif_md, .o_pb_motif.o_pb_motif_lg")) {
        motif.classList.remove("is-played");
        motif.classList.add("is-armed");
        void motif.getBoundingClientRect(); // restart the animations
        motif.classList.add("is-played");
    }
}

function setupLab() {
    const lab = document.querySelector(".o_pbw_motif_lab");
    if (!lab) {
        return;
    }
    lab.addEventListener("click", (ev) => {
        const button = ev.target.closest("[data-lab]");
        if (!button) {
            return;
        }
        if (button.dataset.lab === "replay-all") {
            replay(lab);
        } else if (button.dataset.lab === "replay") {
            replay(button.closest(".o_pbw_lab_item"));
        } else if (button.dataset.lab === "walkout") {
            playWalkout(JSON.parse(button.dataset.reveal));
        }
    });
    const reduced = lab.querySelector("[data-lab='reduced']");
    reduced.addEventListener("change", () => {
        document.documentElement.classList.toggle("o_pb_motion_off", reduced.checked);
        for (const motif of document.querySelectorAll(".o_pb_motif")) {
            motif.classList.remove("is-armed", "is-played", "is-live");
            delete motif.dataset.pbWatched;
        }
        if (!reduced.checked) {
            watchMotifs();
        }
    });
    const live = lab.querySelector("[data-lab='live']");
    const total = lab.querySelector("[data-lab='total']");
    setInterval(() => {
        live.textContent = document.querySelectorAll(".o_pb_motif.is-live").length;
        total.textContent = document.querySelectorAll(".o_pb_motif.o_pb_motif_md, .o_pb_motif.o_pb_motif_lg").length;
    }, 500);
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupLab);
} else {
    setupLab();
}
