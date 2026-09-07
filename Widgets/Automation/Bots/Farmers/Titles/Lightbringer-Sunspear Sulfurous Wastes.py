from Py4GWCoreLib import *
from Py4GWCoreLib.ImGui_src.ImGuisrc import ImGui
from Py4GWCoreLib.BottingTree import BottingTree
from Py4GWCoreLib.py4gwcorelib_src.BehaviorTree import BehaviorTree
from Py4GWCoreLib.routines_src.behaviourtrees_src.composite import BTComposite
from Py4GWCoreLib.routines_src.behaviourtrees_src.movement import BTMovement
from Py4GWCoreLib.routines_src.behaviourtrees_src.map import BTMap
from Py4GWCoreLib.routines_src.behaviourtrees_src.party import BTParty
from Py4GWCoreLib.routines_src.behaviourtrees_src.player import BTPlayer
from Py4GWCoreLib.routines_src.behaviourtrees_src.agents import BTAgents
from Py4GWCoreLib.routines_src.behaviourtrees_src.shared import BTShared
from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings
from Py4GWCoreLib.enums_src.Model_enums import ModelID
from Sources.ApoSource.ApoBottingLib import wrappers as BT
from Widgets.System.Messaging import get_inventory_state, reset_inventory_state
import PySystem
import PyImGui
import os
import time
import json
from dataclasses import dataclass
from typing import List, Dict, Optional, Callable

MODULE_NAME = "Lightbringer-Sunspear Sulfurous Wastes"
MODULE_ICON = "Assets/Textures/Skill_Icons/[1813] - Lightbringer.jpg"

_RANGE_AGGRO = Range.Earshot.value  # 1012 — OOC detection range for junundu fight nodes
_BLESSING_PRE_DIALOG_WAIT_MS = 8_000  # let every account arrive/settle before a multi-account dialog dispatch


class BotSettings:
    BOT_NAME             = "Lightbringer-Sunspear Sulfurous Wastes"
    # TODO: verify these map IDs in-game (from PyQuishAI TheSulfurousWastes_ids)
    OUTPOST_TO_TRAVEL    = 545    # Remains of Sahlahja
    EXPLORABLE_TO_TRAVEL = 444    # The Sulfurous Wastes
    COORD_TO_EXIT_MAP    = (2200.0, -4900.0)   # Walk from outpost gate into explorable

    # Sunspear Undead Blessing NPC (near junundu entrance)
    SUNSPEAR_NPC_COORDS = (-660.0, 16000.0)
    SUNSPEAR_DIALOG_1   = 0x83
    SUNSPEAR_DIALOG_2   = 0x85

    # Junundu wurm burrow entry point (gadget agent)
    JUNUNDU_ENTRY_COORDS = (-615.0, 13450.0)

    # Lightbringer Margonite Blessing NPC (mid-run, before margonite groups)
    LB_NPC_COORDS = (-20600.0, 7270.0)
    LB_DIALOG     = 0x85

    # Tome pickup: pick up + drop to trigger quest update
    TOME_COORDS = (-21300.0, -14000.0)

    # Boss spawn trigger item
    BOSS_SPAWN_APPROACH = (-16000.0, -13100.0)
    BOSS_SPAWN_COORDS   = (-18180.0, -13540.0)

    # Pass-through path between groups 4 and 5 — enemies here are unreachable;
    # HeroAI is disabled and heroes are flagged forward during traversal.
    PASS_THROUGH_COORDS: list[tuple[float, float]] = [
        (-5553.0,  11502.0),
        (-9904.0,  12412.0),
        (-12235.0, 10215.0),
        (-13478.0, 8572.0),
    ]

    # 31 combat group positions as (x, y, label)
    COMBAT_GROUPS: list[tuple[float, float, str]] = [
        (-800.0,    12000.0,  "First Undead Group 1"),
        (-1700.0,   9800.0,   "First Undead Group 2"),
        (-3000.0,   10900.0,  "Second Undead Group 1"),
        (-4500.0,   11500.0,  "Second Undead Group 2"),
        (-5500.0,   11250.0,  "Second Undead Group 3"),
        (-13250.0,  6750.0,   "Third Undead Group"),
        (-22000.0,  9000.0,   "First Margonite Group 1"),
        (-22350.0,  11100.0,  "First Margonite Group 2"),
        (-19000.0,  5700.0,   "Djinn Group 1"),
        (-20800.0,  600.0,    "Djinn Group 2"),
        (-22000.0,  -1200.0,  "Djinn Group 3"),
        (-21500.0,  -6000.0,  "Undead Ritualist Boss 1"),
        (-20400.0,  -7400.0,  "Undead Ritualist Boss 2"),
        (-19500.0,  -9500.0,  "Undead Ritualist Boss 3"),
        (-22000.0,  -9400.0,  "Third Margonite Group 1"),
        (-22800.0,  -9800.0,  "Third Margonite Group 2"),
        (-23000.0,  -10600.0, "Fourth Margonite Group 1"),
        (-23150.0,  -12250.0, "Fourth Margonite Group 2"),
        (-22800.0,  -13500.0, "Fifth Margonite Group 1"),
        (-21300.0,  -14000.0, "Fifth Margonite Group 2"),
        (-22800.0,  -13500.0, "Sixth Margonite Group 1"),
        (-23000.0,  -10600.0, "Sixth Margonite Group 2"),
        (-21500.0,  -9500.0,  "Sixth Margonite Group 3"),
        (-21000.0,  -9500.0,  "Seventh Margonite Group 1"),
        (-19500.0,  -8500.0,  "Seventh Margonite Group 2"),
        (-22000.0,  -9400.0,  "Temple Monolith Group 1"),
        (-23000.0,  -10600.0, "Temple Monolith Group 2"),
        (-22800.0,  -13500.0, "Temple Monolith Group 3"),
        (-19500.0,  -13100.0, "Temple Monolith Group 4"),
        (-18000.0,  -13100.0, "Temple Monolith Group 5"),
        (-18000.0,  -13100.0, "Margonite Boss Group"),
    ]

    TEXTURE = os.path.join(
        PySystem.Console.get_projects_path(),
        "Assets", "Textures", "Skill_Icons", "[1813] - Lightbringer.jpg",
    )


# ── Globals ─────────────────────────────────────────────────────────────────────
_botting_tree: BottingTree | None = None
_heroes_setup_done: bool = False
_diag_timer = ThrottledTimer(3000)  # diagnostic log every 3 s

# ── Party mode (Single Account with Heroes / Multiboxing) ────────────────────────
INI_PATH     = "Widgets/Automation/Bots/Farmers/Titles/Lightbringer-Sunspear Sulfurous Wastes"
INI_FILENAME = "Lightbringer-Sunspear_Sulfurous_Wastes.ini"
_SETTINGS_SECTION  = "Settings"
_USE_MULTIBOX_KEY  = "use_multibox_alts"

_settings_ini    = Settings(f"{INI_PATH}/{INI_FILENAME}", "account")
_party_mode: int = 0      # 0 = Single Account with Heroes, 1 = Multiboxing
_settings_loaded: bool = False
_tree_party_mode: int | None = None  # party mode the current _botting_tree was built for


def _is_multibox() -> bool:
    return _party_mode == 1


# ── Merchant / inventory maintenance ──────────────────────────────────────────────
MERCHANT_RULES_WIDGET_NAME = "MerchantRules"
INVENTORY_PLUS_WIDGET_NAME = "InventoryPlus"
INVENTORY_BAG_IDS = frozenset((1, 2, 3, 4))
ID_KIT_MODEL_IDS = (int(ModelID.Identification_Kit.value), int(ModelID.Superior_Identification_Kit.value))
SALVAGE_KIT_MODEL_IDS = (int(ModelID.Expert_Salvage_Kit.value),)

INVENTORY_MAINTENANCE_RETRY_COUNT = 2
INVENTORY_SNAPSHOT_SETTLE_MS = 2_000
INVENTORY_MERCHANT_TIMEOUT_MS = 240_000
_INVENTORY_QUERY_POLL_MS = 200
_INVENTORY_QUERY_TIMEOUT_MS = 10_000

_INVENTORY_SETTINGS_KEY_ENABLED = "InventoryMaintenanceEnabled"
_INVENTORY_SETTINGS_KEY_MIN_FREE_SLOTS = "InventoryMinFreeSlots"
_INVENTORY_SETTINGS_KEY_MIN_ID_KITS = "InventoryMinIdKits"
_INVENTORY_SETTINGS_KEY_MIN_SALVAGE_KITS = "InventoryMinSalvageKits"

_inventory_maintenance_enabled: bool = True
_inventory_min_free_slots: int = 5
_inventory_min_id_kits: int = 1
_inventory_min_salvage_kits: int = 2
_inventory_status_snapshot: dict[str, dict[str, object]] = {}


def _load_settings() -> None:
    global _settings_loaded, _party_mode
    global _inventory_maintenance_enabled, _inventory_min_free_slots, _inventory_min_id_kits, _inventory_min_salvage_kits
    if _settings_loaded:
        return
    _party_mode = 1 if _settings_ini.get_bool(_SETTINGS_SECTION, _USE_MULTIBOX_KEY, False) else 0
    _inventory_maintenance_enabled = _settings_ini.get_bool(_SETTINGS_SECTION, _INVENTORY_SETTINGS_KEY_ENABLED, True)
    _inventory_min_free_slots = max(0, _settings_ini.get_int(_SETTINGS_SECTION, _INVENTORY_SETTINGS_KEY_MIN_FREE_SLOTS, 5))
    _inventory_min_id_kits = max(0, _settings_ini.get_int(_SETTINGS_SECTION, _INVENTORY_SETTINGS_KEY_MIN_ID_KITS, 1))
    _inventory_min_salvage_kits = max(0, _settings_ini.get_int(_SETTINGS_SECTION, _INVENTORY_SETTINGS_KEY_MIN_SALVAGE_KITS, 2))
    _settings_loaded = True


def _save_settings() -> None:
    _settings_ini.set(_SETTINGS_SECTION, _USE_MULTIBOX_KEY, _is_multibox())
    _settings_ini.set(_SETTINGS_SECTION, _INVENTORY_SETTINGS_KEY_ENABLED, _inventory_maintenance_enabled)
    _settings_ini.set(_SETTINGS_SECTION, _INVENTORY_SETTINGS_KEY_MIN_FREE_SLOTS, _inventory_min_free_slots)
    _settings_ini.set(_SETTINGS_SECTION, _INVENTORY_SETTINGS_KEY_MIN_ID_KITS, _inventory_min_id_kits)
    _settings_ini.set(_SETTINGS_SECTION, _INVENTORY_SETTINGS_KEY_MIN_SALVAGE_KITS, _inventory_min_salvage_kits)


def _rebuild_tree_for_party_mode() -> None:
    """Drop the cached BottingTree so _get_bot() rebuilds it for the new party mode."""
    global _botting_tree, _tree_party_mode, _heroes_setup_done
    if _botting_tree is not None:
        try:
            if _botting_tree.IsStarted():
                _botting_tree.Stop()
        except Exception:
            pass
    _botting_tree = None
    _tree_party_mode = None
    _heroes_setup_done = False


# ── Hero config ─────────────────────────────────────────────────────────────────
@dataclass
class _PartyHeroSlot:
    hero_id: int = 0
    template: str = ""


