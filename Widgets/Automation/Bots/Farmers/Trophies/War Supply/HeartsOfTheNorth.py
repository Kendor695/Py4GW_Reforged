import PyImGui
from typing import Literal, Callable
from dataclasses import dataclass
import time

from Py4GW_widget_manager import get_widget_handler
from Py4GWCoreLib.Builds.Any.KeiranThackerayEOTN import KeiranThackerayEOTN
from Py4GWCoreLib import (GLOBAL_CACHE, Routines, Range, Py4GW, ConsoleLog, ModelID, Botting,
                          Map, ImGui, ActionQueueManager, Agent, Player, AgentArray,
                          Pathing, TitleID, TITLE_TIERS)
from Py4GWCoreLib import *
from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

MODULE_NAME = "Hearts of the North - Keiran Missons (War Supplies)"
MODULE_ICON = "Textures\\Module_Icons\\Keiran Farm.png"
MODULE_TAGS = ["War","Supply", "Keiran", "AB", "Rise", "EOTN", "HotN"]

_HOTN_DIALOG_BASE_OFFSET = 0xE  # first HotN mission (AB) is always base_id + 0xE; each subsequent mission adds 1

@dataclass
class MissionConfig:
    name: str
    map_id: int
    mission_slot: int           # 0=AB, 1=AVoB, 2=SitJ, 3=Rise â€” added to base_id + 0xE at runtime
    run_movement_fn: Callable   # fn(bot: Botting) -> adds mission-specific movement states


@dataclass
class MissionStats:
    successful_runs: int         = 0
    failed_runs: int             = 0
    total_run_time: float        = 0.0
    fastest_run: float           = float('inf')
    slowest_run: float           = 0.0

    @property
    def total_runs(self) -> int:
        return self.successful_runs + self.failed_runs

    def success_rate(self) -> str:
        if self.total_runs == 0:
            return "0.00%"
        return f"{self.successful_runs / self.total_runs * 100:.2f}%"

    def average_time(self) -> str:
        if self.successful_runs == 0:
            return "--:--"
        return _format_time(self.total_run_time / self.successful_runs)

    def fastest_time(self) -> str:
        return _format_time(self.fastest_run)

    def slowest_time(self) -> str:
        return _format_time(self.slowest_run)


class BotSettings:
    # Map/Outpost IDs
    EOTN_OUTPOST_ID = 642
    HOM_OUTPOST_ID = 646

    # Mission selection (set before starting the bot)
    SELECTED_MISSION: str = "Auspicious Beginnings"

    # Sequence mode
    SEQUENCE_MODE: bool = False
    SEQUENCE_INDEX: int = 0

    # Custom Bow ID - If this is left 0 you will automatically craft a suitable bow.
    CUSTOM_BOW_ID: int = 0

    # Gold threshold for deposit
    GOLD_THRESHOLD_DEPOSIT: int = 90000

    # If free inventory slots drop below this, detour to EOTN so AutoInventoryHandler
    # (Inventory Plus) can identify/salvage/deposit before the bags actually fill up.
    MANAGE_INVENTORY_ON_LOW_SLOTS: bool = True
    LOW_SLOTS_THRESHOLD: int = 10

    # Identify+triage pass run whenever the bot is in EOTN: sells everything
    # except declared keepers (Superior Vigor runes, black/white dyes, double
    # vamp weapons, maxed non-inscribable gold weapons/shields). Starts in
    # dry-run (log only, nothing actually sold) until verified correct.
    INVENTORY_TRIAGE_DRY_RUN: bool = True

    # Whether triage keeps materials (deposited to storage) or sells them off
    # like everything else. Wood Planks are always sold regardless of this.
    KEEP_MATERIALS: bool = True

    # Whether triage keeps black/white dyes (deposited to storage) instead of
    # selling them like every other dye colour.
    KEEP_DYES: bool = True

    # Whether triage extracts+keeps Superior Vigor runes (+50 HP) instead of
    # selling them as-is.
    KEEP_VIGOR_RUNES: bool = True

    # Whether triage keeps "double vamp" weapons (inherent Vampiric mod +
    # Vampiric prefix/inscription stacked) instead of selling them.
    KEEP_DOUBLE_VAMP: bool = True

    # Whether triage keeps maxed non-inscribable gold weapons/shields instead
    # of selling them.
    KEEP_MAXED_GOLD: bool = True

    # Master override: when on, every optional keep-rule above (materials,
    # dyes, vigor runes, double vamp, maxed non-inscribable gold) is ignored
    # and triage sells everything sellable. Kits/consumables/lockpicks are
    # never touched by this -- they're excluded from triage entirely for
    # functional reasons, not value ones.
    SELL_EVERYTHING: bool = False

    # Whether to spend excess gold (character >=90k with >=800k already in
    # storage) buying Globs of Ectoplasm from the rune trader. Purely
    # discretionary -- turning it off just leaves the excess gold on the
    # character to keep depositing normally.
    BUY_ECTOS_ENABLED: bool = True

    # Properties to enable/disable via setting tab
    WAR_SUPPLIES_ENABLED: bool = False

    # Runs counters
    TOTAL_RUNS: int = 0
    SUCCESSFUL_RUNS: int = 0
    FAILED_RUNS: int = 0

    # Material purchases
    ECTOS_BOUGHT: int = 0

    # Vanguard title cache (populated at start and after each successful run)
    VANGUARD_RANK: int = 0
    VANGUARD_TIER_NAME: str = "â€“"
    VANGUARD_POINTS: int = 0

    # Run timing
    CURRENT_RUN_START_TIME: float = 0.0
    TOTAL_RUN_TIME: float = 0.0
    FASTEST_RUN: float = float('inf')
    SLOWEST_RUN: float = 0.0

    # Per-mission stats (populated after MISSIONS dict is defined)
    MISSION_STATS: dict = None  # type: ignore[assignment]

    # Misc
    DEBUG: bool = False

    # UI
    SHOW_HELP: bool = True



# Module-level UI state (not persisted)
_reset_confirm:               bool            = False
_settings_ini:                Settings|None = None
_settings_ini_account_email:  str             = ""
_save_requested:              bool            = False

# ---------------------------------------------------------------------------
# Per-mission movement routines
# ---------------------------------------------------------------------------

# BUGFIX (2026-09-03): bot.Wait.UntilOnCombat() (Py4GWCoreLib/botting_src/
# subclases_src/WAIT_src.py) resolves to _coro_until_condition(), a bare
# `while True:` loop with no timeout at all -- it blocks the entire FSM
# forever if InDanger() never becomes True. Confirmed live: an account sat
# frozen at fsm_state=WasteTimeUntilOnCombat_4, position never leaving the
# mission's own spawn point, for 12+ minutes straight.
#
# REVERTED (2026-09-04): the 45s-timeout replacement (bounded custom state,
# commit d822bed0) caused a far worse regression -- 100% run failure across
# all 5 accounts for 2.5+ hours straight, every single run dying ~60-160s
# after map load instead of freezing. Read: InDanger() gates an ambush at
# (11714,-4590) the mission needs the party to actually fight in place;
# forcing movement onward after 45s regardless of combat state pulled the
# party out of position mid-fight (or before the ambush even triggered)
# straight into a wipe. Back to the unbounded wait -- it hangs rarely (one
# confirmed 12-minute freeze) but that beats a guaranteed death every run.
# If the freeze recurs, fix it with a smarter/longer grace (e.g. only give
# up once the player is ALSO stationary/not casting, not just "no combat
# yet"), not a short deadline that yanks movement mid-fight.
def _run_ab_movement(bot: Botting) -> None:
    bot.Wait.ForMapLoad(849)
    bot.Move.XY(11714,-4590)
    bot.Wait.UntilOnCombat()
    bot.Move.XY(9973,-6394)
    bot.Move.XY(8448,-8676)
    bot.Move.XY(4284,-7384)
    bot.Move.XY(2442,-9532)
    bot.Move.XY(948,-11427)
    bot.Move.XY(-1605,-11181)
    bot.Move.XY(-2279,-9099)
    bot.Move.XY(-5688,-10252)
    bot.Move.XY(-9311,-8500)
    bot.Move.XY(-12904,-7805)
    bot.Move.XY(-15338,-8893)
    bot.Wait.ForTime(10000)
    bot.Move.XY(-17952,-8940)

def _run_avob_movement(bot: Botting) -> None:
    bot.Properties.Disable("hero_ai")
    bot.Move.XY(15827,3742)
    bot.Move.XY(17666,5247)
    bot.Properties.Enable("hero_ai")
    bot.Move.XY(15484,3559)
    bot.Move.XY(16680,360)
    bot.Move.XY(15511,-2017)
    bot.Move.XY(10577,-1307)
    bot.Move.XY(9088,-3635)
    bot.Move.XY(7230,-2052)
    bot.Move.XY(6990,2470)
    bot.Move.XY(5819,4335)
    bot.Move.XY(2972,2707)
    bot.Move.XY(903,345)
    bot.Move.XY(-4050,-1905)
    bot.Move.XY(-7441,-2538)
    bot.Move.XY(-11014,-744)
    bot.Move.XY(-14120,1656)
    bot.Move.XY(-16702,-202)
    bot.Move.XY(-20921,418)
    bot.Wait.UntilOnCombat()
    bot.Move.XY(-22694,1015)

def _run_sitj_movement(bot: Botting) -> None:
    bot.Move.XY(-8661,-4032)
    bot.Move.XY(-6092,-4463)
    bot.Move.XY(-3489,-1162)
    bot.Move.XY(-2386,3966)
    bot.Move.XY(-6606,8215)
    bot.Move.XY(-4914,11700)
    bot.Move.XY(-65,12308)
    bot.Properties.Disable("hero_ai")
    bot.Move.XY(1165,10230)
    bot.Properties.Enable("hero_ai")
    bot.Move.XY(4549,10181)
    bot.Move.XY(7136,6288)
    bot.Move.XY(6073,3836)
    bot.Move.XY(7478,2800)
    bot.Move.XY(10116,4081)
    bot.Move.XY(12126,2201)
    bot.Move.XYAndInteractNPC(12047, 380)

def _run_rise_movement(bot: Botting) -> None:
    bot.Move.XY(21501.29, -11654.24, "First Group")
    bot.Wait.UntilOnCombat()
    bot.Move.XY(17606.40, -10386.07, "Second Group")
    bot.Wait.UntilOnCombat()
    bot.Move.XY(21501.29, -11654.24, "Third Group")
    bot.Wait.UntilOnCombat()
    bot.Move.XY(18833.73, -10746.32, "Fourth Group")
    bot.Wait.UntilOnCombat()
    bot.Move.XY(21501.29, -11654.24, "Fifth Group")
    bot.Wait.UntilOnCombat()
    bot.Move.XY(19678.33, -11051.54, "Sixth Group")
    bot.Wait.UntilOnCombat()
    bot.Move.XY(21501.29, -11654.24, "Seventh Group")
    bot.Wait.UntilOnCombat()
    bot.Move.XY(18833.73, -10746.32, "Eighth Group")
    bot.Wait.UntilOnCombat()

# ---------------------------------------------------------------------------
# Mission registry
# ---------------------------------------------------------------------------

MISSIONS: dict[str, MissionConfig] = {
    "Auspicious Beginnings": MissionConfig(
        name="Auspicious Beginnings",
        map_id=849,
        mission_slot=0,
        run_movement_fn=_run_ab_movement,
    ),
    "A Vengance of Blades - WIP": MissionConfig(
        name="A Vengance of Blades - WIP",
        map_id=848,
        mission_slot=1,
        run_movement_fn=_run_avob_movement,
    ),
    "Shadows in the Jungle - WIP": MissionConfig(
        name="Shadows in the Jungle - WIP",
        map_id=847,
        mission_slot=2,
        run_movement_fn=_run_sitj_movement,
    ),
    "Rise - WIP": MissionConfig(
        name="Rise - WIP",
        map_id=846,
        mission_slot=3,
        run_movement_fn=_run_rise_movement,
    ),
}

MISSION_NAMES = list(MISSIONS.keys())

# Per-mission stats storage and short INI key prefixes
BotSettings.MISSION_STATS = {name: MissionStats() for name in MISSION_NAMES}
_MISSION_INI_PREFIX: dict[str, str] = {
    "Auspicious Beginnings":       "ab",
    "A Vengance of Blades - WIP":  "avob",
    "Shadows in the Jungle - WIP": "sitj",
    "Rise - WIP":                  "rise",
}

_MISSION_COL_LABEL: dict[str, str] = {
    "Auspicious Beginnings":       "AB",
    "A Vengance of Blades - WIP":  "AVoB",
    "Shadows in the Jungle - WIP": "SinJ",
    "Rise - WIP":                  "Rise",
}

# Fixed order for sequence mode: AB â†’ AVoB â†’ SitJ â†’ Rise
SEQUENCE_ORDER: list[str] = [
    "Auspicious Beginnings",
    "A Vengance of Blades - WIP",
    "Shadows in the Jungle - WIP",
    "Rise - WIP",
]

# Gate state names used by the runtime dispatcher in RunQuest
_MISSION_GATE_NAMES: dict[str, str] = {
    "Auspicious Beginnings":       "GateAB",
    "A Vengance of Blades - WIP":  "GateAVoB",
    "Shadows in the Jungle - WIP": "GateSitJ",
    "Rise - WIP":                  "GateRise",
}


def _get_active_mission() -> MissionConfig:
    """Returns the mission to run this iteration (sequence-aware)."""
    if BotSettings.SEQUENCE_MODE:
        return MISSIONS[SEQUENCE_ORDER[BotSettings.SEQUENCE_INDEX]]
    return MISSIONS[BotSettings.SELECTED_MISSION]


def _advance_sequence() -> None:
    """Advance to the next mission in the sequence (wraps around)."""
    BotSettings.SEQUENCE_INDEX = (BotSettings.SEQUENCE_INDEX + 1) % len(SEQUENCE_ORDER)
    BotSettings.SELECTED_MISSION = SEQUENCE_ORDER[BotSettings.SEQUENCE_INDEX]
    if BotSettings.DEBUG:
        print(f"[DEBUG] Sequence advanced to: {BotSettings.SELECTED_MISSION}")


# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

_keiran_build = KeiranThackerayEOTN(debug_fn=lambda: BotSettings.DEBUG)
bot = Botting("Hearts of the North", custom_build=_keiran_build)
_keiran_build.set_fsm(bot.config.FSM)
bot.config.reset_pause_on_danger_fn(aggro_area=Range.Longbow)


