import { reactive } from "@odoo/owl";
import { clampToCanvas, normalizeAngle, round, snap } from "./geometry";

const HISTORY_LIMIT = 60;
const OBJECT_FIELDS = [
    "name", "object_type", "x", "y", "width", "height", "rotation", "z_index",
    "fill_color", "border_color", "border_width", "text_color", "font_size", "icon",
    "link_key", "link_res_id",
];
let keySeq = 0;

function newKey() {
    keySeq += 1;
    return `new_${Date.now().toString(36)}_${keySeq}`;
}

/**
 * Client-side state of the layout being edited.
 *
 * All edits happen here, in memory; nothing is sent to the server until
 * ``serialize()`` is saved. Every object has a stable client ``key`` (saved
 * objects also have an ``id``).
 */
export class LayoutStore {
    static create(data) {
        const store = reactive(new LayoutStore());
        store.load(data);
        return store;
    }

    constructor() {
        this.plan = {};
        this.objects = [];
        this.presets = [];
        this.statusPalette = {};
        this.statusList = [];
        this.providers = [];
        this.statusByObjectId = {};
        this.statusMeta = {};
        this.summary = {};
        this.selectedKey = null;
        this.dirty = false;
        this.saving = false;
        this.view = { zoom: 1, panX: 0, panY: 0 };
        this.undoStack = [];
        this.redoStack = [];
    }

    // ------------------------------------------------------------------
    // MARK: LOADING / SAVING
    // ------------------------------------------------------------------
    load(data) {
        this.plan = { ...data.plan };
        this.presets = data.presets;
        this.statusList = data.statuses;
        this.statusPalette = Object.fromEntries(data.statuses.map((s) => [s.code, s]));
        this.providers = data.providers;
        this.objects = data.objects.map((o) => ({ ...o, key: `id_${o.id}` }));
        this.dirty = false;
        this.undoStack = [];
        this.redoStack = [];
    }

    serialize() {
        return {
            version: this.plan.layout_version,
            plan: {
                grid_size: this.plan.grid_size,
                show_grid: this.plan.show_grid,
                snap_to_grid: this.plan.snap_to_grid,
            },
            objects: this.objects.map((o) => {
                const vals = Object.fromEntries(OBJECT_FIELDS.map((f) => [f, o[f]]));
                if (o.id) {
                    vals.id = o.id;
                } else {
                    vals.client_key = o.key;
                }
                return vals;
            }),
        };
    }

    /** Replace local state with the server's answer, keeping the selection. */
    applySaveResult(result) {
        const selected = this.selected;
        let selectedId = selected && selected.id;
        if (selected && !selected.id) {
            selectedId = result.id_map[selected.key];
        }
        this.load(result);
        this.selectedKey = selectedId ? `id_${selectedId}` : null;
    }

    setStatuses(result) {
        this.statusByObjectId = result.objects;
        this.summary = result.summary || {};
        this.statusMeta = {
            at: result.at,
            timeDependent: result.time_dependent,
            computedAt: result.computed_at,
        };
    }

    // ------------------------------------------------------------------
    // MARK: QUERIES
    // ------------------------------------------------------------------
    get selected() {
        return this.objects.find((o) => o.key === this.selectedKey) || null;
    }

    get sortedObjects() {
        return [...this.objects].sort((a, b) => a.z_index - b.z_index);
    }

    statusOf(obj) {
        const info = (obj.id && this.statusByObjectId[obj.id]) || { status: "unknown" };
        return { ...info, display: this.statusPalette[info.status] || this.statusPalette.unknown };
    }

    providersFor(objectType) {
        return this.providers.filter((p) => p.object_types.includes(objectType));
    }

    // ------------------------------------------------------------------
    // MARK: HISTORY
    // ------------------------------------------------------------------
    _snapshot() {
        return JSON.stringify({ objects: this.objects, plan: this.plan });
    }

    /** Call once before a user action that changes the layout. */
    checkpoint() {
        this.undoStack.push(this._snapshot());
        if (this.undoStack.length > HISTORY_LIMIT) {
            this.undoStack.shift();
        }
        this.redoStack = [];
        this.dirty = true;
    }

    _restore(snapshot) {
        const state = JSON.parse(snapshot);
        this.objects = state.objects;
        this.plan = state.plan;
        if (!this.selected) {
            this.selectedKey = null;
        }
        this.dirty = true;
    }

