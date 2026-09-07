"""Map Overlay config editor.

One window covering the whole superset: mode selector, opt-in legacy import, position,
terrain, snap, grouped agent markers, range rings, and custom markers. Edits mutate the live
config; the whole config is saved once at the end of the frame (``Settings`` throttles the
actual disk write), so there is no per-control change tracking.
"""

from typing import TYPE_CHECKING

import PyImGui

from Py4GWCoreLib import Agent
from Py4GWCoreLib import ImGui
from Py4GWCoreLib import Player
from Py4GWCoreLib.Overlay import Overlay

from . import persistence
from . import shapes
from .model import MARKER_GROUPS
from .model import RGBA
from .model import CustomMarker
from .model import OverlayMode

if TYPE_CHECKING:
    from .host import MapOverlay

_SHAPES = list(shapes.SHAPE_NAMES)


def _norm(rgba: RGBA) -> tuple[float, float, float, float]:
    return (rgba[0] / 255.0, rgba[1] / 255.0, rgba[2] / 255.0, rgba[3] / 255.0)


def _rgba(t) -> RGBA:
    return (int(round(t[0] * 255)), int(round(t[1] * 255)), int(round(t[2] * 255)), int(round(t[3] * 255)))


def _tip(text: str) -> None:
    """Tooltip for the control just emitted."""
    if PyImGui.is_item_hovered():
        ImGui.show_tooltip(text)


#: X offset where a row's controls start, so every row's name column lines up.
_NAME_COL = 150.0


