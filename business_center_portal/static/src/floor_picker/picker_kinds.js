import { _t } from "@web/core/l10n/translation";

/**
 * What each portal floor picker picks: its link key, its routes and its
 * texts. Adding a new kind of unit means adding an entry here; the picker
 * component itself does not change.
 *
 * States sent by the server: "free", "booked", "closed", and for meeting
 * rooms "small" (fewer seats than the group).
 */
const KINDS = {
    hot_desk: () => ({
        linkKey: "bc_hot_desk",
        floorUrl: (planId) => `/my/hot-desks/floor/${planId}`,
        slotsUrl: (planId) => `/my/hot-desks/floor/${planId}/slots`,
        detailsUrl: (id) => `/my/hot-desks/desk/${id}`,
        empty: _t("No hot desk of your centre is drawn on a floor plan. Choose from the list below."),
        loadError: _t("Could not load which desks are free. Choose from the list below, or reload the page."),
        notes: {
            booked: _t("This desk is taken for part of your time. Pick a green desk or change the time."),
            closed: _t("This desk is not open for booking right now."),
        },
        legend: ["free", "booked", "closed"],
    }),
    meeting_room: () => ({
        linkKey: "bc_meeting_room",
        floorUrl: (planId) => `/my/bookings/floor/${planId}`,
        slotsUrl: (planId) => `/my/bookings/floor/${planId}/slots`,
        detailsUrl: (id) => `/my/bookings/room/${id}`,
        empty: _t("No meeting room of your centre is drawn on a floor plan. Choose from the list below."),
        loadError: _t("Could not load which rooms are free. Choose from the list below, or reload the page."),
        notes: {
            booked: _t("This room is taken for part of your time. Pick a green room or change the time."),
            closed: _t("This room is closed at that time or not open for booking. Its opening hours are below."),
            small: _t("This room has fewer seats than your group. Pick a green room or change the number of attendees."),
        },
        legend: ["free", "booked", "small", "closed"],
    }),
};

/** The settings of one kind of picker (built on call, so texts are translated). */
export function pickerKind(kind) {
    const build = KINDS[kind];
    if (!build) {
        throw new Error(`Unknown floor picker kind: ${kind}`);
    }
    return build();
}
