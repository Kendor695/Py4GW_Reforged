"""Offline fixture for the loot filter matcher's damage criterion (filter-structure contract, T4).

The defect: ``min_damage`` handed lambdas to ``Item.Mods.HasMod``, which rejects callables, so
"Damage at least" could never match. The fix compares the damage range's TOP end through the
declarative ``Item.Mods.GetValues``. This fixture runs WITHOUT the injected client: the factory
modules are loaded directly from source and ``Py4GWCoreLib.Item`` / ``mods_types`` are stubbed
with canned values. The stub's ``HasMod`` raises on callables, so a regression to the lambda
path fails loudly instead of silently returning False.

Run:  python "Examples and tests/tests/test_loot_filter_matcher.py"
Exit code 1 on any failure.
"""

import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
FACTORY_DIR = ROOT / "Py4GWCoreLib" / "py4gwcorelib_src" / "system_settings" / "loot_filter_factory"


def _load_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None, "could not build a module spec for %s" % path
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "_lff"   # relative imports inside the factory resolve against this stub
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Load the factory model/matcher without importing Py4GWCoreLib (which needs the client).
_pkg = types.ModuleType("_lff")
_pkg.__path__ = []
sys.modules["_lff"] = _pkg
model = _load_module("_lff.model", FACTORY_DIR / "model.py")
matcher = _load_module("_lff.matcher", FACTORY_DIR / "matcher.py")

# Canned item state: damage ranges are [low, high] (arg2, arg1), exactly as mods_core.value_of
# returns them. Item 5 has no damage mod; 6 carries a value for the composition cases.
_DAMAGE = {1: [11, 21], 2: [11, 21], 3: [11, 21], 4: [11, 21], 6: [11, 21], 7: [11, 21]}
_VALUES = {6: 750, 7: 100}


class _FakeModifierIdentifier:
    Damage = 1
    AttributeRequirement = 2
    SunderingEffect = 3


class _FakeMods:
    @staticmethod
    def GetValues(item_id, mod):
        return list(_DAMAGE.get(int(item_id), []))

    @staticmethod
    def HasMod(item_id, mod, *values):
        # Mirrors the real Item.Mods.HasMod contract: callables are rejected. The whole point
        # of this fixture is that the matcher must not depend on that path.
        if any(callable(value) for value in values):
            raise TypeError("Item.Mods.HasMod accepts declarative subtype and numeric threshold values only")
        return int(item_id) == 8 and int(mod) == 3

    @staticmethod
    def GetSubtype(item_id, mod):
        return 7 if int(item_id) == 8 and int(mod) == 3 else None

    @staticmethod
    def GetUpgrades(item_id):
        if int(item_id) in (9, 10):
            return [("Sundering", 1)]
        if int(item_id) == 11:
            return [("RuneOfMinorVigor2", 5)]
        return []

    @staticmethod
    def IsMaxed(item_id, name):
        return int(item_id) == 10 and str(name) == "Sundering"


class _FakeItem:
    Mods = _FakeMods

    class Properties:
        @staticmethod
        def GetValue(item_id):
            return _VALUES.get(int(item_id), 0)


_item_module = types.ModuleType("Py4GWCoreLib.Item")
setattr(_item_module, "Item", _FakeItem)
sys.modules["Py4GWCoreLib.Item"] = _item_module
_mods_module = types.ModuleType("Py4GWCoreLib.mods_types")
setattr(_mods_module, "ModifierIdentifier", _FakeModifierIdentifier)
sys.modules["Py4GWCoreLib.mods_types"] = _mods_module

# (label, filter, item_id, expected verdict, expected breakdown)
CASES = [
    ("top of range beats the minimum", model.Filter(min_damage=15), 1, True,
     [("damage 15 or better", True)]),
    ("top end exactly meets the minimum", model.Filter(min_damage=21), 2, True,
     [("damage 21 or better", True)]),
    ("above the top end never matches", model.Filter(min_damage=22), 3, False,
     [("damage 22 or better", False)]),
    # Discriminates top-end vs low-end comparison: the LOW end is 11, so comparing against it
    # would wrongly fail this. Only the top end (21) may answer.
    ("the TOP end answers, not the low end", model.Filter(min_damage=13), 4, True,
     [("damage 13 or better", True)]),
    ("no damage mod means no match", model.Filter(min_damage=15), 5, False,
     [("damage 15 or better", False)]),
    ("ALL mode: both criteria pass", model.Filter(min_damage=13, min_value=500), 6, True,
     [("damage 13 or better", True), ("worth 500 or more", True)]),
    ("ALL mode: one criterion fails", model.Filter(min_damage=13, min_value=500), 7, False,
     [("damage 13 or better", True), ("worth 500 or more", False)]),
    ("ANY mode: one pass is enough", model.Filter(mode=model.MATCH_ANY, min_damage=13, min_value=500), 7,
     True, [("damage 13 or better", True), ("worth 500 or more", False)]),
    ("full modifier criterion uses Item.Mods", model.Filter(
        modifiers=(model.ModifierCriterion(3, subtype=7),)), 8, True,
     [("modifier 3 [7]", True)]),
    ("named upgrade matches its physical slot", model.Filter(
        upgrades=(model.UpgradeCriterion("Sundering", slot=1),)), 9, True,
     [("upgrade Sundering (slot 1)", True)]),
    ("named upgrade maxed check is declarative", model.Filter(
        upgrades=(model.UpgradeCriterion("Sundering", slot=1, maxed=True),)), 10, True,
     [("upgrade Sundering (slot 1) (maxed)", True)]),
    ("Minor Vigor alias matches canonical name", model.Filter(
        upgrades=(model.UpgradeCriterion("RuneOfMinorVigor"),)), 11, True,
     [("upgrade RuneOfMinorVigor", True)]),
    ("saved Minor Vigor alias remains compatible", model.Filter(
        upgrades=(model.UpgradeCriterion("RuneOfMinorVigor2"),)), 11, True,
     [("upgrade RuneOfMinorVigor2", True)]),
]

failures = 0
for label, candidate, item_id, expected_verdict, expected_breakdown in CASES:
    verdict, breakdown = matcher.evaluate(candidate, item_id)
    ok = verdict == expected_verdict and breakdown == expected_breakdown
    if not ok:
        failures += 1
    print("[%s] %s" % ("PASS" if ok else "FAIL", label))
    if not ok:
        print("      filter:   %s" % candidate)
        print("      expected: verdict=%s breakdown=%s" % (expected_verdict, expected_breakdown))
        print("      observed: verdict=%s breakdown=%s" % (verdict, breakdown))

round_trip = model.Filter(
    mode=model.MATCH_ALL,
    modifiers=(model.ModifierCriterion(3, subtype=7, values=(9,)),),
    upgrades=(model.UpgradeCriterion("Sundering", slot=1, maxed=True),),
)
round_trip_ok = model.Filter.from_dict(round_trip.to_dict()) == round_trip
print("[%s] full Item.Mods criteria survive persistence" % ("PASS" if round_trip_ok else "FAIL"))
if not round_trip_ok:
    failures += 1

print("=" * 68)
print("%d case(s) failed" % failures)
sys.exit(1 if failures else 0)
