"""The Loot Filter Factory's authoring surface.

**This stands on its own.** It is not embedded in Loot Filters or in Recolor & Beacons -- a consumer
*selects*, it never hosts the authoring UI. Both features simply inherit the filters and filter sets
made here.

The criteria editor copies the **Item Mods Playground**
(`Widgets/Coding/Debug/Py4GW/Item Mods Playground.py:206-280`), which is the existing working example
of filtering items by mods: slot-based upgrade combos with `(any)` first, a requirement *at most*, a
max-damage checkbox, one **ALL / ANY** radio for the whole filter, and a live verdict with a
per-criterion breakdown.

Id entry copies **Inventory+**'s two-pane picker
(`Sources/ApoSource/InvPlus/AutoHandlerModule.py:119-190`) -- search, Contains / Starts With, all on
the left, chosen on the right, click to add or remove -- **inline**, not as a modal.
"""

import PyImGui

from ....ImGui import ImGui
from ..loot_filters import catalog as catalog_data
from . import item_types as item_type_data
from . import store
from .matcher import evaluate
from .model import MATCH_ALL
from .model import MATCH_ANY
from .model import Filter
from .model import FilterSet
from .model import ModifierCriterion
from .model import UpgradeCriterion
from .model import canonical_upgrade_name
from . import upgrades as upgrade_data

#: `text_disabled` renders too dim to read; a mid gray keeps secondary text legible.
GRAY = (0.66, 0.67, 0.70, 1.0)
WARN = (0.79, 0.63, 0.29, 1.0)

_state: dict = {
    "filters": None, "filter_sets": None,
    "search": {}, "search_mode": {}, "open_picker": {},
    "new_filter_set": "",
}


# ---------------------------------------------------------------- cached state


def filters() -> list[Filter]:
    if _state["filters"] is None:
        _state["filters"] = store.load_filters()
    return _state["filters"]


def filter_sets() -> list[FilterSet]:
    if _state["filter_sets"] is None:
        _state["filter_sets"] = store.load_filter_sets()
    return _state["filter_sets"]


def reload() -> None:
    """Drop the caches so the next draw re-reads the store."""
    _state["filters"] = None
    _state["filter_sets"] = None


def _commit_filters() -> None:
    store.save_filters(filters())
    _notify()


def _commit_filter_sets() -> None:
    store.save_filter_sets(filter_sets())
    _notify()


def _notify() -> None:
    """Tell the consumers the pool changed. Neither feature is imported by the other.

    Two failures are NOT the same thing and must not share a handler:

    * the module is not loaded -- fine, there is nothing to refresh;
    * the module is loaded but the name is wrong -- a bug, and a silent one. It shipped exactly
      once: this named ``Marking`` where the class is ``RecolorBeacons``, so every refresh raised
      ``AttributeError`` into a bare ``except`` and Recolor & Beacons kept a stale filter set list
      forever -- deleted filter sets still listed, new ones missing.

    So a missing attribute is reported, never swallowed.
    """
    import importlib

    for path, attribute in (
        ("Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filters", "LootFilters"),
        ("Py4GWCoreLib.py4gwcorelib_src.system_settings.recolor_beacons", "RecolorBeacons"),
    ):
        try:
            module = importlib.import_module(path)
        except Exception:
            continue                      # not loaded -- nothing to refresh
        feature = getattr(module, attribute, None)
        if feature is None:
            _log("cannot refresh %s: %s has no %s" % (path, path, attribute))
            continue
        try:
            feature().reload_factory()
        except Exception as exc:
            _log("refreshing %s failed: %r" % (attribute, exc))


def _log(message: str) -> None:
    try:
        from Py4GWCoreLib.Py4GWcorelib import ConsoleLog

        ConsoleLog("Loot Filter Factory", message)
    except Exception:
        pass


# ---------------------------------------------------------------- the two-pane picker


