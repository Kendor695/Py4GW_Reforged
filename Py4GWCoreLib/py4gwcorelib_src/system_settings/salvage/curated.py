"""Current-layer Salvage keep-list catalog helpers.

This module owns presentation groupings only. The values come from the current Item.Mods upgrade
registry; it does not import or execute the legacy LootEx/ItemManager rule system.
"""

from ..loot_filter_factory import item_types
from ..loot_filter_factory import upgrades


_PROFESSIONS = (
    "Assassin",
    "Dervish",
    "Elementalist",
    "Mesmer",
    "Monk",
    "Necromancer",
    "Paragon",
    "Ranger",
    "Ritualist",
    "Warrior",
)
_TIERS = ("Superior", "Major", "Minor", "General")
_WEAPON_COMPONENTS = (
    ("Axe", ("Axe Haft", "Axe Grip")),
    ("Bow", ("Bow String", "Bow Grip")),
    ("Daggers", ("Dagger Tang", "Dagger Handle")),
    ("Hammer", ("Hammer Haft", "Hammer Grip")),
    ("Scythe", ("Scythe Snathe", "Scythe Grip")),
    ("Spear", ("Spearhead", "Spear Grip")),
    ("Sword", ("Sword Hilt", "Sword Pommel")),
    ("Staff", ("Staff Head", "Staff Wrapping")),
    ("Wand", ("Wand Wrapping",)),
    ("Shield", ("Shield Handle",)),
    ("Offhand", ("Focus Core",)),
)
_WEAPON_MOD_TARGETS: dict[str, tuple[str, ...]] = {
    "Adept": ("Staff",),
    "Barbed": ("Axe", "Bow", "Daggers", "Scythe", "Spear", "Sword"),
    "Crippling": ("Axe", "Bow", "Daggers", "Scythe", "Spear", "Sword"),
    "Cruel": ("Axe", "Daggers", "Hammer", "Scythe", "Spear", "Sword"),
    "Defensive": ("Staff",),
    "Ebon": ("Axe", "Bow", "Daggers", "Hammer", "Scythe", "Spear", "Sword"),
    "Fiery": ("Axe", "Bow", "Daggers", "Hammer", "Scythe", "Spear", "Sword"),
    "Furious": ("Axe", "Daggers", "Hammer", "Scythe", "Spear", "Sword"),
    "Hale": ("Staff",),
    "Heavy": ("Axe", "Hammer", "Scythe", "Spear"),
    "Icy": ("Axe", "Bow", "Daggers", "Hammer", "Scythe", "Spear", "Sword"),
    "Insightful": ("Staff",),
    "Poisonous": ("Axe", "Bow", "Daggers", "Scythe", "Spear", "Sword"),
    "Shocking": ("Axe", "Bow", "Daggers", "Hammer", "Scythe", "Spear", "Sword"),
    "Silencing": ("Bow", "Daggers", "Spear"),
    "Sundering": ("Axe", "Bow", "Daggers", "Hammer", "Scythe", "Spear", "Sword"),
    "Swift": ("Staff",),
    "VampiricMajor": ("Bow", "Hammer", "Scythe"),
    "VampiricMinor": ("Axe", "Daggers", "Spear", "Sword"),
    "Zealous": ("Axe", "Bow", "Daggers", "Hammer", "Scythe", "Spear", "Sword"),
    "OfAttribute": ("Axe", "Bow", "Daggers", "Hammer", "Scythe", "Spear", "Staff", "Sword"),
    "OfAptitude": ("Offhand",),
    "OfAxeMastery": ("Axe",),
    "OfDaggerMastery": ("Daggers",),
    "OfDefense": ("Axe", "Bow", "Daggers", "Hammer", "Scythe", "Spear", "Staff", "Sword"),
    "OfDevotion": ("Offhand", "Shield", "Staff"),
    "OfEnchanting": ("Axe", "Bow", "Daggers", "Hammer", "Scythe", "Spear", "Staff", "Sword"),
    "OfEndurance": ("Offhand", "Shield", "Staff"),
    "OfFortitude": ("Axe", "Bow", "Daggers", "Hammer", "Offhand", "Scythe", "Shield", "Spear", "Staff", "Sword"),
    "OfHammerMastery": ("Hammer",),
    "OfMarksmanship": ("Bow",),
    "OfMastery": ("Staff",),
    "OfMemory": ("Wand",),
    "OfQuickening": ("Wand",),
    "OfScytheMastery": ("Scythe",),
    "OfShelter": ("Axe", "Bow", "Daggers", "Hammer", "Scythe", "Spear", "Staff", "Sword"),
    "OfSlaying": ("Axe", "Bow", "Hammer", "Staff", "Sword"),
    "OfSpearMastery": ("Spear",),
    "OfSwiftness": ("Offhand",),
    "OfSwordsmanship": ("Sword",),
    "OfTheProfession": ("Axe", "Bow", "Daggers", "Hammer", "Scythe", "Spear", "Staff", "Sword", "Wand"),
    "OfValor": ("Offhand", "Shield", "Staff"),
    "OfWarding": ("Axe", "Bow", "Daggers", "Hammer", "Scythe", "Spear", "Staff", "Sword"),
}
_INSCRIPTION_TARGET_GROUPS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    # These target classes come from the current Item.Mods registry. The UI expands them to
    # concrete item types so a generated keep filter remains specific to the selected weapon.
    (("Axe", "Bow", "Daggers", "Hammer", "Scythe", "Spear", "Sword", "Staff", "Wand"), (
        "BrawnOverBrains",
        "DanceWithDeath",
        "DontFearTheReaper",
        "DontThinkTwice",
        "GuidedByFate",
        "StrengthAndHonor",
        "ToThePain",
        "TooMuchInformation",
        "VengeanceIsMine",
    )),
    (("Axe", "Bow", "Daggers", "Hammer", "Scythe", "Spear", "Sword"), (
        "IHaveThePower",
        "LetTheMemoryLiveAgain",
    )),
    (("Staff", "Wand"), (
        "AptitudeNotAttitude",
        "DontCallItAComeback",
        "HaleAndHearty",
        "HaveFaith",
        "IAmSorrow",
        "SeizeTheDay",
    )),
    (("Offhand",), (
        "BeJustAndFearNot",
        "DownButNotOut",
        "FaithIsMyShield",
        "ForgetMeNot",
        "HailToTheKing",
        "IgnoranceIsBliss",
        "KnowingIsHalfTheBattle",
        "LifeIsPain",
        "LiveForToday",
        "ManForAllSeasons",
        "MightMakesRight",
        "SerenityNow",
        "SurvivalOfTheFittest",
    )),
    (("Offhand", "Shield"), (
        "CastOutTheUnclean",
        "FearCutsDeeper",
        "ICanSeeClearlyNow",
        "LeafOnTheWind",
        "LikeARollingStone",
        "LuckOfTheDraw",
        "MasterOfMyDomain",
        "NotTheFace",
        "NothingToFear",
        "OnlyTheStrongSurvive",
        "PureOfHeart",
        "RidersOnTheStorm",
        "RunForYourLife",
        "ShelteredByFaith",
        "SleepNowInTheFire",
        "SoundnessOfMind",
        "StrengthOfBody",
        "SwiftAsTheWind",
        "TheRiddleOfSteel",
        "ThroughThickAndThin",
    )),
    (("Axe", "Bow", "Daggers", "Hammer", "Offhand", "Scythe", "Shield", "Spear", "Staff", "Sword", "Wand"), (
        "MeasureForMeasure",
        "ShowMeTheMoney",
    )),
)
_INSIGNIA_PROFESSIONS = {
    "DreadnoughtInsignia": "Warrior",
    "KnightsInsignia": "Warrior",
    "LieutenantsInsignia": "Warrior",
    "SentinelsInsignia": "Warrior",
    "StonefistInsignia": "Warrior",
    "BeastmastersInsignia": "Ranger",
    "EarthboundInsignia": "Ranger",
    "FrostboundInsignia": "Ranger",
    "PyreboundInsignia": "Ranger",
    "ScoutsInsignia": "Ranger",
    "StormboundInsignia": "Ranger",
    "AnchoritesInsignia": "Monk",
    "DisciplesInsignia": "Monk",
    "WanderersInsignia": "Monk",
    "BlightersInsignia": "Necromancer",
    "BloodstainedInsignia": "Necromancer",
    "BonelaceInsignia": "Necromancer",
    "MinionMastersInsignia": "Necromancer",
    "TormentorsInsignia": "Necromancer",
    "UndertakersInsignia": "Necromancer",
    "ArtificersInsignia": "Mesmer",
    "ProdigysInsignia": "Mesmer",
    "VirtuososInsignia": "Mesmer",
    "AeromancerInsignia": "Elementalist",
    "GeomancerInsignia": "Elementalist",
    "HydromancerInsignia": "Elementalist",
    "PrismaticInsignia": "Elementalist",
    "PyromancerInsignia": "Elementalist",
    "InfiltratorsInsignia": "Assassin",
    "NightstalkersInsignia": "Assassin",
    "SaboteursInsignia": "Assassin",
    "VanguardsInsignia": "Assassin",
    "GhostForgeInsignia": "Ritualist",
    "MysticsInsignia": "Ritualist",
    "ShamansInsignia": "Ritualist",
    "CenturionsInsignia": "Paragon",
    "ForsakenInsignia": "Dervish",
    "WindwalkerInsignia": "Dervish",
}
_GENERAL_RUNE_RARITIES = {
    "RuneOfAttunement": "Minor",
    "RuneOfVitae": "Minor",
    "RuneOfClarity": "Major",
    "RuneOfPurity": "Major",
    "RuneOfRecovery": "Major",
    "RuneOfRestoration": "Major",
}