def _humanize_hero_name(enum_name: str) -> str:
    if enum_name == "None_":
        return "<Empty>"
    words: List[str] = []
    current = enum_name[0]
    for char in enum_name[1:]:
        if (char.isupper() and not current[-1].isupper()) or (char.isdigit() and not current[-1].isdigit()):
            words.append(current)
            current = char
        else:
            current += char
    words.append(current)
    return " ".join(words)


_HERO_OPTIONS: List[HeroType] = [HeroType.None_] + sorted(
    [h for h in HeroType if h != HeroType.None_],
    key=lambda h: _humanize_hero_name(h.name),
)
_HERO_OPTION_LABELS: List[str]          = [_humanize_hero_name(h.name) for h in _HERO_OPTIONS]
_HERO_ID_TO_OPTION_INDEX: Dict[int, int] = {int(h): i for i, h in enumerate(_HERO_OPTIONS)}

_HERO_ICON_FILENAMES: Dict[HeroType, str] = {
    HeroType.Norgu: "Norgu-icon.jpg",           HeroType.Goren: "Goren-icon.jpg",
    HeroType.Tahlkora: "Tahlkora-icon.jpg",      HeroType.MasterOfWhispers: "MasterOfWhispers-icon.jpg",
    HeroType.AcolyteJin: "AcolyteSousuke-icon.jpg", HeroType.Koss: "Koss-icon.jpg",
    HeroType.Dunkoro: "Dunkoro-icon.jpg",        HeroType.AcolyteSousuke: "AcolyteSousuke-icon.jpg",
    HeroType.Melonni: "Melonni-icon.jpg",        HeroType.ZhedShadowhoof: "ZhedShadowhoof-icon.jpg",
    HeroType.GeneralMorgahn: "GeneralMorgahn-icon.jpg", HeroType.MagridTheSly: "MargridTheSly-icon.jpg",
    HeroType.Zenmai: "Zenmai-icon.jpg",          HeroType.Olias: "Olias-icon.jpg",
    HeroType.Razah: "Razah-icon.jpg",            HeroType.MOX: "M.O.X.-icon.jpg",
    HeroType.KeiranThackeray: "KeiranThackeray-icon.jpg", HeroType.Jora: "Jora-icon.jpg",
    HeroType.PyreFierceshot: "Pyre_Fierceshot-icon.jpg", HeroType.Anton: "Anton-icon.jpg",
    HeroType.Livia: "Livia-icon.jpg",            HeroType.Hayda: "Hayda-icon.jpg",
    HeroType.Kahmu: "Kahmu-icon.jpg",            HeroType.Gwen: "Gwen-icon.jpg",
    HeroType.Xandra: "Xandra-icon.jpg",          HeroType.Vekk: "Vekk-icon.jpg",
    HeroType.Ogden: "Ogden_Stonehealer-icon.jpg", HeroType.Miku: "Miku-icon.jpg",
    HeroType.ZeiRi: "Zei_Ri-icon.jpg",
}

_DEFAULT_HERO_TEMPLATES: Dict[HeroType, str] = {}  # fill with preferred Junundu-ready templates

_hero_slots: List[_PartyHeroSlot] = [_PartyHeroSlot() for _ in range(7)]
_hero_config_dirty: bool  = False
_hero_config_status: str  = ""
_hero_import_source_index: int = 0

_BOT_SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
_HERO_CONFIG_PATH = os.path.join(_BOT_SCRIPT_DIR, f"{BotSettings.BOT_NAME} Heroes.json")
_HERO_ICONS_BASE  = os.path.normpath(os.path.join(
    PySystem.Console.get_projects_path(), "..", "Property-of-Wick-Divinus-and-Kendor",
    "PVE Skills Unlocker", "Textures", "Skill_Icons",
))
_HERO_SLOTS_COUNT = 7


# ── BT Node builders ────────────────────────────────────────────────────────────

def _setup_heroai_junundu_node() -> BehaviorTree:
    """
    After entering the wurm:
    1. Force HeroAI to rediscover the JununduWurm build by clearing both the
       class-level scan cache and the instance-level build caches on HeroAI's
       own BuildRegistry — no widget restart required.
    2. Block skill slot 8 (Leave Junundu) in HeroAI options so it is never fired.
    """
    def _configure():
        import sys
        from Py4GWCoreLib.BuildMgr import BuildRegistry

        # 1. Clear the class-level filesystem scan cache.
        BuildRegistry.ClearCache()

        # 2. Find HeroAI's BuildRegistry instance via sys.modules and clear
        #    its per-instance build caches so _iter_matchable_builds rescans.
        for module in list(sys.modules.values()):
            heroai_build_obj = getattr(module, "heroai_build", None)
            if heroai_build_obj is None:
                continue
            registry = getattr(heroai_build_obj, "_build_registry", None)
            if registry is None:
                continue
            registry._cached_runtime_builds = None
            registry._cached_match_only_builds = None
            registry._cached_runtime_matchable_builds = None
            registry._cached_match_only_matchable_builds = None
            break

        # 3. Block Leave Junundu (slot 8, index 7) in HeroAI options.
        email = str(Player.GetAccountEmail() or "")
        if not email:
            PySystem.Console.Log(MODULE_NAME, "[JununduSetup] No account email — skipping skill toggle.", PySystem.Console.MessageType.Warning)
            return BehaviorTree.NodeState.SUCCESS
        options = GLOBAL_CACHE.ShMem.GetHeroAIOptionsFromEmail(email)
        if options is None:
            PySystem.Console.Log(MODULE_NAME, "[JununduSetup] HeroAI options not found — skipping skill toggle.", PySystem.Console.MessageType.Warning)
            return BehaviorTree.NodeState.SUCCESS
        skills = getattr(options, "Skills", None)
        if skills is not None:
            for i in range(min(7, len(skills))):
                skills[i] = True   # enable slots 1-7
            if len(skills) > 7:
                skills[7] = False  # block slot 8 = Leave Junundu (1443)
            PySystem.Console.Log(MODULE_NAME, f"[JununduSetup] Skills configured: slots 1-7 enabled, slot 8 blocked. len={len(skills)}", PySystem.Console.MessageType.Info)
        else:
            PySystem.Console.Log(MODULE_NAME, "[JununduSetup] options.Skills is None — skill toggle skipped.", PySystem.Console.MessageType.Warning)
        GLOBAL_CACHE.ShMem.SetHeroAIOptionsByEmail(email, options)
        PySystem.Console.Log(MODULE_NAME, "[JununduSetup] HeroAI setup complete. Registry caches cleared.", PySystem.Console.MessageType.Success)
        return BehaviorTree.NodeState.SUCCESS

    return BehaviorTree(BehaviorTree.ActionNode(_configure, name="SetupHeroAIJunundu"))


def _set_party_combat_node(enabled: bool, *, name: str = "") -> BehaviorTree:
    """Toggle HeroAIOptions.Combat directly (via shared memory) for every active account,
    including the leader's own email.

    KNOWN INCOMPLETE for the leader: BottingTree's own ticks.py calls
    EnsureHeroAIOptionsEnabled() every tick while headless HeroAI is enabled, which
    treats Combat=False on the LOCAL account as a policy violation and force-writes
    it back to True before the next frame (Py4GWCoreLib/botting_tree_src/heroai.py,
    _heroai_options_match_runtime_policy/RestoreHeroAIOptions) — so this write does
    not actually stop the leader from fighting the unreachable hill enemies during
    pass-through. It is still correct and load-bearing for every ALT, which has no
    such self-heal running against it.

    Do NOT "fix" this by calling BottingTree.EnableHeroAITree/DisableHeroAITree for
    the leader instead — tried and reverted. SetHeadlessHeroAIEnabled() (which that
    calls) unconditionally calls _sync_multibox_heroai_widget(), which broadcasts
    SharedCommandType.DisableWidget/EnableWidget for "HeroAI" to every OTHER account
    whenever multibox mode is on — so it doesn't just disable the leader's own
    combat, it shuts off every alt's actual "HeroAI" widget (Following included, not
    just Combat) for as long as the leader's toggle is off. Confirmed broken live.
    The real fix needs a way to suppress just the leader's own combat engagement
    without touching headless_heroai's enabled state at all — not yet found; see
    [[project-lbss-bot]] before attempting this again.
    """
    node_name = name or ("EnableCombat" if enabled else "DisableCombat")

    def _apply(node: BehaviorTree.Node) -> BehaviorTree.NodeState:
        seen: set[str] = set()

        local_email = str(Player.GetAccountEmail() or "").strip()
        if local_email:
            local_options = GLOBAL_CACHE.ShMem.GetHeroAIOptionsFromEmail(local_email)
            if local_options is not None:
                local_options.Combat = bool(enabled)
                GLOBAL_CACHE.ShMem.SetHeroAIOptionsByEmail(local_email, local_options)
                seen.add(local_email)

        for account, options in GLOBAL_CACHE.ShMem.GetAllActiveAccountHeroAIPairs(sort_results=False):
            email = str(getattr(account, "AccountEmail", "") or "")
            if not email or email in seen:
                continue
            seen.add(email)
            options.Combat = bool(enabled)
            GLOBAL_CACHE.ShMem.SetHeroAIOptionsByEmail(email, options)
        return BehaviorTree.NodeState.SUCCESS

    return BehaviorTree(BehaviorTree.ActionNode(_apply, name=node_name))


def _explorable_guarded(name: str, child: BehaviorTree) -> BehaviorTree:
    """Only run child while actually on the farm's own explorable map.

    Ported from Shards Of Orr's _map_guarded_point. Named planner steps can be
    resumed directly from the BottingTree UI's "Start At" dropdown (or after a
    party-wipe-recovery restart) — without this gate, resuming a fight/pickup
    step while still at the outpost would call BTMovement.Move with raw
    explorable coordinates from the wrong map instead of failing loudly. LBSS
    has a single explorable (no multi-level progression), so unlike Shards Of
    Orr's version this only needs the "still on the active map" branch, not a
    skip_if_in_maps list for already-passed levels.
    """
    return BT.Sequence(
        name=name,
        children=[
            BT.IsCurrentMap(map_id=BotSettings.EXPLORABLE_TO_TRAVEL, log=False),
            child,
        ],
    )


def _junundu_pass_through_node(path: list[tuple[float, float]]) -> BehaviorTree:
    """Move through path with a narrow stretch where unreachable enemies sit on a hill
    above: with combat left on, every account (leader and, in multibox, every alt) stops
    to try to fight them and never manages to kill any of them. Combat is suppressed for
    the whole party via _set_party_combat_node, while Following stays on so everyone keeps
    walking through rather than getting stuck fighting.

    The disable is reasserted before every waypoint but the last, rather than once at the
    start: an alt that's already mid-attack or gets aggro'd right as it enters the stretch
    may not have that interrupted by the flag alone, so re-applying it periodically
    corrects that within one waypoint instead of leaving combat effectively on for the
    whole pass-through.

    Combat is re-enabled before the FINAL leg, not after the whole path: re-enabling only
    once fully done left just the short hop into the next fight for HeroAIOptions.Combat=True
    to actually land on every account, and it wasn't reliably ready in time (some accounts
    just didn't resume fighting on the next group). Flipping it back on a whole waypoint-leg
    earlier gives it that entire leg's travel time to settle instead of almost none.
    """
    wp_nodes: list[BehaviorTree] = []
    last_index = len(path) - 1
    for i, (wx, wy) in enumerate(path):
        if i < last_index:
            wp_nodes.append(_set_party_combat_node(False, name="DisableCombatForPassThrough"))
        else:
            wp_nodes.append(_set_party_combat_node(True, name="EnableCombatBeforeFinalLeg"))
        wp_nodes.append(BTMovement.Move(wx, wy, pause_on_combat=False))
        if i < last_index:
            wp_nodes.append(_maybe_revive_during_pass_through_node(f"PassThroughRevive{i}"))

    return BTComposite.Sequence(*wp_nodes, name="PassThroughPath")


