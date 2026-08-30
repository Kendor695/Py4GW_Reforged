"""Offline regression for exact Item.Mods-slot salvage selection.

Automatic Salvage may extract only the slot occupied by the named upgrade that matched a
Keep List filter.  It must not choose a different component merely because it is also present.

Run:  python "Examples and tests/tests/test_salvage_upgrade_slot.py"
Exit code 1 on any failure.
"""

from enum import IntEnum
import importlib.util
import pathlib
import sys
import types


ROOT = pathlib.Path(__file__).resolve().parents[2]
SALVAGE_DIR = ROOT / "Py4GWCoreLib" / "py4gwcorelib_src" / "system_settings" / "salvage"
FACTORY_DIR = ROOT / "Py4GWCoreLib" / "py4gwcorelib_src" / "system_settings" / "loot_filter_factory"


def package(name: str) -> None:
    module = types.ModuleType(name)
    module.__path__ = []
    sys.modules[name] = module


def module(name: str, **values) -> None:
    value = types.ModuleType(name)
    for key, entry in values.items():
        setattr(value, key, entry)
    sys.modules[name] = value


def load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None, "could not load %s" % path
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


for package_name in (
    "Py4GWCoreLib",
    "Py4GWCoreLib.routines_src",
    "Py4GWCoreLib.routines_src.behaviourtrees_src",
    "Py4GWCoreLib.enums_src",
    "Py4GWCoreLib.py4gwcorelib_src",
    "Py4GWCoreLib.py4gwcorelib_src.system_settings",
    "Py4GWCoreLib.py4gwcorelib_src.system_settings.inventory",
    "Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filter_factory",
    "Py4GWCoreLib.py4gwcorelib_src.system_settings.salvage",
):
    package(package_name)


class SalvageMode(IntEnum):
    NONE = 0
    LesserCraftingMaterials = 1
    RareCraftingMaterials = 2
    Prefix = 3
    Suffix = 4
    Inscription = 5


class Slot(IntEnum):
    Prefix = 1
    Suffix = 2
    Inscription = 3


class FakeMods:
    Slot = Slot
    upgrades: dict[int, list[tuple[str, Slot]]] = {}

    @classmethod
    def GetUpgrades(cls, item_id: int) -> list[tuple[str, Slot]]:
        return list(cls.upgrades.get(int(item_id), []))

    @staticmethod
    def IsMaxed(item_id: int, name: str) -> bool:
        return True


class FakeItem:
    Mods = FakeMods


class FakeLease:
    def is_available(self, _owner: str) -> bool:
        return True

    def acquire(self, _owner: str) -> bool:
        return True

    def release(self, _owner: str) -> None:
        return None

    def owner(self) -> str:
        return ""


setattr(sys.modules["Py4GWCoreLib"], "ThrottledTimer", object)
module("Py4GWCoreLib.Item", Item=FakeItem)
module(
    "Py4GWCoreLib.Inventory",
    Inventory=types.SimpleNamespace(IsSalvageChoiceDialogVisible=lambda: False),
)
module("Py4GWCoreLib.routines_src.BehaviourTrees", BT=object)
module(
    "Py4GWCoreLib.routines_src.behaviourtrees_src.items",
    scan_salvage_kits=lambda *_args, **_kwargs: [],
    select_salvage_kit=lambda *_args, **_kwargs: None,
)
module("Py4GWCoreLib.enums_src.Item_enums", INVENTORY_BAGS=(), SalvageMode=SalvageMode)
module(
    "Py4GWCoreLib.py4gwcorelib_src.system_settings.item_runtime",
    StableMapGate=object,
    get_item_operation_lease=lambda: FakeLease(),
)
module("Py4GWCoreLib.py4gwcorelib_src.system_settings.inventory.store", load_bags=lambda: None)
module("Py4GWCoreLib.py4gwcorelib_src.system_settings.inventory.model", BAGS=())
module("Py4GWCoreLib.py4gwcorelib_src.system_settings.inventory.monitor", InventoryMonitor=object)
module("Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filter_factory.matcher", matching_filters=lambda *_args: [])
factory_model = load(
    "Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filter_factory.model",
    FACTORY_DIR / "model.py",
)
module("Py4GWCoreLib.py4gwcorelib_src.system_settings.salvage.store", load=lambda: None)
module("Py4GWCoreLib.py4gwcorelib_src.system_settings.salvage.model", SalvageSettings=object)
controller = load(
    "Py4GWCoreLib.py4gwcorelib_src.system_settings.salvage.controller",
    SALVAGE_DIR / "controller.py",
)

