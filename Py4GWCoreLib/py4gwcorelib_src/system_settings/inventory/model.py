"""Plain System Settings data for inventory presentation and shared bag scope."""

from dataclasses import dataclass, field
from typing import Any

from Py4GWCoreLib.enums_src.Item_enums import (
    INVENTORY_BAGS,
    STORAGE_BAGS,
    Bags,
)


RARITIES: tuple[str, ...] = ("White", "Blue", "Green", "Purple", "Gold")
_FALLBACK_COLORS: dict[str, tuple[int, int, int, int]] = {
    "White": (255, 255, 255, 255),
    "Blue": (0, 0, 255, 255),
    "Green": (0, 255, 0, 255),
    "Purple": (128, 0, 128, 255),
    "Gold": (255, 215, 0, 255),
}


def _palette_colors() -> dict[str, tuple[int, int, int, int]]:
    try:
        from Py4GWCoreLib.py4gwcorelib_src.Color import ColorPalette

        return {rarity: tuple(ColorPalette.GetColor("GW_%s" % rarity).to_tuple()) for rarity in RARITIES}
    except Exception:
        return dict(_FALLBACK_COLORS)


DEFAULT_COLORS: dict[str, tuple[int, int, int, int]] = _palette_colors()

SLOT_MODE_ALL = "all"
SLOT_MODE_INCLUDE = "include"
SLOT_MODE_EXCLUDE = "exclude"
SLOT_MODES = (SLOT_MODE_ALL, SLOT_MODE_INCLUDE, SLOT_MODE_EXCLUDE)

# This is deliberately broader than the current Identification feature. The policy is shared by
# identification, salvage, and storage so those features cannot each grow a subtly different bag
# selector later. Vault and materials bags are presented here but are not enabled by default.
BAGS: tuple[Bags, ...] = (
    *INVENTORY_BAGS,
    Bags.EquipmentPack,
    Bags.MaterialStorage,
    *STORAGE_BAGS,
)

BAG_GROUPS: tuple[tuple[str, str, tuple[Bags, ...]], ...] = (
    (
        "Inventory",
        "Your active inventory bags. Identification currently operates on these bags by default.",
        tuple(INVENTORY_BAGS),
    ),
    (
        "Equipment Bags",
        "Equipment Pack slots. Keep this disabled unless equipment items are intentionally part of the operation.",
        (Bags.EquipmentPack,),
    ),
    (
        "Xunlai Vault",
        "Shared storage tabs, including Material Storage. These are disabled by default to prevent accidental vault handling.",
        (*STORAGE_BAGS, Bags.MaterialStorage),
    ),
)


def _color(value: Any, fallback: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    try:
        channels = tuple(max(0, min(255, int(channel))) for channel in value)[:4]
    except (TypeError, ValueError):
        return fallback
    return channels if len(channels) == 4 else fallback


@dataclass
class ColorizeSettings:
    enabled: bool = False
    imgui_frame: bool = True
    imgui_outline: bool = True
    native_frame: bool = False
    native_outline: bool = False
    context_menu_toggle: bool = True
    rarities: dict[str, bool] = field(default_factory=lambda: {
        "White": False, "Blue": True, "Green": True, "Purple": True, "Gold": True,
    })
    colors: dict[str, tuple[int, int, int, int]] = field(default_factory=lambda: dict(DEFAULT_COLORS))

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "imgui_frame": self.imgui_frame,
            "imgui_outline": self.imgui_outline,
            "native_frame": self.native_frame,
            "native_outline": self.native_outline,
            "context_menu_toggle": self.context_menu_toggle,
            "rarities": {name: bool(self.rarities.get(name, False)) for name in RARITIES},
            "colors": {name: list(_color(self.colors.get(name), DEFAULT_COLORS[name])) for name in RARITIES},
        }

    @staticmethod
    def from_dict(raw: Any) -> "ColorizeSettings":
        raw = raw if isinstance(raw, dict) else {}
        stored_rarities = raw.get("rarities", {})
        stored_colors = raw.get("colors", {})
        default_rarities = {
            "White": False, "Blue": True, "Green": True, "Purple": True, "Gold": True,
        }
        return ColorizeSettings(
            enabled=bool(raw.get("enabled", False)),
            imgui_frame=bool(raw.get("imgui_frame", True)),
            imgui_outline=bool(raw.get("imgui_outline", True)),
            native_frame=bool(raw.get("native_frame", False)),
            native_outline=bool(raw.get("native_outline", False)),
            context_menu_toggle=bool(raw.get("context_menu_toggle", True)),
            rarities={name: bool(stored_rarities.get(name, default_rarities[name])) for name in RARITIES}
            if isinstance(stored_rarities, dict) else dict(default_rarities),
            colors={name: _color(stored_colors.get(name), DEFAULT_COLORS[name]) for name in RARITIES}
            if isinstance(stored_colors, dict) else dict(DEFAULT_COLORS),
        )