def _junundu_fight_node(x: float, y: float, label: str = "") -> BehaviorTree:
    """Move to (x,y) and wait for HeroAI to clear the group."""
    node_label = label or f"{int(x)},{int(y)}"

    def _start(node: BehaviorTree.Node) -> BehaviorTree.NodeState:
        PySystem.Console.Log(MODULE_NAME, f"[Planner] → {node_label} ({x:.0f},{y:.0f})", PySystem.Console.MessageType.Info)
        return BehaviorTree.NodeState.SUCCESS

    return BTComposite.Sequence(
        BehaviorTree.ActionNode(_start, name="Start"),
        BTMovement.Move(x, y, pause_on_combat=False),
        BTAgents.WaitUntilOutOfCombat(range=_RANGE_AGGRO, timeout_ms=120000),
        _revive_dead_party_node(name=f"RevivePartyAfter_{node_label}"),
        name=f"JFight_{node_label}",
    )


def _sunspear_blessing_node() -> BehaviorTree:
    """Move to the Sunspear NPC and take both dialog steps.

    Ported straight from Shards of Orr's own blessing pickup: a bare
    BT.MoveAndDialog(..., multi_account=True, log=True), no failure-catching
    wrapper around it. Previously this went through a _resilient_dialog_node
    Selector+Succeeder wrapper, because a multi-account dialog dispatch timeout
    is a FAILURE, and this repo's SequenceNode resets to its first child on
    FAILURE — which used to mean an unabsorbed timeout here reset the *entire*
    farm loop back to the outpost. Now that the farm run uses named planner
    steps (_build_farm_sequence), an unrecovered FAILURE only restarts this one
    named step, the same protection Shards of Orr already gets from its own
    named steps — the wrapper was redundant once that landed.

    A flat wait before each dialog call (replacing the old wait wedged *between*
    the two calls) gives every account time to actually arrive and settle before
    the multi-account dispatch fires, instead of firing the moment the leader
    arrives and forcing the broadcast to time out on anyone still catching up —
    that race was the actual disconnect risk, not the dialog call itself.
    """
    xy = BotSettings.SUNSPEAR_NPC_COORDS
    multi_account = _is_multibox()
    return BT.Sequence(
        name="SunspearBlessing",
        children=[
            BT.Wait(_BLESSING_PRE_DIALOG_WAIT_MS),
            BT.MoveAndDialog(xy, dialog_id=BotSettings.SUNSPEAR_DIALOG_1, multi_account=multi_account, log=True),
            BT.Wait(_BLESSING_PRE_DIALOG_WAIT_MS),
            BT.MoveAndDialog(xy, dialog_id=BotSettings.SUNSPEAR_DIALOG_2, multi_account=multi_account, log=True),
        ],
    )


def _enter_junundu_node() -> BehaviorTree:
    """Walk to the wurm burrow and transform.

    Multiboxing: BT.MoveAndInteractWithGadget's multi_account mode makes the
    leader interact first, then dispatches the same gadget interaction to
    every other account in the same map instance in turn — each alt actually
    transforms into its own wurm, instead of only the leader doing so while
    alts stand there in human form.
    """
    x, y = BotSettings.JUNUNDU_ENTRY_COORDS

    def _build(node: BehaviorTree.Node) -> BehaviorTree:
        if _is_multibox():
            # Like the blessing dialogs (see _sunspear_blessing_node), an unrecovered
            # FAILURE here now only resets this node's own named planner step ("Enter
            # Junundu"), not the whole farm loop, now that the run uses named steps —
            # so this fallback is no longer load-bearing the way it used to be. Left
            # in place since it wasn't part of the blessing-dialog change; its default
            # 90s timeout is generous but not infinite, so there's no real cost to
            # keeping it.
            return BT.Selector(
                name="EnterJununduMultibox",
                children=[
                    BT.MoveAndInteractWithGadget(
                        pos=(x, y),
                        search_distance=300.0,
                        interaction_distance=300.0,
                        account_settle_ms=3000,
                        multi_account=True,
                        include_self=True,
                        log=True,
                    ),
                    BT.Sequence(
                        name="EnterJununduMultiboxTimedOut",
                        children=[
                            BT.LogMessage(
                                message="EnterJunundu: gadget dispatch to one or more accounts timed out; continuing without resetting the run.",
                                module_name=MODULE_NAME,
                            ),
                            BT.Succeeder(name="EnterJununduMultiboxTimedOutContinue"),
                        ],
                    ),
                ],
            )
        return BTComposite.Sequence(
            BTMovement.Move(x, y, pause_on_combat=False),
            BTPlayer.Wait(2000),
            BTMovement.InteractWithGadgetAtXY(x, y, target_distance=300.0),
            BTPlayer.Wait(3500),
            name="EnterJununduSingleAccount",
        )

    return BehaviorTree(BehaviorTree.SubtreeNode(_build, name="EnterJunundu"))


def _lb_blessing_node() -> BehaviorTree:
    """Lightbringer Margonite Blessing, mid-run. See _sunspear_blessing_node for why this
    is now a bare BT.MoveAndDialog(multi_account=...), matching Shards of Orr, instead of
    going through a failure-catching wrapper."""
    xy = BotSettings.LB_NPC_COORDS

    return BTComposite.Sequence(
        BT.Wait(_BLESSING_PRE_DIALOG_WAIT_MS),
        BT.MoveAndDialog(xy, dialog_id=BotSettings.LB_DIALOG, multi_account=_is_multibox(), log=True),
        name="LightbringerBlessing",
    )


def _pickup_and_drop_node(x: float, y: float) -> BehaviorTree:
    return BTComposite.Sequence(
        BTMovement.Move(x, y, pause_on_combat=False),
        BTPlayer.Wait(500),
        BTAgents.TargetNearestItemXY(x, y, 200.0),
        BTPlayer.InteractTarget(),
        BTPlayer.Wait(2000),
        BTParty.DropBundle(),
        BTPlayer.Wait(1000),
        name=f"PickupAndDrop({int(x)},{int(y)})",
    )


def _boss_spawn_trigger_node(x: float, y: float) -> BehaviorTree:
    """Move to the boss spawn gadget and interact with it to trigger the boss group.

    InteractWithGadgetAtXY does not move — it searches for the nearest gadget within
    target_distance of the coordinates it's given and interacts, assuming the
    preceding Move already put the player in range. Both steps target the same
    verified approach point for that reason; giving them different coordinates
    (Move to one spot, then search for the gadget ~480 units away near the original
    BOSS_SPAWN_COORDS) is what was making the player walk back and forth between them.
    """
    approach_x, approach_y = -18191.19, -13059.67
    return BTComposite.Sequence(
        BTMovement.Move(approach_x, approach_y, pause_on_combat=False),
        BTPlayer.Wait(500),
        BTMovement.InteractWithGadgetAtXY(x, y, target_distance=300.0),
        BTPlayer.Wait(2000),
        name=f"BossSpawnTrigger({int(x)},{int(y)})",
    )


# ── Hero setup nodes ─────────────────────────────────────────────────────────────

def _setup_heroes_node() -> BehaviorTree:
    def _kick() -> BehaviorTree.NodeState:
        GLOBAL_CACHE.Party.Heroes.KickAllHeroes()
        return BehaviorTree.NodeState.SUCCESS

    def _add() -> BehaviorTree.NodeState:
        seen: set = set()
        for slot in _hero_slots:
            hero_id = int(slot.hero_id)
            if hero_id > 0 and hero_id not in seen:
                seen.add(hero_id)
                GLOBAL_CACHE.Party.Heroes.AddHero(hero_id)
        return BehaviorTree.NodeState.SUCCESS

    def _load_templates() -> BehaviorTree.NodeState:
        template_map = {int(s.hero_id): s.template for s in _hero_slots if s.template}
        hero_count = GLOBAL_CACHE.Party.GetHeroCount()
        for pos in range(1, hero_count + 1):
            agent_id = GLOBAL_CACHE.Party.Heroes.GetHeroAgentIDByPartyPosition(pos)
            if agent_id > 0:
                hero_id = GLOBAL_CACHE.Party.Heroes.GetHeroIDByAgentID(agent_id)
                template = template_map.get(hero_id, "")
                if template:
                    GLOBAL_CACHE.SkillBar.LoadHeroSkillTemplate(pos, template)
        return BehaviorTree.NodeState.SUCCESS

    return BTComposite.Sequence(
        BehaviorTree.ActionNode(_kick, aftercast_ms=500, name="KickHeroes"),
        BehaviorTree.ActionNode(_add, aftercast_ms=1000, name="AddHeroes"),
        BehaviorTree.ActionNode(_load_templates, aftercast_ms=500, name="LoadTemplates"),
        name="SetupHeroes",
    )


def _multibox_party_setup_node() -> BehaviorTree:
    """Summon every configured alt account and invite it into the local party.

    Matches Shards Of Orr's own party-setup step exactly: BT.CreateParty's
    multibox_invite branch already polls for every account's confirmed arrival
    before summoning completes, and Shards Of Orr never does anything more
    custom than call it with a longer-than-default timeout. The only prior
    difference here was the default 15s timeout_ms instead of Shards Of Orr's
    explicit 30s — not a reason to build a separate summon/invite primitive.
    """
    return BT.CreateParty(multibox_invite=True, timeout_ms=30_000, log=True)


def _maybe_setup_party_node() -> BehaviorTree:
    """One-time party setup: heroes for Single Account mode, alt accounts for Multiboxing."""

    def _check_skip() -> bool:
        return _heroes_setup_done

    def _mark_done() -> BehaviorTree.NodeState:
        global _heroes_setup_done
        _heroes_setup_done = True
        return BehaviorTree.NodeState.SUCCESS

    def _build_setup(node: BehaviorTree.Node) -> BehaviorTree:
        return _multibox_party_setup_node() if _is_multibox() else _setup_heroes_node()

    return BehaviorTree(
        BehaviorTree.SelectorNode(
            name="MaybeSetupParty",
            children=[
                BehaviorTree.ConditionNode(_check_skip, name="AlreadySetup"),
                BehaviorTree.SequenceNode(
                    name="DoSetup",
                    children=[
                        BehaviorTree.SubtreeNode(_build_setup, name="SetupSubtree"),
                        BehaviorTree.ActionNode(_mark_done, name="MarkDone"),
                    ],
                ),
            ],
        )
    )


def _combat_mode_node() -> BehaviorTree:
    def _get_mode(node: BehaviorTree.Node) -> BehaviorTree:
        return _get_bot().Config.Aggressive(
            multi_account=_is_multibox(),
            account_isolation=not _is_multibox(),
        )

    return BehaviorTree(
        BehaviorTree.SubtreeNode(_get_mode, name="ConfigureCombatMode")
    )


