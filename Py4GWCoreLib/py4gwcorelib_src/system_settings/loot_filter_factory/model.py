"""Filter definitions -- pure data.

**Vocabulary (settled, see `docs/loot/redesign/filter-structure.md`).** An
**evaluation** is one declarative test; a **filter** is a named set of
evaluations with one ALL/ANY mode; a **filter set** is a named group of
filters for one feature ("melee loot"). There is no profile layer: each
feature keeps its own store and its own per-feature selection of a filter
set. The word "rule" is retired.

A filter carries criteria and nothing else. For Loot Filters a match means
*wanted*; for Recolor & Beacons a match means *mark it*. Those outcomes belong
to the consuming feature, in its own store, **not** to the filter: Recolor &
Beacons keeps ``filter_id -> outcome`` in its own per-account store.

**Nothing here decides.** No callables, no predicates: a filter is values, and
the matcher owns all evaluation. That is what stops a script handing the class
its own ruling to run.

**Shape follows the Item Mods Playground** (`Widgets/Coding/Debug/Py4GW/Item Mods Playground.py`),
which is the existing, working example of filtering items by mods: upgrades are chosen by **slot and
name** (never modifier ids), the requirement is *at most*, and there is **one ALL/ANY mode for the
whole filter** rather than separate all-of and any-of lists.

**Numbers are match-or-better, never exact** -- item mods are defined that way, so filters follow the
data.
"""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace

MATCH_ALL = "all"
MATCH_ANY = "any"

# The game exposes two internal IDs for the same user-facing Minor Vigor rune.
# Keep the alias here because presentation and evaluation must share one identity,
# including filters saved before the duplicate was merged in the UI.
_UPGRADE_ALIASES = {
    "RuneOfMinorVigor2": "RuneOfMinorVigor",
}


def canonical_upgrade_name(name: str) -> str:
    """Return the canonical identity for an internal upgrade name."""
    return _UPGRADE_ALIASES.get(str(name), str(name))


@dataclass(frozen=True)
class ModifierCriterion:
    """One declarative ``Item.Mods.HasMod`` test.

    ``values`` are match-or-better thresholds in the same order accepted by
    ``Item.Mods.HasMod``. ``subtype`` stores the numeric value of the relevant
    enum (attribute, damage type, ailment, and so on).
    """

    identifier: int
    subtype: int | None = None
    values: tuple[int, ...] = ()


@dataclass(frozen=True)
class UpgradeCriterion:
    """One declarative test against a named applied upgrade."""

    name: str
    slot: int | None = None
    maxed: bool = False


