"""Offline coverage for feature-owned Salvage Keep List checkbox persistence.

The Salvage Keep List is direct account-owned checkbox state.  It must not create, stage,
or attach advanced filter definitions.  This fixture loads the real model/store with an
in-memory JsonFactory and verifies malformed reads plus the one-time, narrow migration of
the former generated Keep List entries.

Run:  python "Examples and tests/tests/test_salvage_keep_list.py"
Exit code 1 on any failure.
"""

import importlib.util
import pathlib
import sys
import types


ROOT = pathlib.Path(__file__).resolve().parents[2]
SALVAGE_DIR = ROOT / "Py4GWCoreLib" / "py4gwcorelib_src" / "system_settings" / "salvage"
FACTORY_DIR = ROOT / "Py4GWCoreLib" / "py4gwcorelib_src" / "system_settings" / "loot_filter_factory"


def _package(name: str) -> None:
    package = types.ModuleType(name)
    package.__path__ = []
    sys.modules[name] = package


for _name in (
    "Py4GWCoreLib",
    "Py4GWCoreLib.py4gwcorelib_src",
    "Py4GWCoreLib.py4gwcorelib_src.system_settings",
    "Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filter_factory",
    "Py4GWCoreLib.py4gwcorelib_src.system_settings.salvage",
):
    _package(_name)


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None, "could not load %s" % path
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeJsonFactory:
    """Small account/global document fake used by the Salvage store."""

    docs: dict[tuple[str, str], dict] = {}

    def __init__(self, path: str, scope: str):
        self.data = self.docs.setdefault((str(path), str(scope)), {})

    def get_json(self, key: str, default=None):
        return self.data.get(key, default)

    def set_json(self, key: str, value) -> None:
        self.data[key] = value


json_module = types.ModuleType("Py4GWCoreLib.py4gwcorelib_src.JsonFactory")
setattr(json_module, "JsonFactory", FakeJsonFactory)
sys.modules["Py4GWCoreLib.py4gwcorelib_src.JsonFactory"] = json_module

factory_model = _load(
    "Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filter_factory.model",
    FACTORY_DIR / "model.py",
)
salvage_model = _load(
    "Py4GWCoreLib.py4gwcorelib_src.system_settings.salvage.model",
    SALVAGE_DIR / "model.py",
)

# The store only needs the current catalog's stable display/type lookups for migration.
curated = types.ModuleType("Py4GWCoreLib.py4gwcorelib_src.system_settings.salvage.curated")
setattr(curated, "upgrade_groups", lambda: (("Runes", [
    ("Ranger Rune of Superior Marksmanship", "RangerRuneOfSuperiorMarksmanship"),
]),))
setattr(curated, "weapon_types", lambda: [("Axe", 2)])
setattr(curated, "item_type_groups", lambda: [("Weapons", [("Axe", 2)])])
sys.modules["Py4GWCoreLib.py4gwcorelib_src.system_settings.salvage.curated"] = curated
store = _load(
    "Py4GWCoreLib.py4gwcorelib_src.system_settings.salvage.store",
    SALVAGE_DIR / "store.py",
)

Filter = factory_model.Filter
FilterSet = factory_model.FilterSet
UpgradeCriterion = factory_model.UpgradeCriterion
CuratedKeepList = salvage_model.CuratedKeepList

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


parsed = CuratedKeepList.from_dict({
    "upgrades": "not a list",
    "item_types": ["bad", 2],
    "item_max_requirement": "bad",
    "model_ids": ["bad", 0, 123],
})
check("malformed direct checkbox document is safe", CuratedKeepList(item_types={2}, model_ids={123}), parsed)

legacy = Filter(
    id="generated",
    name="Keep Ranger Rune of Superior Marksmanship",
    upgrades=(UpgradeCriterion("RangerRuneOfSuperiorMarksmanship"),),
)
custom = Filter(
    id="custom",
    name="Keep My Private Rule",
    upgrades=(UpgradeCriterion("RangerRuneOfSuperiorMarksmanship"),),
)
filters_document = FakeJsonFactory.docs.setdefault((store.FILTERS_DOCUMENT, "account"), {})
filters_document["filters"] = [legacy.to_dict(), custom.to_dict()]
filters_document["filter_sets"] = [FilterSet("advanced", "Advanced", ("generated", "custom")).to_dict()]

check("only the old generated Keep List rule migrates", 1, store.migrate_legacy_keep_filters())
keep_document = FakeJsonFactory.docs[(store.KEEP_LIST_DOCUMENT, "account")]["keep_list"]
check("migration writes direct checkbox state", {"RangerRuneOfSuperiorMarksmanship"}, set(keep_document["upgrades"]))
active_ids = FakeJsonFactory.docs[(store.FILTERS_DOCUMENT, "account")]["filter_sets"][0]["filter_ids"]
check("migration removes only the generated rule from advanced membership", ["custom"], active_ids)
saved_filters = FakeJsonFactory.docs[(store.FILTERS_DOCUMENT, "account")]["filters"]
check("migration removes only the generated filter definition", ["custom"], [entry["id"] for entry in saved_filters])
check("migration is one-time after membership removal", 0, store.migrate_legacy_keep_filters())

print("=" * 68)
print("%d case(s) failed" % failures)
sys.exit(1 if failures else 0)
