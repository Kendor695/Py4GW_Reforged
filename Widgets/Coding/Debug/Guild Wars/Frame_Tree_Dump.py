"""Live frame-tree capture as a plain dictionary.

No file I/O and no json - see AGENTS.md: json.load/json.dump/open() for data are
forbidden in project code. The capture is held in memory and exposed as
FRAME_TREE / FRAME_TREE_META for anything that wants to consume it.

Name tables come from Py4GWCoreLib.FrameTree.frame_names (dict literals).
"""

import PyImGui

from Py4GWCoreLib import UIManager
from Py4GWCoreLib.FrameTree import Frame, FrameId, FrameTree
from Py4GWCoreLib.enums_src.UI_enums import NumberPreference
from Py4GWCoreLib.FrameTree.frame_names import (
    FRAME_NAMES_CONFIRMED,
    FRAME_NAMES_OBSERVED,
)

MODULE_NAME = "Frame Tree Dump"

# ---- capture, as dictionaries ------------------------------------------
FRAME_TREE: dict[int, dict] = {}      # frame_id -> node
FRAME_TREE_META: dict[str, int] = {}  # counts
FRAME_ROOTS: list[int] = []
UNKNOWN_HASHES: list[dict] = []       # hashed frames with no name

status_text = "Ready - press Dump Frame Tree"
FILTERS = ("All", "Named", "Unknown hashed")
filter_mode = 0
_keep: set[int] = set()

_XUNLAI_CONTENT_CODES = {i: ("Content" if i == 0 else "Content%d" % (i + 1))
                          for i in range(15)}
_XUNLAI_TAB_CODES = {
    (0xFFFFFFFF - i) & 0xFFFFFFFF: "Tab%d" % (i + 1)
    for i in range(14)
}
_XUNLAI_TAB_CODES[(0xFFFFFFFF - 14) & 0xFFFFFFFF] = "TabMaterialStorage"


def classify(h: int) -> tuple[str, str]:
    """-> (name, src) with src in 'confirmed' | 'observed' | 'unknown' | ''."""
    if not h:
        return "", ""
    name = FRAME_NAMES_CONFIRMED.get(h)
    if name:
        return name, "confirmed"
    name = FRAME_NAMES_OBSERVED.get(h)
    if name:
        return name, "observed"
    return "", "unknown"


def build_frame_tree() -> dict[int, dict]:
    """Walk the live tree and return {frame_id: node}. Also refreshes globals."""
    global FRAME_TREE, FRAME_TREE_META, FRAME_ROOTS, UNKNOWN_HASHES

    frames = {f.frame_id: f for f in FrameTree.all_frames()}

    children: dict[int, list[int]] = {}
    roots: list[int] = []
    for fid, fr in frames.items():
        pid = fr.parent_id
        children.setdefault(pid, []).append(fid)
        if pid == 0 or pid not in frames:
            roots.append(fid)
    for pid in children:
        children[pid].sort()
    roots.sort()

    tree: dict[int, dict] = {}
    for fid, fr in frames.items():
        h = fr.hash
        name, src = classify(h)
        tree[fid] = {
            "id": fid,
            "parent": fr.parent_id,
            "code": fr.code,
            "hash": h,
            "name": name,
            "src": src,
            "children": [k for k in children.get(fid, []) if k in frames],
        }

    FRAME_TREE = tree
    FRAME_ROOTS = roots
    FRAME_TREE_META = {
        "frames": len(tree),
        "leaves": sum(1 for n in tree.values() if not n["children"]),
        "hashed": sum(1 for n in tree.values() if n["hash"]),
        "confirmed": sum(1 for n in tree.values() if n["src"] == "confirmed"),
        "observed": sum(1 for n in tree.values() if n["src"] == "observed"),
        "unknown": sum(1 for n in tree.values() if n["src"] == "unknown"),
    }
    UNKNOWN_HASHES = [
        {"hash": n["hash"], "id": n["id"], "code": n["code"], "path": ancestry(n["id"])}
        for n in tree.values() if n["src"] == "unknown"
    ]
    _rebuild_keep()
    return tree


