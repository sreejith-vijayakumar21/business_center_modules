/**
 * Cancel dialog on a booking's page (hot desks, meeting rooms, ...): once
 * free cancellation has ended while the page was open, show the
 * cancellation request form instead of free cancellation.
 *
 * The page marks the dialog with ``o_bc_cancel_dialog`` and gives the
 * server's seconds-left in ``data-free-seconds``; they are counted down here,
 * so the member's own clock and time zone don't matter. The server checks
 * again on submit.
 */
function initCancelDialogs() {
    for (const modal of document.querySelectorAll(".o_bc_cancel_dialog[data-free-seconds]")) {
        const freeUntil = Date.now() + Number(modal.dataset.freeSeconds) * 1000;
        modal.addEventListener("show.bs.modal", () => {
            const ended = Date.now() >= freeUntil;
            modal.querySelector(".o_bc_cancel_free")?.classList.toggle("d-none", ended);
            modal.querySelector(".o_bc_cancel_request")?.classList.toggle("d-none", !ended);
        });
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initCancelDialogs);
} else {
    initCancelDialogs();
}
