/** @odoo-module **/
/**
 * Flip cards (.o_pbw_flip): a tap, Enter or Space turns the card over to
 * its back (card catalog: how to earn it; profile: the player file).
 */
function toggle(flip) {
    const flipped = flip.classList.toggle("o_pbw_flipped");
    flip.setAttribute("aria-pressed", String(flipped));
    flip.querySelector(".o_pbw_flip_front")?.setAttribute("aria-hidden", String(flipped));
    flip.querySelector(".o_pbw_flip_back")?.setAttribute("aria-hidden", String(!flipped));
}

document.addEventListener("click", (ev) => {
    const flip = ev.target.closest(".o_pbw_flip");
    if (flip && !ev.target.closest("a, button, input, label")) {
        toggle(flip);
    }
});

document.addEventListener("keydown", (ev) => {
    if ((ev.key === "Enter" || ev.key === " ") && ev.target.classList?.contains("o_pbw_flip")) {
        ev.preventDefault();
        toggle(ev.target);
    }
});
