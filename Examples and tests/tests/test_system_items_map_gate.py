"""Offline regression for the System Settings stable-map item barrier.

Run: python "Examples and tests/tests/test_system_items_map_gate.py"
Exit code 1 on any failure.
"""

import importlib.util
import pathlib
import sys
import types


ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNTIME_PATH = ROOT / "Py4GWCoreLib" / "py4gwcorelib_src" / "system_settings" / "item_runtime.py"


def package(name: str) -> None:
    value = types.ModuleType(name)
    value.__path__ = []
    sys.modules[name] = value


for package_name in (
    "Py4GWCoreLib",
    "Py4GWCoreLib.routines_src",
    "Py4GWCoreLib.py4gwcorelib_src",
    "Py4GWCoreLib.py4gwcorelib_src.system_settings",
):
    package(package_name)


class FakeMap:
    ready = True
    loading = False
    map_id = 1
    uptime = 0
    explorable = True
    outpost = False

    @classmethod
    def IsMapReady(cls) -> bool:
        return cls.ready

    @classmethod
    def IsMapLoading(cls) -> bool:
        return cls.loading

    @classmethod
    def GetInstanceUptime(cls) -> int:
        return cls.uptime

    @classmethod
    def GetMapID(cls) -> int:
        return cls.map_id

    @classmethod
    def IsExplorable(cls) -> bool:
        return cls.explorable

    @classmethod
    def IsOutpost(cls) -> bool:
        return cls.outpost


class FakeChecks:
    valid = True

    class Map:
        @staticmethod
        def MapValid() -> bool:
            return FakeChecks.valid


map_module = types.ModuleType("Py4GWCoreLib.Map")
setattr(map_module, "Map", FakeMap)
sys.modules[map_module.__name__] = map_module
checks_module = types.ModuleType("Py4GWCoreLib.routines_src.Checks")
setattr(checks_module, "Checks", FakeChecks)
sys.modules[checks_module.__name__] = checks_module

spec = importlib.util.spec_from_file_location(
    "Py4GWCoreLib.py4gwcorelib_src.system_settings.item_runtime", str(RUNTIME_PATH)
)
assert spec is not None and spec.loader is not None, "could not load item runtime barrier"
runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime
spec.loader.exec_module(runtime)

clock = [0.0]
runtime.time.monotonic = lambda: clock[0]
gate = runtime.StableMapGate()
failures = 0


def check(label: str, expected, observed) -> None:
    global failures
    if expected != observed:
        failures += 1
    print("[%s] %s" % ("PASS" if expected == observed else "FAIL", label))
    if expected != observed:
        print("      expected: %r" % (expected,))
        print("      observed: %r" % (observed,))


check("first valid frame observes the configured arrival delay", None, gate.context(2.0))
clock[0] = 1.999
check("configured arrival delay blocks inventory work", None, gate.context(2.0))
clock[0] = 2.0
check("configured arrival delay admits the stable valid map", (1, True, False), gate.context(2.0))

FakeMap.loading = True
check("loading immediately revokes an already admitted map", None, gate.context())
FakeMap.loading = False
FakeMap.map_id = 2
check("a new map must be observed again", None, gate.context(3.0))
clock[0] = 2.0
check("new map retains its own configured delay", None, gate.context(3.0))
clock[0] = 5.0
check("new stable map admits after its configured delay", (2, True, False), gate.context(3.0))

FakeChecks.valid = False
check("Checks.Map.MapValid remains a hard boundary", None, gate.context(0.0))

lease = runtime.get_item_operation_lease()
check("first operation acquires the native item lease", True, lease.acquire("identification"))
check("same operation can continue polling its lease", True, lease.acquire("identification"))
check("salvage cannot overlap active identification", False, lease.acquire("salvage"))
lease.release("salvage")
check("a non-owner cannot release active identification", "identification", lease.owner())
lease.release("identification")
check("salvage acquires the lease only after identification releases it", True, lease.acquire("salvage"))
lease.release("salvage")

print("=" * 68)
print("%d case(s) failed" % failures)
sys.exit(1 if failures else 0)
