/** Resize handles: name, cursor and position as a fraction of the shape. */
export const HANDLES = [
    { name: "nw", cursor: "nwse-resize", fx: 0, fy: 0 },
    { name: "n", cursor: "ns-resize", fx: 0.5, fy: 0 },
    { name: "ne", cursor: "nesw-resize", fx: 1, fy: 0 },
    { name: "e", cursor: "ew-resize", fx: 1, fy: 0.5 },
    { name: "se", cursor: "nwse-resize", fx: 1, fy: 1 },
    { name: "s", cursor: "ns-resize", fx: 0.5, fy: 1 },
    { name: "sw", cursor: "nesw-resize", fx: 0, fy: 1 },
    { name: "w", cursor: "ew-resize", fx: 0, fy: 0.5 },
];
