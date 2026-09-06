"""Map Overlay model — pure data + game taxonomy for the unified map overlay.

This module holds the overlay's **configuration data structures** and the **classification
taxonomy** (marker styles, range rings, custom markers, and the spirit categorisation that
turns a model id into a marker + range). It is the from-scratch replacement for the two
independent, hand-maintained tables that lived inside ``Compass +.py`` and
``Mission Map +.py``.

Boundary
--------
Depends **only on the shared taxonomy** (``Py4GWCoreLib.enums`` — ``Range``, ``SpiritModelID``,
``PetModelID``, ``SPIRIT_BUFF_MAP``). It must **never** import live-game surfaces (``Agent``,
``Map``, ``Player`` …) or any renderer (``PyImGui``, ``DXOverlay``). Everything here is plain
data + membership lookups, so the render / agent / projection layers can all consume it
without a dependency cycle, and the single spirit source of truth is not duplicated again.

Colours
-------
Colours are stored as plain ``RGBA`` tuples (``(r, g, b, a)``, each 0-255) — the same integer
form the legacy inis persist. Packing to draw-list ints / normalised floats is the render
layer's job, keeping this module free of the ``Color`` helper.
"""

from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from typing import Optional

from Py4GWCoreLib.enums import PetModelID
from Py4GWCoreLib.enums import Range
from Py4GWCoreLib.enums import SpiritModelID
from Py4GWCoreLib.enums_src.Model_enums import SPIRIT_BUFF_MAP

# ── Primitive aliases ────────────────────────────────────────────────────────────────────
RGBA = tuple[int, int, int, int]  # (r, g, b, a), each 0-255

#: Ritualist "longbow" spirits project at a fixed 1350 range that has no ``Range`` member.
LONGBOW_SPIRIT_RANGE: int = 1350


# ── Modes ────────────────────────────────────────────────────────────────────────────────
class OverlayMode(str, Enum):
    """Which game frame the overlay draws onto. Exactly one is active at a time."""

    COMPASS = "compass"   # minimap frame — rotates with the camera
    MISSION = "mission"   # mission-map frame — pans/zooms, never rotates


# ── Spirit taxonomy ──────────────────────────────────────────────────────────────────────
class SpiritCategory(str, Enum):
    """The visual family a spirit belongs to — selects its marker style + accent."""

    RANGER = "ranger"
    RITUALIST = "ritualist"
    VANGUARD = "vanguard"


class SpiritRangeClass(str, Enum):
    """The aura/range a spirit projects. Resolved to gwinches by :func:`spirit_range`."""

    SPIRIT = "spirit"     # default spirit range
    AREA = "area"
    EARSHOT = "earshot"
    LONGBOW = "longbow"   # ritualist longbow spirits — fixed 1350


def spirit_range(range_class: SpiritRangeClass) -> int:
    """Resolve a :class:`SpiritRangeClass` to its range in gwinches."""
    if range_class is SpiritRangeClass.AREA:
        return int(Range.Area.value)
    if range_class is SpiritRangeClass.EARSHOT:
        return int(Range.Earshot.value)
    if range_class is SpiritRangeClass.LONGBOW:
        return LONGBOW_SPIRIT_RANGE
    return int(Range.Spirit.value)


# Category membership — merged from both widgets, using Compass's finer ritualist breakdown
# (spirit / longbow / earshot / area) as the authoritative split.
_RANGER_SPIRITS: frozenset[int] = frozenset(int(m) for m in (
    SpiritModelID.BRAMBLES, SpiritModelID.CONFLAGRATION, SpiritModelID.EDGE_OF_EXTINCTION,
    SpiritModelID.ENERGIZING_WIND, SpiritModelID.EQUINOX, SpiritModelID.FAMINE,
    SpiritModelID.FAVORABLE_WINDS, SpiritModelID.FERTILE_SEASON, SpiritModelID.FROZEN_SOIL,
    SpiritModelID.GREATER_CONFLAGRATION, SpiritModelID.INFURIATING_HEAT, SpiritModelID.LACERATE,
    SpiritModelID.MUDDY_TERRAIN, SpiritModelID.NATURES_RENEWAL, SpiritModelID.PESTILENCE,
    SpiritModelID.PREDATORY_SEASON, SpiritModelID.PRIMAL_ECHOES, SpiritModelID.QUICKENING_ZEPHYR,
    SpiritModelID.QUICKSAND, SpiritModelID.ROARING_WINDS, SpiritModelID.SYMBIOSIS,
    SpiritModelID.TOXICITY, SpiritModelID.TRANQUILITY, SpiritModelID.WINNOWING,
    SpiritModelID.WINTER,
))

