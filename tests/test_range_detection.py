"""Tests ciblés de la détection locale de portée de Coagulation."""
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.combat import (  # noqa: E402
    Fighter,
    assess_targets_in_range,
    find_enemies,
    range_fraction,
    range_mask,
)


class RangeDetectionTests(unittest.TestCase):
    def test_small_visible_area_can_confirm_a_target_locally(self):
        mask = np.zeros((1020, 1920), dtype=np.uint8)
        target = (900, 500)
        # 120 pixels violets dans la zone de la cible : fraction > 5 %,
        # mais masque global inférieur à l'ancien seuil de 800 pixels.
        mask[493:505, 895:905] = 1
        self.assertLess(int(mask.sum()), 800)
        self.assertGreaterEqual(range_fraction(mask, target), 0.05)
        enemy = Fighter(*target, pixels=200)
        found, known, fractions = assess_targets_in_range(mask, [enemy], 0.05)
        self.assertEqual(found, [enemy])
        self.assertTrue(known)
        self.assertGreaterEqual(fractions[0], 0.05)

    def test_weak_mask_elsewhere_does_not_confirm_target(self):
        mask = np.zeros((1020, 1920), dtype=np.uint8)
        mask[100:112, 100:110] = 1
        enemy = Fighter(900, 500, pixels=200)
        found, known, fractions = assess_targets_in_range(mask, [enemy], 0.05)
        self.assertEqual(found, [])
        self.assertFalse(known)
        self.assertEqual(fractions, [0.0])

    def test_existing_game_fixtures_keep_their_range_classification(self):
        fixtures = ROOT / "tests" / "fixtures"
        expected = {
            "10_sort_choisi.png": (4, 1),
            "09c_creature_sort_choisi.png": (2, 2),
            "19_nouvelle_carte_sort_choisi.png": (3, 2),
        }
        for name, (enemy_count, in_range_count) in expected.items():
            with self.subTest(fixture=name):
                image = cv2.imread(str(fixtures / name))
                self.assertIsNotNone(image)
                enemies = find_enemies(image)
                found, known, _ = assess_targets_in_range(range_mask(image), enemies, 0.05)
                self.assertEqual(len(enemies), enemy_count)
                self.assertTrue(known)
                self.assertEqual(len(found), in_range_count)


if __name__ == "__main__":
    unittest.main()
