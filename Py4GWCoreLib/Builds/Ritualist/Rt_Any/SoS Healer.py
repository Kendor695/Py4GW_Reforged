from dataclasses import dataclass

from Py4GWCoreLib import Agent, Player, Profession, Routines, BuildMgr
from Py4GWCoreLib.Skill import Skill
from Py4GWCoreLib.Builds.Any.HeroAI import HeroAI as HeroAIBuild
from Py4GWCoreLib.Builds.Skills import SkillsTemplate


Signet_of_Spirits_ID = Skill.GetID("Signet_of_Spirits")
Bloodsong_ID = Skill.GetID("Bloodsong")
Spirit_Transfer_ID = Skill.GetID("Spirit_Transfer")
Mend_Body_and_Soul_ID = Skill.GetID("Mend_Body_and_Soul")
Spirit_Light_ID = Skill.GetID("Spirit_Light")
Spirit_Siphon_ID = Skill.GetID("Spirit_Siphon")
Weapon_of_Shadow_ID = Skill.GetID("Weapon_of_Shadow")
Death_Pact_Signet_ID = Skill.GetID("Death_Pact_Signet")


@dataclass(slots=True)
class _SoSHealerBarSnapshot:
    in_aggro: bool = False
    close_to_aggro: bool = False
    player_energy_pct: float = 1.0


class SoS_Healer(BuildMgr):
    def __init__(self, match_only: bool = False):
        super().__init__(
            name="SoS Healer",
            required_primary=Profession.Ritualist,
            template_code="OACjEyiM5MXzypwTaO5YmXvkLA",
            required_skills=[
                Signet_of_Spirits_ID,
                Spirit_Light_ID,
                Mend_Body_and_Soul_ID,
            ],
            optional_skills=[
                Bloodsong_ID,
                Spirit_Transfer_ID,
                Spirit_Siphon_ID,
                Weapon_of_Shadow_ID,
                Death_Pact_Signet_ID,
            ],
        )
        if match_only:
            return

        self.SetFallback("HeroAI", HeroAIBuild(standalone_fallback=True))
        self.SetBlockedSkills([
            Signet_of_Spirits_ID,
            Bloodsong_ID,
            Spirit_Transfer_ID,
            Mend_Body_and_Soul_ID,
            Spirit_Light_ID,
            Spirit_Siphon_ID,
            Weapon_of_Shadow_ID,
            Death_Pact_Signet_ID,
        ])
        self.SetSkillCastingFn(self._run_local_skill_logic)
        self.skills: SkillsTemplate = SkillsTemplate(self)

    def _get_bar_snapshot(self) -> _SoSHealerBarSnapshot:
        snapshot = _SoSHealerBarSnapshot()
        snapshot.in_aggro = bool(self.IsInAggro())
        snapshot.close_to_aggro = snapshot.in_aggro or self.IsCloseToAggro()
        snapshot.player_energy_pct = float(Agent.GetEnergy(Player.GetAgentID()))
        return snapshot

    def _find_dead_ally(self) -> int:
        """Nearest dead ally in earshot, or 0. Used for Death Pact Signet, which
        only has a target while an ally is actually dead."""
        from Py4GWCoreLib import Range
        from Py4GWCoreLib.HeroAI.targeting import GetAllAlliesArray

        ally_array = GetAllAlliesArray(Range.Earshot.value) or []
        dead = [aid for aid in ally_array if Agent.IsValid(aid) and not Agent.IsAlive(aid)]
        if not dead:
            return 0
        dead.sort(key=lambda aid: Agent.GetHealth(aid))
        return dead[0]

    def _find_low_health_ally(self, threshold: float) -> int:
        """Lowest-health ally under threshold in earshot, or 0. Used for
        Weapon of Shadow -- no named-skill wrapper exists for it anywhere in
        the skills library yet, so this keeps the condition simple and
        honest (upkeep on whoever needs help) rather than guessing at its
        exact intended mechanic."""
        from Py4GWCoreLib import Range
        from Py4GWCoreLib.HeroAI.targeting import GetAllAlliesArray

        ally_array = GetAllAlliesArray(Range.Earshot.value) or []
        candidates = [
            aid for aid in ally_array
            if Agent.IsValid(aid) and Agent.IsAlive(aid) and Agent.GetHealth(aid) <= threshold
        ]
        if not candidates:
            return 0
        candidates.sort(key=lambda aid: Agent.GetHealth(aid))
        return candidates[0]

    def _run_local_skill_logic(self):
        if not Routines.Checks.Skills.CanCast():
            yield from Routines.Yield.wait(100)
            return False

        snapshot = self._get_bar_snapshot()
        if not snapshot.close_to_aggro:
            return False

        # Emergency energy refill before committing to the heal rotation.
        if self.IsSkillEquipped(Spirit_Siphon_ID) and (yield from self.skills.Ritualist.ChannelingMagic.Spirit_Siphon(max_self_energy_pct=0.25)):
            return True

        # Rez first -- a dead ally outweighs everything else.
        if self.IsSkillEquipped(Death_Pact_Signet_ID):
            dead_ally = self._find_dead_ally()
            if dead_ally and (yield from self.CastSkillID(Death_Pact_Signet_ID, target_agent_id=dead_ally, log=False, aftercast_delay=250)):
                return True

        # Direct heals, most urgent first.
        if (yield from self.skills.Ritualist.RestorationMagic.Spirit_Light(health_threshold=0.60)):
            return True

        if (yield from self.skills.Ritualist.RestorationMagic.Mend_Body_and_Soul(health_threshold=0.75)):
            return True

        if self.IsSkillEquipped(Spirit_Transfer_ID) and (yield from self.skills.Ritualist.RestorationMagic.Spirit_Transfer(health_threshold=0.50)):
            return True

        # Ongoing spirit pressure/utility.
        if (yield from self.skills.Ritualist.ChannelingMagic.Signet_of_Spirits()):
            return True

        if self.IsSkillEquipped(Bloodsong_ID) and (yield from self.skills.Ritualist.ChannelingMagic.Bloodsong()):
            return True

        if self.IsSkillEquipped(Weapon_of_Shadow_ID):
            ally = self._find_low_health_ally(0.90)
            if ally and (yield from self.CastSkillID(Weapon_of_Shadow_ID, target_agent_id=ally, log=False, aftercast_delay=250)):
                return True

        # Opportunistic energy refill: skip when at or above 70% energy.
        if self.IsSkillEquipped(Spirit_Siphon_ID) and (yield from self.skills.Ritualist.ChannelingMagic.Spirit_Siphon(max_self_energy_pct=0.70)):
            return True

        return False
