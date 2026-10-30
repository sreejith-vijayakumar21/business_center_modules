import { describe, expect, test } from "@odoo/hoot";
import {
    clampToCanvas,
    fitView,
    normalizeAngle,
    resizeRect,
    rotationFromPointer,
} from "@workspace_floor_planner/floor_planner/core/geometry";
import { LayoutStore } from "@workspace_floor_planner/floor_planner/core/layout_store";

describe.current.tags("headless");

const PLAN_DATA = {
    plan: {
        id: 1, name: "L1", canvas_width: 1000, canvas_height: 800, grid_size: 20,
        show_grid: true, snap_to_grid: true, layout_version: 3, units_per_meter: 50, can_edit: true,
    },
    objects: [
        {
            id: 7, name: "Desk 1", object_type: "hot_desk", category: "rentable", x: 100, y: 100,
            width: 50, height: 40, rotation: 0, z_index: 1, fill_color: "#FFFFFF", border_color: "#000000",
            border_width: 2, text_color: "#000000", font_size: 14, icon: false,
            link_key: "unit", link_res_id: 42, link_name: "Desk A", link_restricted: false,
        },
    ],
    presets: [],
    statuses: [
        { code: "available", name: "Available", color: "#00FF00" },
        { code: "unknown", name: "Unknown", color: "#999999" },
    ],
    providers: [{ key: "unit", label: "Unit", object_types: ["hot_desk"] }],
};
const PRESET = {
    id: 1, name: "Hot Desk", object_type: "hot_desk", category: "rentable", width: 50, height: 40,
    fill_color: "#FFFFFF", border_color: "#000000", border_width: 2, text_color: "#000000", font_size: 14,
};

describe("geometry", () => {
    test("normalizeAngle folds into [0, 360)", () => {
        expect(normalizeAngle(-90)).toBe(270);
        expect(normalizeAngle(720)).toBe(0);
    });

    test("resize east handle on an unrotated rect keeps the west edge", () => {
        const r = resizeRect({ x: 10, y: 10, width: 100, height: 50, rotation: 0 }, "e", 30, 99);
        expect(r).toEqual({ x: 10, y: 10, width: 130, height: 50 });
    });

    test("resize respects the minimum size", () => {
        const r = resizeRect({ x: 10, y: 10, width: 100, height: 50, rotation: 0 }, "w", 500, 0);
        expect(r.width).toBe(2);
        expect(r.x).toBe(108);
    });

    test("resize a 90° rotated rect works in its local frame", () => {
        // Rotated 90° clockwise, the local +x axis points down on screen.
        const r = resizeRect({ x: 0, y: 0, width: 100, height: 20, rotation: 90 }, "e", 0, 40);
        expect(r.width).toBe(140);
        expect(r.height).toBe(20);
    });

    test("rotation handle angle", () => {
        const rect = { x: 0, y: 0, width: 100, height: 100 };
        expect(rotationFromPointer(rect, { x: 50, y: -100 })).toBe(0);
        expect(rotationFromPointer(rect, { x: 200, y: 50 })).toBe(90);
        expect(rotationFromPointer(rect, { x: 200, y: 40 }, 15)).toBe(90);
    });

    test("clampToCanvas keeps shapes on the canvas", () => {
        expect(clampToCanvas({ x: -10, y: 790, width: 50, height: 40 }, 1000, 800)).toEqual({
            x: 0, y: 760, width: 50, height: 40,
        });
    });

    test("fitView centres the canvas", () => {
        const v = fitView(1000, 500, 1048, 548, 24);
        expect(v.zoom).toBe(1);
        expect(v.panX).toBe(-24);
    });
});

describe("LayoutStore", () => {
    test("serialize sends ids for saved objects and client keys for new ones", () => {
        const store = LayoutStore.create(JSON.parse(JSON.stringify(PLAN_DATA)));
        store.addFromPreset(PRESET, { x: 500, y: 400 });
        const payload = store.serialize();
        expect(payload.version).toBe(3);
        expect(payload.objects[0].id).toBe(7);
        expect(payload.objects[1].client_key).toMatch(/^new_/);
        expect("status" in payload.objects[1]).toBe(false);
        expect(store.dirty).toBe(true);
    });

    test("duplicate never copies the business link", () => {
        const store = LayoutStore.create(JSON.parse(JSON.stringify(PLAN_DATA)));
        const copy = store.duplicate("id_7");
        expect(copy.link_key).toBe(false);
        expect(copy.link_res_id).toBe(false);
        expect(copy.id).toBe(false);
    });

    test("undo and redo restore the layout", () => {
        const store = LayoutStore.create(JSON.parse(JSON.stringify(PLAN_DATA)));
        store.update("id_7", { x: 300 });
        expect(store.objects[0].x).toBe(300);
        store.undo();
        expect(store.objects[0].x).toBe(100);
        store.redo();
        expect(store.objects[0].x).toBe(300);
    });

    test("updates are clamped to the canvas", () => {
        const store = LayoutStore.create(JSON.parse(JSON.stringify(PLAN_DATA)));
        store.update("id_7", { x: 5000, rotation: -45 });
        expect(store.objects[0].x).toBe(950);
        expect(store.objects[0].rotation).toBe(315);
    });

    test("unknown status for unsaved or unlisted objects", () => {
        const store = LayoutStore.create(JSON.parse(JSON.stringify(PLAN_DATA)));
        expect(store.statusOf(store.objects[0]).status).toBe("unknown");
        store.setStatuses({ objects: { 7: { status: "available" } }, at: false, time_dependent: false });
        expect(store.statusOf(store.objects[0]).display.name).toBe("Available");
    });
});