@dataclass
class BagSlotPolicy:
    """Slot policy for one bag: all slots, an allow-list, or a deny-list."""

    mode: str = SLOT_MODE_ALL
    slots: tuple[int, ...] = ()

    def allows(self, slot: int) -> bool:
        if self.mode == SLOT_MODE_INCLUDE:
            return int(slot) in self.slots
        if self.mode == SLOT_MODE_EXCLUDE:
            return int(slot) not in self.slots
        return True

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode if self.mode in SLOT_MODES else SLOT_MODE_ALL,
                "slots": list(self.slots)}

    @staticmethod
    def from_dict(raw: Any) -> "BagSlotPolicy":
        raw = raw if isinstance(raw, dict) else {}
        mode = str(raw.get("mode", SLOT_MODE_ALL))
        if mode not in SLOT_MODES:
            mode = SLOT_MODE_ALL
        try:
            slots = tuple(sorted({int(value) for value in raw.get("slots", ()) or () if int(value) >= 0}))
        except (TypeError, ValueError):
            slots = ()
        return BagSlotPolicy(mode=mode, slots=slots)


def _default_bag_policies() -> dict[int, BagSlotPolicy]:
    return {int(bag.value): BagSlotPolicy() for bag in BAGS}


@dataclass
class BagSettings:
    """Shared bag/slot scope for every automated item operation."""

    enabled_bags: tuple[int, ...] = field(default_factory=lambda: tuple(int(bag.value) for bag in INVENTORY_BAGS))
    bag_policies: dict[int, BagSlotPolicy] = field(default_factory=_default_bag_policies)
    show_slot_overlay: bool = False
    outpost_arrival_delay_ms: int = 3_500

    def allows(self, bag: int | Bags, slot: int) -> bool:
        bag_id = int(bag.value) if isinstance(bag, Bags) else int(bag)
        if bag_id not in self.enabled_bags:
            return False
        return self.bag_policies.get(bag_id, BagSlotPolicy()).allows(int(slot))

    def arrival_delay_seconds(self, is_outpost: bool) -> float:
        """Extra wait after ``Checks.Map.MapValid`` before automatic item work."""
        return self.outpost_arrival_delay_ms / 1000.0 if is_outpost else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled_bags": list(self.enabled_bags),
            "bag_policies": {str(bag): policy.to_dict() for bag, policy in self.bag_policies.items()},
            "show_slot_overlay": self.show_slot_overlay,
            "outpost_arrival_delay_ms": self.outpost_arrival_delay_ms,
        }

    @staticmethod
    def from_dict(raw: Any) -> "BagSettings":
        raw = raw if isinstance(raw, dict) else {}
        valid_bags = {int(bag.value) for bag in BAGS}
        stored_bags = raw.get("enabled_bags")
        try:
            enabled = tuple(sorted({int(value) for value in (stored_bags if stored_bags is not None else
                                                             (int(bag.value) for bag in INVENTORY_BAGS))
                                    if int(value) in valid_bags}))
        except (TypeError, ValueError):
            enabled = tuple(int(bag.value) for bag in INVENTORY_BAGS)
        raw_policies = raw.get("bag_policies", {})
        policies = _default_bag_policies()
        if isinstance(raw_policies, dict):
            for key, value in raw_policies.items():
                try:
                    bag_id = int(key)
                except (TypeError, ValueError):
                    continue
                if bag_id in valid_bags:
                    policies[bag_id] = BagSlotPolicy.from_dict(value)
        try:
            if "outpost_arrival_delay_ms" in raw:
                outpost_arrival_delay_ms = int(raw.get("outpost_arrival_delay_ms", 3_500))
            else:
                # Compatibility with the short-lived seconds-based document.
                outpost_arrival_delay_ms = int(raw.get("outpost_arrival_delay_seconds", 3.5) * 1000)
        except (TypeError, ValueError):
            outpost_arrival_delay_ms = 3_500
        return BagSettings(
            enabled_bags=enabled,
            bag_policies=policies,
            show_slot_overlay=bool(raw.get("show_slot_overlay", False)),
            outpost_arrival_delay_ms=max(0, min(60_000, outpost_arrival_delay_ms)),
        )

@dataclass
class InventoryFeatureSettings:
    colorize: ColorizeSettings = field(default_factory=ColorizeSettings)
    context_menu_xunlai: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"colorize": self.colorize.to_dict(), "context_menu_xunlai": self.context_menu_xunlai}

    @staticmethod
    def from_dict(raw: Any) -> "InventoryFeatureSettings":
        raw = raw if isinstance(raw, dict) else {}
        return InventoryFeatureSettings(
            colorize=ColorizeSettings.from_dict(raw.get("colorize")),
            context_menu_xunlai=bool(raw.get("context_menu_xunlai", True)),
        )