_RIT_SPIRIT_SPIRITS: frozenset[int] = frozenset(int(m) for m in (
    SpiritModelID.DISPLACEMENT, SpiritModelID.EARTHBIND, SpiritModelID.EMPOWERMENT,
    SpiritModelID.LIFE, SpiritModelID.RECOVERY, SpiritModelID.RECUPERATION,
    SpiritModelID.SHELTER, SpiritModelID.SOOTHING, SpiritModelID.UNION,
))

_RIT_LONGBOW_SPIRITS: frozenset[int] = frozenset(int(m) for m in (
    SpiritModelID.ANGUISH, SpiritModelID.BLOODSONG, SpiritModelID.DISENCHANTMENT,
    SpiritModelID.DISSONANCE, SpiritModelID.PAIN, SpiritModelID.SHADOWSONG,
    SpiritModelID.ANGER, SpiritModelID.HATE, SpiritModelID.SUFFERING,
    SpiritModelID.VAMPIRISM, SpiritModelID.WANDERLUST,
))

_RIT_EARSHOT_SPIRITS: frozenset[int] = frozenset(int(m) for m in (
    SpiritModelID.AGONY, SpiritModelID.REJUVENATION,
))

_RIT_AREA_SPIRITS: frozenset[int] = frozenset(int(m) for m in (
    SpiritModelID.PRESERVATION, SpiritModelID.DESTRUCTION, SpiritModelID.RESTORATION,
))

_VANGUARD_SPIRITS: frozenset[int] = frozenset(int(m) for m in (
    SpiritModelID.WINDS,
))


@dataclass(frozen=True)
class SpiritInfo:
    """Resolved classification for one spirit model id."""

    model_id: int
    category: SpiritCategory
    range_class: SpiritRangeClass
    skill_id: int            # from SPIRIT_BUFF_MAP, 0 if unknown
    marker_key: str          # which MarkerStyle drives its shape/colour

    @property
    def range_value(self) -> int:
        return spirit_range(self.range_class)


def classify_spirit(model_id: int) -> Optional[SpiritInfo]:
    """Return the :class:`SpiritInfo` for ``model_id``, or ``None`` if it is not a spirit."""
    mid = int(model_id)
    skill_id = int(SPIRIT_BUFF_MAP.get(SpiritModelID(mid), 0)) if mid in _ALL_SPIRIT_IDS else 0

    if mid in _RANGER_SPIRITS:
        return SpiritInfo(mid, SpiritCategory.RANGER, SpiritRangeClass.SPIRIT, skill_id,
                          MARKER_SPIRIT_RANGER)
    if mid in _VANGUARD_SPIRITS:
        return SpiritInfo(mid, SpiritCategory.VANGUARD, SpiritRangeClass.SPIRIT, skill_id,
                          MARKER_SPIRIT_VANGUARD)
    if mid in _RIT_SPIRIT_SPIRITS:
        return SpiritInfo(mid, SpiritCategory.RITUALIST, SpiritRangeClass.SPIRIT, skill_id,
                          MARKER_SPIRIT_RITUALIST)
    if mid in _RIT_LONGBOW_SPIRITS:
        return SpiritInfo(mid, SpiritCategory.RITUALIST, SpiritRangeClass.LONGBOW, skill_id,
                          MARKER_SPIRIT_RITUALIST)
    if mid in _RIT_EARSHOT_SPIRITS:
        return SpiritInfo(mid, SpiritCategory.RITUALIST, SpiritRangeClass.EARSHOT, skill_id,
                          MARKER_SPIRIT_RITUALIST)
    if mid in _RIT_AREA_SPIRITS:
        return SpiritInfo(mid, SpiritCategory.RITUALIST, SpiritRangeClass.AREA, skill_id,
                          MARKER_SPIRIT_RITUALIST)
    return None


