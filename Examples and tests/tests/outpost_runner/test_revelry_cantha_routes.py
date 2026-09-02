from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
CANTHA = (
    ROOT
    / 'Sources'
    / 'aC_Scripts'
    / 'OutpostRunner'
    / 'maps'
    / 'Wayfarers Reverie - Cantha'
)


def _segments(route_name: str):
    path = CANTHA / route_name
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id.endswith('_segments'):
            return ast.literal_eval(node.value)
    raise AssertionError(f'{route_name}: segments were not found')


class RevelryCanthaRouteTests(unittest.TestCase):
    def test_minister_cho_replacement_ending(self):
        points = _segments(
            '_1_ministerchosestateoutpost_to_sunquavale.py'
        )[0]['path']
        self.assertEqual(points[-1], (-6922, 7879))
        self.assertNotIn((-6977, 7834), points)

    def test_zen_daijun_replacement_ending(self):
        points = _segments(
            '_2_zendaijunoutpost_to_haijulagoon.py'
        )[0]['path']
        self.assertEqual(points[-1], (-2813, 6697))
        self.assertNotIn((-3186, 6184), points)

    def test_raisu_palace_reversal_is_removed(self):
        points = _segments(
            '_8_imperialsanctumoutpost_to_raisupalace.py'
        )[0]['path']
        self.assertNotIn((1082, -7045), points)
        self.assertIn((3146, -7106), points)
        self.assertIn((2918, -6205), points)


if __name__ == '__main__':
    unittest.main()