def _all_active_accounts() -> list[object]:
    try:
        accounts = GLOBAL_CACHE.ShMem.GetAllAccountData(sort_results=False)
    except TypeError:
        accounts = GLOBAL_CACHE.ShMem.GetAllAccountData()
    except Exception:
        accounts = []

    unique: list[object] = []
    seen: set[str] = set()
    for account in accounts or []:
        email = str(getattr(account, "AccountEmail", "") or "").strip()
        if not email or email in seen:
            continue
        seen.add(email)
        unique.append(account)
    return unique


def _account_map_id(account: object) -> int:
    agent_data = getattr(account, "AgentData", None)
    map_data = getattr(agent_data, "Map", None)
    return int(getattr(map_data, "MapID", 0) or 0)


def _all_accounts_on_map(map_id: int) -> bool:
    accounts = _all_active_accounts()
    return bool(accounts) and all(_account_map_id(a) == int(map_id) for a in accounts)


def _all_accounts_on_map_node(map_id: int, name: str) -> BehaviorTree:
    return BehaviorTree(BehaviorTree.ConditionNode(name=name, condition_fn=lambda node: _all_accounts_on_map(map_id)))


def _wait_for_all_accounts_on_map(map_id: int, *, name: str, timeout_ms: int = 60000) -> BehaviorTree:
    def _check(node: BehaviorTree.Node) -> BehaviorTree.NodeState:
        if _all_accounts_on_map(map_id):
            return BehaviorTree.NodeState.SUCCESS
        return BehaviorTree.NodeState.RUNNING

    return BehaviorTree(BehaviorTree.WaitUntilNode(name=name, condition_fn=_check, throttle_interval_ms=500, timeout_ms=timeout_ms))


def _party_is_fully_alive() -> bool:
    hero_count = GLOBAL_CACHE.Party.GetHeroCount()
    for pos in range(1, hero_count + 1):
        hero_agent_id = GLOBAL_CACHE.Party.Heroes.GetHeroAgentIDByPartyPosition(pos)
        if hero_agent_id > 0 and not Agent.IsAlive(hero_agent_id):
            return False

    for account in _all_active_accounts():
        agent_data = getattr(account, "AgentData", None)
        agent_id = int(getattr(agent_data, "AgentID", 0) or 0)
        if agent_id > 0 and not Agent.IsAlive(agent_id):
            return False

    return True


def _find_dead_party_member_position() -> tuple[float, float] | None:
    """Return the (x, y) of the first dead hero or active account found, or None if
    everyone's alive (or no position can be resolved for the one that's dead)."""
    hero_count = GLOBAL_CACHE.Party.GetHeroCount()
    for pos in range(1, hero_count + 1):
        hero_agent_id = GLOBAL_CACHE.Party.Heroes.GetHeroAgentIDByPartyPosition(pos)
        if hero_agent_id > 0 and not Agent.IsAlive(hero_agent_id):
            return Agent.GetXY(hero_agent_id)

    for account in _all_active_accounts():
        agent_data = getattr(account, "AgentData", None)
        agent_id = int(getattr(agent_data, "AgentID", 0) or 0)
        if agent_id > 0 and not Agent.IsAlive(agent_id):
            return Agent.GetXY(agent_id)

    return None


def _wait_until_party_alive_or_fail(*, name: str, timeout_ms: int) -> BehaviorTree:
    def _check(node: BehaviorTree.Node) -> BehaviorTree.NodeState:
        if _party_is_fully_alive():
            return BehaviorTree.NodeState.SUCCESS
        return BehaviorTree.NodeState.RUNNING

    return BehaviorTree(BehaviorTree.WaitUntilNode(name=name, condition_fn=_check, throttle_interval_ms=500, timeout_ms=timeout_ms))


def _revive_dead_party_attempt(attempt_number: int) -> BehaviorTree:
    """One pass: if anyone's dead, walk back to their corpse and give Junundu Wail a
    chance to fire — JununduWurm.ProcessSkillCasting casts it on priority whenever
    _has_dead_party_member_nearby() is true (Py4GWCoreLib/Builds/Any/Junundu_Wurm.py),
    but only once the reviver is actually close enough — then re-check. Fails (so the
    enclosing Selector tries the next attempt) if the party is still not fully alive
    once the wait times out.
    """

    def _build(node: BehaviorTree.Node) -> BehaviorTree:
        if _party_is_fully_alive():
            return BT.Succeeder(name=f"RevivePartyAttempt{attempt_number}AllAlive")

        corpse_xy = _find_dead_party_member_position()
        if corpse_xy is None:
            return BT.Succeeder(name=f"RevivePartyAttempt{attempt_number}NoCorpseFound")

        return BT.Sequence(
            name=f"RevivePartyAttempt{attempt_number}ReturnToCorpse",
            children=[
                BTMovement.Move(corpse_xy[0], corpse_xy[1], pause_on_combat=False),
                _wait_until_party_alive_or_fail(name=f"RevivePartyAttempt{attempt_number}WaitAfterReturn", timeout_ms=10000),
            ],
        )

    return BehaviorTree(BehaviorTree.SubtreeNode(_build, name=f"RevivePartyAttempt{attempt_number}"))


def _revive_dead_party_node(*, name: str, max_attempts: int = 3) -> BehaviorTree:
    """If anyone (hero or, in multibox, an active account) is dead, walk back to their
    corpse and wait for Junundu Wail to revive them, then continue.

    WaitUntilOutOfCombat alone just holds position where the fight ended — if the
    corpse is out of range of that spot, the group never gets back close enough to
    revive it and just moves on missing a member. This actively returns to wherever
    the corpse actually is instead. Retries up to max_attempts (another death, Wail
    still on recharge, etc. can each cost an attempt without anyone actually being
    unrecoverable), then gives up and continues rather than blocking the run forever.

    Selector, not left to fail outright: this repo's SequenceNode resets to child 0
    on FAILURE, all the way up through every enclosing Sequence — so an unabsorbed
    failure here would reset the entire farm loop back to the outpost instead of
    just leaving one account behind. Logged so it's visible when it happens.
    """
    attempts = [_revive_dead_party_attempt(n) for n in range(1, max_attempts + 1)]
    attempts.append(
        BT.Sequence(
            name=f"{name}GaveUp",
            children=[
                BT.LogMessage(
                    message=f"{name}: a party member is still dead after {max_attempts} attempt(s) to return to them; continuing without resetting the run.",
                    module_name=MODULE_NAME,
                ),
                BT.Succeeder(name=f"{name}GaveUpContinue"),
            ],
        )
    )

    return BT.Selector(name=name, children=attempts)


def _maybe_revive_during_pass_through_node(name: str) -> BehaviorTree:
    """Check for a dead teammate between pass-through waypoints.

    Combat is deliberately suppressed (HeroAIOptions.Combat = False) for most of the
    pass-through, to stop the party fighting the unreachable hill enemies — but the
    standard "HeroAI" widget gates BOTH HandleCombat and HandleOutOfCombat behind that
    same Combat flag, so Wail can't fire at all while it's off, even after walking
    back to the corpse. If someone died during the no-combat stretch, briefly
    re-enable combat, run the normal revive-and-return logic, then re-suppress combat
    before continuing the rest of the path.
    """

    def _build(node: BehaviorTree.Node) -> BehaviorTree:
        if _party_is_fully_alive():
            return BT.Succeeder(name=f"{name}AllAlive")
        return BT.Sequence(
            name=f"{name}ReviveThenResumeSuppression",
            children=[
                _set_party_combat_node(True, name=f"{name}EnableCombatForRevive"),
                _revive_dead_party_node(name=f"{name}Revive"),
                _set_party_combat_node(False, name=f"{name}ResumeCombatSuppression"),
            ],
        )

    return BehaviorTree(BehaviorTree.SubtreeNode(_build, name=name))


# ── Merchant rules / inventory maintenance ─────────────────────────────────────────
# Ported from Shards Of Orr BT test.py's InventoryCheckAndMaintenance()/StartupInventoryCheck()
# and the _inventory_* helpers around it. Query real inventory state locally on every
# active account, and if anyone is below threshold, run MerchantRules across the whole
# party at the outpost.

def _local_inventory_state() -> tuple[int, int, int, int]:
    occupied, capacity = Inventory.GetInventorySpace()
    id_kits = sum(int(GLOBAL_CACHE.Inventory.GetModelCount(model_id)) for model_id in ID_KIT_MODEL_IDS)
    salvage_kits = sum(int(GLOBAL_CACHE.Inventory.GetModelCount(model_id)) for model_id in SALVAGE_KIT_MODEL_IDS)
    return int(occupied), int(capacity), int(id_kits), int(salvage_kits)


def _inventory_target_accounts() -> list[tuple[str, str]]:
    """Return every active account as (email, display label), including self."""
    targets: list[tuple[str, str]] = []
    seen: set[str] = set()

    for account in _all_active_accounts():
        email = str(getattr(account, "AccountEmail", "") or "").strip()
        if not email or email in seen:
            continue
        seen.add(email)
        agent_data = getattr(account, "AgentData", None)
        character_name = str(getattr(agent_data, "CharacterName", "") or "").strip()
        targets.append((email, character_name or email))

    local_email = str(Player.GetAccountEmail() or "").strip()
    if local_email and local_email not in seen:
        local_name = str(Player.GetName() or "").strip()
        targets.append((local_email, local_name or local_email))

    return targets


def _build_inventory_status(email: str, label: str, state: tuple[int, int, int, int] | None) -> dict[str, object]:
    if state is None:
        occupied = capacity = id_kits = salvage_kits = -1
    else:
        occupied, capacity, id_kits, salvage_kits = (int(value) for value in state)

    available = capacity > 0 and occupied >= 0 and occupied <= capacity
    free_slots = max(0, capacity - occupied) if available else 0

    return {
        "email": str(email),
        "label": str(label),
        "available": available,
        "capacity": capacity,
        "occupied": occupied,
        "free_slots": free_slots,
        "id_kits": id_kits,
        "salvage_kits": salvage_kits,
    }


def _inventory_account_statuses() -> list[dict[str, object]]:
    statuses: list[dict[str, object]] = []
    for raw_status in _inventory_status_snapshot.values():
        status = dict(raw_status)
        account_issues: list[str] = []

        if not bool(status.get("available", False)):
            account_issues.append("inventory query unavailable")
        else:
            free_slots = int(status.get("free_slots", 0) or 0)
            id_kits = int(status.get("id_kits", 0) or 0)
            salvage_kits = int(status.get("salvage_kits", 0) or 0)

            if _inventory_min_free_slots > 0 and free_slots < _inventory_min_free_slots:
                account_issues.append(f"free slots {free_slots}/{_inventory_min_free_slots}")
            if _inventory_min_id_kits > 0 and id_kits < _inventory_min_id_kits:
                account_issues.append(f"ID kits {id_kits}/{_inventory_min_id_kits}")
            if _inventory_min_salvage_kits > 0 and salvage_kits < _inventory_min_salvage_kits:
                account_issues.append(f"salvage kits {salvage_kits}/{_inventory_min_salvage_kits}")

        status["issues"] = account_issues
        statuses.append(status)

    return statuses


def _inventory_maintenance_issues() -> list[str]:
    statuses = _inventory_account_statuses()
    if not statuses:
        return ["No active account inventory query result is available."]
    return [f"{status['label']}: {', '.join(status['issues'])}" for status in statuses if status["issues"]]