_ALL_SPIRIT_IDS: frozenset[int] = (
    _RANGER_SPIRITS | _RIT_SPIRIT_SPIRITS | _RIT_LONGBOW_SPIRITS
    | _RIT_EARSHOT_SPIRITS | _RIT_AREA_SPIRITS | _VANGUARD_SPIRITS
)


# ── Other classification constants ───────────────────────────────────────────────────────
#: Gadget ids that should render as a chest rather than a generic signpost (from Mission Map).
CHEST_GADGET_IDS: frozenset[int] = frozenset((9, 69, 4579, 8141, 9523, 4582))

#: Model ids that are pets (used to tell an unspawned enemy pet from a generic enemy).
PET_MODEL_IDS: frozenset[int] = frozenset(int(m) for m in PetModelID)


# ── Config data structures ───────────────────────────────────────────────────────────────
@dataclass
class MarkerStyle:
    """How one agent class is drawn. ``fill_range`` > 0 draws a translucent aura ring."""

    name: str
    visible: bool = True
    shape: str = "Circle"
    color: RGBA = (255, 255, 255, 255)
    accent: RGBA = (0, 0, 0, 200)
    size: float = 5.0
    fill_range: int = 0
    fill_color: Optional[RGBA] = None


@dataclass
class Ring:
    """A player-centred range ring."""

    name: str
    visible: bool
    range: int
    fill_color: RGBA
    outline_color: RGBA
    outline_thickness: float


@dataclass
class CustomMarker:
    """A user-defined marker keyed by agent model id (Compass feature)."""

    name: str
    model_id: int = 0
    visible: bool = True
    shape: str = "Tear"
    color: RGBA = (125, 125, 125, 255)
    size: float = 6.0
    fill_range: int = 0
    fill_color: Optional[RGBA] = None


@dataclass
class TerrainConfig:
    """Pathing/terrain render options (DXOverlay)."""

    enabled: bool = True
    inverted: bool = True
    color: RGBA = (0, 0, 0, 200)
    zoom_fill_color: RGBA = (75, 75, 75, 200)   # mission mega-zoom fill


@dataclass
class SnapConfig:
    """NavMesh right-click snap-to-move options (Mission Map feature)."""

    enabled: bool = False
    pause_on_danger: bool = True
    danger_radius: float = float(Range.Earshot.value)


@dataclass
class PositionConfig:
    """Placement + orientation options. Some fields apply to one mode only."""

    snap_to_game: bool = True            # both: snap overlay to the live game frame
    always_point_north: bool = False     # compass, detached only
    culling: int = 4365                  # compass: distance cull for agents
    detached: bool = False               # compass: float the compass free of the frame
    detached_x: int = 0                  # compass detached centre
    detached_y: int = 0
    detached_size: int = 400
    mega_zoom: float = 0.0               # mission: extra zoom beyond native


# ── Marker keys (stable ids used across config + agent pass) ─────────────────────────────
MARKER_PLAYER = "Player"
MARKER_ALLY = "Ally"
MARKER_ALLY_NPC = "Ally (NPC)"
MARKER_PLAYERS = "Players"
MARKER_NEUTRAL = "Neutral"
MARKER_ENEMY = "Enemy"
MARKER_ENEMY_PET = "Enemy Pet"
MARKER_PET = "Pet"
MARKER_MINION = "Minion"
MARKER_NPC = "NPC"
MARKER_MERCHANT = "Merchant"
MARKER_MINIPET = "Minipet"
MARKER_GADGET = "Gadget"
MARKER_CHEST = "Chest"
MARKER_ITEM = "Item"
MARKER_DEFAULT = "Default"
MARKER_SPIRIT_RANGER = "Spirit (Ranger)"
MARKER_SPIRIT_RITUALIST = "Spirit (Ritualist)"
MARKER_SPIRIT_VANGUARD = "Spirit (Vanguard)"

