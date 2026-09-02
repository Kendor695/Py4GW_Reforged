from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).parents[2]
WIDGET_DIR = ROOT / "Widgets" / "Automation" / "Bots" / "SkillsUnlocker"
WIDGET_PATH = WIDGET_DIR / "EOTN_SKILL_UNLOCKER.py"


class SkillsUnlockerWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WIDGET_PATH.read_text(encoding="utf-8")
        start = cls.source.index("def draw_window_light")
        end = cls.source.index("\n# Monkeypatch UI method", start)
        cls.draw_window_source = cls.source[start:end]

    def test_widget_folder_has_discovery_marker(self) -> None:
        self.assertTrue(
            (WIDGET_DIR / ".widget").is_file(),
            "Skills Unlocker requires a .widget marker for widget discovery",
        )

    def test_draw_window_light_does_not_close_unopened_child_or_tab(self) -> None:
        self.assertNotIn(
            "PyImGui.end_child()",
            self.draw_window_source,
            "draw_window_light must not close a child scope it did not open",
        )
        self.assertNotIn(
            "PyImGui.end_tab_item()",
            self.draw_window_source,
            "draw_window_light must not close child or tab scopes it did not open",
        )


if __name__ == "__main__":
    unittest.main()