def upgrade_groups() -> tuple[tuple[str, list[tuple[str, str]]], ...]:
    values = upgrades.lists()
    return tuple(
        (label, list(values.get(key, [])))
        for key, label in (
            ("runes", "Runes"),
            ("insignias", "Insignias"),
            ("inscriptions", "Inscriptions"),
            ("prefixes", "Weapon prefixes"),
            ("suffixes", "Weapon suffixes"),
        )
        if values.get(key)
    )


def weapon_types() -> list[tuple[str, int]]:
    for group, entries in item_types.grouped():
        if group == "Weapons":
            return entries
    return []


def item_type_groups() -> list[tuple[str, list[tuple[str, int]]]]:
    """Return the concrete item types in the shared user-facing groups."""
    return item_types.grouped()


def grouped_weapon_mods() -> list[tuple[str, list[tuple[str, list[tuple[str, str]]]]]]:
    """Return weapon upgrades as ``weapon -> component -> entries`` groups."""
    values = dict(upgrade_groups())
    prefixes = {internal: (display, internal) for display, internal in values.get("Weapon prefixes", [])}
    suffixes = {internal: (display, internal) for display, internal in values.get("Weapon suffixes", [])}
    inscriptions = {internal: (display, internal) for display, internal in values.get("Inscriptions", [])}
    inscription_targets = {
        internal: targets
        for targets, names in _INSCRIPTION_TARGET_GROUPS
        for internal in names
    }
    output: list[tuple[str, list[tuple[str, list[tuple[str, str]]]]]] = []
    for weapon, components in _WEAPON_COMPONENTS:
        target_names = set(_WEAPON_MOD_TARGETS)
        component_groups: list[tuple[str, list[tuple[str, str]]]] = []
        for index, component in enumerate(components):
            source = prefixes if index == 0 and len(components) == 2 else suffixes
            entries = [
                source[internal]
                for internal in target_names
                if weapon in _WEAPON_MOD_TARGETS[internal] and internal in source
            ]
            if entries:
                component_groups.append((component, sorted(entries)))
        inscription_entries = [
            inscriptions[internal]
            for internal, targets in inscription_targets.items()
            if weapon in targets and internal in inscriptions
        ]
        if inscription_entries:
            component_groups.append(("Inscriptions", sorted(inscription_entries)))
        if component_groups:
            output.append((weapon, component_groups))
    return output