#: Item rarity → colour (Mission Map's single-marker-plus-rarity-colour approach).
ITEM_RARITY_COLORS: dict[int, RGBA] = {
    0: (225, 225, 225, 255),   # white / common
    1: (0, 170, 255, 255),     # blue
    2: (110, 65, 200, 255),    # purple
    3: (225, 150, 0, 255),     # gold
    4: (25, 200, 0, 255),      # green
}

#: Guild Wars profession id → colour for boss-glow enemies (Compass feature).
PROFESSION_COLORS: tuple[RGBA, ...] = (
    (102, 102, 102, 255), (238, 170, 51, 255), (85, 170, 0, 255), (68, 68, 187, 255),
    (0, 170, 85, 255), (136, 0, 170, 255), (187, 51, 51, 255), (170, 0, 136, 255),
    (0, 170, 170, 255), (153, 102, 0, 255), (119, 119, 204, 255),
)

# Marker-group layout for the config editor (Mission Map grouping).
MARKER_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Party", (MARKER_PLAYER, MARKER_ALLY, MARKER_ALLY_NPC, MARKER_PLAYERS, MARKER_PET)),
    ("Hostile", (MARKER_ENEMY, MARKER_ENEMY_PET, MARKER_MINION)),
    ("World", (MARKER_NEUTRAL, MARKER_NPC, MARKER_MERCHANT, MARKER_MINIPET,
               MARKER_GADGET, MARKER_CHEST, MARKER_ITEM, MARKER_DEFAULT)),
    ("Spirits", (MARKER_SPIRIT_RANGER, MARKER_SPIRIT_RITUALIST, MARKER_SPIRIT_VANGUARD)),
)


def default_markers() -> dict[str, MarkerStyle]:
    """The fresh-install marker set — the union of both widgets' defaults."""
    accent: RGBA = (0, 0, 0, 200)
    defs: tuple[MarkerStyle, ...] = (
        MarkerStyle(MARKER_PLAYER, shape="Tear", color=(5, 190, 5, 255), accent=accent, size=10.0),
        MarkerStyle(MARKER_ALLY, shape="Tear", color=(0, 179, 0, 255), accent=accent, size=8.0),
        MarkerStyle(MARKER_ALLY_NPC, shape="Tear", color=(153, 255, 153, 255), accent=accent, size=8.0),
        MarkerStyle(MARKER_PLAYERS, shape="Tear", color=(100, 100, 255, 255), accent=accent, size=8.0),
        MarkerStyle(MARKER_NEUTRAL, shape="Circle", color=(0, 220, 220, 255), accent=accent, size=4.0),
        MarkerStyle(MARKER_ENEMY, shape="Tear", color=(255, 0, 0, 255), accent=accent, size=8.0),
        MarkerStyle(MARKER_ENEMY_PET, shape="Circle", color=(255, 255, 0, 255), accent=accent, size=4.0),
        MarkerStyle(MARKER_PET, shape="Circle", color=(0, 179, 0, 255), accent=accent, size=4.0),
        MarkerStyle(MARKER_MINION, shape="Circle", color=(0, 128, 96, 255), accent=accent, size=4.0),
        MarkerStyle(MARKER_NPC, shape="Triangle", color=(153, 255, 153, 255), accent=accent, size=8.0),
        MarkerStyle(MARKER_MERCHANT, shape="Scale", color=(153, 255, 153, 255), accent=accent, size=8.0),
        MarkerStyle(MARKER_MINIPET, shape="Circle", color=(153, 255, 153, 255), accent=accent, size=2.0),
        MarkerStyle(MARKER_GADGET, shape="SignPost", color=(165, 135, 75, 255), accent=accent, size=6.0),
        MarkerStyle(MARKER_CHEST, shape="Lock", color=(165, 135, 75, 255), accent=accent, size=6.0),
        MarkerStyle(MARKER_ITEM, shape="Square", color=(200, 200, 0, 255), accent=accent, size=6.0),
        MarkerStyle(MARKER_DEFAULT, shape="Circle", color=(70, 70, 70, 255), accent=accent, size=4.0),
        MarkerStyle(MARKER_SPIRIT_RANGER, shape="Circle", color=(204, 255, 153, 255), accent=accent, size=4.0),
        MarkerStyle(MARKER_SPIRIT_RITUALIST, shape="Tear", color=(187, 255, 255, 255), accent=accent, size=4.0),
        MarkerStyle(MARKER_SPIRIT_VANGUARD, shape="Circle", color=(66, 3, 1, 255), accent=accent, size=4.0),
    )
    return {m.name: m for m in defs}


