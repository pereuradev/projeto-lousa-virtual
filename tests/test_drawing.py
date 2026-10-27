"""Behavioral checks for drawing, undo/export, and camera-independent gestures."""

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops

from lousa.drawing import Board, GestureFilter


def hand(point=(0.5, 0.5), ratio=0.2, palm_size=0.2):
    landmarks = [SimpleNamespace(x=0.5, y=0.5) for _ in range(21)]
    landmarks[8] = SimpleNamespace(x=point[0], y=point[1])
    landmarks[4] = SimpleNamespace(x=point[0] + ratio * palm_size, y=point[1])
    landmarks[5] = SimpleNamespace(x=0.4, y=0.7)
    landmarks[17] = SimpleNamespace(x=0.4 + palm_size, y=0.7)
    return landmarks


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.board = Board(100, 70)

    def assertImagesEqual(self, first, second):
        self.assertEqual(first.mode, second.mode)
        self.assertEqual(first.size, second.size)
        self.assertIsNone(ImageChops.difference(first, second).getbbox())

    def test_initial_point_is_drawn_and_undo_restores_blank(self):
        self.assertFalse(self.board.dirty)
        self.assertFalse(self.board.undo())
        self.board.begin((20, 30), "#123456", 7)
        self.assertEqual(self.board.image.getpixel((20, 30)), (18, 52, 86))
        self.assertEqual(self.board.stroke_count, 1)
        self.assertTrue(self.board.dirty)
        self.assertTrue(self.board.undo())
        self.assertEqual(self.board.image.getpixel((20, 30)), (255, 255, 255))
        self.assertEqual(self.board.stroke_count, 0)
        self.assertFalse(self.board.dirty)

    def test_stroke_is_continuous_with_round_caps_and_single_undo(self):
        self.board.begin((15, 30), "black", 9)
        self.board.move((45, 30))
        self.board.move((80, 30))
        self.board.end()
        self.assertEqual(self.board.stroke_count, 1)
        for x in range(15, 81):
            self.assertEqual(self.board.image.getpixel((x, 30)), (0, 0, 0))
        self.assertEqual(self.board.image.getpixel((12, 30)), (0, 0, 0))
        self.assertEqual(self.board.image.getpixel((83, 30)), (0, 0, 0))
        self.assertTrue(self.board.undo())
        self.assertFalse(self.board.undo())

    def test_released_strokes_do_not_connect(self):
        self.board.begin((10, 15), "black", 3)
        self.board.move((25, 15))
        self.board.end()
        self.board.move((75, 15))
        self.board.begin((75, 15), "black", 3)
        self.board.end()
        self.assertEqual(self.board.image.getpixel((50, 15)), (255, 255, 255))
        self.assertEqual(self.board.stroke_count, 2)

    def test_coordinates_are_clamped_to_canvas(self):
        self.board.begin((-100, -100), "red", 1)
        self.board.move((200, 140))
        self.board.end()
        self.assertEqual(self.board.image.getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(self.board.image.getpixel((99, 69)), (255, 0, 0))

    def test_eraser_is_white_uses_width_and_can_be_undone(self):
        self.board.begin((10, 35), "blue", 15)
        self.board.move((90, 35))
        self.board.end()
        drawing = self.board.image.copy()
        self.board.begin((50, 10), "red", 9, erase=True)
        self.board.move((50, 60))
        self.board.end()
        self.assertEqual(self.board.image.getpixel((50, 35)), (255, 255, 255))
        self.assertEqual(self.board.image.getpixel((47, 35)), (255, 255, 255))
        self.assertEqual(self.board.image.getpixel((40, 35)), (0, 0, 255))
        self.assertTrue(self.board.undo())
        self.assertImagesEqual(self.board.image, drawing)
        self.assertEqual(self.board.stroke_count, 1)

    def test_clear_is_undoable_and_repeated_empty_clear_is_not_recorded(self):
        self.board.clear()
        self.assertFalse(self.board.undo())
        self.board.begin((30, 30), "black", 8)
        self.board.end()
        drawing = self.board.image.copy()
        self.board.clear()
        self.assertEqual(self.board.stroke_count, 0)
        self.board.clear()
        self.board.clear()
        self.assertTrue(self.board.undo())
        self.assertImagesEqual(self.board.image, drawing)
        self.assertEqual(self.board.stroke_count, 1)
        self.assertTrue(self.board.undo())
        self.assertFalse(self.board.undo())

    def test_erasing_blank_does_not_consume_history(self):
        self.board.begin((10, 10), "black", 8, erase=True)
        self.board.move((80, 50))
        self.board.end()
        self.assertFalse(self.board.undo())
        self.assertFalse(self.board.dirty)
        self.assertEqual(self.board.stroke_count, 0)

    def test_clear_resets_count_after_all_ink_was_erased(self):
        self.board.begin((20, 20), "black", 5)
        self.board.end()
        self.board.begin((20, 20), "black", 11, erase=True)
        self.board.end()
        self.assertEqual(self.board.stroke_count, 2)
        self.board.clear()
        self.assertEqual(self.board.stroke_count, 0)
        self.assertTrue(self.board.undo())
        self.assertEqual(self.board.image.getpixel((20, 20)), (0, 0, 0))

    def test_eraser_starting_on_blank_keeps_snapshot_when_it_reaches_ink(self):
        self.board.begin((50, 30), "black", 11)
        self.board.end()
        drawing = self.board.image.copy()
        self.board.begin((5, 30), "black", 9, erase=True)
        self.board.move((80, 30))
        self.board.end()
        self.assertTrue(self.board.undo())
        self.assertImagesEqual(self.board.image, drawing)

    def test_undo_limit_keeps_only_25_states(self):
        for x in range(30):
            self.board.begin((x * 3 + 2, 20), "black", 1)
            self.board.end()
        undone = sum(self.board.undo() for _ in range(30))
        self.assertEqual(undone, 25)
        self.assertEqual(self.board.stroke_count, 5)
        self.assertEqual(self.board.image.getpixel((2, 20)), (0, 0, 0))
        self.assertEqual(self.board.image.getpixel((89, 20)), (255, 255, 255))

    def test_unicode_png_export_is_canvas_only_and_never_overwrites(self):
        self.board.begin((10, 12), "green", 5)
        self.board.end()
        with TemporaryDirectory() as root:
            directory = Path(root) / "Exportações da lousa" / "ação 東京"
            with patch("lousa.drawing.datetime") as clock:
                clock.now.return_value = datetime(2026, 10, 26, 12, 34, 56, 789)
                first = self.board.save(directory)
                first_bytes = first.read_bytes()
                second = self.board.save(directory)
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_bytes(), first_bytes)
            self.assertEqual(len(list(directory.glob("*.png"))), 2)
            with Image.open(second) as exported:
                self.assertEqual(exported.format, "PNG")
                self.assertEqual(exported.mode, "RGB")
                self.assertImagesEqual(exported, self.board.image)
                self.assertEqual(exported.getpixel((99, 69)), (255, 255, 255))
            self.assertFalse(self.board.dirty)
            self.board.begin((60, 50), "black", 5)
            self.board.end()
            self.assertTrue(self.board.dirty)
            self.assertTrue(self.board.undo())
            self.assertFalse(self.board.dirty)

    def test_invalid_arguments_are_rejected_without_altering_drawing(self):
        for point, width in [((float("nan"), 1), 2), ((1, 1), 0)]:
            with self.assertRaises(ValueError):
                self.board.begin(point, "black", width)
        self.assertFalse(self.board.dirty)
        self.assertFalse(self.board.undo())
        with self.assertRaises(ValueError):
            Board(0, 70)