def create_bot_routine(bot: Botting) -> None:
    widget_handler = get_widget_handler()
    if not widget_handler.is_widget_enabled("Return to outpost on defeat"):
        widget_handler.enable_widget("Return to outpost on defeat")

    # "Messaging" must stay ON: the framework's own upkeep_auto_loot()
    # coroutine (auto_loot is active by default, botting_src/property.py)
    # sends itself a PickUpLoot command over the ShMem message bus after
    # every fight, but Messaging.py's ProcessMessages() is the ONLY consumer
    # of that message (see PickUpLoot() in Widgets/System/Messaging.py). With
    # Messaging disabled, that message is never processed, the loot never
    # gets picked up, and bot.Move.XY's FollowPath then pauses forever on its
    # own loot_pause() check (MOVE_src.py) because there's still lootable
    # trophies within earshot -- the bot freezes right next to unlooted loot
    # after every group. This was disabled at one point to silence a known
    # Hero AI snapshot-stack spam bug in Messaging.py (py4gw-botting-gotchas
    # skill, entry #41; narrow try/finally leak fix already applied there,
    # but did not fully resolve the spam live) -- re-enabled here because
    # losing loot pickup on a trophy farmer is worse. If the snapshot spam
    # reappears, that gotcha entry is the place to pick the investigation
    # back up.
    if not widget_handler.is_widget_enabled("Messaging"):
        widget_handler.enable_widget("Messaging")

    # This bot installs its own full custom combat build (KeiranThackerayEOTN)
    # and drives its hero party members via the native hero_ai property/struct
    # fields directly (see bot.Templates.AggressiveForceHeroAI calls below).
    # The standalone "HeroAI" widget (Widgets/Automation/Multiboxing/HeroAI.py)
    # runs its OWN independent HeroAI_Build with its own combat/loot
    # BehaviorTree -- having both active fights over the same account at once
    # (confirmed: HeroAI's LootingNode bails out whenever its own separate
    # in_aggro tracking is stuck true, which this dual-build conflict can
    # cause). This toggle only fires when THIS bot's script launches, so it
    # never touches the widget's state on other accounts that use it on
    # purpose.
    if widget_handler.is_widget_enabled("HeroAI"):
        widget_handler.disable_widget("HeroAI")

    InitializeBot(bot)
    def _initial_vanguard_scan():
        _update_vanguard_cache()
        yield
    bot.States.AddCustomState(lambda: _initial_vanguard_scan(), "ScanVanguardRank")
    GoToEOTN(bot)
    GetBonusBow(bot)
    QuestLoopEntry(bot)


def QuestLoopEntry(bot: Botting) -> None:
    """Main quest loop: checks gold, deposits if needed, then runs the selected mission."""
    CheckAndDepositGold(bot)
    ExitToHOM(bot)
    PrepareForQuest(bot)
    EnterQuest(bot)
    RunQuest(bot)


# ---------------------------------------------------------------------------
# Death handling
# ---------------------------------------------------------------------------

def _on_death(bot: "Botting"):
    _increment_runs_counters(bot, "fail")
    bot.Properties.ApplyNow("pause_on_danger", "active", False)
    bot.Properties.ApplyNow("halt_on_death", "active", True)
    bot.Properties.ApplyNow("movement_timeout", "value", 15000)
    bot.Properties.ApplyNow("hero_ai", "active", False)
    yield from Routines.Yield.wait(3000)

    # Auspicious Beginnings is an explorable-area quest, not an instanced mission:
    # a full party wipe does NOT auto-teleport back to the outpost. The "You have
    # been defeated" screen needs an explicit GLOBAL_CACHE.Party.ReturnToOutpost()
    # call (normally issued by the "Return to outpost on defeat" widget). That
    # widget isn't guaranteed to be present/enabled, so retry the call directly
    # here instead of depending on it and passively waiting for a map load that
    # may never happen on its own.
    #
    # Retries indefinitely rather than giving up after a fixed window: for
    # unattended multi-account farming, a bot that stops itself on a slow
    # recovery just silently sits idle until someone notices -- across 5+
    # accounts that could be hours. Keep trying and log periodically instead.
    last_attempt = 0.0
    last_log = time.time()
    # GLOBAL_CACHE.Party.ReturnToOutpost() only has any effect after a genuine
    # full party wipe (GLOBAL_CACHE.Party.IsPartyDefeated()) -- the reference
    # "Return to outpost on defeat" widget gates the exact same call on that
    # flag. A solo player death with heroes/henchmen still fighting doesn't
    # wipe the party: the player can get revived (hero rez, res signet, etc.)
    # right back onto the SAME explorable map, and this loop's original only
    # exit condition (arriving at HOM) then never becomes true -- the retried
    # ReturnToOutpost() call just keeps being a no-op forever, freezing the
    # bot indefinitely. Detect that case directly: nobody in the party is
    # dead anymore, but we're still not in HOM. A short grace window guards
    # against the single-frame gap right as a genuine wipe's death flags
    # clear during the transition.
    _alive_since: float | None = None
    _REVIVED_WITHOUT_WIPE_GRACE_S = 3.0
    while True:
        # Hall of Monuments is an explorable zone, not a town/outpost (no merchant,
        # no Xunlai storage -- that's Eye of the North). Don't gate this on
        # Routines.Checks.Map.IsOutpost(): if the game engine doesn't classify HOM
        # as InstanceType.Outpost, that check never passes even after genuinely
        # arriving.
        if Map.GetMapID() == BotSettings.HOM_OUTPOST_ID and Routines.Checks.Map.MapValid():
            break
        now = time.time()
        if not Routines.Checks.Party.IsPartyMemberDead():
            if _alive_since is None:
                _alive_since = now
            elif now - _alive_since >= _REVIVED_WITHOUT_WIPE_GRACE_S:
                ConsoleLog(
                    MODULE_NAME,
                    "[OnDeath] Revived without a party wipe -- resuming in place instead of waiting for HOM.",
                    PySystem.Console.MessageType.Warning,
                )
                break
        else:
            _alive_since = None
        if now - last_attempt >= 2.0:
            GLOBAL_CACHE.Party.ReturnToOutpost()
            last_attempt = now
        if now - last_log >= 60.0:
            ConsoleLog(MODULE_NAME, "[OnDeath] Still trying to return to HOM...", PySystem.Console.MessageType.Warning)
            last_log = now
        yield from Routines.Yield.wait(500)

    bot.Properties.ApplyNow("halt_on_death", "active", False)
    fsm = bot.config.FSM
    if Map.GetMapID() == BotSettings.HOM_OUTPOST_ID:
        fsm.jump_to_state_by_name("[H]Prepare for Quest_5")
    fsm.resume()
    yield


def on_death(bot: "Botting"):
    print("Player is dead. Run Failed, Restarting...")
    ActionQueueManager().ResetAllQueues()
    fsm = bot.config.FSM
    fsm.pause()
    fsm.AddManagedCoroutine("OnDeath", _on_death(bot))


def _handle_unmanaged_fail(bot: "Botting") -> bool:
    """Recover from an unmanaged failure (e.g. a stuck dialog or a map load
    that never completes) the same way a death recovers, instead of accepting
    the framework's default behavior of stopping the bot outright.

    For unattended multi-account farming, a bot that stops itself just sits
    idle until someone happens to notice -- across 5+ accounts that could be
    hours. _on_death()'s recovery (return to HOM, resume the quest loop) is
    exactly the right fix here too: the trigger differs, but "something went
    wrong, get back to a known-good state and keep going" is the same job.
    """
    ConsoleLog(MODULE_NAME, "[UnmanagedFail] Recovering instead of stopping.", PySystem.Console.MessageType.Warning)
    ActionQueueManager().ResetAllQueues()
    fsm = bot.config.FSM
    fsm.pause()
    fsm.AddManagedCoroutine("UnmanagedFailRecovery", _on_death(bot))
    return False  # tell the framework NOT to stop the bot -- recovery above handles it


# ---------------------------------------------------------------------------
# Combat templates
# ---------------------------------------------------------------------------

def _enable_combat(bot: Botting) -> None:
    bot.OverrideBuild(KeiranThackerayEOTN(fsm=bot.config.FSM, debug_fn=lambda: BotSettings.DEBUG))
    bot.Templates.AggressiveForceHeroAI(enable_imp=False)
def _disable_combat(bot: Botting) -> None:
    bot.Templates.PacifistForceAutocombat()


# ---------------------------------------------------------------------------
# Shared bot states
# ---------------------------------------------------------------------------

def InitializeBot(bot: Botting) -> None:
    condition = lambda: on_death(bot)
    bot.Events.OnDeathCallback(condition)
    # Gold/green sales (e.g. maxed non-inscribable golds triage decides not to
    # keep) would otherwise pop a confirmation dialog that nothing here clicks
    # through, silently stalling the sale. This memory-patch listener removes
    # that prompt at the source instead of trying to detect/accept a window.
    Listeners.DisableGoldConfirmation.Enable()
    # See _handle_unmanaged_fail(): recover instead of letting the framework
    # stop the bot on any unmanaged failure (stuck dialog, map load timeout, etc).
    bot.helpers.Events.set_on_unmanaged_fail(lambda: _handle_unmanaged_fail(bot))


def _load_navmesh_object(bot) -> None:
    """Schedule async navmesh load for the current map into AutoPathing's internal cache."""
    try:
        if AutoPathing().get_navmesh() is not None:
            return  # Already loaded for this map
    except Exception as e:
        PySystem.Console.Log("Navmesh", f"Navmesh check failed: {e}", PySystem.Console.MessageType.Warning)
    def _load_coro():
        yield from AutoPathing().load_pathing_maps()
    GLOBAL_CACHE.Coroutines.append(_load_coro())


def GoToEOTN(bot: Botting) -> None:
    bot.States.AddHeader("Go to EOTN")

    def _go_to_eotn(bot: Botting):
        current_map = Map.GetMapID()
        should_skip_travel = current_map in [BotSettings.EOTN_OUTPOST_ID, BotSettings.HOM_OUTPOST_ID]
        if should_skip_travel:
            if BotSettings.DEBUG:
                print(f"[DEBUG] Already in EOTN or HOM, skipping travel")
            return

        Map.Travel(BotSettings.EOTN_OUTPOST_ID)
        yield from Routines.Yield.Map.WaitforMapLoad(BotSettings.EOTN_OUTPOST_ID, timeout=15000)
        bot.Party.SetHardMode(False)

    bot.States.AddCustomState(lambda: _go_to_eotn(bot), "GoToEOTN")

def GetBonusBow(bot: Botting):
    bot.States.AddHeader("Check for Bonus Bow")

    def _bow_gate():
        if BotSettings.CUSTOM_BOW_ID != 0 or _is_model_owned(11723):
            bot.config.FSM.jump_to_state_by_name("BowCraftEnd")
        yield

    bot.States.AddCustomState(_bow_gate, "BowCraftGate")
    bot.Map.Travel(194)
    bot.Move.XY(1592.00, -796.00)
    bot.Items.WithdrawGold(10000)
    bot.Move.XYAndInteractNPC(1592.00, -796.00)
    bot.States.AddCustomState(BuyLongbowMaterials, "Buy Weapon Materials")
    bot.Wait.ForTime(1500)
    bot.Move.XYAndInteractNPC(-1387.00, -3910.00)
    bot.Wait.ForTime(1000)
    bot.States.AddCustomState(lambda: DoCraftLongbow(bot), "Craft Weapons")
    bot.States.AddCustomState(_noop_gate, "BowCraftEnd")

_LONGBOW_DATA = {
    "buy":    [(ModelID.Wood_Plank.value, 10), (ModelID.Feather.value, 5)],
    "pieces": [(11723, [ModelID.Wood_Plank.value, ModelID.Feather.value], [100, 50])],
}

def BuyLongbowMaterials():
    for mat, count in _LONGBOW_DATA["buy"]:
        for _ in range(count):
            yield from Routines.Yield.Merchant.BuyMaterial(mat)

def DoCraftLongbow(bot: Botting):
    for weapon_id, mats, qtys in _LONGBOW_DATA["pieces"]:
        result = yield from Routines.Yield.Items.CraftItem(weapon_id, 5000, mats, qtys)
        if not result:
            ConsoleLog("DoCraftWeapon", f"Failed to craft weapon ({weapon_id}).", PySystem.Console.MessageType.Error)
            bot.helpers.Events.on_unmanaged_fail()
            return False
        yield
        result = yield from Routines.Yield.Items.EquipItem(weapon_id)
        if not result:
            ConsoleLog("DoCraftWeapon", f"Failed to equip weapon ({weapon_id}).", PySystem.Console.MessageType.Error)
            bot.helpers.Events.on_unmanaged_fail()
            return False
        yield
    return True


def _count_free_bag_slots() -> int:
    """Count free slots across the 4 standard bags directly.

    GLOBAL_CACHE.Inventory.GetFreeSlotCount() (via GetInventorySpace()) sums
    bag.GetItemCount() per bag -- observed in testing to always report 0
    items regardless of actual contents, so it always returns full bag
    capacity (e.g. 60) no matter how full the bags really are. Count items
    directly with ItemArray instead, which reads real bag contents correctly
    (already relied on elsewhere in this file for the Equipment Pack checks).
    """
    total_capacity = sum(GLOBAL_CACHE.Inventory.GetBagSize(bag_id) for bag_id in (1, 2, 3, 4))
    total_items = len(ItemArray.GetItemArray(ItemArray.CreateBagList(1, 2, 3, 4)))
    return max(total_capacity - total_items, 0)


def _is_sellable_junk(item_id: int) -> bool:
    """White-rarity items eligible to sell off to free a slot.

    Excludes ID kits, salvage kits (base/lesser/expert/perfect), consumables
    (usables), lockpicks, and materials (rare or not, except Wood Planks --
    see _triage_keep_reason) -- selling any of those away would either break
    AutoInventoryHandler's own tooling (it needs a spare kit to
    salvage/identify with) or throw away things worth keeping.
    """
    if not Item.Rarity.IsWhite(item_id):
        return False
    if Item.Usage.IsIDKit(item_id):
        return False
    if (Item.Usage.IsSalvageKit(item_id) or Item.Usage.IsLesserKit(item_id)
            or Item.Usage.IsExpertSalvageKit(item_id) or Item.Usage.IsPerfectSalvageKit(item_id)):
        return False
    if Item.Usage.IsUsable(item_id):
        return False
    if Item.GetModelID(item_id) == ModelID.Lockpick.value:
        return False
    if (BotSettings.KEEP_MATERIALS and Item.GetModelID(item_id) != ModelID.Wood_Plank.value
            and (Item.Type.IsMaterial(item_id) or Item.Type.IsRareMaterial(item_id))):
        return False
    if Item.GetItemType(item_id)[1] == "Dye":
        return False
    return True


def _is_superior_vigor_rune(item_id: int) -> bool:
    """Keep: Rune of Superior Vigor (+50 HP)."""
    return any(name == "RuneOfSuperiorVigor" for name, _slot in Item.Mods.GetUpgrades(item_id))


def _is_keeper_dye(item_id: int) -> bool:
    """Keep: black and white dye vials specifically -- other colours are sold."""
    if Item.GetItemType(item_id)[1] != "Dye":
        return False
    return Item.Dye.GetColor(item_id) in (DyeColor.Black, DyeColor.White)