def _log_inventory_statuses(statuses: list[dict[str, object]]) -> None:
    if not statuses:
        PySystem.Console.Log(MODULE_NAME, "[Inventory] No active account inventory query result is available.", PySystem.Console.MessageType.Warning)
        return

    for status in statuses:
        issues = list(status["issues"])
        result = "MAINTENANCE" if issues else "OK"
        if bool(status.get("available", False)):
            message = (
                f"[Inventory] {status['label']}: free={status['free_slots']}/{status['capacity']}, "
                f"occupied={status['occupied']}, ID kits={status['id_kits']}, "
                f"Expert salvage kits={status['salvage_kits']} -> {result}"
            )
        else:
            message = f"[Inventory] {status['label']}: local inventory query unavailable -> {result}"
        PySystem.Console.Log(MODULE_NAME, message, PySystem.Console.MessageType.Warning if issues else PySystem.Console.MessageType.Info)


def _query_all_inventory_states_node(name: str, *, timeout_ms: int = _INVENTORY_QUERY_TIMEOUT_MS) -> BehaviorTree:
    """Query real inventory state locally on every active Guild Wars client."""
    state: dict[str, object] = {"started": False, "request_id": "", "sender_email": "", "pending": {}, "results": {}, "started_at": 0.0}

    def _reset() -> None:
        state["started"] = False
        state["request_id"] = ""
        state["sender_email"] = ""
        state["pending"] = {}
        state["results"] = {}
        state["started_at"] = 0.0

    def _finish() -> BehaviorTree.NodeState:
        global _inventory_status_snapshot
        _inventory_status_snapshot = dict(state["results"])
        _reset()
        return BehaviorTree.NodeState.SUCCESS

    def _start() -> None:
        request_id = f"lbss_inventory_state_{int(time.monotonic() * 1000)}"
        sender_email = str(Player.GetAccountEmail() or "").strip()
        targets = _inventory_target_accounts()

        results: dict[str, dict[str, object]] = {}
        pending: dict[str, str] = {}

        for email, label in targets:
            if email == sender_email:
                try:
                    local_state = _local_inventory_state()
                except Exception as exc:
                    PySystem.Console.Log(MODULE_NAME, f"[Inventory] Local inventory query failed on {label}: {exc}", PySystem.Console.MessageType.Error)
                    local_state = None
                results[email] = _build_inventory_status(email, label, local_state)
                continue

            if not sender_email:
                results[email] = _build_inventory_status(email, label, None)
                continue

            reset_inventory_state(email, request_id)
            GLOBAL_CACHE.ShMem.SendMessage(
                sender_email, email, SharedCommandType.InventoryQuery,
                (
                    float(ID_KIT_MODEL_IDS[0] if len(ID_KIT_MODEL_IDS) > 0 else 0),
                    float(ID_KIT_MODEL_IDS[1] if len(ID_KIT_MODEL_IDS) > 1 else 0),
                    float(SALVAGE_KIT_MODEL_IDS[0] if SALVAGE_KIT_MODEL_IDS else 0),
                    0.0,
                ),
                ("report_inventory_state", request_id, "", ""),
            )
            pending[email] = label

        state["started"] = True
        state["request_id"] = request_id
        state["sender_email"] = sender_email
        state["pending"] = pending
        state["results"] = results
        state["started_at"] = time.monotonic()

        PySystem.Console.Log(MODULE_NAME, f"[Inventory] Requested real inventory state from {len(targets)} active account(s).", PySystem.Console.MessageType.Info)

    def _tick(node: BehaviorTree.Node) -> BehaviorTree.NodeState:
        try:
            if bool(node.blackboard.get("USER_INTERRUPT_ACTIVE", False)):
                _reset()
                return BehaviorTree.NodeState.FAILURE

            if not bool(state["started"]):
                _start()

            pending: dict[str, str] = state["pending"]
            request_id = str(state["request_id"])

            for email in list(pending):
                reply = get_inventory_state(email, request_id)
                if reply is None:
                    continue
                label = pending.pop(email)
                state["results"][email] = _build_inventory_status(email, label, reply)

            if not pending:
                return _finish()

            elapsed_ms = int((time.monotonic() - float(state["started_at"])) * 1000.0)
            if elapsed_ms < max(0, int(timeout_ms)):
                return BehaviorTree.NodeState.RUNNING

            for email, label in list(pending.items()):
                state["results"][email] = _build_inventory_status(email, label, None)
                PySystem.Console.Log(MODULE_NAME, f"[Inventory] Real inventory query timed out for {label}.", PySystem.Console.MessageType.Warning)
            pending.clear()
            return _finish()

        except Exception as exc:
            PySystem.Console.Log(MODULE_NAME, f"[Inventory] Multibox inventory-state query failed: {exc}", PySystem.Console.MessageType.Error)
            return _finish()

    return BehaviorTree(BehaviorTree.ActionNode(name=name, action_fn=_tick, aftercast_ms=_INVENTORY_QUERY_POLL_MS))


def _inventory_recipient_emails() -> list[str]:
    return [email for email, _label in _inventory_target_accounts()]


def _inventory_maintenance_trigger_node() -> BehaviorTree:
    def _log(node: BehaviorTree.Node) -> BehaviorTree.NodeState:
        statuses = _inventory_account_statuses()
        trigger_labels = [str(status["label"]) for status in statuses if status["issues"]]
        recipients = _inventory_recipient_emails()
        trigger_text = ", ".join(trigger_labels) if trigger_labels else "inventory verification"
        recipient_text = ", ".join(str(status["label"]) for status in statuses if str(status["email"]) in recipients)
        PySystem.Console.Log(
            MODULE_NAME,
            f"[Inventory] Maintenance triggered by: {trigger_text}. MerchantRules will run on ALL {len(recipients)} active account(s)"
            + (f": {recipient_text}." if recipient_text else "."),
            PySystem.Console.MessageType.Warning,
        )
        return BehaviorTree.NodeState.SUCCESS

    return BehaviorTree(BehaviorTree.ActionNode(name="Log Collective Inventory Maintenance Trigger", action_fn=_log, aftercast_ms=0))


def _inventory_is_healthy_node(name: str, *, log_success: bool = True) -> BehaviorTree:
    def _check(node: BehaviorTree.Node) -> BehaviorTree.NodeState:
        statuses = _inventory_account_statuses()
        _log_inventory_statuses(statuses)

        if not statuses:
            PySystem.Console.Log(MODULE_NAME, "Inventory maintenance required - no active account inventory snapshot is available.", PySystem.Console.MessageType.Warning)
            return BehaviorTree.NodeState.FAILURE

        issues = [f"{status['label']}: {', '.join(status['issues'])}" for status in statuses if status["issues"]]
        if issues:
            PySystem.Console.Log(MODULE_NAME, "Inventory maintenance required - " + "; ".join(issues), PySystem.Console.MessageType.Warning)
            return BehaviorTree.NodeState.FAILURE

        if log_success:
            PySystem.Console.Log(MODULE_NAME, "Inventory check passed on every active account.", PySystem.Console.MessageType.Success)
        return BehaviorTree.NodeState.SUCCESS

    return BehaviorTree(BehaviorTree.ConditionNode(name=name, condition_fn=_check))


def _send_widget_state(widget_name: str, *, enabled: bool, refs_key: str) -> BehaviorTree:
    return BTShared.SendAndWait(
        command=SharedCommandType.EnableWidget if enabled else SharedCommandType.DisableWidget,
        extra_data=(widget_name, "", "", ""),
        include_self=True,
        refs_blackboard_key=refs_key,
        timeout_ms=20000,
        poll_interval_ms=100,
        log=True,
    )


def _set_local_auto_inventory_handler(enabled: bool) -> BehaviorTree:
    def _set(node: BehaviorTree.Node) -> BehaviorTree.NodeState:
        if _botting_tree is None:
            return BehaviorTree.NodeState.SUCCESS
        fn = getattr(_botting_tree, "SetAutoInventoryHandlerEnabled", None)
        if fn is None:
            return BehaviorTree.NodeState.SUCCESS
        try:
            fn(enabled)
        except Exception:
            return BehaviorTree.NodeState.SUCCESS
        return BehaviorTree.NodeState.SUCCESS

    return BehaviorTree(BehaviorTree.ActionNode(name="Enable Local Auto Inventory Handler" if enabled else "Disable Local Auto Inventory Handler", action_fn=_set, aftercast_ms=0))


def _restore_inventoryplus_after_merchant(attempt_key: str) -> BehaviorTree:
    return BT.Sequence(
        name="Restore InventoryPlus After MerchantRules",
        children=[
            _send_widget_state(INVENTORY_PLUS_WIDGET_NAME, enabled=True, refs_key=f"{attempt_key}_enable_inventoryplus_refs"),
            _set_local_auto_inventory_handler(True),
        ],
    )


def _run_merchant_rules(attempt_key: str) -> BehaviorTree:
    def _build(node: BehaviorTree.Node) -> BehaviorTree:
        recipients = _inventory_recipient_emails()
        if not recipients:
            PySystem.Console.Log(MODULE_NAME, "[Inventory] MerchantRules aborted: no active account recipients.", PySystem.Console.MessageType.Error)
            return BehaviorTree(BehaviorTree.FailerNode(name="No Active MerchantRules Recipients"))

        request_id = f"lbss_inventory_{attempt_key}_{int(time.monotonic() * 1000)}"
        PySystem.Console.Log(MODULE_NAME, f"[Inventory] Dispatching MerchantRules to all {len(recipients)} active account(s).", PySystem.Console.MessageType.Info)
        execute = BTShared.SendAndWait(
            command=SharedCommandType.MerchantRules,
            params=(3.0, 0.0, 0.0, 0.0),
            extra_data=(request_id, "", "0", "0"),
            recipients=recipients,
            include_self=True,
            refs_blackboard_key=f"{attempt_key}_merchant_rules_refs",
            timeout_ms=INVENTORY_MERCHANT_TIMEOUT_MS,
            poll_interval_ms=250,
            log=True,
        )

        return BT.Selector(
            name="Execute MerchantRules And Restore InventoryPlus",
            children=[
                BT.Sequence(name="MerchantRules Completed", children=[execute, _restore_inventoryplus_after_merchant(attempt_key)]),
                BT.Sequence(name="Restore InventoryPlus After MerchantRules Failure", children=[_restore_inventoryplus_after_merchant(f"{attempt_key}_failure"), BehaviorTree(BehaviorTree.FailerNode(name="Propagate MerchantRules Failure"))]),
            ],
        )

    return BT.Subtree(name="Run MerchantRules On All Active Accounts", subtree_fn=_build)


def _inventory_maintenance_attempt(attempt_number: int) -> BehaviorTree:
    attempt_key = f"inventory_attempt_{attempt_number}"
    return BT.Sequence(
        name=f"Inventory Maintenance Attempt {attempt_number}",
        children=[
            BT.LogMessage(message=f"Inventory maintenance attempt {attempt_number}/{INVENTORY_MAINTENANCE_RETRY_COUNT}.", module_name=MODULE_NAME),
            _set_local_auto_inventory_handler(False),
            _send_widget_state(INVENTORY_PLUS_WIDGET_NAME, enabled=False, refs_key=f"{attempt_key}_disable_inventoryplus_refs"),
            _send_widget_state(MERCHANT_RULES_WIDGET_NAME, enabled=True, refs_key=f"{attempt_key}_enable_merchant_rules_refs"),
            BT.Wait(1_000),
            _run_merchant_rules(attempt_key),
            BT.Wait(INVENTORY_SNAPSHOT_SETTLE_MS),
            _query_all_inventory_states_node(name=f"Refresh Real Inventories After Attempt {attempt_number}"),
            _inventory_is_healthy_node(f"Verify Inventory After Attempt {attempt_number}", log_success=True),
        ],
    )