def draw(overlay: "MapOverlay") -> None:
    cfg = overlay.cfg
    PyImGui.set_next_window_size((540.0, 720.0), PyImGui.ImGuiCond.FirstUseEver)
    if PyImGui.begin("Map Overlay Config"):
        # ── Mode ─────────────────────────────────────────────────────────────────────────
        modes = ["Mission Map", "Compass"]
        cur = 0 if cfg.mode is OverlayMode.MISSION else 1
        sel = PyImGui.combo("Mode", cur, modes)
        new_mode = OverlayMode.MISSION if sel == 0 else OverlayMode.COMPASS
        if new_mode is not cfg.mode:
            cfg.mode = new_mode
            overlay.on_mode_changed()

        # ── Import ───────────────────────────────────────────────────────────────────────
        if PyImGui.collapsing_header("Import legacy settings"):
            PyImGui.indent(10)
            PyImGui.text_wrapped("Optional. Pull settings from the old widgets into this one.")
            if PyImGui.button("Import Mission Map settings"):
                persistence.import_mission_map(cfg)
            if PyImGui.button("Import Compass settings"):
                persistence.import_compass(cfg)
            PyImGui.unindent(10)

        # ── Position ─────────────────────────────────────────────────────────────────────
        if PyImGui.collapsing_header("Position"):
            PyImGui.indent(10)
            p = cfg.position
            p.snap_to_game = PyImGui.checkbox("Snap to game frame", p.snap_to_game)
            p.culling = PyImGui.slider_int("Culling range", p.culling, 4000, 5000)
            if cfg.mode is OverlayMode.COMPASS and not p.snap_to_game:
                p.detached = True
                p.always_point_north = PyImGui.checkbox("Always point north", p.always_point_north)
                disp = Overlay().GetDisplaySize()
                if PyImGui.button("Snap to screen center"):
                    p.detached_x = round(disp.x / 2)
                    p.detached_y = round(disp.y / 2)
                p.detached_x = PyImGui.slider_int("X position", p.detached_x, p.detached_size, round(disp.x - p.detached_size))
                p.detached_y = PyImGui.slider_int("Y position", p.detached_y, p.detached_size, round(disp.y - p.detached_size))
                p.detached_size = PyImGui.slider_int("Scale", p.detached_size, 100, 1000)
            else:
                p.detached = False
            PyImGui.unindent(10)

        # ── Terrain ──────────────────────────────────────────────────────────────────────
        if PyImGui.collapsing_header("Terrain"):
            PyImGui.indent(10)
            t = cfg.terrain
            t.enabled = PyImGui.checkbox("Show terrain", t.enabled)
            inv = PyImGui.checkbox("Invert terrain", t.inverted)
            if inv != t.inverted:
                t.inverted = inv
                overlay.terrain.invalidate()
            col = _rgba(PyImGui.color_edit4("Terrain color", _norm(t.color)))
            if col != t.color:
                t.color = col
                overlay.terrain.invalidate()
            if cfg.mode is OverlayMode.MISSION:
                t.zoom_fill_color = _rgba(PyImGui.color_edit4("Mega zoom fill", _norm(t.zoom_fill_color)))
            PyImGui.unindent(10)

        # ── Player ranges: mission indicators + the configurable range rings ─────────────
        if PyImGui.collapsing_header("Player ranges"):
            PyImGui.indent(10)

            if cfg.mode is OverlayMode.MISSION:
                PyImGui.text_disabled("Mission map indicators")
                pr = cfg.player_ranges
                pr.show_aggro_bubble = PyImGui.checkbox("Show aggro bubble (earshot)", pr.show_aggro_bubble)
                _tip("Earshot bubble drawn around the player.")
                pr.show_compass_range = PyImGui.checkbox("Show compass range", pr.show_compass_range)
                _tip("Zoom-scaled band showing how far the in-game compass reaches.")
                pr.color = _rgba(PyImGui.color_edit4("Indicator color", _norm(pr.color)))
                _tip("Shared color of the aggro bubble and the compass-range band.")
                pr.compass_outline = _rgba(PyImGui.color_edit4("Compass outline", _norm(pr.compass_outline)))
                _tip("Hairline drawn at exactly the compass radius.")
                PyImGui.separator()

            PyImGui.text_disabled("Range rings")
            PyImGui.text_disabled("columns:  show · ring · range · fill · outline · thickness")
            for ring in cfg.rings:
                ring.visible = PyImGui.checkbox(f"##ringvis_{ring.name}", ring.visible)
                _tip(f"Show the {ring.name} ring")
                PyImGui.same_line(0, 6)
                PyImGui.text(ring.name)
                _tip(f"{ring.name} — {ring.range} gwinches")
                PyImGui.same_line(_NAME_COL, -1)
                PyImGui.text_disabled(str(ring.range))
                PyImGui.same_line(_NAME_COL + 55.0, -1)
                ring.fill_color = _rgba(PyImGui.color_edit4(f"##ringfill_{ring.name}", _norm(ring.fill_color)))
                _tip(f"{ring.name}: fill color (alpha 0 = hollow)")
                PyImGui.same_line(0, 6)
                ring.outline_color = _rgba(PyImGui.color_edit4(f"##ringline_{ring.name}", _norm(ring.outline_color)))
                _tip(f"{ring.name}: outline color")
                PyImGui.same_line(0, 6)
                PyImGui.push_item_width(60)
                ring.outline_thickness = PyImGui.input_float(f"##ringthk_{ring.name}", ring.outline_thickness)
                _tip(f"{ring.name}: outline thickness")
                PyImGui.pop_item_width()
            PyImGui.unindent(10)
            
        # ── Portals & teleports ───────────────────────────────────────────────────────────
        if PyImGui.collapsing_header("Portals & teleports (mission map)"):
            PyImGui.indent(10)
            pt = cfg.portals_and_teleports

            # Portals section
            PyImGui.text_disabled("Portals")
            pt.show_portals = PyImGui.checkbox("Show portals", pt.show_portals)
            _tip("Show portal indicators on the map.")

            pt.color_portals = _rgba(PyImGui.color_edit4("Portal color", _norm(pt.color_portals)))
            _tip("Color of portal indicators.")

            PyImGui.push_item_width(60)
            pt.radius_portals = PyImGui.input_float("Portal radius", pt.radius_portals)
            PyImGui.pop_item_width()
            _tip("Display size/radius of portal indicators.")

            PyImGui.separator()

            # Teleports section
            PyImGui.text_disabled("Teleports")
            pt.show_teleports = PyImGui.checkbox("Show teleports", pt.show_teleports)
            _tip("Show teleport indicators on the map.")

            pt.color_teleports = _rgba(PyImGui.color_edit4("Teleport color", _norm(pt.color_teleports)))
            _tip("Color of teleport indicators.")

            PyImGui.push_item_width(60)
            pt.radius_teleports = PyImGui.input_float("Teleport radius", pt.radius_teleports)
            PyImGui.pop_item_width()
            _tip("Display size/radius of teleport indicators.")

            PyImGui.unindent(10)

        # ── Movement / snap ──────────────────────────────────────────────────────────────
        if PyImGui.collapsing_header("Movement (snap)"):
            PyImGui.indent(10)
            sn = cfg.snap
            sn.enabled = PyImGui.checkbox("Enable snap movement", sn.enabled)
            sn.pause_on_danger = PyImGui.checkbox("Pause snap on danger", sn.pause_on_danger)
            sn.danger_radius = PyImGui.slider_float("Danger radius", sn.danger_radius, 0.0, 5000.0)
            PyImGui.unindent(10)

        # ── Agents ───────────────────────────────────────────────────────────────────────
        if PyImGui.collapsing_header("Agents"):
            PyImGui.indent(10)
            for group_name, keys in MARKER_GROUPS:
                if not PyImGui.collapsing_header(group_name):
                    continue
                PyImGui.indent(8)
                PyImGui.text_disabled("columns:  show · name · shape · size · color")
                for key in keys:
                    m = cfg.markers.get(key)
                    if m is None:
                        continue
                    m.visible = PyImGui.checkbox(f"##vis_{key}", m.visible)
                    _tip(f"Show {m.name} markers")
                    PyImGui.same_line(0, 6)
                    PyImGui.text(m.name)
                    PyImGui.same_line(_NAME_COL, -1)
                    PyImGui.push_item_width(90)
                    idx = _SHAPES.index(m.shape) if m.shape in _SHAPES else 0
                    m.shape = _SHAPES[PyImGui.combo(f"##shape_{key}", idx, _SHAPES)]
                    _tip(f"{m.name}: marker shape")
                    PyImGui.same_line(0, 6)
                    m.size = PyImGui.slider_float(f"##size_{key}", float(m.size), 1.0, 20.0)
                    _tip(f"{m.name}: marker size")
                    PyImGui.pop_item_width()
                    PyImGui.same_line(0, 6)
                    m.color = _rgba(PyImGui.color_edit4(f"##col_{key}", _norm(m.color)))
                    _tip(f"{m.name}: marker color")
                PyImGui.unindent(8)
            PyImGui.separator()
            cfg.boss_accent = _rgba(PyImGui.color_edit4("Boss outline", _norm(cfg.boss_accent)))
            _tip("Outline drawn around bosses so they stand out from normal enemies.")
            PyImGui.same_line(0, 6)
            cfg.boss_profession_colors = PyImGui.checkbox("Color bosses by profession", cfg.boss_profession_colors)
            _tip("Bosses reporting no profession keep the enemy color (never grey).")
            PyImGui.separator()
            cfg.show_spirit_range = PyImGui.checkbox("Show spirit ranges", cfg.show_spirit_range)
            PyImGui.same_line(0, 6)
            PyImGui.push_item_width(160)
            cfg.spirit_alpha = PyImGui.slider_int("Spirit range alpha", cfg.spirit_alpha, 0, 255)
            PyImGui.pop_item_width()
            PyImGui.unindent(10)

        # ── Custom markers ───────────────────────────────────────────────────────────────
        if PyImGui.collapsing_header("Custom markers (by model id)"):
            PyImGui.indent(10)
            to_delete = None
            for name, cm in list(cfg.custom_markers.items()):
                cm.visible = PyImGui.checkbox(f"##cmvis_{name}", cm.visible)
                _tip(f"Show the '{name}' custom marker")
                PyImGui.same_line(0, 6)
                if PyImGui.collapsing_header(f"{name}##cmhdr_{name}"):
                    PyImGui.indent(8)
                    PyImGui.push_item_width(120)
                    cm.model_id = PyImGui.input_int(f"Model ID##{name}", cm.model_id)
                    PyImGui.same_line(0, 6)
                    if PyImGui.button(f"Get from target##{name}"):
                        cm.model_id = Agent.GetPlayerNumber(Player.GetTargetID())
                    cm.size = PyImGui.slider_int(f"Size##{name}", int(cm.size), 1, 20)
                    idx = _SHAPES.index(cm.shape) if cm.shape in _SHAPES else 0
                    cm.shape = _SHAPES[PyImGui.combo(f"Shape##{name}", idx, _SHAPES)]
                    PyImGui.pop_item_width()
                    cm.color = _rgba(PyImGui.color_edit4(f"Color##{name}", _norm(cm.color)))
                    cm.fill_range = PyImGui.slider_int(f"Fill range##{name}", cm.fill_range, 0, 5000)
                    if PyImGui.button(f"Delete##{name}"):
                        to_delete = name
                    PyImGui.unindent(8)
            if to_delete is not None:
                cfg.custom_markers.pop(to_delete, None)
            PyImGui.separator()
            PyImGui.push_item_width(160)
            overlay._new_custom_name = PyImGui.input_text("##new_custom", overlay._new_custom_name)
            _tip("Name for a new custom marker, then press Add")
            PyImGui.pop_item_width()
            PyImGui.same_line(0, 6)
            if PyImGui.button("Add custom marker"):
                nm = overlay._new_custom_name or "Custom Agent Name"
                cfg.custom_markers[nm] = CustomMarker(name=nm)
                overlay._new_custom_name = "Custom Agent Name"
            PyImGui.unindent(10)

    PyImGui.end()
    overlay.save()