def ancestry(fid: int) -> str:
    """Readable chain from the nearest named ancestor down to this frame."""
    chain, cur, seen = [], fid, set()
    while cur and cur not in seen:
        seen.add(cur)
        n = FRAME_TREE.get(cur)
        if n is None:
            break
        chain.append(n)
        if cur != fid and n["name"]:
            break
        cur = n["parent"]
    chain.reverse()
    return " -> ".join(
        (n["name"] if (i == 0 and n["name"]) else str(n["code"]))
        for i, n in enumerate(chain)
    )


# ---- drawing -----------------------------------------------------------
def _match(n: dict) -> bool:
    if filter_mode == 1:
        return bool(n["name"])
    if filter_mode == 2:
        return n["src"] == "unknown"
    return True


def _rebuild_keep() -> None:
    global _keep
    _keep = set()

    def visit(fid, seen):
        if fid in seen:
            return False
        seen.add(fid)
        n = FRAME_TREE.get(fid)
        if n is None:
            return False
        hit = _match(n)
        for k in n["children"]:
            if visit(k, seen):
                hit = True
        if hit:
            _keep.add(fid)
        return hit

    seen: set[int] = set()
    for r in FRAME_ROOTS:
        visit(r, seen)


def _label(n: dict) -> str:
    s = "#%d  code=%d" % (n["id"], n["code"])
    if n["hash"]:
        if n["src"] == "confirmed":
            s += "   %s" % n["name"]
        elif n["src"] == "observed":
            s += "   ~%s" % n["name"]
        else:
            s += "   ? UNKNOWN hash=%d" % n["hash"]
    return s


def _color(n: dict) -> tuple[float, float, float, float]:
    if n["src"] == "confirmed":
        return (0.50, 0.92, 0.50, 1.0)
    if n["src"] == "observed":
        return (0.92, 0.86, 0.42, 1.0)
    if n["src"] == "unknown":
        return (0.95, 0.45, 0.45, 1.0)
    return (0.62, 0.62, 0.62, 1.0)


def _frame_rect(frame) -> str:
    """Return a compact rectangle without allowing one bad frame to abort the dump."""
    try:
        pos = frame.position
        return "L%s T%s R%s B%s" % (
            pos.left_on_screen,
            pos.top_on_screen,
            pos.right_on_screen,
            pos.bottom_on_screen,
        )
    except Exception as exc:
        return "<unavailable: %s>" % exc


def _frame_dump_line(frame, label: str, depth: int) -> str:
    """Describe one live frame using only the FrameTree public inspection surface."""
    indent = "  " * depth
    frame_id = int(getattr(frame, "frame_id", 0) or 0)
    parent_id = int(getattr(frame, "parent_id", 0) or 0)
    code = int(getattr(frame, "code", 0) or 0)
    unsigned_code = code & 0xFFFFFFFF
    frame_hash = int(getattr(frame, "hash", 0) or 0)
    name = str(getattr(frame, "name", "") or "")
    try:
        runtime_path = frame.path()
    except Exception:
        runtime_path = ""
    return (
        "%s%s id=%d parent=%d code=%d (0x%08X) hash=%d "
        "created=%s visible=%s rect=[%s] path=%s name=%s"
        % (
            indent,
            label,
            frame_id,
            parent_id,
            code,
            unsigned_code,
            frame_hash,
            bool(getattr(frame, "is_created", False)),
            bool(getattr(frame, "is_visible", False)),
            _frame_rect(frame),
            runtime_path or "<none>",
            name or "<anonymous>",
        )
    )


def _print_frame_subtree(fid: int, depth: int, seen: set[int]) -> None:
    """Print one captured subtree in native child-code order."""
    if fid in seen:
        print("%s<cycle to frame %d>" % ("  " * depth, fid))
        return
    seen.add(fid)

    node = FRAME_TREE.get(fid)
    if node is None:
        print("%s<missing frame id=%d>" % ("  " * depth, fid))
        return

    try:
        frame = Frame.from_id(fid)
    except Exception as exc:
        print("%s<frame id=%d unavailable: %s>" % ("  " * depth, fid, exc))
        return

    code = int(getattr(frame, "code", 0) or 0) & 0xFFFFFFFF
    label = (
        _XUNLAI_CONTENT_CODES.get(code, _XUNLAI_TAB_CODES.get(code, "UNMAPPED"))
        if depth == 1 else "child"
    )
    print(_frame_dump_line(frame, label, depth))
    for child_id in node["children"]:
        _print_frame_subtree(child_id, depth + 1, seen)