def _stop_for_inventory_failure_node() -> BehaviorTree:
    stopped = False

    def _stop(node: BehaviorTree.Node) -> BehaviorTree.NodeState:
        nonlocal stopped
        if not stopped:
            stopped = True
            issues = _inventory_maintenance_issues()
            issue_text = "; ".join(issues) if issues else "unknown verification error"
            PySystem.Console.Log(MODULE_NAME, f"Inventory maintenance failed twice. The bot was paused safely. Remaining issue(s): {issue_text}", PySystem.Console.MessageType.Error)

            if _botting_tree is not None:
                fn = getattr(_botting_tree, "SetAutoInventoryHandlerEnabled", None)
                if callable(fn):
                    try:
                        fn(True)
                    except Exception:
                        pass

            sender_email = str(Player.GetAccountEmail() or "").strip()
            for account in _all_active_accounts():
                receiver_email = str(getattr(account, "AccountEmail", "") or "").strip()
                if not sender_email or not receiver_email:
                    continue
                GLOBAL_CACHE.ShMem.SendMessage(sender_email, receiver_email, SharedCommandType.EnableWidget, (0.0, 0.0, 0.0, 0.0), (INVENTORY_PLUS_WIDGET_NAME, "", "", ""))

            if _botting_tree is not None:
                fn = getattr(_botting_tree, "Pause", None)
                if callable(fn):
                    try:
                        fn(True)
                    except Exception:
                        pass

        return BehaviorTree.NodeState.RUNNING

    return BehaviorTree(BehaviorTree.ActionNode(name="Pause Bot After Inventory Maintenance Failure", action_fn=_stop, aftercast_ms=0))


def _inventory_check_and_maintenance_node() -> BehaviorTree:
    """Query every active account's real inventory; if anyone is below threshold, run
    MerchantRules across the whole party. Same structure as Shards of Orr's
    InventoryCheckAndMaintenance() + StartupInventoryCheck().

    Adaptation: Shards of Orr is multibox-only and always leaves party before running
    merchant, then re-forms it as a normal part of its loop. This bot also supports
    Single Account (heroes), where leaving party would eject the heroes for no reason,
    so the leave/re-invite pair is skipped there and only used in Multiboxing.
    """
    disabled = BehaviorTree(BehaviorTree.ConditionNode(name="Inventory Maintenance Disabled", condition_fn=lambda node: not _inventory_maintenance_enabled))

    maintenance_attempts = [_inventory_maintenance_attempt(n) for n in range(1, INVENTORY_MAINTENANCE_RETRY_COUNT + 1)]
    maintenance_attempts.append(_stop_for_inventory_failure_node())

    maintenance_children: list[BehaviorTree | BehaviorTree.Node] = [_inventory_maintenance_trigger_node()]
    if _is_multibox():
        maintenance_children.append(BT.LeaveParty())
    maintenance_children.append(BT.Wait(INVENTORY_SNAPSHOT_SETTLE_MS))
    maintenance_children.append(BT.Selector(name="Retry Inventory Maintenance At Outpost", children=maintenance_attempts))
    if _is_multibox():
        maintenance_children.append(_multibox_party_setup_node())

    enabled_flow = BT.Sequence(
        name="Enabled Inventory Check And Maintenance",
        children=[
            _query_all_inventory_states_node(name="Query Real Inventory State On Every Active Account"),
            BT.Selector(
                name="Check Inventory Thresholds",
                children=[
                    _inventory_is_healthy_node("Inventory Thresholds Already Satisfied", log_success=True),
                    BT.Sequence(name="Run Inventory Maintenance", children=maintenance_children),
                ],
            ),
        ],
    )

    return BT.Sequence(
        name="Inventory Check And Maintenance At Outpost",
        children=[
            BT.IsCurrentMap(map_id=BotSettings.OUTPOST_TO_TRAVEL, log=False),
            BT.Selector(name="Inventory Check And Maintenance", children=[disabled, enabled_flow]),
        ],
    )


def _resign_node() -> BehaviorTree:
    """Ensure every active account is back at the outpost — full port of Shards of
    Orr's _return_all_accounts_to_vlox, not just its inner BT.Resign + wait pair:
    skip if everyone's already at the outpost, resign the party from the explorable
    if that's where everyone still is, and fall back to an explicit map-travel
    dispatch (SharedCommandType.TravelToMap, include_self=True) if resigning
    doesn't apply.
    """
    currently_in_explorable = BT.IsCurrentMap(map_id=BotSettings.EXPLORABLE_TO_TRAVEL, log=False)

    resign_from_explorable = BT.Sequence(
        name="Resign Party To Outpost",
        children=[
            currently_in_explorable,
            BT.Resign(
                wait_for_map_load=True,
                target_map_id=BotSettings.OUTPOST_TO_TRAVEL,
                multi_account=_is_multibox(),
                timeout_ms=60000,
                log=True,
            ),
            _wait_for_all_accounts_on_map(BotSettings.OUTPOST_TO_TRAVEL, name="Wait For Party Return To Outpost"),
        ],
    )

    travel_all_accounts_to_outpost = BT.Sequence(
        name="Travel Every Account To Outpost",
        children=[
            BTShared.SendAndWait(
                command=SharedCommandType.TravelToMap,
                params=(float(BotSettings.OUTPOST_TO_TRAVEL), 0.0, 0.0, 0.0),
                include_self=True,
                refs_blackboard_key="resign_travel_outpost_refs",
                timeout_ms=60000,
                poll_interval_ms=250,
                log=True,
            ),
            _wait_for_all_accounts_on_map(BotSettings.OUTPOST_TO_TRAVEL, name="Wait For Every Account At Outpost"),
        ],
    )

    return BT.Selector(
        name="Ensure Every Account Is At The Outpost",
        children=[
            _all_accounts_on_map_node(BotSettings.OUTPOST_TO_TRAVEL, "Every Account Already At Outpost"),
            resign_from_explorable,
            travel_all_accounts_to_outpost,
        ],
    )


# ── Farm sequence ────────────────────────────────────────────────────────────────

def _build_farm_sequence() -> list[tuple[str, Callable[[], BehaviorTree]]]:
    """Named, individually-resumable planner steps (same shape Shards Of Orr BT test.py
    uses: get_execution_steps() -> list[(step_name, zero-arg builder)]), passed straight
    into BottingTree.Create(main_routine=..., repeat=True).

    Every entry pairs a name with a callable that builds a fresh BehaviorTree, not a
    pre-built tree object: BottingTreePlannerMixin rebuilds the whole named-step tree
    whenever the user (or the party-wipe-recovery service) restarts from a step, and a
    stale, already-ticked node instance carried across that rebuild could keep leftover
    internal state. Building fresh each time avoids that.

    Picking "Start At: Fight Group 12" from the BottingTree UI (or after a crash) skips
    every earlier step entirely rather than re-running it, so only pick a resume point at
    a stage whose prerequisites (party formed, hard mode set, transformed into the
    Junundu, relevant blessing already taken) are actually already true. This also means
    an unrecovered FAILURE deep in one step (e.g. every revive attempt exhausted) now only
    restarts that named step via ticks.py's "Restarting the current named step" path,
    not the whole farm loop back to the outpost - a side benefit of naming steps at all,
    independent of manual navigation.
    """
    G = BotSettings.COMBAT_GROUPS
    sx, sy = BotSettings.BOSS_SPAWN_APPROACH

    def _initial_setup() -> BehaviorTree:
        # One-time setup (party setup is flag-guarded; travel and hard-mode are idempotent).
        # Party mode (multi_account / isolation) must be applied before party setup, since
        # summoning/inviting alts relies on isolation already being disabled in shared memory.
        return BTComposite.Sequence(
            BTMap.TravelToOutpost(outpost_id=BotSettings.OUTPOST_TO_TRAVEL),
            _combat_mode_node(),
            _maybe_setup_party_node(),
            BTMap.SetHardMode(hard_mode=True),
            name="InitialSetup",
        )

    def _travel_and_enter_explorable() -> BehaviorTree:
        return BTComposite.Sequence(
            BTMap.TravelToOutpost(outpost_id=BotSettings.OUTPOST_TO_TRAVEL),
            BTMovement.MoveAndExitMap(
                x=BotSettings.COORD_TO_EXIT_MAP[0],
                y=BotSettings.COORD_TO_EXIT_MAP[1],
                target_map_id=BotSettings.EXPLORABLE_TO_TRAVEL,
            ),
            name="TravelAndEnterExplorable",
        )

    def _ensure_combat_enabled_for_junundu() -> BehaviorTree:
        # Best-effort: the standard "HeroAI" widget that drives multibox alts gates its
        # entire out-of-combat tick (Widgets/Automation/Multiboxing/HeroAI.py:HandleOutOfCombat)
        # behind HeroAIOptions.Combat -- if that's off for an alt, ProcessOOC() (and so
        # Wail-on-a-dead-teammate, see Junundu_Wurm.py) never runs for them at all. Force
        # it on (and re-enable the leader's own Headless HeroAI) for every active account
        # here, up front, rather than relying on whatever state each client already
        # happened to be left in.
        return _set_party_combat_node(True, name="EnsureCombatEnabledForJunundu")

    def _boss_spawn_approach_and_trigger() -> BehaviorTree:
        return _explorable_guarded(
            "BossSpawnApproachAndTriggerMapGuard",
            BTComposite.Sequence(
                BTMovement.Move(sx, sy, pause_on_combat=False),
                _boss_spawn_trigger_node(BotSettings.BOSS_SPAWN_COORDS[0], BotSettings.BOSS_SPAWN_COORDS[1]),
                name="BossSpawnApproachAndTrigger",
            ),
        )

    def _tome_pickup() -> BehaviorTree:
        return _explorable_guarded(
            "TomePickupMapGuard",
            _pickup_and_drop_node(BotSettings.TOME_COORDS[0], BotSettings.TOME_COORDS[1]),
        )

    def _pass_through_to_group_05() -> BehaviorTree:
        return _explorable_guarded(
            "PassThroughToGroup05MapGuard",
            _junundu_pass_through_node(BotSettings.PASS_THROUGH_COORDS),
        )

    def _fight_group_builder(index: int) -> Callable[[], BehaviorTree]:
        def _build() -> BehaviorTree:
            return _explorable_guarded(
                f"FightGroup{index:02d}MapGuard",
                _junundu_fight_node(G[index][0], G[index][1], G[index][2]),
            )
        return _build

    steps: list[tuple[str, Callable[[], BehaviorTree]]] = [
        ("Initial Setup", _initial_setup),
        ("Travel And Enter Explorable", _travel_and_enter_explorable),
        # Farm run. HeroAI is intentionally left running here (as Shards of Orr does through
        # its own blessing pickups) -- each multiboxed alt's headless HeroAI is what actually
        # walks it to the blessing NPCs and the wurm entrance by following the leader; the
        # blessing/gadget nodes themselves scope their own brief HeroAI pause around the
        # actual interaction (see BT.MoveAndDialog / BT.MoveAndInteractWithGadget).
        ("Sunspear Blessing", _sunspear_blessing_node),
        ("Enter Junundu", _enter_junundu_node),
        ("Ensure Combat Enabled For Junundu", _ensure_combat_enabled_for_junundu),
        ("Setup HeroAI Junundu", _setup_heroai_junundu_node),

        # Groups 0-4: undead clusters around junundu entrance
        *[(f"Fight Group {i:02d}", _fight_group_builder(i)) for i in range(5)],

        # Pass-through path to Group 05 (HeroAI combat suppressed; hill enemies unreachable)
        ("Pass Through To Group 05", _pass_through_to_group_05),
        ("Fight Group 05", _fight_group_builder(5)),

        # Lightbringer Margonite Blessing (granted before first margonite group)
        ("Lightbringer Blessing", _lb_blessing_node),

        # Groups 6-19: margonites, djinn, ritualist bosses
        *[(f"Fight Group {i:02d}", _fight_group_builder(i)) for i in range(6, 20)],

        # Tome pickup at group-19 position (triggers quest update)
        ("Tome Pickup", _tome_pickup),

        # Groups 20-29: sixth/seventh margonites + temple monoliths
        *[(f"Fight Group {i:02d}", _fight_group_builder(i)) for i in range(20, 30)],

        # Boss spawn: approach then interact with the spawn gadget
        ("Boss Spawn Approach And Trigger", _boss_spawn_approach_and_trigger),

        # Final boss group (group 30)
        ("Fight Group 30 (Boss)", _fight_group_builder(30)),

        # Return, resign, and sell/restock via MerchantRules if anyone needs it.
        # _resign_node() itself checks whether we're still in the explorable and
        # resigns from there -- no separate TravelToOutpost first, since that call
        # can't do anything (and just hangs) while still in an explorable map.
        ("Resign", _resign_node),
        ("Inventory Check And Maintenance", _inventory_check_and_maintenance_node),
    ]

    return steps


