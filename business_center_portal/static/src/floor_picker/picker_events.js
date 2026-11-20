/**
 * Events between a booking form and its floor picker, so neither knows the
 * other's internals; both only know these names. Each kind of picker (hot
 * desk, meeting room, ...) has its own names, so two pickers never mix.
 *
 *  ready   picker -> form: mounted, send the current options
 *  options form -> picker: {contractId, params, sites}; ``params`` are the
 *          query parameters of the slot states route (date, times, ...)
 *  chosen  form -> picker: {id} chosen in the dropdown
 *  picked  picker -> form: {id} clicked on the plan
 *
 * @param {string} kind e.g. "hot_desk", "meeting_room"
 */
export function pickerEvents(kind) {
    const prefix = `bc-floor-picker:${kind}`;
    return Object.freeze({
        ready: `${prefix}:ready`,
        options: `${prefix}:options`,
        chosen: `${prefix}:chosen`,
        picked: `${prefix}:picked`,
    });
}
