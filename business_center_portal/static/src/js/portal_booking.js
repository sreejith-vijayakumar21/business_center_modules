import { pickerEvents } from "@business_center_portal/floor_picker/picker_events";

const EVENTS = pickerEvents("meeting_room");

/**
 * Meeting room booking form: the rooms free for the date, time and group
 * size, the picked room's day strip, the wallet and cost summary, and the
 * floor picker kept in step through pickerEvents("meeting_room").
 * Availability always comes from the server.
 */
function initBookingForm() {
    const form = document.getElementById("o_bc_booking_form");
    if (!form) {
        return;
    }
    const byId = (id) => document.getElementById(id);
    const contract = byId("contract_id");
    const date = byId("booking_date");
    const startEl = byId("start_time");
    const endEl = byId("end_time");
    const attendees = byId("attendees");
    const room = byId("meeting_room_id");
    const hint = byId("o_bc_room_hint");
    const slots = byId("o_bc_slots");
    const hours = byId("o_bc_hours");
    const rateEl = byId("o_bc_rate");
    const wallet = byId("o_bc_wallet");
    const summary = byId("o_bc_summary");
    const symbol = form.dataset.currency || "";

    let walletHours = parseFloat(wallet.textContent) || 0;
    let options = { contractId: Number(contract.value), params: {}, sites: [] };

    const send = (name, detail) => document.dispatchEvent(new CustomEvent(name, { detail }));
    const announce = () => send(EVENTS.options, options);
    const slotParams = () => ({
        booking_date: date.value,
        start_time: startEl.value,
        end_time: endEl.value,
        attendees: attendees.value,
    });
    const toHHMM = (value) => {
        const total = Math.round(parseFloat(value) * 60);
        return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
    };
    const toFloat = (value) => {
        if (!value) {
            return null;
        }
        const [h, m] = value.split(":");
        return parseInt(h, 10) + parseInt(m, 10) / 60;
    };
    const roomRate = () => parseFloat((room.selectedOptions[0] || {}).dataset?.rate || "0");

    const setSummary = (cls, html) => {
        summary.className = `o_bc_summary ${cls}`;
        summary.innerHTML = html;
    };

    const updateSummary = () => {
        const s = toFloat(startEl.value);
        const e = toFloat(endEl.value);
        if (s === null || e === null) {
            return setSummary("o_bc_summary_idle", "Pick a start and end time to see the cost.");
        }
        if (e <= s) {
            return setSummary("o_bc_summary_bad", "The end time must be after the start time.");
        }
        if (!room.value) {
            return setSummary("o_bc_summary_idle", "Pick a room to see the cost.");
        }
        const used = e - s;
        const fmt = (n) => (Math.round(n * 100) / 100).toString();
        if (used <= walletHours) {
            return setSummary("o_bc_summary_ok",
                `<strong>${fmt(used)} hr</strong> from your wallet · ` +
                `<span>${fmt(walletHours - used)} hr will remain</span>`);
        }
        const extra = used - walletHours;
        setSummary("o_bc_summary_warn",
            `<strong>${fmt(used)} hr</strong> booked · ${fmt(walletHours)} hr from wallet · ` +
            `<strong>${fmt(extra)} hr</strong> billed extra (≈ ${symbol}${(extra * roomRate()).toFixed(2)})`);
    };

    /** The picked room's opening hours, rate and day strip. */
    const refreshStrip = async () => {
        rateEl.textContent = room.value ? `${symbol}${roomRate().toFixed(2)}` : "—";
        if (!room.value) {
            slots.innerHTML = '<span class="o_bc_dim small">Pick a room to see its day.</span>';
            hours.textContent = "—";
            return;
        }
        const params = new URLSearchParams({
            contract_id: contract.value,
            meeting_room_id: room.value,
            booking_date: date.value,
        });
        slots.innerHTML = '<span class="o_bc_dim small">Loading availability…</span>';
        try {
            const response = await fetch(`/my/bookings/slots?${params}`);
            const data = await response.json();
            slots.innerHTML = data.slots ||
                '<span class="o_bc_dim small">No availability to show for this day.</span>';
            hours.textContent = data.hours || "—";
        } catch {
            slots.innerHTML = '<span class="text-danger small">Could not load availability. Please retry.</span>';
        }
    };

    /** Free rooms for the date, time and group; tells the floor picker. */
    const refreshRooms = async () => {
        const params = new URLSearchParams({ contract_id: contract.value, ...slotParams() });
        hint.textContent = "Loading free rooms…";
        try {
            const response = await fetch(`/my/bookings/rooms?${params}`);
            const data = await response.json();
            const keep = room.value;
            const opts = data.rooms.map((r) => {
                const opt = new Option(r.name, r.id);
                opt.dataset.rate = r.rate;
                return opt;
            });
            room.replaceChildren(new Option("Choose a room…", ""), ...opts);
            if (data.rooms.some((r) => String(r.id) === keep)) {
                room.value = keep;
            }
            hint.textContent = data.rooms.length
                ? `${data.rooms.length} room(s) free for this time.`
                : "No meeting room is free for this time and group size.";
            wallet.textContent = data.wallet;
            walletHours = parseFloat(data.wallet) || 0;
            options = { contractId: Number(contract.value), params: slotParams(), sites: data.sites };
            announce();
            if (room.value !== keep) {
                send(EVENTS.chosen, { id: Number(room.value) });
            }
            await refreshStrip();
            updateSummary();
        } catch {
            hint.textContent = "Could not load the free rooms. Please retry.";
        }
    };

    const pickRoom = (id) => {
        room.value = String(id);
        refreshStrip();
        updateSummary();
    };

    [contract, date, startEl, endEl, attendees].forEach((el) => el && el.addEventListener("change", refreshRooms));
    room.addEventListener("change", () => {
        send(EVENTS.chosen, { id: Number(room.value) });
        refreshStrip();
        updateSummary();
    });
    document.addEventListener(EVENTS.ready, announce);
    document.addEventListener(EVENTS.picked, (ev) => pickRoom(ev.detail.id));

    // A free box on the picked room's day strip fills the times.
    slots.addEventListener("click", (ev) => {
        const box = ev.target.closest(".o_bc_slot_free");
        if (!box) {
            return;
        }
        slots.querySelectorAll(".o_bc_slot_active").forEach((el) => el.classList.remove("o_bc_slot_active"));
        box.classList.add("o_bc_slot_active");
        startEl.value = toHHMM(box.dataset.start);
        endEl.value = toHHMM(box.dataset.end);
        refreshRooms();
    });

    refreshRooms();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initBookingForm);
} else {
    initBookingForm();
}
