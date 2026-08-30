"""Evaluating filters against a live item.

**All evaluation lives here.** Filters are values; nothing outside this module supplies logic that
decides whether an item matches. Data in, decisions out.

:func:`evaluate` returns the per-criterion breakdown as well as the verdict, because the Item Mods
Playground already shows exactly that -- *"ITEM MATCHES (all of 4 criteria)"* with a pass/fail line
per condition -- and the filter editor's live preview copies it.

Two levels above that:

* :func:`matches` -- does one filter match one item.
* :func:`any_match` -- does *any* enabled filter match. This is the HAS-ANY both features use.
"""

from .model import MATCH_ANY
from .model import canonical_upgrade_name
from .model import Filter
from .model import ModifierCriterion
from .model import UpgradeCriterion


def _modifier_matches(item_id: int, criterion: ModifierCriterion) -> bool:
    """Evaluate one full-class modifier criterion through ``Item.Mods``."""
    try:
        from Py4GWCoreLib.Item import Item

        if not Item.Mods.HasMod(item_id, criterion.identifier, *criterion.values):
            return False
        if criterion.subtype is None:
            return True
        subtype = Item.Mods.GetSubtype(item_id, criterion.identifier)
        return subtype is not None and int(subtype) == int(criterion.subtype)
    except Exception:
        return False


def _upgrade_matches(item_id: int, criterion: UpgradeCriterion) -> bool:
    """Match a named upgrade by name, optional slot, and optional maxed state."""
    try:
        from Py4GWCoreLib.Item import Item

        for name, slot in Item.Mods.GetUpgrades(item_id):
            if canonical_upgrade_name(name) != canonical_upgrade_name(criterion.name):
                continue
            if criterion.slot is not None and int(slot) != int(criterion.slot):
                continue
            if criterion.maxed and not Item.Mods.IsMaxed(item_id, name):
                continue
            return True
    except Exception:
        return False
    return False


def _modifier_label(criterion: ModifierCriterion) -> str:
    try:
        from Py4GWCoreLib import mods_core

        label = mods_core.effect_name(criterion.identifier)
    except Exception:
        label = "modifier %d" % criterion.identifier
    if criterion.values:
        label += " %s+" % "/".join(str(value) for value in criterion.values)
    if criterion.subtype is not None:
        label += " [%d]" % criterion.subtype
    return label


def _upgrade_label(criterion: UpgradeCriterion) -> str:
    label = "upgrade %s" % criterion.name
    if criterion.slot is not None:
        label += " (slot %d)" % criterion.slot
    if criterion.maxed:
        label += " (maxed)"
    return label