@dataclass(frozen=True)
class Filter:
    """One composite resolver: a named, toggleable set of evaluations.

    Identity is :attr:`id` -- a short sequential number. :attr:`name` is a **label**, never a key, so
    titles may repeat and be renamed freely and duplicating a filter costs nothing.
    """

    id: str = ""
    name: str = "New filter"
    enabled: bool = True

    #: How this filter's evaluations combine. ALL = every set criterion must hold; ANY = at least one.
    mode: str = MATCH_ALL

    # -- evaluations. An unset criterion is NOT a constraint; a filter with none matches nothing. --
    item_types: tuple[int, ...] = ()          # any-of
    model_ids: tuple[int, ...] = ()           # any-of
    dye_colors: tuple[int, ...] = ()          # any-of; dyes are item-type + colour, never model id
    salvages_into: tuple[int, ...] = ()       # any-of material model ids

    #: Rarities, any-of. 0=White 1=Blue 2=Purple 3=Gold 4=Green.
    #:
    #: Rarity is readable on an unidentified drop -- it comes off the interaction flags
    #: (GREEN 0x10, GOLD 0x20000, PURPLE 0x400000), which is why the dump decodes exactly those.
    #:
    #: This is NOT the same thing as the rarity toggles in Loot Filters. Those are a global
    #: "take golds" switch on the hand-crafted side. This is a *criterion*, so it composes: it is
    #: what makes "gold weapons at requirement 9" or "beacon every green" expressible at all.
    rarities: tuple[int, ...] = ()

    #: Substrings of the item's name. Any-of, case-insensitive.
    #:
    #: **contains** is one of the two operators in the closed set, and it applies to **names only** --
    #: a substring test does not mean anything on a type, a model or a number. This is what lets the
    #: settled example be written: *item type AND name contains ... AND value ... AND requirement*.
    name_contains: tuple[str, ...] = ()

    #: Worth **at least** -- match-or-better, since higher is better for value.
    #: Not a mod: gold value is a field on the item, not an effect word.
    min_value: int | None = None

    # -- the MOD evaluations. --
    #
    # The three named shortcuts below describe what an unidentified drop exposes. The generic
    # ``modifiers`` and ``upgrades`` fields below extend the same vocabulary to identified items;
    # they are still declarative Item.Mods criteria, not a second rule system.
    #
    #     Chaos Dmg: 11-21 (Requires 11 Illusion Magic)
    #       0x2798  arg1=1  arg2=11   Requirement 11 (IllusionMagic)
    #       0x24B8  arg1=6  arg2=0    Damage Type (Blunt)
    #       0xA7A8  arg1=21 arg2=11   Damage 11        <- a RANGE, arg2..arg1
    #
    # Those are the INHERENT mods (`mods_core.Slot.Inherent`). Prefixes, suffixes, runes,
    # insignias and inscriptions are NOT visible before identifying, so filtering on them could
    # never fire -- they were dead controls and are gone.
    #
    #: Requirement **at most** -- match-or-better, and the direction is not ours to choose:
    #: `Requirement` is the one mod in the table declaring `better_low=True`.
    max_requirement: int | None = None
    #: Which attribute that requirement is in (the mod's subtype). None = any attribute.
    requirement_attribute: int | None = None

    #: Damage **at least** -- compared against the range's TOP end (`arg1`), since that is the
    #: number the game shows as the weapon's damage and higher is better.
    #: This is what replaces the old "require max damage" checkbox: a real ranged comparison
    #: instead of a boolean that collapsed the range and nullified match-or-better.
    min_damage: int | None = None

    #: Damage types, any-of -- Blunt, Slashing, Chaos, Fire ... (the mod's subtype enum).
    damage_types: tuple[int, ...] = ()

    #: Full Item.Mods effect tests, beyond the unidentified-drop shortcuts above.
    modifiers: tuple[ModifierCriterion, ...] = ()
    #: Named upgrades, optionally constrained by physical slot and maxed value.
    upgrades: tuple[UpgradeCriterion, ...] = ()

    def is_empty(self) -> bool:
        """A filter with no criteria at all. It matches nothing, rather than everything."""
        return not (
            self.item_types or self.model_ids or self.dye_colors or self.salvages_into
            or self.name_contains or self.rarities
            or self.max_requirement is not None or self.min_value is not None
            or self.min_damage is not None or self.damage_types
            or self.modifiers or self.upgrades
        )

    def renamed(self, name: str) -> "Filter":
        return replace(self, name=name)

    def with_enabled(self, enabled: bool) -> "Filter":
        return replace(self, enabled=bool(enabled))

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "enabled": self.enabled, "mode": self.mode,
            "item_types": list(self.item_types), "model_ids": list(self.model_ids),
            "dye_colors": list(self.dye_colors), "salvages_into": list(self.salvages_into),
            "name_contains": list(self.name_contains), "rarities": list(self.rarities),
            "max_requirement": self.max_requirement,
            "requirement_attribute": self.requirement_attribute,
            "min_value": self.min_value, "min_damage": self.min_damage,
            "damage_types": list(self.damage_types),
            "modifiers": [
                {"identifier": criterion.identifier,
                 "subtype": criterion.subtype,
                 "values": list(criterion.values)}
                for criterion in self.modifiers
            ],
            "upgrades": [
                {"name": criterion.name, "slot": criterion.slot, "maxed": criterion.maxed}
                for criterion in self.upgrades
            ],
        }

    @staticmethod
    def from_dict(raw: dict) -> "Filter":
        def ints(key: str) -> tuple[int, ...]:
            return tuple(int(v) for v in raw.get(key, ()) or ())

        def strs(key: str) -> tuple[str, ...]:
            return tuple(str(v) for v in raw.get(key, ()) or ())

        mode = str(raw.get("mode", MATCH_ALL))
        max_req = raw.get("max_requirement")
        min_val = raw.get("min_value")

        modifiers: list[ModifierCriterion] = []
        for value in raw.get("modifiers", ()) or ():
            if not isinstance(value, dict):
                continue
            try:
                identifier = int(value["identifier"])
                subtype = None if value.get("subtype") is None else int(value["subtype"])
                thresholds = tuple(int(v) for v in value.get("values", ()) or ())
            except (KeyError, TypeError, ValueError):
                continue
            modifiers.append(ModifierCriterion(identifier, subtype, thresholds))

        upgrades: list[UpgradeCriterion] = []
        for value in raw.get("upgrades", ()) or ():
            if not isinstance(value, dict):
                continue
            name = str(value.get("name", "")).strip()
            if not name:
                continue
            try:
                slot = None if value.get("slot") is None else int(value["slot"])
            except (TypeError, ValueError):
                slot = None
            upgrades.append(UpgradeCriterion(name, slot, bool(value.get("maxed", False))))

        return Filter(
            id=str(raw.get("id", "")),
            name=str(raw.get("name", "New filter")),
            enabled=bool(raw.get("enabled", True)),
            mode=mode if mode in (MATCH_ALL, MATCH_ANY) else MATCH_ALL,
            item_types=ints("item_types"), model_ids=ints("model_ids"),
            dye_colors=ints("dye_colors"), salvages_into=ints("salvages_into"),
            name_contains=tuple(s for s in strs("name_contains") if s),
            rarities=ints("rarities"),
            max_requirement=None if max_req is None else int(max_req),
            min_value=None if min_val is None else int(min_val),
            requirement_attribute=(None if raw.get("requirement_attribute") is None
                                   else int(raw["requirement_attribute"])),
            min_damage=(None if raw.get("min_damage") is None else int(raw["min_damage"])),
            damage_types=ints("damage_types"),
            modifiers=tuple(modifiers),
            upgrades=tuple(upgrades),
        )


@dataclass(frozen=True)
class FilterSet:
    """A named group of filters for one feature -- "Caster", "Ranger", "Melee".

    Global, so a filter set composed once is usable from every account. Holds **filters only**: toggles
    and hand lists are per-account settings, and putting them in a shared object would stop two
    accounts running one filter set with different toggles.

    Identity is :attr:`id` (stable, sequential); :attr:`name` is a label and may repeat.
    """

    id: str = ""
    name: str = ""
    filter_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "filter_ids": list(self.filter_ids)}

    @staticmethod
    def from_dict(raw: dict) -> "FilterSet":
        return FilterSet(
            id=str(raw.get("id", "")),
            name=str(raw.get("name", "")),
            filter_ids=tuple(str(v) for v in raw.get("filter_ids", ()) or ()),
        )
