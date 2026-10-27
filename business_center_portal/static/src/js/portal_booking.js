/** Booking form: refresh availability, click-to-fill slots, live cost summary. */
function initBookingForm() {
    const form = document.getElementById('o_bc_booking_form');
    if (!form) {
        return;
    }
    const contract = document.getElementById('contract_id');
    const room = document.getElementById('meeting_room_id');
    const date = document.getElementById('booking_date');
    const slots = document.getElementById('o_bc_slots');
    const hours = document.getElementById('o_bc_hours');
    const wallet = document.getElementById('o_bc_wallet');
    const startEl = document.getElementById('start_time');
    const endEl = document.getElementById('end_time');
    const summary = document.getElementById('o_bc_summary');

    let rate = parseFloat(form.dataset.rate || '0');
    let walletHours = parseFloat(wallet.textContent) || 0;

    const toHHMM = (value) => {
        const total = Math.round(parseFloat(value) * 60);
        const h = String(Math.floor(total / 60)).padStart(2, '0');
        const m = String(total % 60).padStart(2, '0');
        return `${h}:${m}`;
    };

    const toFloat = (value) => {
        if (!value) { return null; }
        const [h, m] = value.split(':');
        return parseInt(h, 10) + parseInt(m, 10) / 60;
    };

    const setSummary = (cls, html) => {
        summary.className = `o_bc_summary ${cls}`;
        summary.innerHTML = html;
    };

    const updateSummary = () => {
        const s = toFloat(startEl.value);
        const e = toFloat(endEl.value);
        if (s === null || e === null) {
            setSummary('o_bc_summary_idle', 'Pick a start and end time to see the cost.');
            return;
        }
        if (e <= s) {
            setSummary('o_bc_summary_bad', 'The end time must be after the start time.');
            return;
        }
        const used = e - s;
        if (used > 8) {
            setSummary('o_bc_summary_bad', 'Bookings cannot run longer than 8 hours.');
            return;
        }
        const fmt = (n) => (Math.round(n * 100) / 100).toString();
        if (used <= walletHours) {
            setSummary('o_bc_summary_ok',
                `<strong>${fmt(used)} hr</strong> from your wallet · ` +
                `<span>${fmt(walletHours - used)} hr will remain</span>`);
        } else {
            const extra = used - walletHours;
            const cost = (extra * rate).toFixed(2);
            setSummary('o_bc_summary_warn',
                `<strong>${fmt(used)} hr</strong> booked · ${fmt(walletHours)} hr from wallet · ` +
                `<strong>${fmt(extra)} hr</strong> billed extra (≈ ${cost})`);
        }
    };

    const refresh = async () => {
        const params = new URLSearchParams({
            contract_id: contract ? contract.value : '',
            meeting_room_id: room.value,
            booking_date: date.value,
        });
        slots.innerHTML = '<span class="o_bc_dim small">Loading availability…</span>';
        try {
            const response = await fetch(`/my/bookings/slots?${params}`);
            const data = await response.json();
            slots.innerHTML = data.slots ||
                '<span class="o_bc_dim small">No availability to show for this day.</span>';
            hours.textContent = data.hours;
            wallet.textContent = data.wallet;
            walletHours = parseFloat(data.wallet) || 0;
            rate = parseFloat(data.rate) || 0;

            const ids = data.rooms.map((r) => String(r.id));
            if (!data.rooms.length) {
                room.innerHTML = '';
                slots.innerHTML =
                    '<span class="o_bc_dim small">No bookable meeting rooms in this centre.</span>';
                updateSummary();
                return;
            }
            if (!ids.includes(room.value)) {
                room.innerHTML = data.rooms
                    .map((r) => `<option value="${r.id}">${r.name}</option>`)
                    .join('');
                refresh();
                return;
            }
            updateSummary();
        } catch (error) {
            slots.innerHTML =
                '<span class="text-danger small">Could not load availability. Please retry.</span>';
        }
    };

    [contract, room, date].forEach((el) => el && el.addEventListener('change', refresh));
    [startEl, endEl].forEach((el) => el && el.addEventListener('input', updateSummary));

    slots.addEventListener('click', (ev) => {
        const box = ev.target.closest('.o_bc_slot_free');
        if (!box) {
            return;
        }
        slots.querySelectorAll('.o_bc_slot_active')
             .forEach((el) => el.classList.remove('o_bc_slot_active'));
        box.classList.add('o_bc_slot_active');
        startEl.value = toHHMM(box.dataset.start);
        endEl.value = toHHMM(box.dataset.end);
        updateSummary();
    });

    updateSummary();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBookingForm);
} else {
    initBookingForm();
}