# ── BottingTree factory ──────────────────────────────────────────────────────────

def _get_bot() -> BottingTree:
    global _botting_tree, _tree_party_mode
    _load_settings()

    if _botting_tree is not None and _tree_party_mode != _party_mode:
        _rebuild_tree_for_party_mode()

    if _botting_tree is None:
        # Native listener, second line of defense underneath BottingTree's own planner-
        # level enable_party_wipe_recovery: auto-returns the leader to the outpost on a
        # full party wipe. Matches Shards Of Orr's ensure_botting_tree(). LBSS sets
        # pause_on_combat=False below ("Junundu is always in combat"), so a full wipe
        # mid-fight is a real scenario here with nothing native catching it otherwise.
        Listeners.AutoReturnOnDefeat.Enable()

        def _configure(tree: BottingTree) -> None:
            tree.Config.ConfigureUpkeep(
                looting_enabled=True,
                auto_inventory_handler_enabled=True,
                enable_party_wipe_recovery=True,
                enable_outpost_imp_service=False,
                enable_explorable_imp_service=False,
            )
            tree.pause_on_combat = False  # Junundu is always in combat; planner must keep ticking

        multi_account = _is_multibox()
        # Named steps instead of one flat repeated Sequence: BottingTree's own UI already
        # renders a "Start At" / "Restart From" dropdown over GetNamedPlannerStepNames()
        # (see Py4GWCoreLib/botting_tree_src/ui.py), so wiring the farm run up this way
        # (matching Shards Of Orr BT test.py's get_execution_steps()) is what actually
        # turns that dropdown on for this bot -- no separate UI work needed. repeat=True
        # reuses BottingTreePlannerMixin's own loop-and-restart-current-step machinery in
        # place of the old manual RepeaterForeverNode wrapper.
        _botting_tree = BottingTree.Create(
            BotSettings.BOT_NAME,
            main_routine=_build_farm_sequence(),
            routine_name="LBSSFarmLoop",
            repeat=True,
            multi_account=multi_account,
            isolation_enabled=not multi_account,
            configure_fn=_configure,
        )
        _botting_tree.UI.override_draw_config(lambda: _draw_settings())
        _botting_tree.UI.override_draw_help(lambda: _draw_help())
        _tree_party_mode = _party_mode

    return _botting_tree


# ── Settings persistence ─────────────────────────────────────────────────────────

# Multibox mode persistence — commented out
# def _ensure_ini_key() -> str: ...
# def _load_mode_setting() -> None: ...
# def _save_mode_setting() -> None: ...


# ── UI ──────────────────────────────────────────────────────────────────────────

def _draw_settings():
    global _party_mode
    _load_settings()

    PyImGui.text("Bot Settings")
    PyImGui.separator()

    PyImGui.text("Party Mode")
    new_mode = PyImGui.radio_button("Single Account with Heroes", _party_mode, 0)
    PyImGui.same_line(0, 16)
    new_mode = PyImGui.radio_button("Multiboxing", new_mode, 1)

    if new_mode != _party_mode:
        _party_mode = int(new_mode)
        _save_settings()
        _rebuild_tree_for_party_mode()

    if _is_multibox():
        PyImGui.text_colored(
            "Multibox: alt accounts are summoned and invited automatically.",
            (0.6, 0.9, 1.0, 1.0),
        )
    else:
        PyImGui.text_colored(
            "Single account: heroes configured on the Heroes tab are loaded automatically.",
            (0.7, 1.0, 0.7, 1.0),
        )

    PyImGui.separator()
    _draw_inventory_maintenance_settings()


def _draw_inventory_maintenance_settings():
    global _inventory_maintenance_enabled, _inventory_min_free_slots, _inventory_min_id_kits, _inventory_min_salvage_kits

    PyImGui.text("Inventory Maintenance")

    changed = False
    value = PyImGui.checkbox("Run MerchantRules when inventory is low", _inventory_maintenance_enabled)
    if value != _inventory_maintenance_enabled:
        _inventory_maintenance_enabled = value
        changed = True

    if _inventory_maintenance_enabled:
        value = max(0, int(PyImGui.input_int("Minimum free slots", _inventory_min_free_slots)))
        if value != _inventory_min_free_slots:
            _inventory_min_free_slots = value
            changed = True

        value = max(0, int(PyImGui.input_int("Minimum ID kits (0 = disabled)", _inventory_min_id_kits)))
        if value != _inventory_min_id_kits:
            _inventory_min_id_kits = value
            changed = True

        value = max(0, int(PyImGui.input_int("Minimum salvage kits (0 = disabled)", _inventory_min_salvage_kits)))
        if value != _inventory_min_salvage_kits:
            _inventory_min_salvage_kits = value
            changed = True

        PyImGui.text_wrapped(
            "Checked when every account returns to the outpost. If any active account "
            "falls below a threshold, MerchantRules runs on ALL active accounts together."
        )

    if changed:
        _save_settings()


def _draw_help():
    title_color = Color(255, 200, 100, 255)
    ImGui.push_font("Regular", 20)
    PyImGui.text_colored(BotSettings.BOT_NAME, title_color.to_tuple_normalized())
    ImGui.pop_font()
    PyImGui.spacing()
    PyImGui.separator()
    PyImGui.text("Farms Lightbringer and Sunspear title points via Junundu wurms")
    PyImGui.text("in the Sulfurous Wastes. Kills all 31 mob groups per run.")
    PyImGui.spacing()
    PyImGui.text_colored("Requirements:", title_color.to_tuple_normalized())
    PyImGui.bullet_text("Start at Remains of Sahlahja outpost")
    PyImGui.bullet_text("Have the quest 'A Show of Force' active (recommended)")
    PyImGui.bullet_text("Have the quest 'Requiem for a Brain' active (recommended)")
    PyImGui.bullet_text("Rune of Doom in inventory (recommended)")
    PyImGui.bullet_text("Holy damage weapons equipped on player and heroes")
    PyImGui.bullet_text("Low-level heroes to share XP (optional)")
    PyImGui.spacing()
    PyImGui.text_colored("Credits:", title_color.to_tuple_normalized())
    PyImGui.bullet_text("Original AutoIt3 script by caustic-kronos (Kronos/Night/Svarog)")
    PyImGui.bullet_text("Py4GW port by george-ctrl")


def tooltip():
    PyImGui.begin_tooltip()
    title_color = Color(255, 200, 100, 255)
    ImGui.push_font("Regular", 20)
    PyImGui.text_colored(BotSettings.BOT_NAME, title_color.to_tuple_normalized())
    ImGui.pop_font()
    PyImGui.spacing()
    PyImGui.separator()
    PyImGui.text("Farms Lightbringer + Sunspear via Junundu in the Sulfurous Wastes.")
    PyImGui.spacing()
    PyImGui.text_colored("Requirements:", title_color.to_tuple_normalized())
    PyImGui.bullet_text("Remains of Sahlahja outpost")
    PyImGui.bullet_text("Credits: caustic-kronos (original Au3), george-ctrl, Northbound (Py4GW port)")
    PyImGui.end_tooltip()


# ── Hero config I/O ─────────────────────────────────────────────────────────────