class GestureFilterTests(unittest.TestCase):
    def setUp(self):
        self.filter = GestureFilter()

    def test_two_consecutive_frames_are_required(self):
        self.assertFalse(self.filter.update(hand(ratio=0.2))[1])
        self.assertTrue(self.filter.update(hand(ratio=0.2))[1])

    def test_release_and_restart_require_new_consecutive_frames(self):
        self.filter.update(hand(ratio=0.2))
        self.assertTrue(self.filter.update(hand(ratio=0.2))[1])
        self.assertFalse(self.filter.update(hand(ratio=0.6))[1])
        self.assertFalse(self.filter.update(hand(ratio=0.2))[1])
        self.assertTrue(self.filter.update(hand(ratio=0.2))[1])

    def test_hysteresis_prevents_chatter(self):
        self.filter.update(hand(ratio=0.3))
        self.assertTrue(self.filter.update(hand(ratio=0.3))[1])
        for ratio in (0.37, 0.48, 0.39, 0.45):
            self.assertTrue(self.filter.update(hand(ratio=ratio))[1])
        self.assertFalse(self.filter.update(hand(ratio=0.51))[1])
        for _ in range(3):
            self.assertFalse(self.filter.update(hand(ratio=0.4))[1])

    def test_threshold_boundaries_allow_start_and_release(self):
        self.assertFalse(self.filter.update(hand(ratio=0.35))[1])
        self.assertTrue(self.filter.update(hand(ratio=0.35))[1])
        self.assertFalse(self.filter.update(hand(ratio=0.50))[1])

    def test_nonconsecutive_close_frames_do_not_start_a_pinch(self):
        for ratio in (0.2, 0.45, 0.2, 0.45, 0.2):
            self.assertFalse(self.filter.update(hand(ratio=ratio))[1])

    def test_pinch_ratio_is_independent_of_palm_size(self):
        for palm_size in (0.08, 0.2, 0.4):
            filter_ = GestureFilter()
            self.assertFalse(filter_.update(hand(ratio=0.3, palm_size=palm_size))[1])
            self.assertTrue(filter_.update(hand(ratio=0.3, palm_size=palm_size))[1])
            self.assertFalse(filter_.update(hand(ratio=0.6, palm_size=palm_size))[1])

    def test_active_camera_region_maps_to_full_canvas(self):
        self.assertEqual(self.filter.update(hand(point=(0.1, 0.1)))[0], (0.0, 0.0))
        self.filter.reset()
        self.assertEqual(self.filter.update(hand(point=(0.9, 0.9)))[0], (1.0, 1.0))
        self.filter.reset()
        self.assertEqual(self.filter.update(hand(point=(-0.5, 1.4)))[0], (0.0, 1.0))

    def test_ema_uses_requested_alpha(self):
        self.filter.update(hand(point=(0.1, 0.1)))
        point, _ = self.filter.update(hand(point=(0.9, 0.9)))
        self.assertAlmostEqual(point[0], 0.38)
        self.assertAlmostEqual(point[1], 0.38)

    def test_lost_hand_resets_pinch_debounce_and_smoothing(self):
        self.filter.update(hand(point=(0.1, 0.1)))
        self.assertTrue(self.filter.update(hand(point=(0.1, 0.1)))[1])
        self.assertEqual(self.filter.update(None), (None, False))
        point, pinching = self.filter.update(hand(point=(0.9, 0.9)))
        self.assertEqual(point, (1.0, 1.0))
        self.assertFalse(pinching)
        self.assertTrue(self.filter.update(hand(point=(0.9, 0.9)))[1])

    def test_invalid_landmarks_reset_an_existing_pinch(self):
        for invalid in ([], [None] * 21, hand(palm_size=0), hand(point=(float("nan"), 0.5))):
            self.filter.update(hand())
            self.filter.update(hand())
            self.assertEqual(self.filter.update(invalid), (None, False))
            self.assertFalse(self.filter.update(hand())[1])


if __name__ == "__main__":
    unittest.main()