def print_xunlai_diagnostics() -> None:
    """Print the evidence needed to correlate Xunlai tabs with storage bags."""
    print("=== Frame Tree Dump: Xunlai diagnostics ===")
    print("captured_frames=%d roots=%d" % (len(FRAME_TREE), len(FRAME_ROOTS)))

    try:
        storage_page = int(UIManager.GetIntPreference(NumberPreference.StorageBagPage.value))
        print("native StorageBagPage preference=%d" % storage_page)
        if 0 <= storage_page <= 14:
            page_name = ("Storage%d" % (storage_page + 1)
                         if storage_page < 14 else "MaterialStorage")
            print("native StorageBagPage interpreted_as=%s" % page_name)
        else:
            print("native StorageBagPage interpreted_as=<outside expected 0..14 range>")
    except Exception as exc:
        print("native StorageBagPage unavailable: %s" % exc)

    storage_candidates: list[int] = []
    try:
        storage_id = int(Frame(FrameId.XunlaiWindow.StorageFrame).frame_id)
        if storage_id in FRAME_TREE:
            storage_candidates.append(storage_id)
    except Exception as exc:
        print("registry StorageFrame resolution failed: %s" % exc)

    if not storage_candidates:
        print("XunlaiWindow.StorageFrame: <not found in captured tree>")
        print("=== End Xunlai diagnostics ===")
        return

    for storage_id in storage_candidates:
        storage_frame = Frame.from_id(storage_id)
        print(_frame_dump_line(storage_frame, "StorageFrame", 0))
        child_ids = FRAME_TREE[storage_id]["children"]
        print("StorageFrame direct_children=%d" % len(child_ids))
        for child_id in child_ids:
            child_node = FRAME_TREE.get(child_id)
            if child_node is None:
                print("  <missing child id=%d>" % child_id)
                continue
            child = Frame.from_id(child_id)
            code = int(getattr(child, "code", 0) or 0) & 0xFFFFFFFF
            role = _XUNLAI_CONTENT_CODES.get(code,
                    _XUNLAI_TAB_CODES.get(code, "UNMAPPED"))
            print(_frame_dump_line(child, "direct_child role=%s" % role, 1))

        print("StorageFrame recursive_subtrees:")
        seen: set[int] = set()
        for child_id in child_ids:
            _print_frame_subtree(child_id, 1, seen)

    print("=== End Xunlai diagnostics ===")


def _print_salvage_frame(label: str, frame) -> None:
    """Print one relevant live salvage frame without assuming its registry alias still resolves."""
    try:
        frame_id = int(getattr(frame, "frame_id", 0) or 0)
        if frame_id <= 0:
            print("%s: <no live frame>" % label)
            return
        print(_frame_dump_line(frame, label, 0))
    except Exception as exc:
        print("%s: <unavailable: %s>" % (label, exc))


def print_salvage_diagnostics() -> None:
    """Print the dialog probes used by automatic Salvage; read-only by design."""
    print("=== Frame Tree Dump: Salvage diagnostics ===")
    print("captured_frames=%d roots=%d" % (len(FRAME_TREE), len(FRAME_ROOTS)))
    try:
        from Py4GWCoreLib.Inventory import Inventory

        dialog = Inventory._salvage_dialog()
        options = Inventory._salvage_option_container()
        confirm = Inventory._salvage_confirm()
        print("generic IsSalvageChoiceDialogVisible=%s" % Inventory.IsSalvageChoiceDialogVisible())
        _print_salvage_frame("generic dialog", dialog)
        _print_salvage_frame("generic option container", options)
        _print_salvage_frame("generic confirm", confirm)

        visible_entries = Inventory._build_visible_frame_entry_map()
        parent_id, children, entries = Inventory._get_salvage_choice_dialog_options(visible_entries)
        print("generic option parent=%d direct_children=%d selectable_options=%d" % (
            int(parent_id), len(children), len(entries),
        ))
        for entry in entries:
            print(
                "  selectable frame_id=%d parent=%d code=%d template=%d rect=[%.1f,%.1f %.1fx%.1f]"
                % (
                    int(entry.get("frame_id", 0)),
                    int(entry.get("parent_id", 0)),
                    int(entry.get("offset", -1)),
                    int(entry.get("template_type", -1)),
                    float(entry.get("left", 0.0)),
                    float(entry.get("top", 0.0)),
                    float(entry.get("width", 0.0)),
                    float(entry.get("height", 0.0)),
                )
            )
        dialog_id = int(getattr(dialog, "frame_id", 0) or 0)
        if dialog_id in FRAME_TREE:
            print("generic dialog subtree:")
            _print_frame_subtree(dialog_id, 0, set())
    except Exception as exc:
        print("generic salvage probe failed: %s" % exc)

    try:
        from Sources.frenkeyLib.ItemHandling.UIManagerExtensions import UIManagerExtensions

        print("legacy IsSalvageWindowOpen=%s" % UIManagerExtensions.IsSalvageWindowOpen())
        legacy_options = UIManagerExtensions.GetSalvageOptions()
        print("legacy option mappings=%s" % {
            getattr(mode, "name", str(mode)): int(frame.frame_id)
            for mode, frame in legacy_options.items()
        })
        for label, frame_key in (
            ("Option1 / Prefix", FrameId.SalvageWindow.Options.Option1),
            ("Option2 / Suffix", FrameId.SalvageWindow.Options.Option2),
            ("Option3 / Inscription", FrameId.SalvageWindow.Options.Option3),
            ("Option4 / Materials", FrameId.SalvageWindow.Options.Option4),
        ):
            _print_salvage_frame("legacy %s" % label, Frame(frame_key))
    except Exception as exc:
        print("legacy salvage probe failed: %s" % exc)
    print("=== End Salvage diagnostics ===")