def _load_hero_config():
    global _hero_slots, _hero_config_dirty, _hero_config_status
    if not os.path.exists(_HERO_CONFIG_PATH):
        _hero_config_status = ""
        return
    try:
        with open(_HERO_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        _hero_slots = _parse_hero_config_entries(raw)
        _hero_config_dirty = False
        _hero_config_status = "Loaded."
    except Exception as exc:
        _hero_config_status = f"Load error: {exc}"


def _save_hero_config():
    global _hero_config_dirty, _hero_config_status
    payload = [{"hero_id": int(s.hero_id), "template": s.template} for s in _hero_slots]
    try:
        os.makedirs(os.path.dirname(_HERO_CONFIG_PATH), exist_ok=True)
        with open(_HERO_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        _hero_config_dirty = False
        _hero_config_status = "Saved."
    except Exception as exc:
        _hero_config_status = f"Save error: {exc}"


def _reset_hero_config():
    global _hero_slots, _hero_config_dirty, _hero_config_status
    _hero_slots = [_PartyHeroSlot() for _ in range(_HERO_SLOTS_COUNT)]
    _hero_config_dirty = True
    _hero_config_status = "Reset to empty."


def _parse_hero_config_entries(raw) -> List[_PartyHeroSlot]:
    slots: List[_PartyHeroSlot] = []
    for i in range(_HERO_SLOTS_COUNT):
        entry = raw[i] if isinstance(raw, list) and i < len(raw) else {}
        hero_id = int(entry.get("hero_id", 0) or 0)
        if hero_id not in _HERO_ID_TO_OPTION_INDEX:
            hero_id = 0
        slots.append(_PartyHeroSlot(hero_id=hero_id, template=str(entry.get("template", "") or "")))
    return slots


def _list_importable_hero_configs() -> List[str]:
    try:
        files = [
            os.path.join(_BOT_SCRIPT_DIR, e)
            for e in os.listdir(_BOT_SCRIPT_DIR)
            if e.endswith(" Heroes.json") and os.path.isfile(os.path.join(_BOT_SCRIPT_DIR, e))
        ]
        files.sort(key=lambda p: os.path.basename(p).lower())
        return files
    except OSError:
        return []


def _hero_import_label(path: str) -> str:
    name = os.path.splitext(os.path.basename(path))[0]
    return name[:-7] if name.endswith(" Heroes") else name


def _import_hero_config(path: str):
    global _hero_slots, _hero_config_dirty, _hero_config_status
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        _hero_slots = _parse_hero_config_entries(raw)
        _hero_config_dirty = True
        _save_hero_config()
        _hero_config_status = f"Imported from {_hero_import_label(path)} and saved."
    except Exception as exc:
        _hero_config_status = f"Import error: {exc}"


def _get_hero_icon_path(hero_id: int) -> Optional[str]:
    try:
        hero_type = HeroType(hero_id)
    except ValueError:
        return None
    filename = _HERO_ICON_FILENAMES.get(hero_type)
    if not filename:
        return None
    path = os.path.join(_HERO_ICONS_BASE, filename)
    return path if os.path.exists(path) else None


def _draw_hero_icon(hero_id: int, size: int = 24):
    path = _get_hero_icon_path(hero_id)
    if path:
        try:
            cx, cy = PyImGui.get_cursor_screen_pos()
            ImGui.DrawTextureInDrawList(pos=(float(cx), float(cy)), size=(float(size), float(size)), texture_path=path)
        except Exception:
            try:
                ImGui.DrawTexture(texture_path=path, width=size, height=size)
            except Exception:
                pass
    PyImGui.dummy((int(size), int(size)))


def _draw_hero_combo(label: str, hero_id: int) -> int:
    current_index = _HERO_ID_TO_OPTION_INDEX.get(hero_id, 0)
    preview = _HERO_OPTION_LABELS[current_index]
    if PyImGui.begin_combo(label, preview, PyImGui.ImGuiComboFlags.NoFlag):
        for index, hero in enumerate(_HERO_OPTIONS):
            if hero != HeroType.None_:
                _draw_hero_icon(int(hero), size=20)
            else:
                PyImGui.dummy((20, 20))
            PyImGui.same_line(0.0, 8.0)
            if PyImGui.selectable(f"{_HERO_OPTION_LABELS[index]}##{label}_{index}", index == current_index, 0, [0.0, 0.0]):
                current_index = index
        PyImGui.end_combo()
    return int(_HERO_OPTIONS[current_index])


def _draw_hero_slot_editor(slot_index: int):
    global _hero_config_dirty
    slot = _hero_slots[slot_index]
    combo_label_width = 70.0

    PyImGui.text(f"Hero {slot_index + 1}")
    PyImGui.same_line(combo_label_width, 8.0)
    _draw_hero_icon(slot.hero_id, size=24)
    PyImGui.same_line(0.0, 8.0)
    PyImGui.set_next_item_width(PyImGui.get_content_region_avail()[0])
    new_hero_id = _draw_hero_combo(f"##hero_{slot_index}", slot.hero_id)
    if new_hero_id != slot.hero_id:
        slot.hero_id = new_hero_id
        if slot.hero_id == HeroType.None_.value:
            slot.template = ""
        elif not slot.template.strip():
            try:
                hero_type = HeroType(slot.hero_id)
            except ValueError:
                hero_type = HeroType.None_
            slot.template = _DEFAULT_HERO_TEMPLATES.get(hero_type, "")
        _hero_config_dirty = True

    PyImGui.text("Template")
    PyImGui.same_line(0.0, 8.0)
    if PyImGui.small_button(f"Clear##slot_{slot_index}"):
        if slot.hero_id != HeroType.None_.value or slot.template:
            slot.hero_id = HeroType.None_.value
            slot.template = ""
            _hero_config_dirty = True
    PyImGui.set_next_item_width(PyImGui.get_content_region_avail()[0])
    new_template = PyImGui.input_text(f"##template_{slot_index}", slot.template)
    if new_template != slot.template:
        slot.template = new_template
        _hero_config_dirty = True


def _draw_hero_settings_tab():
    global _hero_import_source_index
    PyImGui.text("Configure up to 7 heroes for Single Account mode.")
    PyImGui.push_style_color(PyImGui.ImGuiCol.Text, (0.7, 0.7, 0.7, 1.0))
    PyImGui.text("Heroes are added in order; duplicates and empty slots are skipped.")
    PyImGui.pop_style_color(1)
    PyImGui.spacing()

    if _hero_config_dirty:
        PyImGui.push_style_color(PyImGui.ImGuiCol.Text, (1.0, 0.8, 0.2, 1.0))
        PyImGui.text("Unsaved changes")
        PyImGui.pop_style_color(1)
    elif _hero_config_status:
        PyImGui.push_style_color(PyImGui.ImGuiCol.Text, (0.6, 0.9, 0.6, 1.0))
        PyImGui.text(_hero_config_status)
        PyImGui.pop_style_color(1)

    if PyImGui.button("Save", 100, 26):
        _save_hero_config()
    PyImGui.same_line(0, 8)
    if PyImGui.button("Reload", 100, 26):
        _load_hero_config()
    PyImGui.same_line(0, 8)
    if PyImGui.button("Reset", 100, 26):
        _reset_hero_config()

    import_paths = _list_importable_hero_configs()
    if import_paths:
        if _hero_import_source_index >= len(import_paths):
            _hero_import_source_index = 0
        import_labels = [_hero_import_label(p) for p in import_paths]
        _hero_import_source_index = PyImGui.combo("Import Team From", _hero_import_source_index, import_labels)
        if PyImGui.button("Import Team", 120, 26):
            _import_hero_config(import_paths[_hero_import_source_index])
    else:
        PyImGui.push_style_color(PyImGui.ImGuiCol.Text, (0.7, 0.7, 0.7, 1.0))
        PyImGui.text("Import Team: save another title bot hero lineup first.")
        PyImGui.pop_style_color(1)

    PyImGui.separator()
    if PyImGui.begin_child("HeroSlotsChild", (0, -1), True):
        for i in range(_HERO_SLOTS_COUNT):
            _draw_hero_slot_editor(i)
            if i < _HERO_SLOTS_COUNT - 1:
                PyImGui.separator()
    PyImGui.end_child()


# ── Title statistics ─────────────────────────────────────────────────────────────

_session_baselines: dict[str, dict[str, int]] = {}
_session_start_times: dict[str, float] = {}


def _get_title_track_accounts():
    accounts = list(GLOBAL_CACHE.ShMem.GetAllAccountData())
    if _is_multibox():
        return accounts
    own_email = Player.GetAccountEmail()
    filtered = [a for a in accounts if getattr(a, "AccountEmail", "") == own_email]
    if filtered:
        return filtered
    own_name = Player.GetName()
    filtered = [a for a in accounts if getattr(a.AgentData, "CharacterName", "") == own_name]
    return filtered if filtered else (accounts[:1] if len(accounts) == 1 else [])


def _draw_single_title(name: str, pts: int, tiers, label: str):
    tier_name = "Unranked"
    tier_rank = 0
    tier_max_rank = len(tiers)
    next_required = tiers[0].required if tiers else 0
    for i, tier in enumerate(tiers):
        if pts >= tier.required:
            tier_rank = i + 1
            tier_name = tier.name
            next_required = tiers[i + 1].required if i + 1 < len(tiers) else tier.required
        else:
            next_required = tier.required
            break
    is_maxed = bool(tiers) and pts >= tiers[-1].required
    tier_missing = max(next_required - pts, 0)

    PyImGui.text(f"{label}: {tier_name} [{tier_rank}/{tier_max_rank}]")
    PyImGui.text(f"Total Points: {pts:,}")
    if is_maxed:
        PyImGui.text("Next Rank: Maxed")
        PyImGui.progress_bar(1.0, -1, 0, "Complete")
        PyImGui.text_colored("Maximum rank achieved.", (0.4, 1.0, 0.4, 1.0))
    else:
        PyImGui.text(f"Points To Go: {tier_missing:,}")
        frac = min(pts / max(next_required, 1), 1.0)
        PyImGui.progress_bar(frac, -1, 0, f"{pts:,} / {next_required:,}")


def _draw_title_track():
    global _session_baselines, _session_start_times
    now = time.time()
    accounts = _get_title_track_accounts()
    if not accounts:
        PyImGui.text("No local account statistics available yet.")
        return

    lb_tiers  = TITLE_TIERS.get(TitleID.Lightbringer, [])
    ss_tiers  = TITLE_TIERS.get(TitleID.Sunspear, [])
    lb_idx = int(TitleID.Lightbringer)
    ss_idx = int(TitleID.Sunspear)

    for account in accounts:
        char_name = account.AgentData.CharacterName
        lb_pts = account.TitlesData.Titles[lb_idx].CurrentPoints
        ss_pts = account.TitlesData.Titles[ss_idx].CurrentPoints

        if char_name not in _session_baselines:
            _session_baselines[char_name] = {"lb": lb_pts, "ss": ss_pts}
            _session_start_times[char_name] = now

        bl = _session_baselines[char_name]
        elapsed = now - _session_start_times[char_name]
        formatted_time = time.strftime('%H:%M:%S', time.gmtime(elapsed))

        lb_gained = lb_pts - bl["lb"]
        ss_gained = ss_pts - bl["ss"]
        lb_hr = int(lb_gained / elapsed * 3600) if elapsed > 0 else 0
        ss_hr = int(ss_gained / elapsed * 3600) if elapsed > 0 else 0

        PyImGui.separator()
        ImGui.push_font("Regular", 18)
        PyImGui.text(f"Statistics – {char_name}")
        ImGui.pop_font()
        PyImGui.spacing()

        _draw_single_title(char_name, lb_pts, lb_tiers, "Lightbringer")
        PyImGui.text(f"  +{lb_gained:,} pts ({lb_hr:,}/hr)")
        PyImGui.spacing()
        _draw_single_title(char_name, ss_pts, ss_tiers, "Sunspear")
        PyImGui.text(f"  +{ss_gained:,} pts ({ss_hr:,}/hr)")
        PyImGui.spacing()
        PyImGui.text(f"Session running: {formatted_time}")


# ── Main ─────────────────────────────────────────────────────────────────────────

_hero_config_loaded = False
_EXPANDED_TAB_CHILD_SIZE = (500, 620)


def _draw_statistics_tab() -> None:
    if PyImGui.begin_child("LBSSStatisticsTabChild", _EXPANDED_TAB_CHILD_SIZE, False):
        _draw_title_track()
    PyImGui.end_child()


def _draw_heroes_tab() -> None:
    if PyImGui.begin_child("LBSSHeroesTabChild", _EXPANDED_TAB_CHILD_SIZE, False):
        _draw_hero_settings_tab()
    PyImGui.end_child()


def main():
    global _hero_config_loaded
    if not _hero_config_loaded:
        _load_hero_config()
        _hero_config_loaded = True
    if Map.IsMapLoading():
        return
    bot = _get_bot()
    bot.tick()

    if bot.IsStarted() and _diag_timer.IsExpired():
        _diag_timer.Reset()
        bb = bot.GetBlackboardValue
        px, py = Agent.GetXY(Player.GetAgentID())
        PySystem.Console.Log(MODULE_NAME,
            f"[Diag] pos=({px:.0f},{py:.0f})"
            f" combat={bb('COMBAT_ACTIVE', False)}"
            f" casting={Agent.IsCasting(Player.GetAgentID())}"
            f" pause_mv={bb('PAUSE_MOVEMENT', False)}"
            f" planner={bb('PLANNER_STATUS','?')}"
            f" move_state={bb('move_state','?')}"
            f" move_reason={bb('move_current_pause_reason','')}"
            f" stall={bb('move_stall_retry_count',0)}",
            PySystem.Console.MessageType.Info)
    bot.UI.draw_window(
        icon_path=BotSettings.TEXTURE,
        extra_tabs=[
            ("Statistics", _draw_statistics_tab),
            ("Heroes",     _draw_heroes_tab),
        ],
    )


if __name__ == "__main__":
    main()
