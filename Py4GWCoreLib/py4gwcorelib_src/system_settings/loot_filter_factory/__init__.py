"""The Loot Filter Factory -- filters and filter sets, owned by neither feature.

Loot Filters and Recolor & Beacons are standalone: neither imports the other, and neither owns the
filters or filter sets they both use. Those live here, and both features **consume** them.

* :mod:`model` -- ``Filter`` (a composite resolver, criteria only) and ``FilterSet`` (a named group of
  filters for one feature).
* :mod:`matcher` -- all evaluation, including the per-criterion breakdown the live preview shows.
* :mod:`upgrades` -- the five slot-based upgrade lists a user picks from, by name.
* :mod:`store` -- the global filter and filter set store, with short sequential ids.

The authoring UI is this module's too, and stands on its own: a consumer selects, it never hosts the
authoring surface.

**Vocabulary (settled).** evaluation → filter → filter set; see
`docs/loot/redesign/filter-structure.md`. The word "rule" is retired.
"""

from .matcher import any_match
from .matcher import evaluate
from .matcher import matches
from .matcher import matching_filters
from .model import MATCH_ALL
from .model import MATCH_ANY
from .model import Filter
from .model import FilterSet
from .model import ModifierCriterion
from .model import UpgradeCriterion
from .store import filter_by_id
from .store import filter_set_by_id
from .store import filter_set_by_name
from .store import filters_in_set
from .store import legacy_mark_entries
from .store import load_filter_sets
from .store import load_filters
from .store import next_filter_id
from .store import next_filter_set_id
from .store import resolve_filter_set_selection
from .store import save_filter_sets
from .store import save_filters

__all__ = [
    "MATCH_ALL", "MATCH_ANY", "Filter", "FilterSet", "ModifierCriterion", "UpgradeCriterion",
    "any_match", "evaluate", "filter_by_id",
    "filter_set_by_id", "filter_set_by_name", "filters_in_set", "legacy_mark_entries",
    "load_filter_sets", "load_filters", "matches", "matching_filters", "next_filter_id",
    "next_filter_set_id", "resolve_filter_set_selection", "save_filter_sets", "save_filters",
]