def _is_double_vamp_weapon(item_id: int) -> bool:
    """Keep: a "double vamp" weapon -- an inherent Vampiric weapon mod
    (damage +14-15%, health regeneration -1) stacked with a separate
    Vampiric prefix/inscription (damage +3, life stealing on hit).

    Detected off the game's own human-readable description lines rather than
    internal mod ids, since that's the one thing guaranteed to match what the
    client actually shows. Best-effort -- this is exactly why dry-run mode
    exists; verify against its output before trusting it to sell for real.
    """
    if not Item.Type.IsWeapon(item_id):
        return False
    lines = " | ".join(Item.Mods.GetDescriptions(item_id)).lower()
    has_inherent = "health regeneration -1" in lines and ("damage +15%" in lines or "damage +14%" in lines)
    has_vamp_upgrade = any("vampiric" in name.lower() for name, _slot in Item.Mods.GetUpgrades(item_id))
    return has_inherent and has_vamp_upgrade


def _is_maxed_noninscribable_gold(item_id: int) -> bool:
    """Keep: a non-inscribable gold weapon or shield with every rolled stat --
    base and upgrades -- at the top of its range.

    Base weapon damage is checked via IsMaxDamage() (a sword at 15-21 instead
    of 15-22 is not maxed even if every upgrade on it is) -- shields skip
    this check since their armor bonus is a fixed value per requirement, not
    a randomized roll, so there's nothing to max there beyond the upgrades.
    """
    if Item.Rarity.GetRarity(item_id)[1] != "Gold":
        return False
    is_shield = Item.GetItemType(item_id)[1] == "Shield"
    is_weapon = Item.Type.IsWeapon(item_id)
    if not (is_weapon or is_shield):
        return False
    if Item.Properties.IsInscribable(item_id):
        return False
    if is_weapon and not Item.Properties.IsMaxDamage(item_id):
        return False
    upgrades = Item.Mods.GetUpgrades(item_id)
    if not upgrades:
        return False
    return all(Item.Mods.IsMaxed(item_id, name) for name, _slot in upgrades)


def _triage_keep_reason(item_id: int) -> str | None:
    """Why this identified item should be kept, or None if it's sellable junk.

    Tools (ID/salvage kits) and consumables/materials are never triage-sold --
    kits are needed for AutoInventoryHandler's own identify/salvage work, and
    materials/consumables are AutoInventoryHandler's to deposit, not this
    triage's to sell. Everything else not matching a keep-criterion below is
    sellable, including dyes that aren't black or white.
    """
    if (Item.Usage.IsIDKit(item_id) or Item.Usage.IsSalvageKit(item_id) or Item.Usage.IsLesserKit(item_id)
            or Item.Usage.IsExpertSalvageKit(item_id) or Item.Usage.IsPerfectSalvageKit(item_id)):
        return "tool (kit)"
    if Item.Usage.IsUsable(item_id):
        return "consumable"
    if Item.GetModelID(item_id) == ModelID.Lockpick.value:
        return "lockpick"
    if Item.GetModelID(item_id) == ModelID.Wood_Plank.value:
        return None
    # Master override: nothing below this point is a keeper -- liquidate it
    # all for gold. Kits/consumables/lockpicks are already handled above and
    # stay untouched regardless (they're excluded for functional reasons, not
    # value ones).
    if BotSettings.SELL_EVERYTHING:
        return None
    if BotSettings.KEEP_MATERIALS and (Item.Type.IsMaterial(item_id) or Item.Type.IsRareMaterial(item_id)):
        return "material"
    if BotSettings.KEEP_DYES and _is_keeper_dye(item_id):
        return "black/white dye"
    if BotSettings.KEEP_VIGOR_RUNES and _is_superior_vigor_rune(item_id):
        return "Superior Vigor rune"
    if BotSettings.KEEP_DOUBLE_VAMP and _is_double_vamp_weapon(item_id):
        return "double vamp weapon"
    if BotSettings.KEEP_MAXED_GOLD and _is_maxed_noninscribable_gold(item_id):
        return "maxed non-inscribable gold"
    return None


def _find_rune_salvage_kit() -> int:
    """Best available kit for extracting a rune without a chance to destroy it.

    Routines.Yield.Items.SalvageItems() calls GLOBAL_CACHE.Inventory.GetFirstSalvageKit(),
    which *prefers lesser (basic) kits* by default -- exactly the kits with a
    chance to destroy the rune on salvage, the opposite of what's wanted here.
    Scan directly for a Perfect (100% success) or Expert-tier kit instead;
    "Superior Salvage Kit" reads as expert-tier through the same native flag.
    """
    bag_items = ItemArray.GetItemArray(ItemArray.CreateBagList(1, 2, 3, 4))
    expert = 0
    for item_id in bag_items:
        if Item.Usage.IsPerfectSalvageKit(item_id):
            return item_id
        if Item.Usage.IsExpertSalvageKit(item_id) and not expert:
            expert = item_id
    return expert


def _salvage_with_kit(item_id: int, kit_id: int):
    """Salvage item_id with a specific kit_id, accepting the salvage-materials
    confirmation window if the game shows one (purple/gold items only).

    Bypasses Routines.Yield.Items.SalvageItems()'s automatic (lesser-kit-
    preferring) kit selection -- see _find_rune_salvage_kit().
    """
    from Py4GWCoreLib.Inventory import Inventory
    Inventory.SalvageItem(item_id, kit_id)
    yield from Routines.Yield.wait(750)
    _, rarity = Item.Rarity.GetRarity(item_id)
    if rarity in ("Purple", "Gold"):
        found_confirm = yield from Routines.Yield.Items._wait_for_salvage_materials_window()
        if found_confirm:
            Inventory.AcceptSalvageMaterialsWindow()
            yield from Routines.Yield.wait(750)


def _resolve_item_name(item_id: int, timeout_ms: int = 1500) -> str:
    """Item names are resolved async by the client -- GetName() reads back
    empty until a RequestName() has round-tripped. Request it and wait
    briefly so dry-run/log output is actually readable instead of "item X ()".
    """
    if Item.IsNameReady(item_id):
        return Item.GetName(item_id)
    Item.RequestName(item_id)
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if Item.IsNameReady(item_id):
            return Item.GetName(item_id)
        yield from Routines.Yield.wait(100)
    return Item.GetName(item_id)


def _wait_for_merchant_window(bot: Botting, timeout_ms: int = 5000) -> bool:
    """Poll until Maryann's trade window is actually open, or give up.

    bot.helpers.Merchant._buy_item()/._sell_item() silently do nothing if the
    merchant frame isn't open yet -- no error, no log, the call just no-ops.
    A fixed post-interact wait(750) is a guess at how long that takes; if the
    window happens to still be opening (interact was queued behind movement,
    game hitching, etc.) the guess comes up short and the "sale" never
    actually happens even though nothing in the log says so. Poll the real
    state instead of guessing at a duration.
    """
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if bot.helpers.Merchant._merchant_frame_exists():
            return True
        yield from Routines.Yield.wait(150)
    ConsoleLog(MODULE_NAME, "[Merchant] Trade window never opened -- buy/sell call skipped.",
               PySystem.Console.MessageType.Warning)
    return False


def _wait_for_merchant_offering(model_id: int, timeout_ms: int = 5000) -> bool:
    """Poll until model_id actually shows up in GetOfferedItems(), or give up.

    The trade window being open (_wait_for_merchant_window) doesn't mean the
    offered-items list has finished streaming in yet -- GetOfferedItems() is
    frame-cached and can read back empty/incomplete for a moment right after
    the window opens. bot.helpers.Merchant._buy_item() does one single
    GetOfferedItems() call and silently does nothing if the model isn't in it
    yet, same "single check instead of polling" trap as everywhere else in
    this framework. If this still times out after polling, the merchant
    genuinely doesn't stock that item (wrong NPC for it), not a timing issue.
    """
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        offered_models = {Item.GetModelID(iid) for iid in GLOBAL_CACHE.Trading.Merchant.GetOfferedItems()}
        if model_id in offered_models:
            return True
        yield from Routines.Yield.wait(150)
    ConsoleLog(MODULE_NAME, f"[Merchant] Model {model_id} never appeared in this merchant's stock -- buy skipped.",
               PySystem.Console.MessageType.Warning)
    return False


def _confirm_item_gone(item_id: int, timeout_ms: int = 3000) -> bool:
    """Poll until item_id is no longer in bags 1-4 (sold/deposited/consumed), or timeout."""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if item_id not in ItemArray.GetItemArray(ItemArray.CreateBagList(1, 2, 3, 4)):
            return True
        yield from Routines.Yield.wait(150)
    return False


def _sell_all(bot: Botting, item_ids: list[int], per_item_timeout_ms: int = 3000):
    """Sell each item one at a time, confirming it's actually gone before
    moving to the next.

    Same reasoning as _identify_all(): Routines.Yield.Merchant.SellItems()
    reports "Sold N items" as soon as its local action queue drains, which
    isn't proof the server processed all N -- the stack-price bug already
    showed a "successful" sell that changed nothing, and a full-inventory
    triage batch is exactly the size at which identify started silently
    dropping most of its work too. Confirming each item is actually gone
    catches that instead of trusting the queue-drained log line.

    Each item is wrapped in its own try/except: the FSM's coroutine runner
    silently drops a custom state (and jumps to whatever's next -- in
    practice, off toward the mission) the instant any exception escapes it,
    with nothing printed to explain why. One bad item id mid-batch used to
    be able to abandon the rest of a 50-item triage without a trace; now a
    failure on one item just gets logged and the loop moves on.
    """
    total = len(item_ids)
    for i, item_id in enumerate(item_ids, 1):
        try:
            quantity = GLOBAL_CACHE.Item.Properties.GetQuantity(item_id) or 1
            value = GLOBAL_CACHE.Item.Properties.GetValue(item_id)
            GLOBAL_CACHE.Trading.Merchant.SellItem(item_id, quantity * value)
            confirmed = yield from _confirm_item_gone(item_id, per_item_timeout_ms)
            if BotSettings.DEBUG:
                if confirmed:
                    print(f"[DEBUG] Sold item {item_id} ({i}/{total})")
                else:
                    print(f"[DEBUG] Item {item_id} did not confirm sold within {per_item_timeout_ms}ms ({i}/{total})")
        except Exception as e:
            ConsoleLog(MODULE_NAME, f"[Sell] Exception on item {item_id} ({i}/{total}): {e}",
                       PySystem.Console.MessageType.Error)


def _deposit_all(item_ids: list[int], per_item_timeout_ms: int = 3000):
    """Deposit each item one at a time, confirming it's actually gone before
    moving to the next -- same reasoning as _sell_all()/_identify_all():
    Routines.Yield.Items.DepositItems() reports "Deposited N items" as soon
    as its queue drains, which isn't proof storage actually received all N.

    Each item is wrapped in its own try/except -- see _sell_all() for why:
    one bad item id used to be able to silently abandon the whole triage
    (and send the bot off toward the mission) without a trace.
    """
    total = len(item_ids)
    for i, item_id in enumerate(item_ids, 1):
        try:
            GLOBAL_CACHE.Inventory.DepositItemToStorage(item_id)
            confirmed = yield from _confirm_item_gone(item_id, per_item_timeout_ms)
            if BotSettings.DEBUG:
                if confirmed:
                    print(f"[DEBUG] Deposited item {item_id} ({i}/{total})")
                else:
                    print(f"[DEBUG] Item {item_id} did not confirm deposited within {per_item_timeout_ms}ms ({i}/{total})")
        except Exception as e:
            ConsoleLog(MODULE_NAME, f"[Deposit] Exception on item {item_id} ({i}/{total}): {e}",
                       PySystem.Console.MessageType.Error)


def _identify_all(bot: Botting, item_ids: list[int], per_item_timeout_ms: int = 3000):
    """Identify each item one at a time, confirming success before moving on.

    Routines.Yield.Items.IdentifyItems() queues the whole batch at once --
    tried that (plus waiting, plus retrying the batch across multiple passes,
    re-topping the ID kit each time) and it consistently only got a small
    fraction of a large unidentified batch to actually flip to identified, no
    matter how many passes were allowed; the rest never went through even
    though the queue reported itself drained. Firing them one at a time and
    confirming each individually is slower but doesn't rely on however many
    of a big batch the client silently drops.

    Each item is wrapped in its own try/except -- see _sell_all() for why:
    one bad item id used to be able to silently abandon the whole triage
    (and send the bot off toward the mission) without a trace.
    """
    from Py4GWCoreLib.Inventory import Inventory
    total = len(item_ids)
    for i, item_id in enumerate(item_ids, 1):
        try:
            if Item.Usage.IsIdentified(item_id):
                continue
            id_kit = GLOBAL_CACHE.Inventory.GetFirstIDKit()
            if id_kit == 0:
                yield from _ensure_id_kit_stock(bot)
                id_kit = GLOBAL_CACHE.Inventory.GetFirstIDKit()
                if id_kit == 0:
                    if BotSettings.DEBUG:
                        print(f"[DEBUG] No ID kit available -- can't identify item {item_id} ({i}/{total})")
                    continue
            Inventory.IdentifyItem(item_id, id_kit)
            deadline = time.time() + per_item_timeout_ms / 1000
            while time.time() < deadline:
                if Item.Usage.IsIdentified(item_id):
                    if BotSettings.DEBUG:
                        print(f"[DEBUG] Identified item {item_id} ({i}/{total})")
                    break
                yield from Routines.Yield.wait(150)
            else:
                if BotSettings.DEBUG:
                    print(f"[DEBUG] Item {item_id} did not confirm identified within {per_item_timeout_ms}ms ({i}/{total})")
        except Exception as e:
            ConsoleLog(MODULE_NAME, f"[Identify] Exception on item {item_id} ({i}/{total}): {e}",
                       PySystem.Console.MessageType.Error)


