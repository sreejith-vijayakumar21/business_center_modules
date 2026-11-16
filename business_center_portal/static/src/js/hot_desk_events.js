/**
 * Events between the hot desk booking form and its floor picker, so neither
 * knows the other's internals; both only know these names.
 */
export const HOT_DESK_EVENTS = Object.freeze({
    // picker -> form: mounted, send the current options
    ready: "bc-hot-desk:picker-ready",
    // form -> picker: {contractId, bookingDate, startTime, endTime, sites}
    options: "bc-hot-desk:options",
    // form -> picker: {id} chosen in the dropdown
    chosen: "bc-hot-desk:chosen",
    // picker -> form: {id} clicked on the plan
    picked: "bc-hot-desk:picked",
});