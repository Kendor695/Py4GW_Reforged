"""System Settings > Items controls for Xunlai, shared Bags, and Colorize."""

import PyImGui

from Py4GWCoreLib.py4gwcorelib_src.Color import Color
from Py4GWCoreLib.enums_src.Item_enums import MAX_BAG_SIZES

from . import model
from .controller import InventorySettingsController, get_controller

MUTED = (0.66, 0.67, 0.70, 1.0)
WARN = (0.86, 0.65, 0.28, 1.0)


def _rgba(color: tuple[int, int, int, int]) -> tuple[float, float, float, float]:
    return Color(*color).to_tuple_normalized()


def _to_color(value) -> tuple[int, int, int, int]:
    return tuple(Color.from_tuple_normalized(tuple(value)).to_tuple())


def add_sections(win, group) -> None:
    controller = get_controller()
    win.add_section(group, "Open Xunlai Vault", lambda: _draw_xunlai(controller))
    win.add_account_section(group, "items.bags", "Bags", lambda: _draw_bags(controller))
    win.add_section(group, "Item Operations", lambda: _draw_operations(controller))
    win.add_section(group, "Colorize", lambda: _draw_colorize(controller))


def _draw_xunlai(controller: InventorySettingsController) -> None:
    settings = controller.settings()
    PyImGui.text_wrapped("Open the Xunlai Vault without enabling an automatic handler.")
    visible = settings.context_menu_xunlai
    next_visible = PyImGui.checkbox("Show Open Xunlai in item context menu##items_xunlai_menu", visible)
    if next_visible != visible:
        settings.context_menu_xunlai = next_visible
        controller.save_settings()
    if PyImGui.button("Open Xunlai Vault##items_xunlai"):
        controller.open_xunlai()
    status = controller.xunlai_status()
    if status:
        PyImGui.text_colored(status, MUTED)


def _draw_operations(controller: InventorySettingsController) -> None:
    PyImGui.text_wrapped(
        "Explicit native item operations. They never select a rule, run on inventory change, or replace the game dialog."
    )
    candidates = controller.unidentified_item_ids()
    identify_label = "Identify current unidentified items (%d)##items_identify" % len(candidates)
    if PyImGui.button(identify_label):
        controller.request_identify(candidates)
    if controller.is_action_active():
        PyImGui.text_colored("An identify batch is active; no second batch can be started.", MUTED)
        if PyImGui.button("Cancel identify batch##items_identify_cancel"):
            controller.cancel_identify()

    hovered_item_id = controller.hovered_item_id()
    if hovered_item_id > 0:
        PyImGui.text("Hovered inventory item: %d" % hovered_item_id)
    else:
        PyImGui.text_colored("Hover an item in an open inventory window for salvage or storage.", MUTED)
    if PyImGui.button("Start native salvage for hovered item##items_salvage"):
        controller.request_salvage_hovered()
    if controller.is_salvage_active():
        PyImGui.same_line()
        if PyImGui.button("Stop salvage batch##items_salvage_stop"):
            controller.cancel_salvage()
    PyImGui.same_line()
    if PyImGui.button("Confirm materials-salvage dialog##items_salvage_confirm"):
        controller.request_confirm_salvage()
    if PyImGui.button("Store hovered item in Xunlai##items_store"):
        controller.request_store_hovered()

    status = controller.action_status()
    if status:
        PyImGui.text_colored(status, MUTED)


def _bag_label(bag: model.Bags) -> str:
    labels = {
        model.Bags.EquipmentPack: "Equipment Pack",
        model.Bags.MaterialStorage: "Material Storage",
    }
    if bag in labels:
        return labels[bag]
    if bag in model.STORAGE_BAGS:
        return "Storage tab %d" % (int(bag.value) - int(model.Bags.Storage1.value) + 1)
    return bag.name


def _bag_size(bag: model.Bags) -> int:
    known_size = int(MAX_BAG_SIZES.get(bag, 0))
    if known_size:
        return known_size
    try:
        import PyInventory

        return max(0, int(PyInventory.Bag(int(bag.value), bag.name).GetSize()))
    except Exception:
        return 0