def _profession(name: str) -> str:
    return next((profession for profession in _PROFESSIONS if name.startswith(profession)), "General")


def _insignia_profession(internal: str) -> str:
    """Return the profession restriction; missing entries are the Common/Any insignias."""
    return _INSIGNIA_PROFESSIONS.get(internal, "Common")


def _tier(name: str) -> str:
    return next((tier for tier in _TIERS[:-1] if tier in name), "General")


def _rune_type(display: str, internal: str, profession: str) -> str:
    """Return the attribute/effect name without profession or rarity words."""
    prefix = "Rune of " if profession == "General" else "%s Rune of " % profession
    if display.startswith(prefix):
        remainder = display[len(prefix):]
        for tier in _TIERS[:-1]:
            tier_prefix = tier + " "
            if remainder.startswith(tier_prefix):
                remainder = remainder[len(tier_prefix):]
                break
        return "Vigor" if remainder == "Vigor2" else remainder

    remainder = internal
    if profession != "General" and remainder.startswith(profession):
        remainder = remainder[len(profession):]
    if remainder.startswith("RuneOf"):
        remainder = remainder[len("RuneOf"):]
    for tier in _TIERS[:-1]:
        if remainder.startswith(tier):
            remainder = remainder[len(tier):]
            break
    if remainder == "Vigor2":
        remainder = "Vigor"
    words: list[str] = []
    current = ""
    for character in remainder:
        if character.isupper() and current:
            words.append(current)
            current = character
        else:
            current += character
    if current:
        words.append(current)
    return " ".join(words) or "General"