def evaluate(filter: Filter, item_id: int, model_id: int | None = None) -> tuple[bool, list[tuple[str, bool]]]:
    """``(verdict, [(label, passed), ...])`` for one filter against one item.

    Only criteria the user actually set are evaluated; an unset criterion is not a constraint. A filter
    with no criteria at all matches nothing.
    """
    from Py4GWCoreLib.Item import Item

    results: list[tuple[str, bool]] = []

    if filter.item_types:
        try:
            got = int(Item.GetItemType(item_id)[0])
        except Exception:
            got = -1
        results.append(("item type", got in filter.item_types))

    if filter.model_ids:
        if model_id is None:
            model_id = Item.GetModelID(item_id)
        results.append(("model", int(model_id) in filter.model_ids))

    if filter.rarities:
        # Readable before identifying: rarity comes off the interaction flags.
        checks = (Item.Rarity.IsWhite, Item.Rarity.IsBlue, Item.Rarity.IsPurple,
                  Item.Rarity.IsGold, Item.Rarity.IsGreen)
        got = False
        for index in filter.rarities:
            try:
                if 0 <= int(index) < len(checks) and checks[int(index)](item_id):
                    got = True
                    break
            except Exception:
                continue
        results.append(("rarity", got))

    if filter.name_contains:
        # `contains` is the other half of the closed operator set, and it applies to names only.
        #
        # A ground item's name decodes ASYNCHRONOUSLY -- it is not there on the first frame or two
        # per item kind. So request it, and while it is not ready report the criterion as not
        # passing rather than guessing: a drop is re-evaluated every frame, so it starts matching
        # the moment the name arrives.
        try:
            if Item.IsNameReady(item_id):
                name = (Item.GetName(item_id) or "").lower()
            else:
                Item.RequestName(item_id)
                name = ""
        except Exception:
            name = ""
        results.append(("name contains %s" % " / ".join(filter.name_contains),
                        bool(name) and any(part.lower() in name for part in filter.name_contains)))

    if filter.dye_colors:
        # Dyes are identified by ITEM TYPE plus colour -- every dye shares one model id.
        from ..loot_filters import dyes as dye_data

        results.append(("dye colour",
                        dye_data.is_dye(item_id) and dye_data.color_of(item_id) in filter.dye_colors))

    if filter.salvages_into:
        from ..loot_filters import materials as material_data

        if model_id is None:
            model_id = Item.GetModelID(item_id)
        targets = material_data.salvage_targets(int(model_id))
        results.append(("salvages into", any(m in filter.salvages_into for m in targets)))

    # -- the mod criteria, all three routed through the MOTHER MODULE --
    #
    # `Item.Mods.HasMod(item_id, mod, *values)` already does exactly what is needed:
    #   "an enum arg = a subtype filter; a number = a value threshold ('N or better',
    #    direction from the mod's metadata)"
    # So the direction is never chosen here -- `Requirement` carries better_low=True and the
    # comparison flips itself. Hand-rolling these comparisons is what lost the direction and the
    # range in the first place.

    if filter.max_requirement is not None:
        args: list = [filter.max_requirement]
        if filter.requirement_attribute is not None:
            try:
                from Py4GWCoreLib.enums import Attribute

                args.append(Attribute(filter.requirement_attribute))   # an enum arg = subtype filter
            except Exception:
                pass
        try:
            from Py4GWCoreLib.mods_types import ModifierIdentifier

            ok = bool(Item.Mods.HasMod(item_id, ModifierIdentifier.AttributeRequirement, *args))
        except Exception:
            ok = False
        results.append(("requirement %d or lower" % filter.max_requirement, ok))

    if filter.min_damage is not None:
        # Damage is a RANGE: `value_of` returns [arg2, arg1] = [low, high]. The top end is the
        # number the game shows ("Chaos Dmg: 11-21"), so that is what is compared.
        # `GetValues` is declarative -- the old lambda pair handed callables to `HasMod`, which
        # rejects them, so this criterion could never pass.
        try:
            from Py4GWCoreLib.mods_types import ModifierIdentifier

            values = Item.Mods.GetValues(item_id, ModifierIdentifier.Damage)
            ok = bool(values) and int(values[-1]) >= int(filter.min_damage)
        except Exception:
            ok = False
        results.append(("damage %d or better" % filter.min_damage, ok))

    if filter.damage_types:
        try:
            from Py4GWCoreLib.enums import DamageType
            from Py4GWCoreLib.mods_types import ModifierIdentifier

            ok = any(Item.Mods.HasMod(item_id, ModifierIdentifier.DamageTypeProperty, DamageType(d))
                     for d in filter.damage_types)
        except Exception:
            ok = False
        results.append(("damage type", ok))

    if filter.min_value is not None:
        try:
            value = int(Item.Properties.GetValue(item_id) or 0)
        except Exception:
            value = 0
        # Match-or-better, because higher is better for value.
        results.append(("worth %d or more" % filter.min_value, value >= filter.min_value))

    for criterion in filter.modifiers:
        results.append((_modifier_label(criterion), _modifier_matches(item_id, criterion)))

    for criterion in filter.upgrades:
        results.append((_upgrade_label(criterion), _upgrade_matches(item_id, criterion)))

    if not results:
        return False, results
    passed = [ok for _label, ok in results]
    verdict = any(passed) if filter.mode == MATCH_ANY else all(passed)
    return verdict, results


def matches(filter: Filter, item_id: int, model_id: int | None = None) -> bool:
    if filter.is_empty():
        return False
    return evaluate(filter, item_id, model_id)[0]


def any_match(filters, item_id: int, model_id: int | None = None) -> bool:
    """HAS-ANY: whether any enabled filter matches. Order is irrelevant here."""
    for f in filters:
        if f.enabled and matches(f, item_id, model_id):
            return True
    return False


def matching_filters(filters, item_id: int, model_id: int | None = None) -> list[Filter]:
    """Every enabled filter that matches, in order."""
    return [f for f in filters if f.enabled and matches(f, item_id, model_id)]