def draw_node(fid: int, seen: set) -> None:
    if fid in seen:
        return
    seen.add(fid)
    n = FRAME_TREE.get(fid)
    if n is None or (filter_mode and fid not in _keep):
        return

    kids = n["children"]
    if filter_mode:
        kids = [k for k in kids if k in _keep]

    if not kids:
        r, g, b, a = _color(n)
        PyImGui.text_colored(r, g, b, a, _label(n))
        return

    if PyImGui.tree_node("%s##%d" % (_label(n), fid)):
        for k in kids:
            draw_node(k, seen)
        PyImGui.tree_pop()


def configure() -> None:
    pass


def main() -> None:
    global status_text, filter_mode

    if PyImGui.begin(MODULE_NAME):
        if PyImGui.button("Dump Frame Tree"):
            try:
                build_frame_tree()
                status_text = "Captured %d frames" % FRAME_TREE_META["frames"]
            except Exception as exc:
                status_text = "Dump failed: %s" % exc
        PyImGui.same_line(0, -1)
        if PyImGui.button("Filter: %s" % FILTERS[filter_mode]):
            filter_mode = (filter_mode + 1) % len(FILTERS)
            _rebuild_keep()
        PyImGui.same_line(0, -1)
        if PyImGui.button("Print Xunlai Diagnostics"):
            try:
                build_frame_tree()
                print_xunlai_diagnostics()
                status_text = "Printed Xunlai diagnostics to the runtime console"
            except Exception as exc:
                status_text = "Xunlai diagnostic failed: %s" % exc
        PyImGui.same_line(0, -1)
        if PyImGui.button("Print Salvage Diagnostics"):
            try:
                build_frame_tree()
                print_salvage_diagnostics()
                status_text = "Printed Salvage diagnostics to the runtime console"
            except Exception as exc:
                status_text = "Salvage diagnostic failed: %s" % exc

        PyImGui.text(status_text)
        PyImGui.text("names: confirmed=%d  observed=%d"
                     % (len(FRAME_NAMES_CONFIRMED), len(FRAME_NAMES_OBSERVED)))
        if FRAME_TREE_META:
            PyImGui.text("frames=%(frames)d  hashed=%(hashed)d  |  confirmed=%(confirmed)d  "
                         "observed=%(observed)d  UNKNOWN=%(unknown)d" % FRAME_TREE_META)
        if UNKNOWN_HASHES:
            PyImGui.text_colored(0.95, 0.45, 0.45, 1.0,
                                 "%d hashed frames have no name" % len(UNKNOWN_HASHES))
        PyImGui.separator()

        if FRAME_TREE:
            seen: set[int] = set()
            for r in FRAME_ROOTS:
                draw_node(r, seen)
        else:
            PyImGui.text("No tree captured.")

    PyImGui.end()


if __name__ == "__main__":
    main()