Filter = factory_model.Filter
UpgradeCriterion = factory_model.UpgradeCriterion
Controller = controller.SalvageController

failures = 0


def check(label: str, expected, observed) -> None:
    global failures
    ok = expected == observed
    if not ok:
        failures += 1
    print("[%s] %s" % ("PASS" if ok else "FAIL", label))
    if not ok:
        print("      expected: %r" % (expected,))
        print("      observed: %r" % (observed,))


rune_filter = Filter(upgrades=(UpgradeCriterion("RangerRuneOfSuperiorMarksmanship"),))
FakeMods.upgrades[10] = [
    ("RangerInsignia", Slot.Prefix),
    ("RangerRuneOfSuperiorMarksmanship", Slot.Suffix),
]
check(
    "matching rune selects its Suffix slot instead of the insignia Prefix slot",
    SalvageMode.Suffix,
    Controller._matched_upgrade_salvage_mode(10, [rune_filter]),
)

FakeMods.upgrades[11] = [("RangerRuneOfSuperiorMarksmanship", Slot.Suffix)]
check(
    "the same rune remains a Suffix after the Prefix component is gone",
    SalvageMode.Suffix,
    Controller._matched_upgrade_salvage_mode(11, [rune_filter]),
)

wrong_slot_filter = Filter(upgrades=(UpgradeCriterion("RangerRuneOfSuperiorMarksmanship", slot=int(Slot.Prefix)),))
check(
    "a rule constrained to the wrong slot cannot request extraction",
    None,
    Controller._matched_upgrade_salvage_mode(11, [wrong_slot_filter]),
)

action = Controller._upgrade_action(SalvageMode.Suffix)
check("candidate preserves the exact matched slot", SalvageMode.Suffix, Controller._salvage_mode(None, 11, action))


class FakeTimer:
    def IsStopped(self) -> bool:
        return False

    def Start(self) -> None:
        return None

    def IsExpired(self) -> bool:
        return False

    def GetTimeElapsed(self) -> int:
        return 0


def drain_one_pulse(map_context: tuple[int, bool, bool], outpost_pass_pending: bool) -> list[int]:
    """Drive two completion frames without a second timer expiry."""
    instance = object.__new__(Controller)
    instance._map_context = lambda: map_context
    instance._timer = FakeTimer()
    instance._last_map_id = map_context[0]
    instance._outpost_pass_pending = outpost_pass_pending
    instance._active_item_id = 0
    instance._settings = types.SimpleNamespace(enabled=True)
    instance._pending_candidates = [(101, "materials"), (102, "materials")]
    instance._trace_execution = lambda *_args, **_kwargs: None
    instance._clear_active = lambda: None
    started: list[int] = []
    instance._start_salvage = lambda item_id, _mode: started.append(item_id) or True

    Controller._pass(instance)
    Controller._pass(instance)
    return started


check(
    "one explorable timer pulse drains every queued eligible item serially",
    [101, 102],
    drain_one_pulse((1, True, False), False),
)
check(
    "one outpost entry pulse drains every queued eligible item serially",
    [101, 102],
    drain_one_pulse((1, False, True), False),
)

print("=" * 68)
print("%d case(s) failed" % failures)
sys.exit(1 if failures else 0)
