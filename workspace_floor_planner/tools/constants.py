"""Shared vocabulary of the floor planner.

Everything other modules (and bridge addons) need to agree on lives here, so
there is exactly one place to read or extend it.
"""

# --- Object types ----------------------------------------------------------
# Each object type belongs to one *category*. The category decides behaviour
# (can it be linked to a rentable record? does it summarise children?), so
# code checks categories, never individual type names.
CATEGORY_RENTABLE = "rentable"      # one object == one rentable business record
CATEGORY_ZONE = "zone"              # visual grouping, never rentable itself
CATEGORY_STRUCTURE = "structure"    # walls, doors, windows, columns...
CATEGORY_FACILITY = "facility"      # reception, canteen, restrooms...
CATEGORY_ANNOTATION = "annotation"  # free text labels

OBJECT_TYPES = [
    # (code, label, category)
    ("private_office", "Private Office", CATEGORY_RENTABLE),
    ("dedicated_desk", "Dedicated Desk", CATEGORY_RENTABLE),
    ("hot_desk", "Hot Desk", CATEGORY_RENTABLE),
    ("meeting_room", "Meeting Room", CATEGORY_RENTABLE),
    ("coworking_zone", "Coworking Zone", CATEGORY_ZONE),
    ("wall", "Wall", CATEGORY_STRUCTURE),
    ("door", "Door", CATEGORY_STRUCTURE),
    ("window", "Window", CATEGORY_STRUCTURE),
    ("column", "Column", CATEGORY_STRUCTURE),
    ("facility", "Facility / Amenity", CATEGORY_FACILITY),
    ("label", "Text Label", CATEGORY_ANNOTATION),
]

OBJECT_TYPE_SELECTION = [(code, label) for code, label, _cat in OBJECT_TYPES]
OBJECT_TYPE_CATEGORY = {code: cat for code, _label, cat in OBJECT_TYPES}
RENTABLE_TYPES = frozenset(
    code for code, _l, cat in OBJECT_TYPES if cat == CATEGORY_RENTABLE
)
ZONE_TYPES = frozenset(code for code, _l, cat in OBJECT_TYPES if cat == CATEGORY_ZONE)

# --- Normalised status contract ---------------------------------------------
STATUS_AVAILABLE = "available"
STATUS_OCCUPIED = "occupied"
STATUS_RESERVED = "reserved"
STATUS_MAINTENANCE = "maintenance"
STATUS_PARTIAL = "partial"
STATUS_UNKNOWN = "unknown"

STATUS_SELECTION = [
    (STATUS_AVAILABLE, "Available"),
    (STATUS_OCCUPIED, "Occupied"),
    (STATUS_RESERVED, "Reserved"),
    (STATUS_MAINTENANCE, "Maintenance"),
    (STATUS_PARTIAL, "Partially available"),
    (STATUS_UNKNOWN, "Unknown / not linked"),
]
STATUS_CODES = frozenset(code for code, _label in STATUS_SELECTION)
# Statuses a provider may return for a single unit. "partial" is reserved for
# zones and is derived by the core from the units inside the zone.
UNIT_STATUS_CODES = STATUS_CODES - {STATUS_PARTIAL}

# --- Geometry / payload limits ----------------------------------------------
# Logical canvas units. x/y is the top-left corner of the *unrotated*
# rectangle; rotation (degrees, clockwise) is applied around the centre.
MIN_OBJECT_SIZE = 2.0
MIN_CANVAS_SIZE = 200
MAX_CANVAS_SIZE = 20000
MAX_OBJECTS_PER_PLAN = 2000
MAX_LABEL_LENGTH = 120
MIN_FONT_SIZE = 6
MAX_FONT_SIZE = 200
MAX_BORDER_WIDTH = 50
MAX_Z_INDEX = 100000
MAX_LINK_SEARCH_LIMIT = 50
COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"
ICON_PATTERN = r"^fa-[a-z0-9-]{1,40}$"