def grouped_runes() -> list[tuple[str, list[tuple[str, list[tuple[str, list[tuple[str, str]]]]]]]]:
    """Return runes as ``profession -> rune type -> rarity -> entries``."""
    entries = dict(upgrade_groups()).get("Runes", [])
    grouped: dict[str, dict[str, dict[str, list[tuple[str, str]]]]] = {}
    for display, internal in entries:
        profession = _profession(internal)
        rune_type = _rune_type(display, internal, profession)
        rarity = _GENERAL_RUNE_RARITIES.get(internal, _tier(internal))
        grouped.setdefault(profession, {}).setdefault(rune_type, {}).setdefault(rarity, []).append(
            (display, internal)
        )

    output: list[tuple[str, list[tuple[str, list[tuple[str, list[tuple[str, str]]]]]]]] = []
    for profession in _PROFESSIONS + ("General",):
        type_groups = grouped.get(profession, {})
        if not type_groups:
            continue
        output.append(
            (
                profession,
                [
                    (
                        rune_type,
                        [
                            (rarity, sorted(type_groups[rune_type][rarity]))
                            for rarity in _TIERS
                            if rarity in type_groups[rune_type]
                        ],
                    )
                    for rune_type in sorted(type_groups)
                ],
            )
        )
    return output


def grouped_upgrades(category: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """Return digestible tree groups for one current upgrade category."""
    if category == "Weapon Mods":
        values = upgrades.lists()
        return [
            ("Prefixes", list(values.get("prefixes", []))),
            ("Suffixes", list(values.get("suffixes", []))),
        ]
    entries = dict(upgrade_groups()).get(category, [])

    if category == "Insignias":
        profession_groups: dict[str, list[tuple[str, str]]] = {}
        for display, internal in entries:
            profession = _insignia_profession(internal)
            profession_groups.setdefault(profession, []).append((display, internal))
        return [
            (profession, sorted(profession_groups[profession]))
            for profession in _PROFESSIONS + ("Common",)
            if profession in profession_groups
        ]

    grouped: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for display, internal in entries:
        key = (_profession(internal), _tier(internal))
        grouped.setdefault(key, []).append((display, internal))
    output: list[tuple[str, list[tuple[str, str]]]] = []
    for profession in _PROFESSIONS + ("General",):
        for tier in _TIERS:
            values = grouped.get((profession, tier), [])
            if values:
                output.append(("%s / %s" % (profession, tier), sorted(values)))
    if category == "Inscriptions":
        # Inscriptions do not carry a stable profession prefix. Alphabetical bands keep
        # this category scannable without inventing a taxonomy that the registry does not own.
        bands: dict[str, list[tuple[str, str]]] = {}
        for _group, values in output:
            for display, internal in values:
                initial = display[:1].upper() or "#"
                band = next(
                    (
                        label
                        for label, letters in (
                            ("A-F", "ABCDEF"),
                            ("G-L", "GHIJKL"),
                            ("M-R", "MNOPQR"),
                            ("S-Z", "STUVWXYZ"),
                        )
                        if initial in letters
                    ),
                    "#",
                )
                bands.setdefault(band, []).append((display, internal))
        return [(band, sorted(values)) for band, values in bands.items()]
    return output


def entry_groups(entries: list[tuple[str, str]]) -> list[tuple[str, list[tuple[str, str]]]]:
    """Split oversized tree groups into alphabetical bands for the configuration UI."""
    if len(entries) <= 24:
        return [("", sorted(entries))]
    bands: dict[str, list[tuple[str, str]]] = {}
    for display, internal in entries:
        initial = display[:1].upper() or "#"
        band = next(
            (
                label
                for label, letters in (
                    ("A-F", "ABCDEF"),
                    ("G-L", "GHIJKL"),
                    ("M-R", "MNOPQR"),
                    ("S-Z", "STUVWXYZ"),
                )
                if initial in letters
            ),
            "#",
        )
        bands.setdefault(band, []).append((display, internal))
    return [(band, sorted(values)) for band, values in bands.items()]
