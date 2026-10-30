import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { HANDLES } from "./handles";

/**
 * One shape on the canvas. Being its own component means that dragging an
 * object only re-renders that object, which keeps large plans fluid.
 */
export class FloorObject extends Component {
    static template = "workspace_floor_planner.FloorObject";
    static props = {
        obj: Object,
        store: Object,
        readonly: Boolean,
    };

    get o() {
        return this.props.obj;
    }

    get store() {
        return this.props.store;
    }

    get selected() {
        return this.store.selectedKey === this.o.key;
    }

    px(px) {
        return px / this.store.view.zoom;
    }

    transformOf(o) {
        return `translate(${o.x} ${o.y}) rotate(${o.rotation} ${o.width / 2} ${o.height / 2})`;
    }

    isRentable(o) {
        return o.category === "rentable";
    }

    isZone(o) {
        return o.category === "zone";
    }

    fillOf(o) {
        return this.isRentable(o) ? this.store.statusOf(o).display.color : o.fill_color;
    }

    fillOpacity(o) {
        if (o.object_type === "label") {
            return 0;
        }
        return this.isRentable(o) ? 0.35 : this.isZone(o) ? 0.45 : 1;
    }

    statusText(o) {
        const status = this.store.statusOf(o);
        if (this.isZone(o)) {
            if (!status.total) {
                return "";
            }
            return _t("%(available)s of %(total)s available", {
                available: status.available || 0,
                total: status.total,
            });
        }
        return this.isRentable(o) ? status.display.name : "";
    }

    tooltipOf(o) {
        const parts = [o.name || o.object_type];
        const text = this.statusText(o);
        if (text) {
            parts.push(text);
        }
        if (o.link_name) {
            parts.push(_t("Linked to: %s", o.link_name));
        } else if (this.isRentable(o)) {
            parts.push(_t("Not linked to a business record"));
        }
        return parts.join(" — ");
    }

    /** Zones put their title at the top so the desks inside stay readable. */
    labelY(o) {
        const size = this.labelFontSize(o);
        if (this.isZone(o)) {
            return Math.min(size * 0.9 + 4, o.height / 2);
        }
        return this.statusText(o) ? o.height / 2 - size * 0.35 : o.height / 2;
    }

    statusY(o) {
        const size = this.labelFontSize(o);
        return this.isZone(o) ? this.labelY(o) + size * 0.95 : o.height / 2 + size * 0.75;
    }

    labelFontSize(o) {
        // Keep labels inside small shapes.
        return Math.max(4, Math.min(o.font_size, o.height * 0.45, (o.width / Math.max((o.name || "").length, 1)) * 1.8));
    }

    /** Edge handles are hidden on shapes too small on screen to grab safely. */
    visibleHandles(o) {
        const small = Math.min(o.width, o.height) * this.store.view.zoom < 36;
        return small ? HANDLES.filter((h) => h.name.length === 2) : HANDLES;
    }

    handlePos(o, h) {
        const size = this.px(9);
        return { x: o.width * h.fx - size / 2, y: o.height * h.fy - size / 2, size };
    }

    onKeydown(ev) {
        if (ev.key === "Enter" || ev.key === " ") {
            this.store.select(this.o.key);
            ev.preventDefault();
        }
    }
}