def _triage_and_sell_inventory(bot: Botting):
    """Identify+triage pass: identify everything identifiable, keep declared
    keepers, sell everything else.

    Identification is done here directly with _identify_all() rather than left
    to AutoInventoryHandler's own background pass -- that widget's timing
    isn't ours to control, and _ensure_id_kit_stock() already guarantees a
    kit is on hand, so there's no reason to wait on it.

    Three outcomes per item:
    - Superior Vigor rune: salvage it out with an Expert/Perfect kit (buying
      one first if needed), then deposit the extracted rune to storage.
    - Other keepers (black/white dyes, double vamp weapons, maxed
      non-inscribable golds): deposited to storage as-is.
    - Everything else: sold to the merchant.
    """
    bag_items = ItemArray.GetItemArray(ItemArray.CreateBagList(1, 2, 3, 4))
    unidentified = [iid for iid in bag_items if not Item.Usage.IsIdentified(iid)]
    if unidentified:
        if BotSettings.DEBUG:
            print(f"[DEBUG] Identifying {len(unidentified)} item(s) before triage")
        yield from _identify_all(bot, unidentified)
        bag_items = ItemArray.GetItemArray(ItemArray.CreateBagList(1, 2, 3, 4))

    to_salvage_for_rune: list[int] = []
    to_deposit: list[int] = []
    to_sell: list[int] = []
    for item_id in bag_items:
        if not Item.Usage.IsIdentified(item_id):
            continue
        # ID/salvage kits are kept ON HAND, not banked -- depositing them to
        # storage defeats the point of always having one available to use
        # (_ensure_id_kit_stock, rune extraction). Leave them in the bag.
        if (Item.Usage.IsIDKit(item_id) or Item.Usage.IsSalvageKit(item_id) or Item.Usage.IsLesserKit(item_id)
                or Item.Usage.IsExpertSalvageKit(item_id) or Item.Usage.IsPerfectSalvageKit(item_id)):
            continue
        # Bonus/custom bow and Keiran's Bow are weapon-set gear (see
        # _equip_or_swap_to_set) that belongs equipped or parked in the
        # Equipment Pack, not banked -- _is_model_owned()/_equip_model() don't
        # look in storage, so depositing either one here would just cause the
        # next lap to think it's missing and re-acquire/re-craft a duplicate.
        # Leave them exactly where they are, same as the kit exclusion above.
        _bonus_bow_id = BotSettings.CUSTOM_BOW_ID if BotSettings.CUSTOM_BOW_ID != 0 else 11723
        if Item.GetModelID(item_id) in (_bonus_bow_id, ModelID.Keirans_Bow.value):
            continue
        if BotSettings.KEEP_VIGOR_RUNES and not BotSettings.SELL_EVERYTHING and _is_superior_vigor_rune(item_id):
            to_salvage_for_rune.append(item_id)
            continue
        keep_reason = _triage_keep_reason(item_id)
        if keep_reason:
            if BotSettings.DEBUG:
                print(f"[TRIAGE] Keep item {item_id}: {keep_reason} -> deposit to storage")
            to_deposit.append(item_id)
            continue
        to_sell.append(item_id)

    if not (to_salvage_for_rune or to_deposit or to_sell):
        return

    if BotSettings.INVENTORY_TRIAGE_DRY_RUN:
        for item_id in to_salvage_for_rune:
            name = yield from _resolve_item_name(item_id)
            print(f"[TRIAGE][DRY RUN] Would salvage item {item_id} ({name}) "
                  f"with an Expert/Perfect Salvage Kit to extract its Superior Vigor rune, then deposit it")
        for item_id in to_deposit:
            name = yield from _resolve_item_name(item_id)
            print(f"[TRIAGE][DRY RUN] Would deposit item {item_id} ({name}) to storage")
        for item_id in to_sell:
            name = yield from _resolve_item_name(item_id)
            print(f"[TRIAGE][DRY RUN] Would sell item {item_id} ({name})")
        return

    if BotSettings.DEBUG:
        print(f"[DEBUG] Triage: {len(to_salvage_for_rune)} to salvage, "
              f"{len(to_deposit)} to deposit, {len(to_sell)} to sell")

    if to_salvage_for_rune:
        kit_id = _find_rune_salvage_kit()
        if not kit_id:
            # Maryann, EOTN's general merchant (see _sell_white_item_to_free_a_slot).
            yield from bot.Move._coro_xy_and_interact_npc(-2748.00, 1019.00)
            if (yield from _wait_for_merchant_window(bot)) and (yield from _wait_for_merchant_offering(ModelID.Expert_Salvage_Kit.value)):
                yield from bot.helpers.Merchant._buy_item(ModelID.Expert_Salvage_Kit.value, 1)
            kit_id = _find_rune_salvage_kit()
        if kit_id:
            for item_id in to_salvage_for_rune:
                yield from _salvage_with_kit(item_id, kit_id)
            # Sweep for whatever's sitting loose now (the freshly-extracted
            # rune(s), and the salvaged husk item if it still exists) and
            # fold it into the deposit pass below.
            fresh_items = ItemArray.GetItemArray(ItemArray.CreateBagList(1, 2, 3, 4))
            to_deposit.extend(iid for iid in fresh_items if iid not in bag_items)
        elif BotSettings.DEBUG:
            print("[DEBUG] No Expert Salvage Kit available and couldn't buy one -- skipping rune salvage")

    if to_deposit:
        yield from _deposit_all(to_deposit)

    if to_sell:
        # Maryann, EOTN's general merchant (see _sell_white_item_to_free_a_slot).
        yield from bot.Move._coro_xy_and_interact_npc(-2748.00, 1019.00)
        if (yield from _wait_for_merchant_window(bot)):
            yield from _sell_all(bot, to_sell)


def _ensure_id_kit_stock(bot: Botting):
    """Keep at least one identification kit on hand at all times.

    AutoInventoryHandler identifies constantly in the background whenever it's
    in EOTN, so it needs a kit available on every single visit -- unlike the
    rune-extraction salvage kit (bought on demand, only when there's actually
    a rune to pull), this one can't wait until it's needed because by the time
    it's needed it's already blocking identification. Superior Identification
    Kits carry 100 charges, so one purchase covers a long run of future
    visits; the depleted kit is removed by the game itself on its last use,
    so an empty-handed check here is enough to know it's time to buy another.
    """
    bag_items = ItemArray.GetItemArray(ItemArray.CreateBagList(1, 2, 3, 4))
    if any(Item.Usage.IsIDKit(item_id) for item_id in bag_items):
        return
    if BotSettings.DEBUG:
        print("[DEBUG] No identification kit in inventory -- buying a Superior Identification Kit")
    # Maryann, EOTN's general merchant (see _sell_white_item_to_free_a_slot).
    yield from bot.Move._coro_xy_and_interact_npc(-2748.00, 1019.00)
    if (yield from _wait_for_merchant_window(bot)) and (yield from _wait_for_merchant_offering(ModelID.Superior_Identification_Kit.value)):
        yield from bot.helpers.Merchant._buy_item(ModelID.Superior_Identification_Kit.value, 1)


def _sell_white_item_to_free_a_slot(bot: Botting):
    """If bags are completely full, sell one item to a merchant to open a slot.

    AutoInventoryHandler's salvage step needs at least one open inventory slot
    to receive the salvage result -- with 0 free slots it can never run, so the
    low-slots detour below would otherwise sit in town waiting forever.

    Prefers a white-rarity junk item (cheapest to give up). If there isn't one,
    falls back to any already-identified gold item that doesn't match one of
    the triage keep-criteria (Superior Vigor rune, double vamp, maxed
    non-inscribable, black/white dye) -- same "not a keeper" logic the full
    triage pass uses, just applied early to unblock the rest of it.
    """
    if _count_free_bag_slots() > 0:
        return

    bag_items = ItemArray.GetItemArray(ItemArray.CreateBagList(1, 2, 3, 4))
    sell_item_id = next((iid for iid in bag_items if _is_sellable_junk(iid)), 0)
    if not sell_item_id:
        sell_item_id = next(
            (iid for iid in bag_items
             if Item.Usage.IsIdentified(iid)
             and Item.Rarity.GetRarity(iid)[1] == "Gold"
             and _triage_keep_reason(iid) is None),
            0)
    if not sell_item_id:
        if BotSettings.DEBUG:
            print("[DEBUG] Inventory full but no sellable item found to free a slot")
        return

    if BotSettings.DEBUG:
        print(f"[DEBUG] Inventory full, selling item {sell_item_id} to free a slot")
    # Maryann, EOTN's general merchant. _find_npc_xy_by_name() can't locate her
    # from far away -- the game only tracks nearby agents, so a name search from
    # across the outpost turns up nothing. Move to her known spot directly.
    yield from bot.Move._coro_xy_and_interact_npc(-2748.00, 1019.00)
    if (yield from _wait_for_merchant_window(bot)):
        yield from _sell_all(bot, [sell_item_id])


def CheckAndDepositGold(bot: Botting) -> None:
    """Check gold on character, deposit if needed."""
    bot.States.AddHeader("Check and Deposit Gold")

    def _check_and_deposit_gold(bot: Botting):
        current_map = Map.GetMapID()
        gold_on_char = GLOBAL_CACHE.Inventory.GetGoldOnCharacter()
        gold_in_storage = GLOBAL_CACHE.Inventory.GetGoldInStorage()
        free_slots = _count_free_bag_slots()

        if BotSettings.DEBUG:
            print(f"[DEBUG] CheckAndDepositGold: current_map={current_map}, gold={gold_on_char}, "
                  f"storage={gold_in_storage}, free_slots={free_slots}")

        needs_gold_trip = gold_on_char > BotSettings.GOLD_THRESHOLD_DEPOSIT
        needs_inventory_trip = (
            BotSettings.MANAGE_INVENTORY_ON_LOW_SLOTS
            and free_slots < BotSettings.LOW_SLOTS_THRESHOLD
        )

        if needs_gold_trip or needs_inventory_trip:
            if current_map != BotSettings.EOTN_OUTPOST_ID:
                if BotSettings.DEBUG:
                    print(f"[DEBUG] Traveling to EOTN from map {current_map} "
                          f"(gold={needs_gold_trip}, low_slots={needs_inventory_trip})")
                Map.Travel(BotSettings.EOTN_OUTPOST_ID)
                yield from Routines.Yield.Map.WaitforMapLoad(BotSettings.EOTN_OUTPOST_ID, timeout=15000)
                current_map = BotSettings.EOTN_OUTPOST_ID

            if needs_gold_trip:
                if gold_in_storage < 800000:
                    if BotSettings.DEBUG:
                        print(f"Depositing {gold_on_char} gold in bank")
                    GLOBAL_CACHE.Inventory.DepositGold(gold_on_char)
                    yield from Routines.Yield.wait(1000)
                else:
                    if BotSettings.DEBUG:
                        print(f"Storage ({gold_in_storage}) has reached 800k+, keeping gold on character for ecto purchases")

            if needs_inventory_trip:
                # _ensure_id_kit_stock/_triage_and_sell_inventory below do the
                # actual identify+salvage+deposit+sell work themselves now --
                # no need to wait around hoping AutoInventoryHandler clears
                # space first. Just guarantee at least one free slot exists
                # (needed for the rune-salvage step to receive its result).
                if BotSettings.DEBUG:
                    print(f"[DEBUG] Low on free slots ({free_slots}/{BotSettings.LOW_SLOTS_THRESHOLD}), "
                          f"freeing a slot before triage")
                yield from _sell_white_item_to_free_a_slot(bot)
        else:
            if BotSettings.DEBUG:
                print(f"Gold ({gold_on_char}) below threshold ({BotSettings.GOLD_THRESHOLD_DEPOSIT}) "
                      f"and free slots ({free_slots}) OK, skipping")

        current_map = Map.GetMapID()
        if current_map == BotSettings.EOTN_OUTPOST_ID:
            yield from _ensure_id_kit_stock(bot)
            yield from BuyMaterials(bot)
            yield from _triage_and_sell_inventory(bot)

        if BotSettings.DEBUG:
            print(f"[DEBUG] After gold check: current_map={current_map}, HOM={BotSettings.HOM_OUTPOST_ID}")

    bot.States.AddCustomState(lambda: _check_and_deposit_gold(bot), "CheckAndDepositGold")


def ExitToHOM(bot: Botting) -> None:
    bot.States.AddHeader("Exit to HOM")

    def _exit_to_hom(bot: Botting):
        current_map = Map.GetMapID()
        should_exit_to_hom = current_map != BotSettings.HOM_OUTPOST_ID
        should_travel_to_eotn = current_map != BotSettings.EOTN_OUTPOST_ID

        if should_exit_to_hom:
            if BotSettings.DEBUG:
                print(f"[DEBUG] Not in HOM, need to go there. Currently in map {current_map}")

            if should_travel_to_eotn:
                if BotSettings.DEBUG:
                    print(f"[DEBUG] Not in EOTN, traveling there first")
                Map.Travel(BotSettings.EOTN_OUTPOST_ID)
                yield from Routines.Yield.Map.WaitforMapLoad(BotSettings.EOTN_OUTPOST_ID, timeout=15000)

            if BotSettings.DEBUG:
                print(f"[DEBUG] Moving to portal coordinates and exiting to HOM")

            yield from bot.Move._coro_xy_and_exit_map(-4873.00, 5284.00, target_map_id=BotSettings.HOM_OUTPOST_ID)
        else:
            if BotSettings.DEBUG:
                print(f"[DEBUG] Already in HOM, skipping travel")
        yield

    bot.States.AddCustomState(lambda: _exit_to_hom(bot), "ExitToHOM")

def _is_model_owned(model_id: int) -> bool:
    """True if the player already owns model_id, anywhere.

    Routines.Checks.Inventory.IsModelInInventoryOrEquipped() only scans the 4
    standard bags (Backpack/Belt Pouch/Bag1/Bag2) plus the currently-active
    equipped items -- it never looks inside the Equipment Pack (bag 5), which
    is exactly where players commonly stash weapon-set spares (Keiran's Bow,
    the bonus/custom combat bow) to keep them safe from auto-sell/salvage
    bots. Without this extra check the bot never sees an item parked there
    (or sitting in the inactive weapon set) and re-acquires/re-crafts one
    every single run.
    """
    if Routines.Checks.Inventory.IsModelInInventoryOrEquipped(model_id):
        return True
    pack_items = ItemArray.GetItemArray(ItemArray.CreateBagList(Bags.EquipmentPack.value))
    return any(Item.GetModelID(item_id) == model_id for item_id in pack_items)


def _equip_or_swap_to_set(bot: Botting, model_id: int, weapon_set: int):
    """Equip model_id, preferring a weapon-set swap over a raw re-equip.

    A player who keeps two prepared weapon sets (e.g. the crafted farming bow
    on set 1, Keiran's Bow on set 2) stores the inactive set's gear in the
    Equipment Pack (bag 5) -- that's what "weapon set 2" physically is. Going
    through _equip_model()'s EquipItem() call in that case forces model_id
    into the *active* set, evicting whatever's currently worn there instead
    of switching to the set that already has it. Pressing the weapon-set
    keybind swaps sets without disturbing either one.

    Only takes the swap path when model_id is actually sitting in the
    Equipment Pack already (i.e. it's a prepared set); a freshly-acquired
    item with nowhere organized yet still goes through the normal equip.

    Requires "Weapon Set 1"/"Weapon Set 2" etc. to have a physical keybind
    assigned in Guild Wars' own Options -> Controls -- the game only
    activates a set in response to that key being pressed, and py4gw can only
    simulate whatever key is actually bound to the action.
    """
    if Routines.Checks.Inventory.IsModelEquipped(model_id):
        return

    pack_items = ItemArray.GetItemArray(ItemArray.CreateBagList(Bags.EquipmentPack.value))
    if any(Item.GetModelID(iid) == model_id for iid in pack_items):
        yield from Routines.Yield.Keybinds.ActivateWeaponSet(weapon_set)
        yield from Routines.Yield.wait(250)
        return

    yield from _equip_model(bot, model_id)


