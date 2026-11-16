import { _t } from "@web/core/l10n/translation";
import { centerOf, rotateVector } from "../core/geometry";

export const PICKABLE = "pickable";
export const UNPICKABLE = "unpickable";
export const PICKED = "picked";
export const CHOSEN = "chosen";

/** True when ``point`` lies inside ``rect`` once the rect is rotated around its centre. */
export function pointInRect(point, rect) {
    const c = centerOf(rect);
    const local = rotateVector(point.x - c.x, point.y - c.y, -(rect.rotation || 0));
    return Math.abs(local.x) <= rect.width / 2 && Math.abs(local.y) <= rect.height / 2;
}

/**
 * Colour a layout by whether each unit may be picked instead of by its
 * business status: picked, pickable, chosen elsewhere or not available.
 * Zones summarise the pickable units inside them. Shared by every picker, so
 * the backend dialog and the portal look and count the same.
 *
 * @param {Object} store a LayoutStore
 * @param {{isPickable: Function, isChosen?: Function}} rules
 */
export function colourByPickability(store, { isPickable, isChosen = () => false }) {
    const palette = store.statusPalette;
    store.statusPalette = {
        ...palette,
        [PICKABLE]: {
            code: PICKABLE,
            name: _t("Available to pick"),
            color: palette.available ? palette.available.color : "#8EDCB0",
        },
        [UNPICKABLE]: { code: UNPICKABLE, name: _t("Not available here"), color: "#DCE0E8" },
        [PICKED]: { code: PICKED, name: _t("Selected"), color: "#8E9BF5" },
        [CHOSEN]: { code: CHOSEN, name: _t("On this contract"), color: "#C9D6FB" },
    };
    const objects = {};
    const units = store.objects.filter((o) => o.category === "rentable");
    for (const unit of units) {
        let status = UNPICKABLE;
        if (isChosen(unit)) {
            status = CHOSEN;
        } else if (isPickable(unit)) {
            status = unit.key === store.selectedKey ? PICKED : PICKABLE;
        }
        objects[unit.id] = { status };
    }
    for (const zone of store.objects.filter((o) => o.category === "zone")) {
        const inside = units.filter((u) => pointInRect(centerOf(u), zone));
        const available = inside.filter((u) => isPickable(u)).length;
        objects[zone.id] = { status: available ? PICKABLE : UNPICKABLE, available, total: inside.length };
    }
    store.setStatuses({ objects, summary: {}, at: false, time_dependent: false, computed_at: false });
}