def _set_group_enabled(settings, bags: tuple[model.Bags, ...], enabled: bool) -> None:
    selected = set(settings.enabled_bags)
    bag_ids = {int(bag.value) for bag in bags}
    if enabled:
        selected.update(bag_ids)
    else:
        selected.difference_update(bag_ids)
    settings.enabled_bags = tuple(sorted(selected))


def _draw_bags(controller: InventorySettingsController) -> None:
    """Configure the shared bag/slot scope used by all automated item operations."""
    settings = controller.bag_settings()
    changed = False
    PyImGui.text_wrapped(
        "Bags is the shared scope for automated item operations. Identification uses it now; "
        "Salvage uses it now, and Storage will use the same scope later."
    )
    PyImGui.text_wrapped(
        "Enable a bag to allow handling. Choose All slots, Include only selected slots, or "
        "Exclude selected slots. Include with no selected slots allows nothing; Exclude with "
        "no selected slots allows everything."
    )
    PyImGui.text_wrapped(
        "Open the relevant inventory or vault window, enable the overlay, and configure the "
        "visible slots by sight. The policy still applies while a bag is closed."
    )
    PyImGui.separator()
    arrival_delay = PyImGui.slider_int(
        "Automatic outpost arrival delay (ms)##items_bags_outpost_arrival_delay",
        int(settings.outpost_arrival_delay_ms),
        0,
        60_000,
    )
    if arrival_delay != settings.outpost_arrival_delay_ms:
        settings.outpost_arrival_delay_ms = arrival_delay
        changed = True
    PyImGui.text_colored(
        "After Checks.Map.MapValid succeeds, automatic Identification and Salvage wait this long "
        "before their one outpost-entry pulse. Set 0 to rely on the Map/Checks boundary alone.",
        MUTED,
    )
    PyImGui.separator()
    overlay = PyImGui.checkbox("Show bag/slot policy overlay##items_bags_overlay",
                               settings.show_slot_overlay)
    if overlay != settings.show_slot_overlay:
        settings.show_slot_overlay = overlay
        changed = True
    PyImGui.same_line()
    PyImGui.text_colored("Eligible", (0.30, 0.82, 0.42, 1.0))
    PyImGui.same_line()
    PyImGui.text_colored("Excluded", (0.88, 0.30, 0.30, 1.0))
    PyImGui.text_colored(
        "The overlay only draws on bag frames the game has currently created; it is diagnostic, "
        "not a second policy.",
        MUTED,
    )
    try:
        from Py4GWCoreLib.UIManager import XunlaiStorageWindow

        if XunlaiStorageWindow.IsOpen():
            visible_bags = XunlaiStorageWindow.GetVisibleTabBags()
            if not visible_bags:
                PyImGui.text_colored(
                    "Xunlai frame probe: vault is open, but no visible storage tab was resolved.",
                    WARN,
                )
            elif len(visible_bags) > 1:
                PyImGui.text_colored(
                    "Xunlai frame probe: multiple visible tabs (%s); frame ownership is ambiguous."
                    % ", ".join(_bag_label(bag) for bag in visible_bags),
                    WARN,
                )
            else:
                PyImGui.text_colored(
                    "Xunlai frame probe: active tab is %s." % _bag_label(visible_bags[0]),
                    MUTED,
                )
    except Exception:
        PyImGui.text_colored("Xunlai frame probe is unavailable in the current UI context.", WARN)
    PyImGui.separator()
    PyImGui.text("Bag domains")
    for group_name, description, group_bags in model.BAG_GROUPS:
        enabled_count = sum(int(bag.value) in settings.enabled_bags for bag in group_bags)
        group_key = group_name.lower().replace(" ", "_")
        if not PyImGui.collapsing_header(
            "%s (%d/%d enabled)###items_bags_group_%s" %
            (group_name, enabled_count, len(group_bags), group_key)
        ):
            continue
        PyImGui.text_wrapped(description)
        if PyImGui.button("Enable all##items_bags_enable_%s" % group_key):
            _set_group_enabled(settings, group_bags, True)
            changed = True
        PyImGui.same_line()
        if PyImGui.button("Disable all##items_bags_disable_%s" % group_key):
            _set_group_enabled(settings, group_bags, False)
            changed = True
        for bag in group_bags:
            bag_id = int(bag.value)
            label = _bag_label(bag)
            enabled = bag_id in settings.enabled_bags
            next_enabled = PyImGui.checkbox("Enable %s##items_bag_%d" % (label, bag_id), enabled)
            if next_enabled != enabled:
                _set_group_enabled(settings, (bag,), bool(next_enabled))
                changed = True
            policy = settings.bag_policies.setdefault(bag_id, model.BagSlotPolicy())
            selected = set(policy.slots)
            size = _bag_size(bag)
            if policy.mode == model.SLOT_MODE_ALL:
                summary = "All slots eligible"
            elif policy.mode == model.SLOT_MODE_INCLUDE:
                summary = "%d selected slot(s) eligible" % len(selected)
            else:
                summary = "%d selected slot(s) excluded" % len(selected)
            PyImGui.text_colored("%s: %s" % (label, summary), MUTED)
            if not next_enabled:
                continue

            mode_names = ["All slots", "Include only selected slots", "Exclude selected slots"]
            mode_index = (model.SLOT_MODES.index(policy.mode)
                          if policy.mode in model.SLOT_MODES else 0)
            next_mode = PyImGui.combo("Slot policy##items_bag_mode_%d" % bag_id, mode_index, mode_names)
            if next_mode != mode_index:
                policy.mode = model.SLOT_MODES[next_mode]
                if policy.mode == model.SLOT_MODE_ALL:
                    policy.slots = ()
                changed = True
            if policy.mode == model.SLOT_MODE_ALL:
                continue
            if size <= 0:
                PyImGui.text_colored(
                    "Open %s to discover its slot count before configuring individual slots." % label,
                    WARN,
                )
                continue
            if PyImGui.button("All##items_bags_slots_all_%d" % bag_id):
                policy.slots = tuple(range(size))
                changed = True
            PyImGui.same_line()
            if PyImGui.button("None##items_bags_slots_none_%d" % bag_id):
                policy.slots = ()
                changed = True
            selected = set(policy.slots)
            for slot in range(size):
                if slot and slot % 5:
                    PyImGui.same_line()
                on = slot in selected
                next_on = PyImGui.checkbox("%d##items_bag_%d_slot_%d" % (slot + 1, bag_id, slot), on)
                if next_on != on:
                    selected.add(slot) if next_on else selected.discard(slot)
                    changed = True
            policy.slots = tuple(sorted(selected))
        PyImGui.separator()
    if changed:
        controller.save_settings()