def _equip_model(bot: Botting, model_id: int):
    """Equip model_id, including a copy parked in the Equipment Pack (bag 5).

    bot.helpers.Items._equip() / Routines.Yield.Items.EquipItem() resolve the
    item to equip via GLOBAL_CACHE.Inventory.GetFirstModelID(), which -- like
    _is_model_owned() above -- only searches the 4 standard bags. An item kept
    in the Equipment Pack is invisible to it, so the equip call silently fails
    (no item_id found) and triggers an unmanaged-fail bot stop even though the
    player owns one. Fall back to our own Equipment-Pack-aware item lookup and
    equip that item_id directly.
    """
    if Routines.Checks.Inventory.IsModelEquipped(model_id):
        return True

    item_id = GLOBAL_CACHE.Inventory.GetFirstModelID(model_id)
    if not item_id:
        pack_items = ItemArray.GetItemArray(ItemArray.CreateBagList(Bags.EquipmentPack.value))
        item_id = next((iid for iid in pack_items if Item.GetModelID(iid) == model_id), 0)

    if not item_id:
        ConsoleLog(MODULE_NAME, f"[Equip] Model {model_id} not found to equip.", PySystem.Console.MessageType.Error)
        bot.helpers.Events.on_unmanaged_fail()
        return False

    GLOBAL_CACHE.Inventory.EquipItem(item_id, Player.GetAgentID())
    yield from Routines.Yield.wait(750)
    return True


def PrepareForQuest(bot: Botting) -> None:
    """Prepare for quest in HOM: acquire and equip Keiran's Bow."""
    bot.States.AddHeader("Prepare for Quest")

    def _prepare_for_quest(bot: Botting):
        if not _is_model_owned(ModelID.Keirans_Bow.value):
            yield from bot.Move._coro_xy_and_dialog(-6583.00, 6672.00, dialog_id=0x0000008A)

        yield from _equip_or_swap_to_set(bot, ModelID.Keirans_Bow.value, weapon_set=2)

    bot.States.AddCustomState(lambda: _prepare_for_quest(bot), "PrepareForQuest")

def BuyMaterials(bot: Botting):
    """Buy Glob of Ectoplasm if gold conditions are met."""
    if not BotSettings.BUY_ECTOS_ENABLED:
        return
    gold_in_inventory = GLOBAL_CACHE.Inventory.GetGoldOnCharacter()
    gold_in_storage = GLOBAL_CACHE.Inventory.GetGoldInStorage()

    if gold_in_inventory >= 90000 and gold_in_storage >= 800000:
        yield from bot.Move._coro_xy_and_dialog(-2079.00, 1046.00, dialog_id=0x00000001)

        for _ in range(100):
            current_gold = GLOBAL_CACHE.Inventory.GetGoldOnCharacter()
            if current_gold < 20000:
                if BotSettings.DEBUG:
                    print(f"[DEBUG] Stopping ecto purchases - gold ({current_gold}) below 20k")
                break
            yield from Routines.Yield.Merchant.BuyMaterial(ModelID.Glob_Of_Ectoplasm.value)
            BotSettings.ECTOS_BOUGHT += 1
            yield from Routines.Yield.wait(500)


# ---------------------------------------------------------------------------
# Mission entry and run (mission-aware)
# ---------------------------------------------------------------------------

def _noop_gate():
    """Single-yield no-op used as a named gate state (avoids generator-lambda type errors)."""
    yield


def EnterQuest(bot: Botting) -> None:
    bot.States.AddHeader("Enter Quest")

    def _enter_quest(bot: Botting):
        import PyDialog
        mission = _get_active_mission()

        # Move to Keiran and open the dialog without sending a specific ID.
        # Retried up to 3 times -- on a loaded machine (e.g. several GW clients
        # running in parallel for multi-account farming), pathing/interact can
        # be slow enough that a single 5s wait for the dialog comes up short
        # even though Keiran and the quest trigger are both fine; re-issuing
        # the move+interact is cheap and self-heals that instead of giving up
        # after one attempt.
        dialog_opened = False
        for attempt in range(1, 4):
            yield from bot.Move._coro_xy_and_interact_npc(-6662.00, 6584.00)

            deadline = time.time() + 5.0
            while not PyDialog.PyDialog.is_dialog_active():
                if time.time() > deadline:
                    break
                yield from Routines.Yield.wait(150)

            if PyDialog.PyDialog.is_dialog_active():
                dialog_opened = True
                break

            ConsoleLog(MODULE_NAME, f"[EnterQuest] Timed out waiting for Keiran's dialog (attempt {attempt}/3)",
                       PySystem.Console.MessageType.Warning)
            yield from Routines.Yield.wait(500)

        if not dialog_opened:
            ConsoleLog(MODULE_NAME, "[EnterQuest] Giving up -- Keiran's dialog never opened after 3 attempts",
                       PySystem.Console.MessageType.Error)
            return

        # Read the first button's dialog_id as the dynamic base
        buttons = [b for b in PyDialog.PyDialog.get_active_dialog_buttons() if getattr(b, "dialog_id", 0) != 0]
        if not buttons:
            ConsoleLog(MODULE_NAME, "[EnterQuest] No dialog buttons found", PySystem.Console.MessageType.Warning)
            return

        base_id = buttons[0].dialog_id
        target_id = base_id + _HOTN_DIALOG_BASE_OFFSET + mission.mission_slot
        ConsoleLog(MODULE_NAME, f"[EnterQuest] base={hex(base_id)} offset={hex(_HOTN_DIALOG_BASE_OFFSET + mission.mission_slot)} -> sending {hex(target_id)}")
        Player.SendDialog(target_id)
        yield from Routines.Yield.wait(500)

    bot.States.AddCustomState(lambda: _enter_quest(bot), "EnterQuest")

def _on_quest_success(bot: Botting) -> None:
    """Called at runtime after any mission completes successfully."""
    _increment_runs_counters(bot, "success")
    _update_vanguard_cache()
    if BotSettings.SEQUENCE_MODE:
        _advance_sequence()
    bot.config.FSM.jump_to_state_by_name("[H]Check and Deposit Gold_3")
    bot.config.FSM.resume()  # clear any stale pause left by the build (mirrors on_death pattern)

def RunQuest(bot: Botting) -> None:
    bot.States.AddHeader("Run Quest")

    def _start_run_timer():
        BotSettings.CURRENT_RUN_START_TIME = time.time()
        if BotSettings.DEBUG:
            print(f"[DEBUG] Started run timer at {BotSettings.CURRENT_RUN_START_TIME}")
        yield
    bot.States.AddCustomState(lambda: _start_run_timer(), "StartRunTimer")
    bot.States.AddCustomState(lambda: _load_navmesh_object(bot), "Navmesh Init")

    bot.Templates.AggressiveForceHeroAI(enable_imp=False)

    def _fresh_build():
        bot.OverrideBuild(KeiranThackerayEOTN(fsm=bot.config.FSM, debug_fn=lambda: BotSettings.DEBUG))
        bot.Templates.AggressiveForceHeroAI(enable_imp=False)  # re-arm HeroAI template each run (Pacifist disables it at run end)
        yield
    bot.States.AddCustomState(_fresh_build, "FreshBuild")
    
    # Runtime dispatcher: jumps to the gate for the active mission
    def _dispatch(bot: Botting):
        gate = _MISSION_GATE_NAMES[_get_active_mission().name]
        bot.config.FSM.jump_to_state_by_name(gate)
        yield
    bot.States.AddCustomState(lambda: _dispatch(bot), "MissionDispatcher")

    # Shared success handler (defined once, reused by each section)
    def _mission_success(bot: Botting):
        _disable_combat(bot)
        _on_quest_success(bot)
        yield

    # Combat loadout must be applied only once the mission map has actually
    # finished loading -- doing it earlier (e.g. right after MissionDispatcher,
    # while EnterQuest's dialog is still transitioning HOM -> the mission map)
    # means the equip lands during the loading screen and gets dropped, leaving
    # Keiran's Bow (equipped back in PrepareForQuest) on the bar for the fight.
    def _prepare_combat_loadout(bot: Botting, map_id: int):
        def _coro():
            yield from Routines.Yield.Map.WaitforMapLoad(map_id, timeout=30000)
            yield from _handle_bonus_bow(bot)
            yield from _handle_war_supplies(bot, BotSettings.WAR_SUPPLIES_ENABLED)
        return _coro

    # ---- Auspicious Beginnings ----
    bot.States.AddHeader("Auspicious Beginnings")
    bot.States.AddCustomState(_noop_gate, "GateAB")
    bot.States.AddCustomState(_prepare_combat_loadout(bot, MISSIONS["Auspicious Beginnings"].map_id), "PrepareCombatLoadout_AB")
    _run_ab_movement(bot)
    bot.Wait.ForMapLoad(target_map_id=BotSettings.HOM_OUTPOST_ID, timeout_ms=60000)
    bot.States.AddCustomState(lambda: _mission_success(bot), "AB_Success")

    # ---- A Vengance of Blades ----
    bot.States.AddHeader("Vengance")
    bot.States.AddCustomState(_noop_gate, "GateAVoB")
    bot.States.AddCustomState(_prepare_combat_loadout(bot, MISSIONS["A Vengance of Blades - WIP"].map_id), "PrepareCombatLoadout_AVoB")
    _run_avob_movement(bot)
    bot.Wait.ForMapLoad(target_map_id=BotSettings.HOM_OUTPOST_ID, timeout_ms=60000)
    bot.States.AddCustomState(lambda: _mission_success(bot), "AVoB_Success")

    # ---- Shadows in the Jungle ----
    bot.States.AddHeader("Shadows")
    bot.States.AddCustomState(_noop_gate, "GateSitJ")
    bot.States.AddCustomState(_prepare_combat_loadout(bot, MISSIONS["Shadows in the Jungle - WIP"].map_id), "PrepareCombatLoadout_SitJ")
    _run_sitj_movement(bot)
    bot.Wait.ForMapLoad(target_map_id=BotSettings.HOM_OUTPOST_ID, timeout_ms=60000)
    bot.States.AddCustomState(lambda: _mission_success(bot), "SitJ_Success")

    # ---- Rise ----
    bot.States.AddHeader("Rise")
    bot.States.AddCustomState(_noop_gate, "GateRise")
    bot.States.AddCustomState(_prepare_combat_loadout(bot, MISSIONS["Rise - WIP"].map_id), "PrepareCombatLoadout_Rise")
    _run_rise_movement(bot)
    bot.Wait.ForMapLoad(target_map_id=BotSettings.HOM_OUTPOST_ID, timeout_ms=60000)
    bot.States.AddCustomState(lambda: _mission_success(bot), "Rise_Success")


# ---------------------------------------------------------------------------
# Runtime helpers
# ---------------------------------------------------------------------------

def _handle_bonus_bow(bot: Botting):
    bonus_bow_id = 11723

    if BotSettings.CUSTOM_BOW_ID != 0:
        bonus_bow_id = BotSettings.CUSTOM_BOW_ID
    has_bonus_bow = _is_model_owned(bonus_bow_id)
    if has_bonus_bow:
        if BotSettings.DEBUG:
            print(f"[DEBUG] Bonus bow found, equipping")
        yield from _equip_or_swap_to_set(bot, bonus_bow_id, weapon_set=1)
    else:
        if BotSettings.DEBUG:
            print(f"[DEBUG] Bonus bow not found in inventory or equipped")
    yield


def _handle_war_supplies(bot: Botting, value: bool):
    if BotSettings.DEBUG:
        print(f"[DEBUG] War supplies {'enabled' if value else 'disabled'}")
    bot.Properties.ApplyNow("war_supplies", "active", value)
    yield


def _ensure_ini_initialized() -> bool:
    """Lazy-initialize the per-account Settings using the account email as the directory.
    Returns True once the handler is ready."""
    global _settings_ini, _settings_ini_account_email
    import os as _os

    account_email = Player.GetAccountEmail()
    if not account_email:
        return False
    if account_email == _settings_ini_account_email and _settings_ini is not None:
        return True

    base_path = PySystem.Console.get_projects_path()
    if not base_path:
        return False

    config_dir = _os.path.join(base_path, "Widgets", "Config", "Accounts", account_email)
    _os.makedirs(config_dir, exist_ok=True)
    ini_path = _os.path.join(config_dir, f"{bot.config.bot_name}.ini")
    _settings_ini = Settings(f"Widgets/Config/Accounts/{account_email}/{bot.config.bot_name}.ini", "global")
    _settings_ini_account_email = account_email

    # â”€â”€ Load persisted settings â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _S = "Settings"
    BotSettings.GOLD_THRESHOLD_DEPOSIT       = _settings_ini.get_int( _S, "gold_threshold",       BotSettings.GOLD_THRESHOLD_DEPOSIT)
    BotSettings.CUSTOM_BOW_ID                = _settings_ini.get_int( _S, "custom_bow_id",        BotSettings.CUSTOM_BOW_ID)
    BotSettings.WAR_SUPPLIES_ENABLED         = _settings_ini.get_bool(_S, "war_supplies",         BotSettings.WAR_SUPPLIES_ENABLED)
    BotSettings.MANAGE_INVENTORY_ON_LOW_SLOTS = _settings_ini.get_bool(_S, "manage_inventory_on_low_slots", BotSettings.MANAGE_INVENTORY_ON_LOW_SLOTS)
    BotSettings.LOW_SLOTS_THRESHOLD          = _settings_ini.get_int( _S, "low_slots_threshold",  BotSettings.LOW_SLOTS_THRESHOLD)
    BotSettings.INVENTORY_TRIAGE_DRY_RUN     = _settings_ini.get_bool(_S, "triage_dry_run",       BotSettings.INVENTORY_TRIAGE_DRY_RUN)
    BotSettings.KEEP_MATERIALS               = _settings_ini.get_bool(_S, "keep_materials",       BotSettings.KEEP_MATERIALS)
    BotSettings.KEEP_DYES                    = _settings_ini.get_bool(_S, "keep_dyes",            BotSettings.KEEP_DYES)
    BotSettings.KEEP_VIGOR_RUNES             = _settings_ini.get_bool(_S, "keep_vigor_runes",     BotSettings.KEEP_VIGOR_RUNES)
    BotSettings.KEEP_DOUBLE_VAMP             = _settings_ini.get_bool(_S, "keep_double_vamp",     BotSettings.KEEP_DOUBLE_VAMP)
    BotSettings.KEEP_MAXED_GOLD              = _settings_ini.get_bool(_S, "keep_maxed_gold",      BotSettings.KEEP_MAXED_GOLD)
    BotSettings.SELL_EVERYTHING              = _settings_ini.get_bool(_S, "sell_everything",      BotSettings.SELL_EVERYTHING)
    BotSettings.BUY_ECTOS_ENABLED            = _settings_ini.get_bool(_S, "buy_ectos_enabled",    BotSettings.BUY_ECTOS_ENABLED)
    BotSettings.DEBUG                        = _settings_ini.get_bool(_S, "debug",                BotSettings.DEBUG)
    BotSettings.SHOW_HELP                    = _settings_ini.get_bool(_S, "show_help",            BotSettings.SHOW_HELP)

    # â”€â”€ Load persisted statistics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _SS = "Statistics"
    BotSettings.TOTAL_RUNS      = _settings_ini.get_int(  _SS, "total_runs",      0)
    BotSettings.SUCCESSFUL_RUNS = _settings_ini.get_int(  _SS, "successful_runs", 0)
    BotSettings.FAILED_RUNS     = _settings_ini.get_int(  _SS, "failed_runs",     0)
    BotSettings.ECTOS_BOUGHT    = _settings_ini.get_int(  _SS, "ectos_bought",    0)
    BotSettings.TOTAL_RUN_TIME  = _settings_ini.get_float(_SS, "total_run_time",  0.0)
    _fastest = _settings_ini.get_float(_SS, "fastest_run", 0.0)
    BotSettings.FASTEST_RUN     = float('inf') if _fastest == 0.0 else _fastest
    BotSettings.SLOWEST_RUN     = _settings_ini.get_float(_SS, "slowest_run",     0.0)
    for _name, _ms in BotSettings.MISSION_STATS.items():
        _p = _MISSION_INI_PREFIX.get(_name, "")
        if not _p:
            continue
        _ms.successful_runs = _settings_ini.get_int(  _SS, f"{_p}_successful_runs", 0)
        _ms.failed_runs     = _settings_ini.get_int(  _SS, f"{_p}_failed_runs",     0)
        _ms.total_run_time  = _settings_ini.get_float(_SS, f"{_p}_total_run_time",  0.0)
        _f2 = _settings_ini.get_float(_SS, f"{_p}_fastest_run", 0.0)
        _ms.fastest_run     = float('inf') if _f2 == 0.0 else _f2
        _ms.slowest_run     = _settings_ini.get_float(_SS, f"{_p}_slowest_run",     0.0)

    _update_vanguard_cache()
    return True


