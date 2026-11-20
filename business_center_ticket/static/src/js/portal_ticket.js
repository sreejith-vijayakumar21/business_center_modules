/** Raise a ticket: show and require the topic box only for a category that
 * asks members to describe the topic (such as Other). The server checks it
 * again on submit. */
function initTicketForm() {
    const category = document.getElementById("tk_category_id");
    const box = document.getElementById("tk_topic_box");
    const topic = document.getElementById("tk_topic");
    if (!(category && box && topic)) {
        return;
    }
    const sync = () => {
        const ask = Boolean(category.selectedOptions[0]?.dataset.askTopic);
        box.classList.toggle("d-none", !ask);
        topic.required = ask;
    };
    category.addEventListener("change", sync);
    sync();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initTicketForm);
} else {
    initTicketForm();
}