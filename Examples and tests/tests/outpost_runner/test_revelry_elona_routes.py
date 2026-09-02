from __future__ import annotations

import ast
import math
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
ELONA = (
    ROOT
    / 'Sources'
    / 'aC_Scripts'
    / 'OutpostRunner'
    / 'maps'
    / 'Wayfarers Reverie - Elona'
)


def _segments(route_name: str):
    path = ELONA / route_name
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id.endswith('_segments'):
            return ast.literal_eval(node.value)
    raise AssertionError(f'{route_name}: segments were not found')


def _turn_angle(a, b, c) -> float:
    incoming = (b[0] - a[0], b[1] - a[1])
    outgoing = (c[0] - b[0], c[1] - b[1])
    dot = incoming[0] * outgoing[0] + incoming[1] * outgoing[1]
    cross = incoming[0] * outgoing[1] - incoming[1] * outgoing[0]
    return abs(math.degrees(math.atan2(cross, dot)))


class RevelryElonaRouteTests(unittest.TestCase):
    def test_replacement_capture_endings_are_present(self):
        route_1 = _segments(
            '_1_blacktideden_to_fahranurthefirstcity.py'
        )[0]['path']
        route_3 = _segments(
            '_3_camphojanu_to_barbarousshore.py'
        )[0]['path']
        route_8 = _segments(
            '_8_themouthoftorment_to_crystaloverlook.py'
        )[1]['path']

        self.assertEqual(route_1[-1], (-4043.49, -1813.56))
        self.assertEqual(route_3[-1], (-3474.06, -4451.10))
        self.assertEqual(route_8[-1], (-10687.53, 9991.01))

    def test_route_5_has_no_geometric_lookback(self):
        route_5 = _segments(
            '_5_mihanutownship_to_holdingsofchokhin.py'
        )[0]['path']
        sharpest = max(
            _turn_angle(route_5[index - 1], route_5[index], route_5[index + 1])
            for index in range(1, len(route_5) - 1)
        )
        self.assertLess(sharpest, 100.0)


if __name__ == '__main__':
    unittest.main()