def _write_settings() -> None:
    """Write all settings and statistics to the per-account INI if a save has been requested."""
    global _save_requested
    if not _save_requested or not _settings_ini:
        return

    _S  = "Settings"
    _settings_ini.set(_S, "gold_threshold",                str(BotSettings.GOLD_THRESHOLD_DEPOSIT))
    _settings_ini.set(_S, "custom_bow_id",                 str(BotSettings.CUSTOM_BOW_ID))
    _settings_ini.set(_S, "war_supplies",                  str(BotSettings.WAR_SUPPLIES_ENABLED))
    _settings_ini.set(_S, "manage_inventory_on_low_slots", str(BotSettings.MANAGE_INVENTORY_ON_LOW_SLOTS))
    _settings_ini.set(_S, "low_slots_threshold",           str(BotSettings.LOW_SLOTS_THRESHOLD))
    _settings_ini.set(_S, "triage_dry_run",                str(BotSettings.INVENTORY_TRIAGE_DRY_RUN))
    _settings_ini.set(_S, "keep_materials",                str(BotSettings.KEEP_MATERIALS))
    _settings_ini.set(_S, "keep_dyes",                     str(BotSettings.KEEP_DYES))
    _settings_ini.set(_S, "keep_vigor_runes",              str(BotSettings.KEEP_VIGOR_RUNES))
    _settings_ini.set(_S, "keep_double_vamp",              str(BotSettings.KEEP_DOUBLE_VAMP))
    _settings_ini.set(_S, "keep_maxed_gold",               str(BotSettings.KEEP_MAXED_GOLD))
    _settings_ini.set(_S, "sell_everything",               str(BotSettings.SELL_EVERYTHING))
    _settings_ini.set(_S, "buy_ectos_enabled",             str(BotSettings.BUY_ECTOS_ENABLED))
    _settings_ini.set(_S, "debug",                         str(BotSettings.DEBUG))
    _settings_ini.set(_S, "show_help",                     str(BotSettings.SHOW_HELP))

    _SS = "Statistics"
    _settings_ini.set(_SS, "total_runs",      str(BotSettings.TOTAL_RUNS))
    _settings_ini.set(_SS, "successful_runs", str(BotSettings.SUCCESSFUL_RUNS))
    _settings_ini.set(_SS, "failed_runs",     str(BotSettings.FAILED_RUNS))
    _settings_ini.set(_SS, "ectos_bought",    str(BotSettings.ECTOS_BOUGHT))
    _settings_ini.set(_SS, "total_run_time",  str(BotSettings.TOTAL_RUN_TIME))
    _fastest = 0.0 if BotSettings.FASTEST_RUN == float('inf') else BotSettings.FASTEST_RUN
    _settings_ini.set(_SS, "fastest_run",     str(_fastest))
    _settings_ini.set(_SS, "slowest_run",     str(BotSettings.SLOWEST_RUN))
    for name, ms in BotSettings.MISSION_STATS.items():
        p = _MISSION_INI_PREFIX.get(name, "")
        if not p:
            continue
        _settings_ini.set(_SS, f"{p}_successful_runs", str(ms.successful_runs))
        _settings_ini.set(_SS, f"{p}_failed_runs",     str(ms.failed_runs))
        _settings_ini.set(_SS, f"{p}_total_run_time",  str(ms.total_run_time))
        _f = 0.0 if ms.fastest_run == float('inf') else ms.fastest_run
        _settings_ini.set(_SS, f"{p}_fastest_run",     str(_f))
        _settings_ini.set(_SS, f"{p}_slowest_run",     str(ms.slowest_run))

    _save_requested = False


def _save_stats():
    global _save_requested
    _save_requested = True


def _reset_stats():
    BotSettings.TOTAL_RUNS      = 0
    BotSettings.SUCCESSFUL_RUNS = 0
    BotSettings.FAILED_RUNS     = 0
    BotSettings.ECTOS_BOUGHT    = 0
    BotSettings.TOTAL_RUN_TIME  = 0.0
    BotSettings.FASTEST_RUN     = float('inf')
    BotSettings.SLOWEST_RUN     = 0.0
    for name in BotSettings.MISSION_STATS:
        BotSettings.MISSION_STATS[name] = MissionStats()
    _save_stats()


def _increment_runs_counters(bot: Botting, result: Literal["success", "fail"]):
    ms = BotSettings.MISSION_STATS.get(BotSettings.SELECTED_MISSION)
    if BotSettings.CURRENT_RUN_START_TIME > 0:
        run_time = time.time() - BotSettings.CURRENT_RUN_START_TIME

        if result == "success":
            BotSettings.TOTAL_RUN_TIME += run_time
            if run_time < BotSettings.FASTEST_RUN:
                BotSettings.FASTEST_RUN = run_time
            if run_time > BotSettings.SLOWEST_RUN:
                BotSettings.SLOWEST_RUN = run_time
            if ms:
                ms.total_run_time += run_time
                if run_time < ms.fastest_run:
                    ms.fastest_run = run_time
                if run_time > ms.slowest_run:
                    ms.slowest_run = run_time

        if BotSettings.DEBUG:
            print(f"[DEBUG] Run completed in {run_time:.2f}s (result: {result})")

        BotSettings.CURRENT_RUN_START_TIME = 0.0
    BotSettings.TOTAL_RUNS += 1
    if result == "success":
        BotSettings.SUCCESSFUL_RUNS += 1
        if ms:
            ms.successful_runs += 1
    elif result == "fail":
        BotSettings.FAILED_RUNS += 1
        if ms:
            ms.failed_runs += 1
    _save_stats()


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------


def _get_vanguard_rank_info():
    tiers = TITLE_TIERS.get(TitleID.Ebon_Vanguard, [])
    title = Player.GetTitle(TitleID.Ebon_Vanguard)
    current_points = title.current_points if title is not None else 0

    current_rank = 0
    tier_name = "Unranked"
    for t in tiers:
        if current_points >= t.required:
            current_rank = t.tier
            tier_name = t.name
        else:
            break

    if current_rank >= len(tiers):
        return current_rank, tier_name, current_points, None

    next_required = tiers[current_rank].required
    return current_rank, tier_name, current_points, next_required


def _update_vanguard_cache():
    rank, tier_name, pts, _ = _get_vanguard_rank_info()
    BotSettings.VANGUARD_RANK = rank
    BotSettings.VANGUARD_TIER_NAME = tier_name
    BotSettings.VANGUARD_POINTS = pts



def _format_time(seconds: float) -> str:
    if seconds == float('inf') or seconds == 0.0:
        return "--:--"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"