def _draw_colorize(controller: InventorySettingsController) -> None:
    colorize = controller.settings().colorize
    changed = False
    colorize.enabled, changed = _checkbox("Enable Colorize##items_colorize", colorize.enabled, changed)
    colorize.context_menu_toggle, changed = _checkbox(
        "Show Colorize toggle in item context menu##items_colorize_menu", colorize.context_menu_toggle, changed)
    PyImGui.text_colored("Bags and the regular inventory are monitored as the same item sources. If both are open, both are tinted.", MUTED)
    PyImGui.separator()
    PyImGui.text("Render targets")
    for label, attr in (("ImGui frame", "imgui_frame"), ("ImGui outline", "imgui_outline"),
                        ("Native frame", "native_frame"), ("Native outline", "native_outline")):
        value = bool(getattr(colorize, attr))
        next_value = PyImGui.checkbox("%s##items_%s" % (label, attr), value)
        if next_value != value:
            setattr(colorize, attr, next_value)
            changed = True
    if colorize.native_outline:
        PyImGui.text_colored("Native outline is not available from the current native UI binding; the option is recorded but has no effect.", WARN)
    PyImGui.separator()
    PyImGui.text("Rarities")
    for rarity in model.RARITIES:
        enabled = bool(colorize.rarities.get(rarity, False))
        next_enabled = PyImGui.checkbox("%s##items_rarity_%s" % (rarity, rarity), enabled)
        if next_enabled != enabled:
            colorize.rarities[rarity] = next_enabled
            changed = True
        picked = _to_color(PyImGui.color_edit4("%s color##items_color_%s" % (rarity, rarity), _rgba(colorize.colors[rarity])))
        if picked != colorize.colors[rarity]:
            colorize.colors[rarity] = picked
            changed = True
    if changed:
        controller.save_settings()


def _checkbox(label: str, value: bool, changed: bool) -> tuple[bool, bool]:
    next_value = PyImGui.checkbox(label, value)
    return bool(next_value), changed or next_value != value