    undo() {
        if (this.undoStack.length) {
            this.redoStack.push(this._snapshot());
            this._restore(this.undoStack.pop());
        }
    }

    redo() {
        if (this.redoStack.length) {
            this.undoStack.push(this._snapshot());
            this._restore(this.redoStack.pop());
        }
    }

    // ------------------------------------------------------------------
    // MARK: EDITS
    // ------------------------------------------------------------------
    select(key) {
        this.selectedKey = key;
    }

    _maxZ() {
        return this.objects.reduce((max, o) => Math.max(max, o.z_index), 0);
    }

    _fit(rect) {
        return clampToCanvas(rect, this.plan.canvas_width, this.plan.canvas_height);
    }

    addFromPreset(preset, center) {
        this.checkpoint();
        const grid = this.plan.snap_to_grid ? this.plan.grid_size : 0;
        const rect = this._fit({
            x: snap(center.x - preset.width / 2, grid, !!grid),
            y: snap(center.y - preset.height / 2, grid, !!grid),
            width: preset.width,
            height: preset.height,
        });
        const obj = {
            key: newKey(),
            id: false,
            name: preset.object_type === "label" ? preset.name : this._nextName(preset),
            object_type: preset.object_type,
            category: preset.category,
            rotation: 0,
            // Zones sit under the desks they group; everything else on top.
            z_index: preset.category === "zone" ? 0 : this._maxZ() + 1,
            fill_color: preset.fill_color,
            border_color: preset.border_color,
            border_width: preset.border_width,
            text_color: preset.text_color,
            font_size: preset.font_size,
            icon: preset.icon || false,
            link_key: false,
            link_res_id: false,
            link_name: false,
            link_restricted: false,
            ...rect,
        };
        this.objects.push(obj);
        this.selectedKey = obj.key;
        return obj;
    }

    _nextName(preset) {
        const names = new Set(this.objects.map((o) => o.name));
        let index = 1;
        while (names.has(`${preset.name} ${index}`)) {
            index += 1;
        }
        return `${preset.name} ${index}`;
    }

    /** Apply a patch to an object. Geometry is clamped to the canvas. */
    update(key, patch, { checkpoint = true } = {}) {
        const obj = this.objects.find((o) => o.key === key);
        if (!obj) {
            return;
        }
        if (checkpoint) {
            this.checkpoint();
        } else {
            this.dirty = true;
        }
        const next = { ...obj, ...patch };
        if ("rotation" in patch) {
            next.rotation = normalizeAngle(next.rotation);
        }
        Object.assign(next, this._fit(next));
        for (const f of ["x", "y", "width", "height"]) {
            next[f] = round(next[f]);
        }
        Object.assign(obj, next);
    }

    remove(key) {
        this.checkpoint();
        this.objects = this.objects.filter((o) => o.key !== key);
        if (this.selectedKey === key) {
            this.selectedKey = null;
        }
    }

    duplicate(key) {
        const source = this.objects.find((o) => o.key === key);
        if (!source) {
            return null;
        }
        this.checkpoint();
        const offset = this.plan.grid_size || 10;
        const copy = {
            ...source,
            key: newKey(),
            id: false,
            name: source.name ? `${source.name} (copy)` : source.name,
            z_index: this._maxZ() + 1,
            // A business record can only be placed once: copies start unlinked.
            link_key: false,
            link_res_id: false,
            link_name: false,
            link_restricted: false,
            ...this._fit({ ...source, x: source.x + offset, y: source.y + offset }),
        };
        this.objects.push(copy);
        this.selectedKey = copy.key;
        return copy;
    }

    reorder(key, direction) {
        const obj = this.objects.find((o) => o.key === key);
        if (!obj) {
            return;
        }
        this.checkpoint();
        if (direction === "front") {
            obj.z_index = this._maxZ() + 1;
        } else {
            obj.z_index = this.objects.reduce((min, o) => Math.min(min, o.z_index), 0) - 1;
        }
    }

    /** Link (or unlink) an object; a linked shape takes the record's name as its label. */
    setLink(key, provider, record) {
        const patch = {
            link_key: provider ? provider.key : false,
            link_res_id: record ? record.id : false,
            link_name: record ? record.display_name : false,
            link_restricted: false,
        };
        if (record) {
            patch.name = record.display_name.slice(0, 120);
        }
        this.update(key, patch);
    }

    setPlanOption(field, value) {
        this.checkpoint();
        this.plan[field] = value;
    }
}