def default_rings() -> list[Ring]:
    """The fresh-install range-ring set (Compass ring list)."""
    hollow: RGBA = (255, 255, 255, 0)
    outline: RGBA = (255, 255, 255, 255)
    specs: tuple[tuple[str, bool, int], ...] = (
        ("Touch", False, int(Range.Touch.value)),
        ("Adjacent", False, int(Range.Adjacent.value)),
        ("Nearby", False, int(Range.Nearby.value)),
        ("Area", False, int(Range.Area.value)),
        ("Earshot", True, int(Range.Earshot.value)),
        ("Spellcast", True, int(Range.Spellcast.value)),
        ("Spirit", True, int(Range.Spirit.value)),
        ("Compass", False, int(Range.Compass.value)),
    )
    return [Ring(name, vis, rng, hollow, outline, 1.5) for name, vis, rng in specs]


@dataclass
class PlayerRangeConfig:
    """Mission-map-exclusive player range indicators.

    These are **not** the configurable range rings (a Compass feature) — they are Mission Map's
    own tailored renderings and are drawn only in mission mode:

    - **aggro bubble** — earshot: a 4px stroke inset 2px plus a translucent fill.
    - **compass range** — a black hairline at exactly the compass radius plus a soft band inset
      by ``2.85 · zoom`` with thickness ``5.7 · zoom``, so it stays readable at any zoom.
    """

    show_aggro_bubble: bool = True
    show_compass_range: bool = True
    color: RGBA = (255, 255, 255, 40)              # shared bubble/band colour
    compass_outline: RGBA = (0, 0, 0, 255)         # hairline at the exact compass radius

@dataclass
class PortalsAndTeleportsConfig:
    """Mission-map-exclusive portal and teleport indicators.
    """
    
    show_portals: bool = True
    show_teleports: bool = True
    color_portals: RGBA = (255, 0, 255, 255)
    color_teleports: RGBA = (255, 255, 255, 255)
    radius_portals: float = 3.0
    radius_teleports: float = 3.0

@dataclass
class OverlayConfig:
    """The full persisted overlay configuration (superset of both widgets)."""

    mode: OverlayMode = OverlayMode.MISSION
    markers: dict[str, MarkerStyle] = field(default_factory=default_markers)
    rings: list[Ring] = field(default_factory=default_rings)
    player_ranges: PlayerRangeConfig = field(default_factory=PlayerRangeConfig)
    portals_and_teleports: PortalsAndTeleportsConfig = field(default_factory=PortalsAndTeleportsConfig)
    custom_markers: dict[str, CustomMarker] = field(default_factory=dict)
    terrain: TerrainConfig = field(default_factory=TerrainConfig)
    snap: SnapConfig = field(default_factory=SnapConfig)
    position: PositionConfig = field(default_factory=PositionConfig)
    #: Colour bosses by primary profession when the agent reports one. Profession 0 is
    #: "None" (grey) and many bosses report it, so index 0 is never selected — those fall
    #: back to the enemy colour. Bosses stay identifiable via ``boss_accent`` regardless.
    boss_profession_colors: bool = True
    boss_accent: RGBA = (0, 200, 45, 255)

    spirit_alpha: int = 50          # aura alpha for spirit range fills
    show_spirit_range: bool = True  # Mission Map always drew spirit auras; keep them on
