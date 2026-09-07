"""Map Overlay persistence — the widget's own account ini, plus opt-in legacy importers.

The overlay owns and writes a fresh config in its **own** account document
``Widgets/Guild Wars/Screen Overlays/Map Overlay.ini``. A clean install works from defaults
with no import. The config UI can *opt in* to pull settings from the legacy widgets via
:func:`import_mission_map` / :func:`import_compass`, which read the old inis best-effort and
merge what they can into the live :class:`OverlayConfig`.

``Settings`` is imported lazily so this module is import-safe offline. Colours persist as the
same packed integer the legacy inis used.
"""

from typing import Optional

from Py4GWCoreLib.py4gwcorelib_src.Color import Color

from .model import CustomMarker
from .model import MarkerStyle
from .model import OverlayConfig
from .model import OverlayMode
from .model import RGBA
from .model import Ring

_DOC = "Widgets/Guild Wars/Screen Overlays/Map Overlay.ini"
_MISSION_DOC = "Widgets/Guild Wars/Screen Overlays/Mission Map +.ini"
_COMPASS_DOC = "Widgets/Config/Compass +.ini"


def _settings(doc: str, scope: str = "account"):
    try:
        from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings
        return Settings(doc, scope)
    except Exception:
        return None


def _slug(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")


def _to_int(rgba: RGBA) -> int:
    return Color(int(rgba[0]), int(rgba[1]), int(rgba[2]), int(rgba[3])).to_color()


def _to_rgba(value: int) -> RGBA:
    c = Color()
    c.from_color(int(value))
    return (c.r, c.g, c.b, c.a)


# ── own document load / save ─────────────────────────────────────────────────────────────
def load(cfg: OverlayConfig) -> None:
    s = _settings(_DOC)
    if s is None:
        return

    cfg.mode = OverlayMode(s.get_str("general", "mode", cfg.mode.value))
    cfg.spirit_alpha = s.get_int("general", "spirit_alpha", cfg.spirit_alpha)
    cfg.show_spirit_range = s.get_bool("general", "show_spirit_range", cfg.show_spirit_range)
    cfg.boss_profession_colors = s.get_bool("general", "boss_profession_colors", cfg.boss_profession_colors)
    cfg.boss_accent = _to_rgba(s.get_int("general", "boss_accent", _to_int(cfg.boss_accent)))

    t = cfg.terrain
    t.enabled = s.get_bool("terrain", "enabled", t.enabled)
    t.inverted = s.get_bool("terrain", "inverted", t.inverted)
    t.color = _to_rgba(s.get_int("terrain", "color", _to_int(t.color)))
    t.zoom_fill_color = _to_rgba(s.get_int("terrain", "zoom_fill_color", _to_int(t.zoom_fill_color)))

    sn = cfg.snap
    sn.enabled = s.get_bool("snap", "enabled", sn.enabled)
    sn.pause_on_danger = s.get_bool("snap", "pause_on_danger", sn.pause_on_danger)
    sn.danger_radius = s.get_float("snap", "danger_radius", sn.danger_radius)

    pr = cfg.player_ranges
    pr.show_aggro_bubble = s.get_bool("player_ranges", "show_aggro_bubble", pr.show_aggro_bubble)
    pr.show_compass_range = s.get_bool("player_ranges", "show_compass_range", pr.show_compass_range)
    pr.color = _to_rgba(s.get_int("player_ranges", "color", _to_int(pr.color)))
    pr.compass_outline = _to_rgba(s.get_int("player_ranges", "compass_outline", _to_int(pr.compass_outline)))
    
    pt = cfg.portals_and_teleports
    pt.show_portals = s.get_bool("portals_and_teleports", "show_portals", pt.show_portals)
    pt.show_teleports = s.get_bool("portals_and_teleports", "show_teleports", pt.show_teleports)
    pt.color_portals = _to_rgba(s.get_int("portals_and_teleports", "color_portals", _to_int(pt.color_portals)))
    pt.color_teleports = _to_rgba(s.get_int("portals_and_teleports", "color_teleports", _to_int(pt.color_teleports)))
    pt.radius_portals = s.get_float("portals_and_teleports", "radius_portals", pt.radius_portals)
    pt.radius_teleports = s.get_float("portals_and_teleports", "radius_teleports", pt.radius_teleports)

    p = cfg.position
    p.snap_to_game = s.get_bool("position", "snap_to_game", p.snap_to_game)
    p.always_point_north = s.get_bool("position", "always_point_north", p.always_point_north)
    p.culling = s.get_int("position", "culling", p.culling)
    p.detached = s.get_bool("position", "detached", p.detached)
    p.detached_x = s.get_int("position", "detached_x", p.detached_x)
    p.detached_y = s.get_int("position", "detached_y", p.detached_y)
    p.detached_size = s.get_int("position", "detached_size", p.detached_size)
    p.mega_zoom = s.get_float("position", "mega_zoom", p.mega_zoom)

    for m in cfg.markers.values():
        sec = f"marker.{_slug(m.name)}"
        m.visible = s.get_bool(sec, "visible", m.visible)
        m.shape = s.get_str(sec, "shape", m.shape)
        m.color = _to_rgba(s.get_int(sec, "color", _to_int(m.color)))
        m.accent = _to_rgba(s.get_int(sec, "accent", _to_int(m.accent)))
        m.size = s.get_float(sec, "size", m.size)
        m.fill_range = s.get_int(sec, "fill_range", m.fill_range)
        fc = s.get_int(sec, "fill_color", -1)
        m.fill_color = _to_rgba(fc) if fc >= 0 else None

    for ring in cfg.rings:
        sec = f"ring.{_slug(ring.name)}"
        ring.visible = s.get_bool(sec, "visible", ring.visible)
        ring.range = s.get_int(sec, "range", ring.range)
        ring.fill_color = _to_rgba(s.get_int(sec, "fill_color", _to_int(ring.fill_color)))
        ring.outline_color = _to_rgba(s.get_int(sec, "outline_color", _to_int(ring.outline_color)))
        ring.outline_thickness = s.get_float(sec, "outline_thickness", ring.outline_thickness)

    for sec in s.sections():
        name = str(sec)
        if name.startswith("custom."):
            key = name[len("custom."):]
            fc = s.get_int(name, "fill_color", -1)
            cfg.custom_markers[key] = CustomMarker(
                name=key,
                model_id=s.get_int(name, "model_id", 0),
                visible=s.get_bool(name, "visible", True),
                shape=s.get_str(name, "shape", "Tear"),
                color=_to_rgba(s.get_int(name, "color", _to_int((125, 125, 125, 255)))),
                size=s.get_float(name, "size", 6.0),
                fill_range=s.get_int(name, "fill_range", 0),
                fill_color=_to_rgba(fc) if fc >= 0 else None,
            )


def save(cfg: OverlayConfig) -> None:
    s = _settings(_DOC)
    if s is None:
        return

    s.set("general", "mode", cfg.mode.value)
    s.set("general", "spirit_alpha", cfg.spirit_alpha)
    s.set("general", "show_spirit_range", cfg.show_spirit_range)
    s.set("general", "boss_profession_colors", cfg.boss_profession_colors)
    s.set("general", "boss_accent", _to_int(cfg.boss_accent))

    t = cfg.terrain
    s.set("terrain", "enabled", t.enabled)
    s.set("terrain", "inverted", t.inverted)
    s.set("terrain", "color", _to_int(t.color))
    s.set("terrain", "zoom_fill_color", _to_int(t.zoom_fill_color))

    sn = cfg.snap
    s.set("snap", "enabled", sn.enabled)
    s.set("snap", "pause_on_danger", sn.pause_on_danger)
    s.set("snap", "danger_radius", sn.danger_radius)

    pr = cfg.player_ranges
    s.set("player_ranges", "show_aggro_bubble", pr.show_aggro_bubble)
    s.set("player_ranges", "show_compass_range", pr.show_compass_range)
    s.set("player_ranges", "color", _to_int(pr.color))
    s.set("player_ranges", "compass_outline", _to_int(pr.compass_outline))

    p = cfg.position
    s.set("position", "snap_to_game", p.snap_to_game)
    s.set("position", "always_point_north", p.always_point_north)
    s.set("position", "culling", p.culling)
    s.set("position", "detached", p.detached)
    s.set("position", "detached_x", p.detached_x)
    s.set("position", "detached_y", p.detached_y)
    s.set("position", "detached_size", p.detached_size)
    s.set("position", "mega_zoom", p.mega_zoom)

    for m in cfg.markers.values():
        sec = f"marker.{_slug(m.name)}"
        s.set(sec, "visible", m.visible)
        s.set(sec, "shape", m.shape)
        s.set(sec, "color", _to_int(m.color))
        s.set(sec, "accent", _to_int(m.accent))
        s.set(sec, "size", m.size)
        s.set(sec, "fill_range", m.fill_range)
        s.set(sec, "fill_color", _to_int(m.fill_color) if m.fill_color is not None else -1)

    for ring in cfg.rings:
        sec = f"ring.{_slug(ring.name)}"
        s.set(sec, "visible", ring.visible)
        s.set(sec, "range", ring.range)
        s.set(sec, "fill_color", _to_int(ring.fill_color))
        s.set(sec, "outline_color", _to_int(ring.outline_color))
        s.set(sec, "outline_thickness", ring.outline_thickness)

    for key, cm in cfg.custom_markers.items():
        sec = f"custom.{key}"
        s.set(sec, "model_id", cm.model_id)
        s.set(sec, "visible", cm.visible)
        s.set(sec, "shape", cm.shape)
        s.set(sec, "color", _to_int(cm.color))
        s.set(sec, "size", cm.size)
        s.set(sec, "fill_range", cm.fill_range)
        s.set(sec, "fill_color", _to_int(cm.fill_color) if cm.fill_color is not None else -1)


# ── opt-in legacy import ─────────────────────────────────────────────────────────────────
def import_mission_map(cfg: OverlayConfig) -> bool:
    """Best-effort import of ``Mission Map +.ini`` (account). Returns True if the doc existed."""
    s = _settings(_MISSION_DOC)
    if s is None:
        return False

    cfg.snap.enabled = s.get_bool("Map", "snap_enabled", cfg.snap.enabled)
    cfg.snap.pause_on_danger = s.get_bool("Map", "snap_pause_on_danger", cfg.snap.pause_on_danger)
    cfg.snap.danger_radius = s.get_float("Map", "snap_danger_radius", cfg.snap.danger_radius)

    cfg.terrain.enabled = s.get_bool("Terrain", "enabled", cfg.terrain.enabled)
    cfg.terrain.inverted = s.get_bool("Terrain", "inverted", cfg.terrain.inverted)
    cfg.terrain.color = _to_rgba(s.get_int("Terrain", "color", _to_int(cfg.terrain.color)))
    cfg.terrain.zoom_fill_color = _to_rgba(s.get_int("Terrain", "zoom_fill_color", _to_int(cfg.terrain.zoom_fill_color)))

    for m in cfg.markers.values():
        sec = f"Marker.{_slug(m.name)}"
        m.visible = s.get_bool(sec, "visible", m.visible)
        m.shape = s.get_str(sec, "marker", m.shape)
        m.color = _to_rgba(s.get_int(sec, "color", _to_int(m.color)))
        m.accent = _to_rgba(s.get_int(sec, "alternate_color", _to_int(m.accent)))
        m.size = s.get_float(sec, "size", m.size)
    save(cfg)
    return True


# Compass legacy marker/ring names → this overlay's marker keys.
_COMPASS_MARKER_MAP: dict[str, str] = {
    "Player": "Player", "Players": "Players", "Ally": "Ally", "Ally (NPC)": "Ally (NPC)",
    "Ally (Pet)": "Pet", "Ally (Minion)": "Minion", "Minipet": "Minipet", "Neutral": "Neutral",
    "Enemy": "Enemy", "Spirit (Ranger)": "Spirit (Ranger)", "Spirit (Ritualist)": "Spirit (Ritualist)",
    "Spirit (Vanguard)": "Spirit (Vanguard)", "Signpost": "Gadget", "Item (White)": "Item",
}


def import_compass(cfg: OverlayConfig) -> bool:
    """Best-effort import of ``Compass +.ini`` (global). Returns True if the doc existed."""
    s = _settings(_COMPASS_DOC, scope="global")
    if s is None:
        return False

    p = cfg.position
    p.snap_to_game = s.get_bool("position", "snap_to_game", p.snap_to_game)
    p.always_point_north = s.get_bool("position", "always_point_north", p.always_point_north)
    p.culling = s.get_int("position", "culling", p.culling)
    p.detached_x = s.get_int("position", "detached_x", p.detached_x)
    p.detached_y = s.get_int("position", "detached_y", p.detached_y)
    p.detached_size = s.get_int("position", "detached_size", p.detached_size)

    cfg.terrain.enabled = s.get_bool("pathing", "visible", cfg.terrain.enabled)
    cfg.terrain.inverted = s.get_bool("pathing", "invert", cfg.terrain.inverted)
    cfg.terrain.color = _to_rgba(s.get_int("pathing", "color", _to_int(cfg.terrain.color)))

    cfg.spirit_alpha = s.get_int("misc", "spirit_alpha", cfg.spirit_alpha)
    cfg.show_spirit_range = s.get_bool("misc", "show_spirit_ranges", cfg.show_spirit_range)

    for ring in cfg.rings:
        sec = f"ring_{ring.name}"
        ring.visible = s.get_bool(sec, "visible", ring.visible)
        ring.range = s.get_int(sec, "range", ring.range)
        ring.fill_color = _to_rgba(s.get_int(sec, "fill_color", _to_int(ring.fill_color)))
        ring.outline_color = _to_rgba(s.get_int(sec, "outline_color", _to_int(ring.outline_color)))
        ring.outline_thickness = s.get_float(sec, "outline_thickness", ring.outline_thickness)

    for legacy_name, key in _COMPASS_MARKER_MAP.items():
        m = cfg.markers.get(key)
        if m is None:
            continue
        sec = f"marker_{legacy_name}"
        m.visible = s.get_bool(sec, "visible", m.visible)
        m.size = s.get_float(sec, "size", m.size)
        m.shape = s.get_str(sec, "shape", m.shape)
        m.color = _to_rgba(s.get_int(sec, "color", _to_int(m.color)))

    for sec in s.sections():
        name = str(sec)
        if name.startswith("custom_marker_"):
            key = name[len("custom_marker_"):]
            cfg.custom_markers[key] = CustomMarker(
                name=key,
                model_id=s.get_int(name, "model_id", 0),
                visible=s.get_bool(name, "visible", True),
                shape=s.get_str(name, "shape", "Tear"),
                color=_to_rgba(s.get_int(name, "color", _to_int((125, 125, 125, 255)))),
                size=s.get_float(name, "size", 6.0),
                fill_range=s.get_int(name, "fill_range", 0),
            )
    save(cfg)
    return True