def _two_pane_picker(key: str, label: str, source, chosen: tuple[int, ...]) -> tuple[int, ...]:
    """Inline add/remove picker. ``source`` is ``[(display, value), ...]``.

    Rows read ``Name (id)`` with the id shown, as the reference does -- the id is what the game
    matches on and stays visible. Names are prettified everywhere.
    """
    needle = _state["search"].get(key, "")
    mode = _state["search_mode"].get(key, 0)

    PyImGui.push_item_width(150)
    typed = PyImGui.input_text("Search##%s_q" % key, needle)
    PyImGui.pop_item_width()
    if typed != needle:
        _state["search"][key] = typed
        needle = typed
    PyImGui.same_line(0, 8)
    mode = PyImGui.radio_button("Contains##%s_c" % key, mode, 0)
    PyImGui.same_line(0, 6)
    mode = PyImGui.radio_button("Starts with##%s_s" % key, mode, 1)
    _state["search_mode"][key] = mode

    lowered = needle.strip().lower()
    result = tuple(chosen)

    if PyImGui.begin_table("tbl_%s" % key, 2):
        PyImGui.table_next_column()
        PyImGui.text_colored("All %s" % label, GRAY)
        if PyImGui.begin_child("all_%s" % key, (250.0, 220.0), True, PyImGui.WindowFlags.NoFlag):
            for display, value in sorted(source, key=lambda e: e[0].lower()):
                if lowered:
                    name = display.lower()
                    if mode == 0 and lowered not in name:
                        continue
                    if mode == 1 and not name.startswith(lowered):
                        continue
                if value in result:
                    continue
                if PyImGui.selectable("%s (%d)##%s_a_%d" % (display, value, key, value),
                                      False, PyImGui.SelectableFlags.NoFlag, (0.0, 0.0)):
                    result = result + (value,)
        PyImGui.end_child()

        PyImGui.table_next_column()
        PyImGui.text_colored("Chosen", GRAY)
        if PyImGui.begin_child("sel_%s" % key, (250.0, 220.0), True, PyImGui.WindowFlags.NoFlag):
            lookup = {v: d for d, v in source}
            for value in result:
                display = lookup.get(value, str(value))
                if PyImGui.selectable("%s (%d)##%s_r_%d" % (display, value, key, value),
                                      False, PyImGui.SelectableFlags.NoFlag, (0.0, 0.0)):
                    result = tuple(v for v in result if v != value)
        PyImGui.end_child()
        PyImGui.end_table()
    return result


def _model_source() -> list[tuple[str, int]]:
    """Every `ModelID` member, so a filter can reach ids that were never catalogued."""
    try:
        from Py4GWCoreLib.enums import ModelID

        return [(" ".join(w.capitalize() for w in m.name.split("_")), int(m.value)) for m in ModelID]
    except Exception:
        return [(e.name, e.model_id) for e in catalog_data.CATALOG]