def _current_run_time():
    # If the bot was stopped mid-run, clear the timer
    if not bot.config.fsm_running and BotSettings.CURRENT_RUN_START_TIME > 0:
        BotSettings.CURRENT_RUN_START_TIME = 0.0
    if BotSettings.CURRENT_RUN_START_TIME > 0:
        return _format_time(time.time() - BotSettings.CURRENT_RUN_START_TIME)
    return "--:--"


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def _draw_mission_selector(width: int = 340) -> None:
    """
    Mission selector rendered as two rows of highlighted buttons.

    Row 1  â”€ one button per mission (abbreviated label, full name as tooltip).
    Row 2  â”€ full-width "All Missions (Sequence)" button.

    The active selection is highlighted with an amber tint.
    """
    # Abbreviated labels shown on the buttons (full names appear as tooltips)
    _SHORT_LABELS = ["Auspicious", "Blades - WIP", "Shadows - WIP", "Rise - WIP"]

    # Muted orange base for unselected option buttons
    OPT_BG  = (0.45, 0.26, 0.05, 1.0)
    OPT_HOV = (0.55, 0.33, 0.08, 1.0)
    OPT_ACT = (0.35, 0.20, 0.03, 1.0)

    # Green for the selected button; hover shifts to amber so it feels interactive
    SEL_BG  = (0.15, 0.50, 0.15, 1.0)
    SEL_HOV = (0.70, 0.40, 0.00, 1.0)
    SEL_ACT = (0.10, 0.38, 0.10, 1.0)

    # Resolve the active selection index
    if BotSettings.SEQUENCE_MODE:
        selected_idx = len(MISSION_NAMES)   # extra slot beyond missions = sequence
    else:
        selected_idx = MISSION_NAMES.index(BotSettings.SELECTED_MISSION)

    n        = len(MISSION_NAMES)
    gap      = 4                            # px between mission buttons
    btn_w    = max(1, (width - gap * (n - 1)) // n)
    btn_h    = 30

    # â”€â”€ Row 1: individual mission buttons â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    for i, (name, short) in enumerate(zip(MISSION_NAMES, _SHORT_LABELS)):
        is_sel = (selected_idx == i)
        bg, hov, act = (SEL_BG, SEL_HOV, SEL_ACT) if is_sel else (OPT_BG, OPT_HOV, OPT_ACT)

        PyImGui.push_style_color(PyImGui.ImGuiCol.Button,        bg)
        PyImGui.push_style_color(PyImGui.ImGuiCol.ButtonHovered, hov)
        PyImGui.push_style_color(PyImGui.ImGuiCol.ButtonActive,  act)

        if PyImGui.button(f"{short}##m{i}", btn_w, btn_h):
            BotSettings.SELECTED_MISSION = name
            BotSettings.SEQUENCE_MODE    = False

        PyImGui.pop_style_color(3)

        if PyImGui.is_item_hovered():
            if PyImGui.begin_tooltip():
                PyImGui.text(name)
                PyImGui.end_tooltip()

        if i < n - 1:
            PyImGui.same_line(0, gap)

    # â”€â”€ Row 2: full-width sequence button (disabled until sequence mode is ready) â”€â”€
    _DISABLED_BTN = (0.35, 0.35, 0.35, 1.0)
    _DISABLED_TXT = (0.55, 0.55, 0.55, 1.0)

    PyImGui.push_style_color(PyImGui.ImGuiCol.Button,        _DISABLED_BTN)
    PyImGui.push_style_color(PyImGui.ImGuiCol.ButtonHovered, _DISABLED_BTN)
    PyImGui.push_style_color(PyImGui.ImGuiCol.ButtonActive,  _DISABLED_BTN)
    PyImGui.push_style_color(PyImGui.ImGuiCol.Text,          _DISABLED_TXT)

    PyImGui.button("All Missions (Sequence) - Coming Soon", width, btn_h)  # click ignored

    PyImGui.pop_style_color(4)

    # Current sequence position label (visible only in sequence mode)
    if BotSettings.SEQUENCE_MODE:
        seq_idx = BotSettings.SEQUENCE_INDEX
        PyImGui.text(f"  Current: {SEQUENCE_ORDER[seq_idx]} ({seq_idx + 1}/{len(SEQUENCE_ORDER)})")


_ROW_H = 26  # table row min-height â€” shared by table_next_row and centering helpers


def _vcenter() -> None:
    """Offset cursor Y to vertically centre text within the current row."""
    th = PyImGui.get_text_line_height()
    PyImGui.set_cursor_pos_y(PyImGui.get_cursor_pos_y() + max(0.0, (_ROW_H - th) / 2))


def _ltext(label: str) -> None:
    """Render text left-justified and vertically centred within the current table cell."""
    _vcenter()
    PyImGui.text(label)


def _ctext(label: str) -> None:
    """Render text horizontally and vertically centred within the current table cell."""
    _vcenter()
    avail = PyImGui.get_content_region_avail()[0]
    tw    = PyImGui.calc_text_size(label)[0]
    PyImGui.set_cursor_pos_x(PyImGui.get_cursor_pos_x() + max(0.0, (avail - tw) / 2))
    PyImGui.text(label)


def _rtext(label: str) -> None:
    """Render text right-justified and vertically centred within the current table cell."""
    _vcenter()
    avail = PyImGui.get_content_region_avail()[0]
    tw    = PyImGui.calc_text_size(label)[0]
    PyImGui.set_cursor_pos_x(PyImGui.get_cursor_pos_x() + max(0.0, avail - tw))
    PyImGui.text(label)


def _draw_stats_tab():
    """Statistics tab content."""
    global _reset_confirm

    # â”€â”€ Per-mission stats table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Columns: label | mission 1 | mission 2 | mission 3 | mission 4
    _missions = list(BotSettings.MISSION_STATS.items())
    _ncols = 1 + len(_missions)

    _tflags = (PyImGui.TableFlags.Borders |
               PyImGui.TableFlags.RowBg   |
               PyImGui.TableFlags.SizingStretchSame)

    if PyImGui.begin_table("MissionStatsTable", _ncols, _tflags):
        PyImGui.table_setup_column("", PyImGui.TableColumnFlags.WidthFixed, 70)
        for _ in _missions:
            PyImGui.table_setup_column("")

        # â”€â”€ Header row (manual, for centred labels) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        _hdr_color = 26 | (38 << 8) | (51 << 16) | (255 << 24)
        PyImGui.table_next_row(0, _ROW_H)
        PyImGui.table_set_bg_color(2, _hdr_color, -1)
        PyImGui.table_set_column_index(0)   # label column â€” leave blank
        for _i, (_mname, _ms) in enumerate(_missions, 1):
            PyImGui.table_set_column_index(_i)
            _ctext(_MISSION_COL_LABEL.get(_mname) or _mname)

        # â”€â”€ Runs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        PyImGui.table_next_row(0, _ROW_H)
        PyImGui.table_set_column_index(0); _ltext("Runs")
        for _i, (_, _ms) in enumerate(_missions, 1):
            PyImGui.table_set_column_index(_i)
            _rtext(str(_ms.total_runs))

        # â”€â”€ Successful â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        PyImGui.table_next_row(0, _ROW_H)
        PyImGui.table_set_column_index(0); _ltext("Successful")
        for _i, (_, _ms) in enumerate(_missions, 1):
            PyImGui.table_set_column_index(_i)
            PyImGui.push_style_color(PyImGui.ImGuiCol.Text, (0.0, 1.0, 0.0, 1.0))
            _rtext(str(_ms.successful_runs))
            PyImGui.pop_style_color(1)

        # â”€â”€ Failed â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        PyImGui.table_next_row(0, _ROW_H)
        PyImGui.table_set_column_index(0); _ltext("Failed")
        for _i, (_, _ms) in enumerate(_missions, 1):
            PyImGui.table_set_column_index(_i)
            PyImGui.push_style_color(PyImGui.ImGuiCol.Text, (1.0, 0.3, 0.3, 1.0))
            _rtext(str(_ms.failed_runs))
            PyImGui.pop_style_color(1)

        # â”€â”€ Success % â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        PyImGui.table_next_row(0, _ROW_H)
        PyImGui.table_set_column_index(0); _ltext("Success %")
        for _i, (_, _ms) in enumerate(_missions, 1):
            PyImGui.table_set_column_index(_i)
            PyImGui.push_style_color(PyImGui.ImGuiCol.Text, (0.0, 1.0, 0.0, 1.0))
            _rtext(_ms.success_rate())
            PyImGui.pop_style_color(1)

        # â”€â”€ Avg Time â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        PyImGui.table_next_row(0, _ROW_H)
        PyImGui.table_set_column_index(0); _ltext("Avg Time")
        for _i, (_, _ms) in enumerate(_missions, 1):
            PyImGui.table_set_column_index(_i)
            _rtext(_ms.average_time())

        # â”€â”€ Fastest â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        PyImGui.table_next_row(0, _ROW_H)
        PyImGui.table_set_column_index(0); _ltext("Fastest")
        for _i, (_, _ms) in enumerate(_missions, 1):
            PyImGui.table_set_column_index(_i)
            PyImGui.push_style_color(PyImGui.ImGuiCol.Text, (0.0, 1.0, 0.0, 1.0))
            _rtext(_ms.fastest_time())
            PyImGui.pop_style_color(1)

        # â”€â”€ Slowest â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        PyImGui.table_next_row(0, _ROW_H)
        PyImGui.table_set_column_index(0); _ltext("Slowest")
        for _i, (_, _ms) in enumerate(_missions, 1):
            PyImGui.table_set_column_index(_i)
            PyImGui.push_style_color(PyImGui.ImGuiCol.Text, (1.0, 0.65, 0.0, 1.0))
            _rtext(_ms.slowest_time())
            PyImGui.pop_style_color(1)

        # â”€â”€ Gold â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        PyImGui.table_next_row(0, _ROW_H)
        PyImGui.table_set_column_index(0); _ltext("Gold")
        for _i, (_, _ms) in enumerate(_missions, 1):
            PyImGui.table_set_column_index(_i)
            PyImGui.push_style_color(PyImGui.ImGuiCol.Text, (1.0, 0.84, 0.0, 1.0))
            _rtext(f"{1000 * _ms.successful_runs:,}")
            PyImGui.pop_style_color(1)

        # â”€â”€ War Supplies â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        PyImGui.table_next_row(0, _ROW_H)
        PyImGui.table_set_column_index(0); _ltext("War Supplies")
        for _i, (_, _ms) in enumerate(_missions, 1):
            PyImGui.table_set_column_index(_i)
            _rtext(str(5 * _ms.successful_runs))

        PyImGui.end_table()

    rank      = BotSettings.VANGUARD_RANK
    tier_name = BotSettings.VANGUARD_TIER_NAME
    pts       = BotSettings.VANGUARD_POINTS
    is_maxed  = rank >= 10
    _GOLD     = (1.0, 0.84, 0.0, 1.0)
    _vflags = (PyImGui.TableFlags.Borders |
               PyImGui.TableFlags.RowBg   |
               PyImGui.TableFlags.SizingStretchProp)
    if PyImGui.begin_table("VanguardTable", 2, _vflags):
        PyImGui.table_setup_column("", PyImGui.TableColumnFlags.WidthStretch, 0.4)
        PyImGui.table_setup_column("", PyImGui.TableColumnFlags.WidthStretch, 0.6)
        # â”€â”€ Header row â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        _hdr_color = 26 | (38 << 8) | (51 << 16) | (255 << 24)
        PyImGui.table_next_row(0, _ROW_H)
        PyImGui.table_set_bg_color(2, _hdr_color, -1)
        PyImGui.table_set_column_index(0); _ctext("Vanguard Rank")
        PyImGui.table_set_column_index(1); _ctext("Runs to Max")
        # â”€â”€ Data row â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        PyImGui.table_next_row(0, _ROW_H)
        PyImGui.table_set_column_index(0)
        if is_maxed:
            PyImGui.push_style_color(PyImGui.ImGuiCol.Text, _GOLD)
        rank_label = f"{rank} - {tier_name}" if rank > 0 else "Unranked"
        _ctext(rank_label)
        PyImGui.table_set_column_index(1)
        if is_maxed:
            _ctext("Title Maxed!")
            PyImGui.pop_style_color(1)
        else:
            remaining   = max(0, 160_000 - pts)
            runs_needed = (remaining + 1249) // 1250
            _ctext(str(runs_needed))
        PyImGui.end_table()

    PyImGui.separator()
    if PyImGui.collapsing_header("Reset"):
        _reset_confirm = PyImGui.checkbox("Confirm reset â€” this cannot be undone", _reset_confirm)
        _avail = PyImGui.get_content_region_avail()
        _reset_w = int(_avail[0]) if _avail[0] > 0 else 340
        if _reset_confirm:
            PyImGui.push_style_color(PyImGui.ImGuiCol.Button,        (0.55, 0.10, 0.10, 1.0))
            PyImGui.push_style_color(PyImGui.ImGuiCol.ButtonHovered, (0.70, 0.15, 0.15, 1.0))
            PyImGui.push_style_color(PyImGui.ImGuiCol.ButtonActive,  (0.40, 0.07, 0.07, 1.0))
        else:
            PyImGui.push_style_color(PyImGui.ImGuiCol.Button,        (0.25, 0.25, 0.25, 1.0))
            PyImGui.push_style_color(PyImGui.ImGuiCol.ButtonHovered, (0.25, 0.25, 0.25, 1.0))
            PyImGui.push_style_color(PyImGui.ImGuiCol.ButtonActive,  (0.25, 0.25, 0.25, 1.0))
        if PyImGui.button("Reset Statistics##ResetStats", _reset_w, 30):
            if _reset_confirm:
                _reset_stats()
                _reset_confirm = False
        PyImGui.pop_style_color(3)


def _draw_settings(bot: Botting):
    from Py4GWCoreLib import ImGui, Color
    from Py4GWCoreLib.ImGui_src.IconsFontAwesome5 import IconsFontAwesome5

    _section_color = Color(255, 200, 100, 255).to_tuple_normalized()
    _live_color    = (1.00, 0.35, 0.35, 1.0)   # live triage: real money on the line
    _dry_color     = (0.40, 0.85, 0.50, 1.0)   # dry-run: safe, log-only
    _muted_color   = (0.55, 0.55, 0.55, 1.0)   # settings currently moot

    def _section(icon: str, title: str) -> None:
        PyImGui.spacing()
        ImGui.push_font("Regular", 16)
        PyImGui.text_colored(f"{icon}  {title}", _section_color)
        ImGui.pop_font()
        PyImGui.separator()
        PyImGui.spacing()

    # ── Economy ──────────────────────────────────────────────────────────
    _section(IconsFontAwesome5.ICON_SACK_DOLLAR, "Economy")
    gold_threshold = BotSettings.GOLD_THRESHOLD_DEPOSIT
    PyImGui.set_next_item_width(150)
    gold_threshold = PyImGui.input_int("Gold deposit threshold", gold_threshold)
    custom_bow_id = BotSettings.CUSTOM_BOW_ID
    PyImGui.set_next_item_width(150)
    custom_bow_id = PyImGui.input_int("Custom Bow ID (0 = Craft Longbow)", custom_bow_id)
    use_war_supplies = BotSettings.WAR_SUPPLIES_ENABLED
    use_war_supplies = PyImGui.checkbox("Use War Supplies", use_war_supplies)
    buy_ectos_enabled = BotSettings.BUY_ECTOS_ENABLED
    buy_ectos_enabled = PyImGui.checkbox("Auto-buy Globs of Ectoplasm with excess gold (>=90k, storage >=800k)", buy_ectos_enabled)

    # ── Inventory Management ────────────────────────────────────────────
    _section(IconsFontAwesome5.ICON_BOXES, "Inventory Management")
    manage_on_low_slots = BotSettings.MANAGE_INVENTORY_ON_LOW_SLOTS
    manage_on_low_slots = PyImGui.checkbox("Detour to EOTN when low on free slots", manage_on_low_slots)
    low_slots_threshold = BotSettings.LOW_SLOTS_THRESHOLD
    if manage_on_low_slots:
        PyImGui.indent(20)
        PyImGui.set_next_item_width(130)
        low_slots_threshold = PyImGui.input_int("Free slots threshold", low_slots_threshold)
        PyImGui.unindent(20)
    keep_materials = BotSettings.KEEP_MATERIALS
    keep_materials = PyImGui.checkbox("Keep materials (deposit to storage instead of selling)", keep_materials)

    # Dry-run vs live is the single highest-stakes toggle in the whole bot
    # (the difference between a log line and a real sale) -- give it its own
    # unmissable badge instead of letting it blend into a normal checkbox row.
    PyImGui.spacing()
    triage_dry_run = BotSettings.INVENTORY_TRIAGE_DRY_RUN
    triage_dry_run = PyImGui.checkbox("Triage dry-run", triage_dry_run)
    PyImGui.same_line(0, 10)
    if triage_dry_run:
        PyImGui.push_style_color(PyImGui.ImGuiCol.Text, _dry_color)
        PyImGui.text(f"{IconsFontAwesome5.ICON_FLASK}  DRY RUN -- log only, nothing sold/salvaged/deposited for real")
    else:
        PyImGui.push_style_color(PyImGui.ImGuiCol.Text, _live_color)
        PyImGui.text(f"{IconsFontAwesome5.ICON_TRIANGLE_EXCLAMATION}  LIVE -- sells/salvages/deposits for real")
    PyImGui.pop_style_color(1)

    # ── Triage Keep Rules ────────────────────────────────────────────────
    _section(IconsFontAwesome5.ICON_SHIELD_HEART, "Triage Keep Rules")
    sell_everything = BotSettings.SELL_EVERYTHING
    if sell_everything:
        PyImGui.push_style_color(PyImGui.ImGuiCol.Text, _live_color)
    sell_everything = PyImGui.checkbox("Sell everything (ignore every keep rule below)", sell_everything)
    if BotSettings.SELL_EVERYTHING:
        PyImGui.pop_style_color(1)

    if sell_everything:
        PyImGui.push_style_color(PyImGui.ImGuiCol.Text, _muted_color)
    keep_dyes = BotSettings.KEEP_DYES
    keep_dyes = PyImGui.checkbox("Keep black/white dyes", keep_dyes)
    keep_vigor_runes = BotSettings.KEEP_VIGOR_RUNES
    keep_vigor_runes = PyImGui.checkbox("Keep Superior Vigor runes (+50 HP)", keep_vigor_runes)
    keep_double_vamp = BotSettings.KEEP_DOUBLE_VAMP
    keep_double_vamp = PyImGui.checkbox("Keep double vamp weapons", keep_double_vamp)
    keep_maxed_gold = BotSettings.KEEP_MAXED_GOLD
    keep_maxed_gold = PyImGui.checkbox("Keep maxed non-inscribable gold weapons/shields", keep_maxed_gold)
    if sell_everything:
        PyImGui.pop_style_color(1)
        PyImGui.text_colored(
            f"{IconsFontAwesome5.ICON_CIRCLE_INFO}  \"Sell everything\" is on -- the rules above are ignored.",
            _muted_color,
        )

    # ── Debug ────────────────────────────────────────────────────────────
    _section(IconsFontAwesome5.ICON_BUG, "Debug")
    debug = BotSettings.DEBUG
    debug = PyImGui.checkbox("Debug", debug)

    # ── Help ─────────────────────────────────────────────────────────────
    _section(IconsFontAwesome5.ICON_CIRCLE_INFO, "Help")
    show_help = BotSettings.SHOW_HELP
    show_help = PyImGui.checkbox("Show help tab", show_help)

    changed = (
        use_war_supplies    != BotSettings.WAR_SUPPLIES_ENABLED           or
        buy_ectos_enabled   != BotSettings.BUY_ECTOS_ENABLED              or
        custom_bow_id       != BotSettings.CUSTOM_BOW_ID                  or
        gold_threshold      != BotSettings.GOLD_THRESHOLD_DEPOSIT         or
        manage_on_low_slots != BotSettings.MANAGE_INVENTORY_ON_LOW_SLOTS  or
        low_slots_threshold != BotSettings.LOW_SLOTS_THRESHOLD            or
        triage_dry_run      != BotSettings.INVENTORY_TRIAGE_DRY_RUN       or
        keep_materials      != BotSettings.KEEP_MATERIALS                 or
        keep_dyes           != BotSettings.KEEP_DYES                      or
        keep_vigor_runes    != BotSettings.KEEP_VIGOR_RUNES               or
        keep_double_vamp    != BotSettings.KEEP_DOUBLE_VAMP               or
        keep_maxed_gold     != BotSettings.KEEP_MAXED_GOLD                or
        sell_everything     != BotSettings.SELL_EVERYTHING                or
        debug               != BotSettings.DEBUG                          or
        show_help           != BotSettings.SHOW_HELP
    )
    BotSettings.WAR_SUPPLIES_ENABLED          = use_war_supplies
    BotSettings.BUY_ECTOS_ENABLED             = buy_ectos_enabled
    BotSettings.CUSTOM_BOW_ID                 = custom_bow_id
    BotSettings.GOLD_THRESHOLD_DEPOSIT        = gold_threshold
    BotSettings.MANAGE_INVENTORY_ON_LOW_SLOTS = manage_on_low_slots
    BotSettings.LOW_SLOTS_THRESHOLD           = low_slots_threshold
    BotSettings.INVENTORY_TRIAGE_DRY_RUN      = triage_dry_run
    BotSettings.KEEP_MATERIALS                = keep_materials
    BotSettings.KEEP_DYES                     = keep_dyes
    BotSettings.KEEP_VIGOR_RUNES              = keep_vigor_runes
    BotSettings.KEEP_DOUBLE_VAMP              = keep_double_vamp
    BotSettings.KEEP_MAXED_GOLD               = keep_maxed_gold
    BotSettings.SELL_EVERYTHING               = sell_everything
    BotSettings.DEBUG                         = debug
    BotSettings.SHOW_HELP                     = show_help

    if changed:
        global _save_requested
        _save_requested = True


bot.SetMainRoutine(create_bot_routine)
bot.UI.override_draw_config(lambda: _draw_settings(bot))


def _draw_hotn_help() -> None:
    import PyImGui
    from Py4GWCoreLib import ImGui, Color, IconsFontAwesome5

    header_color = Color(255, 200, 100, 255)
    green_color  = Color(100, 220, 100, 255)
    red_color    = Color(220, 80,  80,  255)
    wip_color    = Color(220, 180, 60,  255)

    PyImGui.push_text_wrap_pos(PyImGui.get_cursor_pos_x() + 380.0)

    # â”€â”€ Title â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    PyImGui.spacing()
    ImGui.push_font("Regular", 20)
    PyImGui.text_colored("Hearts of the North - Bot Help", header_color.to_tuple_normalized())
    ImGui.pop_font()
    PyImGui.separator()
    PyImGui.spacing()
    PyImGui.text_wrapped("Welcome to the complete Hearts of the North farming bot. This bot is still in development. As additional missions have been mapped they will be added. Expect issues with WIP missions, but feel free to test.")
    PyImGui.text_colored("Features", header_color.to_tuple_normalized())
    PyImGui.bullet_text("Access to all four Keiran missions.")
    PyImGui.bullet_text("Useable by any class, any specialization, any gear.")
    PyImGui.bullet_text("Capable of setting a custom weapon in Settings")
    PyImGui.bullet_text("Automatically crafts suitable longbow otherwise.")
    PyImGui.bullet_text("Advanced statistics to track lifetime stats.")
    PyImGui.spacing()

    # â”€â”€ Requirements â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if PyImGui.collapsing_header("Currently Working Missions"):
        PyImGui.indent(10)
        PyImGui.text_colored(IconsFontAwesome5.ICON_CHECK         + "  Auspicious Beginnings",    green_color.to_tuple_normalized())
        PyImGui.text_colored(IconsFontAwesome5.ICON_ARROWS_ROTATE + "  A Vengance of Blades",     wip_color.to_tuple_normalized())
        PyImGui.text_colored(IconsFontAwesome5.ICON_ARROWS_ROTATE + "  Shadows in the Jungle",    wip_color.to_tuple_normalized())
        PyImGui.text_colored(IconsFontAwesome5.ICON_ARROWS_ROTATE + "  Rise",                     wip_color.to_tuple_normalized())
        PyImGui.text_colored(IconsFontAwesome5.ICON_TIMES         + "  All Missions in Sequence", red_color.to_tuple_normalized())
        PyImGui.unindent(10)
        PyImGui.spacing()

    # â”€â”€ Quest Phases â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if PyImGui.collapsing_header("Optimized Farming"):
        PyImGui.spacing()
        PyImGui.text_wrapped("General Notes")
        PyImGui.bullet_text("Any modifications to Health or Mana are completely ignored.")
        PyImGui.bullet_text("Attunement/Survivor/Radiant/Vigor/Vitae are useless.")
        PyImGui.bullet_text("Focus on upgrades that give bonus armor.")
        PyImGui.bullet_text("All classes have a minimum of 70 armor for these missions.")
        PyImGui.bullet_text("Classes with 80 armor will have 80 armor.")
        PyImGui.spacing()
        PyImGui.text_wrapped("Best Classes")
        PyImGui.bullet_text("Paragon - 80 Armor")
        PyImGui.bullet_text("Warrior - 80 Armor")
        PyImGui.spacing()
        PyImGui.text_wrapped("Best Runes")
        PyImGui.bullet_text("Paragon - Centurion")
        PyImGui.bullet_text("Warrior - Knight's/Dreadnought")
        PyImGui.bullet_text("General - Stalwart/Brawler's")
        PyImGui.spacing()
        PyImGui.text_wrapped("Best Runes")
        PyImGui.bullet_text("Clarity")
        PyImGui.bullet_text("Purity")
        PyImGui.bullet_text("Recovery")
        PyImGui.bullet_text("Restoration")
        PyImGui.bullet_text("Absorption - if Warrior")
        PyImGui.spacing()
        PyImGui.text_wrapped("Best Weapons")
        PyImGui.bullet_text("Base: Max Damage Longbow/Flatbow")
        PyImGui.bullet_text("Inscription: 15% ^ 50 or 15% -5e")
        PyImGui.bullet_text("Prefix: Vampiric/Sundering.")
        PyImGui.bullet_text("Vamp will always do more damage, but Sunder may be safer.")
        PyImGui.bullet_text("Suffix: Defence/Shelter/Warding")
        PyImGui.bullet_text("Anniversary Suffixes do not work, as far as I know")
        PyImGui.spacing()

    # â”€â”€ Known Issues / Tips â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if PyImGui.collapsing_header("Tips & Known Issues"):
        PyImGui.bullet_text("TODO: Add tips and known quirks here.")
        PyImGui.spacing()

    # â”€â”€ Close button (centered, bottom) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    PyImGui.separator()
    PyImGui.spacing()
    btn_label = "Close Help"
    btn_text_w, _ = PyImGui.calc_text_size(btn_label)
    btn_w = btn_text_w + 16.0
    avail_w = PyImGui.get_content_region_avail()[0]
    PyImGui.set_cursor_pos_x(PyImGui.get_cursor_pos_x() + (avail_w - btn_w) * 0.5)
    if PyImGui.button(btn_label):
        BotSettings.SHOW_HELP = False
        global _save_requested
        _save_requested = True
    PyImGui.spacing()
    PyImGui.pop_text_wrap_pos()


bot.UI.override_draw_help(_draw_hotn_help)


def _draw_hotn_window(icon_path: str) -> None:
    """
    Fully custom window for Hearts of the North.

    Layout of the Main tab child (top â†’ bottom):
        Header table  (icon | bot-name / step / status)
        â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        â–¶ Start / â–  Stop  button
        â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•  â† thin separator
        Mission selector  (sequence checkbox + combo)
        â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        Overall Progress  [â–ˆâ–ˆâ–ˆâ–ˆâ–‘â–‘â–‘â–‘]
        Step Progress     [â–ˆâ–ˆâ–‘â–‘â–‘â–‘â–‘â–‘]
    """
    from Py4GWCoreLib import ImGui, Color, Routines
    from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings
    from Py4GWCoreLib.ImGui_src.IconsFontAwesome5 import IconsFontAwesome5
    from Py4GWCoreLib.Py4GWcorelib import ConsoleLog, Console
    from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

    WINDOW_W = 420
    CHILD_W,  CHILD_H  = 410, 400
    ICON_W             = 96

    # â”€â”€ Window state INI (position/size) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if not bot.config.ini_key_initialized:
        bot.config.ini_key = Settings(f"{f"BottingClass/bot_{bot.config.bot_name}"}/{f"bot_{bot.config.bot_name}.ini"}", "account").name
        bot.config.ini_key_initialized = True

    if not bot.config.ini_key:
        return

    # â”€â”€ Per-account settings/statistics INI (lazy, requires account email) â”€â”€â”€
    _ensure_ini_initialized()
    _write_settings()

    # â”€â”€ Outer window â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if ImGui.Begin(
        ini_key=bot.config.ini_key,
        name=bot.config.bot_name,
        p_open=True,
        flags=PyImGui.WindowFlags.AlwaysAutoResize,
    ):
        if PyImGui.begin_tab_bar(bot.config.bot_name + "_tabs"):

            # â”€â”€ Help tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if BotSettings.SHOW_HELP and PyImGui.begin_tab_item("Help"):
                bot.UI._draw_help_child()
                PyImGui.dummy((WINDOW_W, 0))
                PyImGui.end_tab_item()

            # â”€â”€ Main tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if PyImGui.begin_tab_item("Main"):
                PyImGui.dummy((WINDOW_W, 0))
                _avail = PyImGui.get_content_region_avail()
                inner_w = int(_avail[0]) if _avail[0] > 0 else (CHILD_W - 10)

                # â”€â”€ Header table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                (current_header_step, header_for_current,
                 current_step, total_steps, step_name, finished) = bot.UI._find_current_header_step()

                if PyImGui.begin_table(
                    "bot_header_table", 2,
                    PyImGui.TableFlags.RowBg | PyImGui.TableFlags.BordersOuterH,
                ):
                    PyImGui.table_setup_column("Icon",   PyImGui.TableColumnFlags.WidthFixed,   ICON_W)
                    PyImGui.table_setup_column("titles", PyImGui.TableColumnFlags.WidthStretch)
                    PyImGui.table_next_row()

                    PyImGui.table_set_column_index(0)
                    bot.UI._draw_texture(texture_path=icon_path, size=(ICON_W, ICON_W))

                    PyImGui.table_set_column_index(1)
                    PyImGui.dummy((0, 3))
                    ImGui.push_font("Regular", 22)
                    PyImGui.push_style_color(PyImGui.ImGuiCol.Text, Color(255, 255, 0, 255).to_tuple_normalized())
                    PyImGui.text(bot.config.bot_name)
                    PyImGui.pop_style_color(1)
                    ImGui.pop_font()

                    # â”€â”€ Active mission label â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                    _active_label = "All Missions (Sequence)" if BotSettings.SEQUENCE_MODE else BotSettings.SELECTED_MISSION
                    PyImGui.push_style_color(PyImGui.ImGuiCol.Text, (0.65, 0.85, 1.0, 1.0))
                    PyImGui.text(_active_label)
                    PyImGui.pop_style_color(1)

                    ImGui.push_font("Bold", 18)
                    PyImGui.text(f"[{max(current_header_step, 0)}] {header_for_current or 'Not started'}")
                    ImGui.pop_font()

                    if total_steps <= 0:
                        PyImGui.text("Step: â€”/â€” - (No steps)")
                    elif finished:
                        PyImGui.text(f"Step: {total_steps-1}/{total_steps-1} - (Finished)")
                    else:
                        PyImGui.text(f"Step: {current_step}/{max(total_steps-1, 0)} - {step_name or '(â€¦?)'}")

                    if not bot.config.fsm_running and finished:
                        bot.config.state_description = "Finished"
                    PyImGui.text(f"Status: {bot.config.state_description}")
                    # â”€â”€ Current run timer + mission average â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                    _ms_active = BotSettings.MISSION_STATS.get(BotSettings.SELECTED_MISSION)
                    _avg = _ms_active.average_time() if _ms_active else "--:--"
                    if BotSettings.CURRENT_RUN_START_TIME > 0:
                        spinner_chars = ['|', '/', '-', '\\']
                        spinner_idx = int(time.time() * 4) % len(spinner_chars)
                        PyImGui.push_style_color(PyImGui.ImGuiCol.Text, (0.4, 0.8, 1.0, 1.0))
                        PyImGui.text(f"Run: {_current_run_time()} {spinner_chars[spinner_idx]}  |  Avg: {_avg}")
                        PyImGui.pop_style_color(1)
                    else:
                        PyImGui.text(f"Run: --:--  |  Avg: {_avg}")
                    PyImGui.end_table()

                # â”€â”€ Mission selector â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                #PyImGui.separator()
                _draw_mission_selector(inner_w)

                # â”€â”€ Start / Stop button â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                PyImGui.separator()
                btn_icon   = IconsFontAwesome5.ICON_STOP_CIRCLE if bot.config.fsm_running else IconsFontAwesome5.ICON_PLAY_CIRCLE
                btn_legend = "  Stop" if bot.config.fsm_running else "  Start"
                if PyImGui.button(btn_icon + btn_legend + "##BotToggle", inner_w, 40):
                    if bot.config.fsm_running:
                        bot.config.fsm_running = False
                        ConsoleLog(bot.config.bot_name, "Script stopped", Console.MessageType.Info)
                        bot.config.state_description = "Idle"
                        bot.config.FSM.stop()
                        GLOBAL_CACHE.Coroutines.clear()
                    else:
                        bot.config.fsm_running = True
                        ConsoleLog(bot.config.bot_name, "Script started", Console.MessageType.Info)
                        bot.config.state_description = "Running"
                        bot.config.FSM.restart()

                # â”€â”€ Progress bars â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                if total_steps > 1:
                    fraction = current_step / float(total_steps - 1)
                else:
                    fraction = 1.0 if (finished and total_steps == 1) else 0.0
                if finished and total_steps > 0:
                    fraction = 1.0
                fraction = max(0.0, min(1.0, fraction))

                PyImGui.separator()
                PyImGui.text("Overall Progress")
                PyImGui.progress_bar(fraction, inner_w, 0, f"{fraction * 100:.2f}%")

                PyImGui.separator()
                PyImGui.text("Step Progress")
                PyImGui.progress_bar(bot.config.state_percentage, inner_w, 0, f"{bot.config.state_percentage * 100:.2f}%")

                PyImGui.end_tab_item()

            # â”€â”€ Navigation tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if PyImGui.begin_tab_item("Navigation"):
                PyImGui.dummy((WINDOW_W, 0))
                PyImGui.text("Jump to step (filtered by step index):")
                bot.UI._draw_fsm_jump_button()
                PyImGui.separator()
                bot.UI.draw_fsm_tree_selector_ranged(child_size=(CHILD_W, CHILD_H))
                PyImGui.end_tab_item()

            # â”€â”€ Settings tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if PyImGui.begin_tab_item("Settings"):
                bot.UI._draw_settings_child()
                PyImGui.dummy((WINDOW_W, 0))
                PyImGui.end_tab_item()

            # â”€â”€ Debug tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if PyImGui.begin_tab_item("Debug"):
                bot.UI.draw_debug_window()
                PyImGui.dummy((WINDOW_W, 0))
                PyImGui.end_tab_item()

            # â”€â”€ Statistics tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if PyImGui.begin_tab_item("Statistics"):
                _draw_stats_tab()                
                PyImGui.dummy((WINDOW_W, 0))
                PyImGui.end_tab_item()

            PyImGui.end_tab_bar()

    ImGui.End(bot.config.ini_key)


def main():
    try:
        projects_path = PySystem.Console.get_projects_path()
        full_path = projects_path + "\\Sources\\ApoSource\\textures\\"

        bot.Update()
        _draw_hotn_window(full_path + "Keiran_art.png")

    except Exception as e:
        PySystem.Console.Log(bot.config.bot_name, f"Error: {str(e)}", PySystem.Console.MessageType.Error)
        raise


if __name__ == "__main__":
    main()
