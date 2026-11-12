/** @odoo-module **/
/**
 * Showcase page: every choice's card is rendered on the server; show the one
 * picked before the member saves.
 */
function setupShowcase() {
    const form = document.querySelector(".o_pbw_gm_showcase_form");
    if (!form) {
        return;
    }
    form.addEventListener("change", (ev) => {
        if (ev.target.name !== "card_id") {
            return;
        }
        for (const preview of form.querySelectorAll("[data-showcase-preview]")) {
            preview.classList.toggle("d-none", preview.dataset.showcasePreview !== ev.target.value);
        }
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupShowcase);
} else {
    setupShowcase();
}
