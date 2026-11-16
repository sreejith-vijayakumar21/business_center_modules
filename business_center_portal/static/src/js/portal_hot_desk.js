import { HOT_DESK_EVENTS } from "@business_center_portal/js/hot_desk_events";

/** Hot desk booking form: free desks for the slot, the cost summary, and the
 * floor picker kept in step through HOT_DESK_EVENTS. */
function initHotDeskForm() {
    const form = document.getElementById("o_bc_hot_desk_form");
    if (!form) {
        return;
    }
    const byId = (id) => document.getElementById(id);
    const contract = byId("hd_contract_id");
    const partner = byId("hd_partner_id");
    const date = byId("hd_booking_date");
    const start = byId("hd_start_time");
    const end = byId("hd_end_time");
    const desk = byId("hd_desk_id");
    const hint = byId("o_bc_hd_desk_hint");
    const summary = byId("o_bc_hd_summary");
    const symbol = form.dataset.currency || "";
    const slotOptions = (sites) => ({
        contractId: Number(contract.value),
        bookingDate: date.value,
        startTime: start.value,
        endTime: end.value,
        sites,
    });
    let options = slotOptions([]);

    const send = (name, detail) => document.dispatchEvent(new CustomEvent(name, { detail }));
    const announce = () => send(HOT_DESK_EVENTS.options, options);
    const toFloat = (value) => {
        if (!value) {
            return null;
        }
        const [h, m] = value.split(":");
        return parseInt(h, 10) + parseInt(m, 10) / 60;
    };
    const setSummary = (cls, text) => {
        summary.className = `o_bc_summary ${cls}`;
        summary.textContent = text;
    };

    const updateSummary = () => {
        const s = toFloat(start.value);
        const e = toFloat(end.value);
        if (s === null || e === null) {
            return setSummary("o_bc_summary_idle", "Pick a start and end time to see the cost.");
        }
        if (e <= s) {
            return setSummary("o_bc_summary_bad", "The end time must be after the start time.");
        }
        const option = desk.selectedOptions[0];
        if (!option || !option.value) {
            return setSummary("o_bc_summary_idle", "Pick a desk to see the cost.");
        }
        const hours = Math.round((e - s) * 100) / 100;
        const rate = parseFloat(option.dataset.rate || "0");
        setSummary("o_bc_summary_ok",
            `${hours} hr × ${symbol}${rate.toFixed(2)} = ${symbol}${(hours * rate).toFixed(2)}`);
    };

    const refill = (select, items, label = (item) => item.name) => {
        const keep = select.value;
        const opts = items.map((item) => {
            const opt = new Option(label(item), item.id);
            if (item.rate !== undefined) {
                opt.dataset.rate = item.rate;
            }
            return opt;
        });
        if (select === desk) {
            opts.unshift(new Option("Choose a desk…", ""));
        }
        select.replaceChildren(...opts);
        if (items.some((item) => String(item.id) === keep)) {
            select.value = keep;
        }
    };

    const refresh = async () => {
        const params = new URLSearchParams({
            contract_id: contract.value,
            booking_date: date.value,
            start_time: start.value,
            end_time: end.value,
        });
        hint.textContent = "Loading free desks…";
        try {
            const response = await fetch(`/my/hot-desks/desks?${params}`);
            const data = await response.json();
            refill(desk, data.desks);
            refill(partner, data.people);
            hint.textContent = data.desks.length
                ? `${data.desks.length} desk(s) free for this time.`
                : "No hot desk is free for this time.";
            options = slotOptions(data.sites);
            announce();
            updateSummary();
        } catch {
            hint.textContent = "Could not load the free desks. Please retry.";
        }
    };

    [contract, date, start, end].forEach((el) => el.addEventListener("change", refresh));
    desk.addEventListener("change", () => {
        send(HOT_DESK_EVENTS.chosen, { id: Number(desk.value) });
        updateSummary();
    });
    document.addEventListener(HOT_DESK_EVENTS.ready, announce);
    document.addEventListener(HOT_DESK_EVENTS.picked, (ev) => {
        desk.value = String(ev.detail.id);
        updateSummary();
    });
    refresh();
}

/** Cancel dialog on a booking's page: once free cancellation has ended
 * while the page was open, show the cancellation request form instead.
 * The server's seconds-left is counted down here, so the member's own clock
 * and time zone don't matter; the server checks again on submit. */
function initHotDeskCancelDialog() {
    const modal = document.getElementById("o_bc_cancel_hot_desk");
    if (!modal || modal.dataset.freeSeconds === undefined) {
        return;
    }
    const freeUntil = Date.now() + Number(modal.dataset.freeSeconds) * 1000;
    modal.addEventListener("show.bs.modal", () => {
        const ended = Date.now() >= freeUntil;
        modal.querySelector(".o_bc_cancel_free").classList.toggle("d-none", ended);
        modal.querySelector(".o_bc_cancel_request").classList.toggle("d-none", !ended);
    });
}
function onReady(callback) {
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", callback);
    } else {
        callback();
    }
}

onReady(initHotDeskForm);
onReady(initHotDeskCancelDialog);