def _curated_grid(key: str, chosen: tuple[int, ...]) -> tuple[int, ...]:
    """The **curated** path: browse category -> group, pick from a textured grid.

    The other half of model entry. The two serve different needs and both exist:

    * this one -- the catalog, a known and visually recognisable set. Browsed, **no search**: a
      curated list is small once you are inside its group, so search tools would be furniture.
    * ``_two_pane_picker`` -- every ``ModelID`` member, including the ones never catalogued. A flat
      search over everything, so it *does* have search.

    Rule of thumb: flat list + search for the whole enum; curated list browsed, no search.
    """
    result = tuple(chosen)
    for category in catalog_data.categories():
        entries = catalog_data.in_category(category)
        picked_here = sum(1 for e in entries if e.model_id in result)
        if not PyImGui.collapsing_header("%s  (%d/%d)###cur_%s_%s"
                                         % (category, picked_here, len(entries), key, category)):
            continue
        groups = catalog_data.groups(category)
        # Trophies has no groups: its A..W split is banded at RENDER time, never in the data.
        bands = ([(name, catalog_data.in_group(category, name)) for name in groups] if groups
                 else catalog_data.alphabetical_bands(entries))
        for band, rows in bands:
            band_ids = [e.model_id for e in rows]
            on_count = sum(1 for i in band_ids if i in result)
            if not PyImGui.collapsing_header("%s  (%d/%d)###cur_%s_%s_%s"
                                             % (band, on_count, len(band_ids), key, category, band)):
                continue
            if PyImGui.small_button("all##cur_on_%s_%s_%s" % (key, category, band)):
                result = result + tuple(i for i in band_ids if i not in result)
            PyImGui.same_line(0, 4)
            if PyImGui.small_button("clear##cur_off_%s_%s_%s" % (key, category, band)):
                result = tuple(i for i in result if i not in band_ids)
            PyImGui.new_line()
            columns = max(1, int(PyImGui.get_content_region_avail()[0] // 54))
            for position, entry in enumerate(rows):
                if position % columns:
                    PyImGui.same_line(0, 4)
                on = entry.model_id in result
                new_state = ImGui.image_toggle_button("##cur_%s_%d" % (key, entry.model_id),
                                                      _texture(entry.model_id), on,
                                                      width=48, height=48)
                if new_state != on:
                    result = (result + (entry.model_id,)) if not on \
                        else tuple(i for i in result if i != entry.model_id)
                # An icon does not identify itself; the id stays visible, as the reference does.
                ImGui.show_tooltip("%s (%d)" % (entry.name, entry.model_id))
            PyImGui.new_line()
    return result


def _texture(model_id: int) -> str:
    try:
        from Py4GWCoreLib.enums_src.Texture_enums import get_texture_for_model

        return get_texture_for_model(int(model_id))
    except Exception:
        return ""


def _item_type_groups(key: str, chosen: tuple[int, ...]) -> tuple[int, ...]:
    """Item types **in their groups** -- Weapons, Armor, Upgrades, Consumables and the rest.

    The taxonomy is curated (`item_types.GROUPS`) and the grouping is the whole point of it: the
    useful question is "every weapon" or "every armor piece", not hunting eleven names out of an
    alphabetical list. Flattening it -- which is what this surface did -- threw away the only
    structure the list had.

    Collapsible headers, bulk `all` / `clear` per group: the house layout, same as everywhere else.
    """
    result = tuple(chosen)
    for group, entries in item_type_data.grouped():
        ids = [value for _display, value in entries]
        on_count = sum(1 for i in ids if i in result)
        if not PyImGui.collapsing_header("%s  (%d/%d)###ity_%s_%s"
                                         % (group, on_count, len(ids), key, group)):
            continue
        if PyImGui.small_button("all##ity_on_%s_%s" % (key, group)):
            result = result + tuple(i for i in ids if i not in result)
        PyImGui.same_line(0, 4)
        if PyImGui.small_button("clear##ity_off_%s_%s" % (key, group)):
            result = tuple(i for i in result if i not in ids)
        PyImGui.new_line()
        columns = max(1, int(PyImGui.get_content_region_avail()[0] // 160))
        for position, (display, value) in enumerate(entries):
            if position % columns:
                PyImGui.same_line(0, 12)
            on = value in result
            if PyImGui.checkbox("%s##ity_%s_%d" % (display, key, value), on) != on:
                result = (result + (value,)) if not on else tuple(v for v in result if v != value)
            ImGui.show_tooltip("%s (%d)" % (display, value))
        PyImGui.new_line()
    return result


def _item_type_source() -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for _group, entries in item_type_data.grouped():
        out.extend(entries)
    return out


# ---------------------------------------------------------------- the criteria editor


def _attribute_source() -> list[tuple[str, int]]:
    """The requirement's subtype. `Requirement` carries an Attribute, as the dump shows:
    `0x2798 arg1=1 arg2=11  Requirement 11 (IllusionMagic)`."""
    try:
        from Py4GWCoreLib.enums import Attribute

        return sorted(((" ".join(w.capitalize() for w in a.name.split("_")), int(a.value))
                       for a in Attribute if a.value >= 0), key=lambda e: e[0])
    except Exception:
        return []


def _damage_type_source() -> list[tuple[str, int]]:
    """The damage type's subtype enum. The placeholder members are not offered."""
    try:
        from Py4GWCoreLib.enums import DamageType

        return [(d.name, int(d.value)) for d in DamageType
                if d.value >= 0 and not d.name.startswith("unknown")]
    except Exception:
        return []


def _modifier_source() -> list[tuple[str, int]]:
    """Every current ``ModifierIdentifier`` with a known Item.Mods effect label."""
    try:
        from Py4GWCoreLib import mods_core
        from Py4GWCoreLib.mods_types import ModifierIdentifier

        output = []
        for identifier in ModifierIdentifier:
            if int(identifier) in (0, 0xFFFF):
                continue
            label = mods_core.effect_name(int(identifier))
            if label and not label.lower().startswith(("unknown", "empty")):
                output.append((label, int(identifier)))
        return sorted(output, key=lambda entry: entry[0].lower())
    except Exception:
        return []


def _upgrade_source() -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    for values in upgrade_data.lists().values():
        output.extend(values)
    return sorted({name: internal for name, internal in output}.items(), key=lambda entry: entry[0].lower())


def _draw_modifier_criteria(filter: Filter, fid: str) -> tuple[ModifierCriterion, ...]:
    """Edit the complete current Item.Mods effect vocabulary in a compact advanced section."""
    criteria = list(filter.modifiers)
    source = _modifier_source()
    lookup = {value: display for display, value in source}
    changed = False
    for index, criterion in enumerate(list(criteria)):
        label = lookup.get(criterion.identifier, "modifier %d" % criterion.identifier)
        PyImGui.text("%s" % label)
        PyImGui.same_line(0, 6)
        if PyImGui.small_button("remove##mod_rm_%s_%d" % (fid, index)):
            criteria.pop(index)
            changed = True
            continue
        PyImGui.same_line(0, 6)
        typed = PyImGui.input_int("threshold##mod_value_%s_%d" % (fid, index),
                                  int(criterion.values[0]) if criterion.values else 0)
        values = criterion.values
        if typed != (values[0] if values else 0):
            values = (typed,)
            criteria[index] = ModifierCriterion(criterion.identifier, criterion.subtype, values)
            changed = True
        PyImGui.same_line(0, 6)
        has_subtype = criterion.subtype is not None
        use_subtype = PyImGui.checkbox("subtype##mod_subtype_%s_%d" % (fid, index), has_subtype)
        if use_subtype != has_subtype:
            criteria[index] = ModifierCriterion(criterion.identifier, 0 if use_subtype else None, values)
            changed = True
        if use_subtype:
            current_criterion = criteria[index]
            PyImGui.same_line(0, 6)
            subtype = PyImGui.input_int("##mod_subtype_value_%s_%d" % (fid, index),
                                        int(current_criterion.subtype or 0))
            if subtype != int(current_criterion.subtype or 0):
                criteria[index] = ModifierCriterion(current_criterion.identifier, subtype,
                                                    current_criterion.values)
                changed = True

    names = [display for display, _identifier in source]
    selected = int(_state.get("new_modifier_%s" % fid, 0))
    if names:
        selected = max(0, min(selected, len(names) - 1))
        selected = PyImGui.combo("Add modifier##mod_add_%s" % fid, selected, names)
        _state["new_modifier_%s" % fid] = selected
        if PyImGui.small_button("Add##mod_add_button_%s" % fid):
            identifier = source[selected][1]
            if not any(item.identifier == identifier for item in criteria):
                criteria.append(ModifierCriterion(identifier))
                changed = True
    if changed:
        return tuple(criteria)
    return filter.modifiers


def _draw_upgrade_criteria(filter: Filter, fid: str) -> tuple[UpgradeCriterion, ...]:
    criteria = list(filter.upgrades)
    source = _upgrade_source()
    lookup = {canonical_upgrade_name(internal): display for display, internal in source}
    changed = False
    slot_names = ["Any slot", "Prefix", "Suffix", "Inscription", "Rune", "Insignia"]
    for index, criterion in enumerate(list(criteria)):
        PyImGui.text(lookup.get(canonical_upgrade_name(criterion.name), criterion.name))
        PyImGui.same_line(0, 6)
        if PyImGui.small_button("remove##up_rm_%s_%d" % (fid, index)):
            criteria.pop(index)
            changed = True
            continue
        slot_index = 0 if criterion.slot is None else max(0, min(int(criterion.slot) + 1, len(slot_names) - 1))
        picked_slot = PyImGui.combo("slot##up_slot_%s_%d" % (fid, index), slot_index, slot_names)
        slot = None if picked_slot == 0 else picked_slot - 1
        maxed = PyImGui.checkbox("maxed##up_maxed_%s_%d" % (fid, index), criterion.maxed)
        if slot != criterion.slot or maxed != criterion.maxed:
            criteria[index] = UpgradeCriterion(criterion.name, slot, maxed)
            changed = True

    names = [display for display, _name in source]
    selected = int(_state.get("new_upgrade_%s" % fid, 0))
    if names:
        selected = max(0, min(selected, len(names) - 1))
        selected = PyImGui.combo("Add upgrade##up_add_%s" % fid, selected, names)
        _state["new_upgrade_%s" % fid] = selected
        if PyImGui.small_button("Add##up_add_button_%s" % fid):
            name = source[selected][1]
            if not any(item.name == name for item in criteria):
                criteria.append(UpgradeCriterion(name))
                changed = True
    if changed:
        return tuple(criteria)
    return filter.upgrades


def _draw_criteria(filter: Filter, index: int) -> Filter | None:
    """Returns a replacement filter when something changed, else None."""
    fid = filter.id
    changed = False
    values = {
        "item_types": filter.item_types, "model_ids": filter.model_ids,
        "dye_colors": filter.dye_colors, "salvages_into": filter.salvages_into,
        "name_contains": filter.name_contains,
    }

    modes = [MATCH_ALL, MATCH_ANY]
    current_mode = modes.index(filter.mode) if filter.mode in modes else 0
    picked_mode = PyImGui.radio_button("Match ALL (AND)##m_%s" % fid, current_mode, 0)
    PyImGui.same_line(0, 8)
    picked_mode = PyImGui.radio_button("Match ANY (OR)##m2_%s" % fid, picked_mode, 1)
    if picked_mode != current_mode:
        changed = True
    PyImGui.text_colored("Only the conditions you set are used. A filter with none matches nothing.", GRAY)
    PyImGui.separator()

    # -- id-based criteria, each behind its own collapsible header --
    for key, label, source in (
        ("item_types", "Item types", _item_type_source()),
        ("model_ids", "Models", _model_source()),
    ):
        count = len(values[key])
        if PyImGui.collapsing_header("%s  (%d)###%s_%s" % (label, count, key, fid)):
            if key == "item_types":
                # Grouped, because the grouping IS the taxonomy. The flat searchable picker
                # follows underneath for reaching one specific type by name.
                PyImGui.text_colored("Pick whole groups, or search for one type below.", GRAY)
                values[key] = _item_type_groups("%s_%s" % (key, fid), values[key])
                PyImGui.separator()
            if key == "model_ids":
                # BOTH paths, because they answer different needs -- the curated catalog you
                # browse, and the flat enum you search.
                PyImGui.text_colored("Browse the catalog, or search every model id below.", GRAY)
                values[key] = _curated_grid("%s_%s" % (key, fid), values[key])
                PyImGui.separator()
            picked = _two_pane_picker("%s_%s" % (key, fid), label.lower(), source, values[key])
            if picked != values[key]:
                values[key] = picked
                changed = True
            elif key in ("model_ids", "item_types") and values[key] != getattr(filter, key):
                changed = True   # the grid changed it even though the picker did not

    # -- rarity: composable, unlike the global toggles in Loot Filters --
    rarities = filter.rarities
    if PyImGui.collapsing_header("Rarity  (%d)###rar_%s" % (len(rarities), fid)):
        PyImGui.text_colored("Any of the ticked ones. Combine with anything else -- this is what "
                             "makes 'gold weapons at req 9' or 'beacon every green' possible.", GRAY)
        for index, label in enumerate(("White", "Blue", "Purple", "Gold", "Green")):
            on = index in rarities
            if PyImGui.checkbox("%s##rar_%s_%d" % (label, fid, index), on) != on:
                rarities = (rarities + (index,)) if not on                     else tuple(v for v in rarities if v != index)
                changed = True

    # -- name: the ONLY subject that takes `contains` --
    count = len(filter.name_contains)
    if PyImGui.collapsing_header("Name contains  (%d)###name_%s" % (count, fid)):
        PyImGui.text_colored("Substring, case-insensitive. Any one matching is enough.", GRAY)
        for position, part in enumerate(filter.name_contains):
            if PyImGui.small_button("remove##nm_%s_%d" % (fid, position)):
                values["name_contains"] = tuple(p for i, p in enumerate(filter.name_contains)
                                                if i != position)
                changed = True
            PyImGui.same_line(0, 6)
            PyImGui.text(part)
        typed = PyImGui.input_text("##nm_new_%s" % fid, _state.get("name_entry_%s" % fid, ""))
        _state["name_entry_%s" % fid] = typed
        PyImGui.same_line(0, 4)
        if PyImGui.button("Add##nm_add_%s" % fid) and typed.strip():
            if typed.strip() not in values["name_contains"]:
                values["name_contains"] = values["name_contains"] + (typed.strip(),)
                changed = True
            _state["name_entry_%s" % fid] = ""

    # -- numeric criteria, match-or-better --
    has_req = filter.max_requirement is not None
    want_req = PyImGui.checkbox("Requirement at most##rq_%s" % fid, has_req)
    max_req = filter.max_requirement
    if want_req != has_req:
        max_req = 9 if want_req else None
        changed = True
    if want_req:
        PyImGui.same_line(0, 6)
        PyImGui.push_item_width(120)
        typed = PyImGui.slider_int("##rqv_%s" % fid, int(max_req or 9), 0, 13)
        PyImGui.pop_item_width()
        if typed != (max_req or 9):
            max_req = typed
            changed = True
        ImGui.show_tooltip("Match-or-better: a requirement at or below this passes. Lower is better.")

    has_value = filter.min_value is not None
    want_value = PyImGui.checkbox("Worth at least##v_%s" % fid, has_value)
    min_value = filter.min_value
    if want_value != has_value:
        min_value = 100 if want_value else None
        changed = True
    if want_value:
        PyImGui.same_line(0, 6)
        PyImGui.push_item_width(120)
        typed = PyImGui.input_int("##vv_%s" % fid, int(min_value or 0))
        PyImGui.pop_item_width()
        if typed != (min_value or 0):
            min_value = max(0, typed)
            changed = True
        ImGui.show_tooltip("Match-or-better: this value or more. Higher is better.")

    # -- the mod criteria --
    PyImGui.separator()
    PyImGui.text_colored("Mods. A drop is unidentified, so these are all it shows.", GRAY)

    req_attribute = filter.requirement_attribute
    if want_req:
        attributes = _attribute_source()
        names = ["(any attribute)"] + [display for display, _v in attributes]
        current = 0
        for index, (_display, value) in enumerate(attributes):
            if value == req_attribute:
                current = index + 1
                break
        chosen = PyImGui.combo("in attribute##rqa_%s" % fid, current, names)
        if chosen != current:
            req_attribute = None if chosen == 0 else attributes[chosen - 1][1]
            changed = True

    has_damage = filter.min_damage is not None
    want_damage = PyImGui.checkbox("Damage at least##dmg_%s" % fid, has_damage)
    min_damage = filter.min_damage
    if want_damage != has_damage:
        min_damage = 10 if want_damage else None
        changed = True
    if want_damage:
        PyImGui.same_line(0, 6)
        PyImGui.push_item_width(120)
        typed = PyImGui.slider_int("##dmgv_%s" % fid, int(min_damage or 10), 1, 100)
        PyImGui.pop_item_width()
        if typed != (min_damage or 10):
            min_damage = typed
            changed = True
        ImGui.show_tooltip("Damage is a RANGE -- 'Chaos Dmg: 11-21'. This compares its top end, "
                           "match-or-better. It is what replaced the old max-damage checkbox, which "
                           "collapsed the range into a yes/no.")

    damage_types = filter.damage_types
    count = len(damage_types)
    if PyImGui.collapsing_header("Damage type  (%d)###dt_%s" % (count, fid)):
        for display, value in _damage_type_source():
            on = value in damage_types
            if PyImGui.checkbox("%s##dt_%s_%d" % (display, fid, value), on) != on:
                damage_types = (damage_types + (value,)) if not on                     else tuple(v for v in damage_types if v != value)
                changed = True

    modifiers = filter.modifiers
    if PyImGui.collapsing_header("All Item.Mods effects  (%d)###mods_%s" % (len(modifiers), fid)):
        PyImGui.text_wrapped("Advanced: every current ModifierIdentifier is available. Thresholds use "
                             "the Item.Mods match-or-better direction; for requirements, 9 includes 9 and lower.")
        edited_modifiers = _draw_modifier_criteria(filter, fid)
        if edited_modifiers != modifiers:
            modifiers = edited_modifiers
            changed = True

    upgrades = filter.upgrades
    if PyImGui.collapsing_header("Applied upgrades  (%d)###upgrades_%s" % (len(upgrades), fid)):
        PyImGui.text_wrapped("Advanced: match named prefixes, suffixes, runes, insignias, or inscriptions "
                             "reported by Item.Mods. Use the optional slot and maxed checks when needed.")
        edited_upgrades = _draw_upgrade_criteria(filter, fid)
        if edited_upgrades != upgrades:
            upgrades = edited_upgrades
            changed = True

    if not changed:
        return None
    return Filter(
        id=filter.id, name=filter.name, enabled=filter.enabled, mode=modes[picked_mode],
        item_types=values["item_types"], model_ids=values["model_ids"],
        name_contains=values["name_contains"], rarities=rarities,
        dye_colors=values["dye_colors"], salvages_into=values["salvages_into"],
        max_requirement=max_req, requirement_attribute=req_attribute,
        min_value=min_value, min_damage=min_damage, damage_types=damage_types,
        modifiers=modifiers, upgrades=upgrades,
    )


def _draw_preview(filter: Filter) -> None:
    """Live verdict against the current target, with the per-criterion breakdown.

    This calls the same ``evaluate`` the features use, so the preview cannot disagree with behaviour.
    """
    try:
        from Py4GWCoreLib.Player import Player

        target = Player.GetTargetID()
    except Exception:
        target = 0
    if not target:
        PyImGui.text_colored("Target an item on the ground to test this filter.", GRAY)
        return
    try:
        from Py4GWCoreLib.Agent import Agent

        item_agent = Agent.GetItemAgentByID(target)
        item_id = item_agent.item_id if item_agent else 0
    except Exception:
        item_id = 0
    if not item_id:
        PyImGui.text_colored("The current target is not a ground item.", GRAY)
        return

    verdict, breakdown = evaluate(filter, item_id)
    PyImGui.text_colored("ITEM MATCHES" if verdict else "ITEM DOES NOT MATCH",
                         (0.45, 0.8, 0.45, 1.0) if verdict else (0.85, 0.4, 0.4, 1.0))
    PyImGui.same_line(0, 8)
    PyImGui.text_colored("(%s of %d conditions)" % ("all" if filter.mode == MATCH_ALL else "any",
                                                    len(breakdown)), GRAY)
    for label, passed in breakdown:
        PyImGui.text_colored(("  [x] " if passed else "  [ ] ") + label,
                             (0.45, 0.8, 0.45, 1.0) if passed else GRAY)


# ---------------------------------------------------------------- sections


def draw_filters() -> None:
    current = filters()

    if PyImGui.button("New filter##lff_new"):
        current.append(Filter(id=store.next_filter_id(current), name="Filter %d" % (len(current) + 1)))
        _commit_filters()
    PyImGui.same_line(0, 8)
    PyImGui.text_colored("%d filter(s)" % len(current), GRAY)
    PyImGui.separator()

    if not current:
        PyImGui.text_colored("None yet. Create one above.", GRAY)
        return

    for index, filter in enumerate(list(current)):
        enabled = PyImGui.checkbox("##en_%s" % filter.id, filter.enabled)
        if enabled != filter.enabled:
            current[index] = filter.with_enabled(enabled)
            _commit_filters()
            continue
        PyImGui.same_line(0, 6)
        # ###id: the label carries the name and position, both of which change.
        if not PyImGui.collapsing_header("%d. %s###hdr_%s" % (index + 1, filter.name, filter.id)):
            continue

        typed = PyImGui.input_text("Name##nm_%s" % filter.id, filter.name)
        if typed != filter.name and typed.strip():
            current[index] = filter.renamed(typed.strip())
            _commit_filters()
            continue

        replacement = _draw_criteria(filter, index)
        if replacement is not None:
            current[index] = replacement
            _commit_filters()

        if filter.is_empty():
            PyImGui.text_colored("No conditions set - this filter matches nothing.", WARN)

        PyImGui.separator()
        _draw_preview(filter)
        PyImGui.separator()

        if PyImGui.small_button("Duplicate##dup_%s" % filter.id):
            copy = Filter.from_dict(filter.to_dict())
            current.insert(index + 1, Filter.from_dict({**copy.to_dict(),
                                                       "id": store.next_filter_id(current),
                                                       "name": filter.name + " (copy)"}))
            _commit_filters()
            return
        PyImGui.same_line(0, 6)
        if index > 0 and PyImGui.small_button("Move up##up_%s" % filter.id):
            current[index - 1], current[index] = current[index], current[index - 1]
            _commit_filters()
            return
        PyImGui.same_line(0, 6)
        if PyImGui.small_button("Delete##del_%s" % filter.id):
            current.pop(index)
            _commit_filters()
            return


def draw_filter_sets() -> None:
    current = filter_sets()
    all_filters = filters()

    PyImGui.text_wrapped(
        "A filter set is a named group of filters for one feature - \"Caster\", \"Ranger\", \"Melee\". "
        "Filter sets are shared across accounts; each feature runs one at a time."
    )
    PyImGui.separator()

    PyImGui.push_item_width(160)
    _state["new_filter_set"] = PyImGui.input_text("##lff_newset", _state["new_filter_set"])
    PyImGui.pop_item_width()
    PyImGui.same_line(0, 6)
    if PyImGui.button("New filter set##lff_addset"):
        name = _state["new_filter_set"].strip()
        if name and not store.filter_set_by_name(current, name):
            current.append(FilterSet(id=store.next_filter_set_id(current), name=name))
            _state["new_filter_set"] = ""
            _commit_filter_sets()
    PyImGui.separator()

    if not current:
        PyImGui.text_colored("No filter sets yet.", GRAY)
        return

    for index, filter_set in enumerate(list(current)):
        if not PyImGui.collapsing_header("%s  (%d)###set_%s" % (filter_set.name,
                                                                len(filter_set.filter_ids),
                                                                filter_set.id)):
            continue
        typed = PyImGui.input_text("Name##snm_%s" % filter_set.id, filter_set.name)
        if typed != filter_set.name and typed.strip():
            current[index] = FilterSet(id=filter_set.id, name=typed.strip(),
                                       filter_ids=filter_set.filter_ids)
            _commit_filter_sets()
            return

        PyImGui.text_colored("Filters in this filter set", GRAY)
        chosen = filter_set.filter_ids
        for filter in all_filters:
            on = filter.id in chosen
            if PyImGui.checkbox("%s##sf_%s_%s" % (filter.name, filter_set.id, filter.id), on) != on:
                chosen = tuple(i for i in chosen if i != filter.id) if on else chosen + (filter.id,)
                current[index] = FilterSet(id=filter_set.id, name=filter_set.name, filter_ids=chosen)
                _commit_filter_sets()
                return
        if not all_filters:
            PyImGui.text_colored("Create a filter first.", GRAY)

        if PyImGui.small_button("Duplicate##sdup_%s" % filter_set.id):
            name = filter_set.name + " (copy)"
            if not store.filter_set_by_name(current, name):
                current.insert(index + 1, FilterSet(id=store.next_filter_set_id(current),
                                                   name=name, filter_ids=filter_set.filter_ids))
                _commit_filter_sets()
                return
        PyImGui.same_line(0, 6)
        if PyImGui.small_button("Delete##sdel_%s" % filter_set.id):
            current.pop(index)
            _commit_filter_sets()
            return


def draw_defects() -> None:
    """Catalog rows with no known model id -- surfaced, never shipped as dead rows."""
    PyImGui.text_wrapped(
        "These are real items whose model id is unknown to every bundled data source, so they cannot "
        "be matched against a drop. They are listed here rather than shown as entries that look "
        "functional but never fire."
    )
    PyImGui.separator()
    for entry in catalog_data.UNRESOLVED:
        PyImGui.text_colored("%s  --  %s" % (entry.name, entry.category), GRAY)


def add_sections(win, group) -> None:
    """Add the Loot Filter Factory section. Its own surface; embedded in no feature."""
    win.add_section(group, "Loot Filter Factory")
    win.add_tab("Loot Filter Factory", "Filters", draw_filters)
    win.add_tab("Loot Filter Factory", "Filter Sets", draw_filter_sets)
    win.add_tab("Loot Filter Factory", "Unresolved", draw_defects)
