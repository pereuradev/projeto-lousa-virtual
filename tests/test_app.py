"""Headless regressions for gesture segments and modal-dialog drawing guards."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageChops

from lousa.app import App, COLORS, tk
from lousa.camera import CameraWorker
from lousa.controls import ControlState
from lousa.drawing import Board, GestureFilter


class AppGestureTests(unittest.TestCase):
    def setUp(self):
        # Bypass __init__: no Tk root, detector, camera or background thread is
        # created. Only the actual App event and drawing methods are exercised.
        self.app = App.__new__(App)
        self.app.board = Board(101, 61)
        self.app.root = Mock()
        self.app.preview = Mock()
        self.app.canvas = Mock()
        self.app.cursor = "cursor"
        self.app.render = Mock()
        self.app.hand_status = Mock()
        self.app.status = Mock()
        self.app.palette_buttons = [Mock() for _ in COLORS]
        self.app.eraser_button = Mock()
        self.app.tool_label = Mock()
        self.app.control_state = ControlState()
        self.app._control_feedback = Mock()
        self.app._render_control_feedback = Mock()
        self.app.width = SimpleNamespace(get=lambda: 3)
        self.app.gesture = Mock(wraps=GestureFilter())
        # Construct only its transport/state: never start the camera thread.
        self.app.worker = CameraWorker(0, Path("unused-test-model.task"))
        self.app.closed = False
        self.app.dialog_open = False
        self.app.gesture_ready = True
        self.app.gesture_segment = None
        self.app.paused = False
        self.app.source = None
        self.app.color = "black"
        self.app.eraser = False
        self.app.image_box = (0, 0, 101, 61)
        self.now = 100.0
        self.app.last_hand_time = self.now
        self.enterContext(patch("lousa.app.time.monotonic", side_effect=lambda: self.now))
        self.enterContext(patch("lousa.app.Image.fromarray", return_value=Image.new("RGB", (8, 8))))
        self.enterContext(patch("lousa.app.ImageTk.PhotoImage", return_value=object()))

    def frame(self, point=(0.2, 0.5), pinch=True, segment=1, hand_count=1,
              control=None, epoch=None, captured_at=None):
        if epoch is None:
            epoch = self.app.worker.control_context()[1]
        if captured_at is None:
            captured_at = self.now
        hands = [[object() for _ in range(21)] for _ in range(hand_count)]
        self.app.worker.publish(("frame", object(), hands, 30.0, point, pinch, segment,
                                 control or ControlState(hand_count=hand_count), epoch, captured_at))

    def action(self, action, value=None, epoch=None, captured_at=None):
        if epoch is None:
            epoch = self.app.worker.control_context()[1]
        self.app.worker.actions.put((epoch, self.now if captured_at is None else captured_at,
                                     action, value))

    def assertBlankBetweenStrokes(self):
        self.assertEqual(self.app.board.image.getpixel((20, 30)), (0, 0, 0))
        self.assertEqual(self.app.board.image.getpixel((80, 30)), (0, 0, 0))
        for x in range(35, 66):
            self.assertEqual(self.app.board.image.getpixel((x, 30)), (255, 255, 255))

    def test_distinct_pinch_segments_do_not_bridge_without_release_frame(self):
        self.frame(point=(0.2, 0.5), segment=10)
        self.app._tick()
        self.frame(point=(0.8, 0.5), segment=11)
        self.app._tick()

        self.assertEqual(self.app.board.stroke_count, 2)
        self.assertEqual(self.app.gesture_segment, 11)
        self.assertBlankBetweenStrokes()

    def test_latest_frame_queue_drain_can_skip_release_without_bridging(self):
        self.frame(point=(0.2, 0.5), segment=10)
        self.app._tick()
        # _tick deliberately consumes only the newest frame. The segment token
        # must preserve the release boundary even when this release is skipped.
        self.frame(point=(0.5, 0.5), pinch=False, segment=10)
        self.frame(point=(0.8, 0.5), pinch=True, segment=11)
        self.app._tick()

        self.assertTrue(self.app.worker.events.empty())
        self.assertEqual(self.app.board.stroke_count, 2)
        self.assertBlankBetweenStrokes()

    def test_dialog_open_prevents_gesture_drawing(self):
        self.app.dialog_open = True
        self.frame(point=(0.2, 0.5), segment=10)
        self.app._tick()
        self.frame(point=(0.8, 0.5), segment=11)
        self.app._tick()

        self.assertEqual(self.app.board.stroke_count, 0)
        self.assertFalse(self.app.board.dirty)
        self.assertIsNone(self.app.source)
        self.app.gesture.reset.assert_called()
        self.app.canvas.itemconfigure.assert_called_with("cursor", state="hidden")

    def test_clear_confirmation_blocks_reentrant_camera_ticks(self):
        self.frame(point=(0.2, 0.5), segment=10)
        self.app._tick()
        before = self.app.board.image.copy()

        def confirm(*args, **kwargs):
            self.assertTrue(self.app.dialog_open)
            self.assertIsNone(self.app.source)
            self.frame(point=(0.8, 0.5), segment=11)
            self.app._tick()
            self.assertEqual(self.app.board.stroke_count, 1)
            self.assertIsNone(ImageChops.difference(before, self.app.board.image).getbbox())
            return False

        with patch("lousa.app.messagebox.askyesno", side_effect=confirm) as prompt:
            self.app.clear()

        prompt.assert_called_once()
        self.assertFalse(self.app.dialog_open)
        self.assertFalse(self.app.gesture_ready)
        self.assertEqual(self.app.board.stroke_count, 1)
        self.assertIsNone(ImageChops.difference(before, self.app.board.image).getbbox())

    def test_dialog_context_ends_stroke_and_resets_filter_on_normal_exit(self):
        self.app._draw((20, 30), "gesture")
        before = self.app.board.image.copy()

        with self.app.dialog():
            self.assertTrue(self.app.dialog_open)
            self.assertIsNone(self.app.source)
            # A stray move after entry cannot continue the pre-dialog stroke.
            self.app.board.move((80, 30))

        self.assertFalse(self.app.dialog_open)
        self.assertFalse(self.app.gesture_ready)
        self.app.gesture.reset.assert_called_once_with()
        self.assertIsNone(ImageChops.difference(before, self.app.board.image).getbbox())

    def test_dialog_context_resets_flags_and_filter_even_after_exception(self):
        self.app._draw((20, 30), "gesture")
        before = self.app.board.image.copy()

        with self.assertRaisesRegex(RuntimeError, "dialog failure"):
            with self.app.dialog():
                self.assertTrue(self.app.dialog_open)
                self.assertIsNone(self.app.source)
                raise RuntimeError("dialog failure")

        self.assertFalse(self.app.dialog_open)
        self.assertFalse(self.app.gesture_ready)
        self.assertIsNone(self.app.source)
        self.app.gesture.reset.assert_called_once_with()
        self.app.board.move((80, 30))
        self.assertIsNone(ImageChops.difference(before, self.app.board.image).getbbox())

    def test_held_pinch_after_dialog_waits_for_release_before_drawing(self):
        self.frame(point=(0.2, 0.5), segment=10)
        self.app._tick()
        with self.app.dialog():
            pass

        self.frame(point=(0.8, 0.5), pinch=True, segment=11)
        self.app._tick()
        self.assertEqual(self.app.board.stroke_count, 1)
        self.assertEqual(self.app.board.image.getpixel((80, 30)), (255, 255, 255))

        self.frame(point=(0.8, 0.5), pinch=False, segment=11)
        self.app._tick()
        self.assertTrue(self.app.gesture_ready)
        self.frame(point=(0.8, 0.5), pinch=True, segment=12)
        self.app._tick()
        self.assertEqual(self.app.board.stroke_count, 2)
        self.assertBlankBetweenStrokes()

    def test_hand_loss_ends_stroke_before_reappearance(self):
        self.frame(point=(0.2, 0.5), segment=10)
        self.app._tick()
        self.frame(point=None, pinch=False, segment=10, hand_count=0)
        self.app._tick()
        self.assertIsNone(self.app.source)

        self.frame(point=(0.8, 0.5), segment=11)
        self.app._tick()
        self.assertEqual(self.app.board.stroke_count, 2)
        self.assertBlankBetweenStrokes()

    def test_finger_count_color_action_ends_old_stroke_and_next_stroke_uses_new_color(self):
        self.frame(point=(0.2, 0.5), segment=10)
        self.app._tick()
        self.action("color", 1)
        self.frame(point=None, pinch=False,
                   control=ControlState(mode="color", color_index=1, finger_count=2,
                                        hand_count=1, progress=1, select_color=1, blocked=True))
        self.app._tick()

        self.assertEqual(self.app.color, COLORS[1][1])
        self.assertIsNone(self.app.source)
        # Receiving the color state ends the old stroke even when the worker
        # retains the same segment token until the next valid drawing frame.
        self.frame(point=(0.8, 0.5), segment=10)
        self.app._tick()

        self.assertEqual(self.app.board.stroke_count, 2)
        self.assertEqual(self.app.board.image.getpixel((20, 30)), (0, 0, 0))
        self.assertEqual(self.app.board.image.getpixel((80, 30)), (37, 99, 235))
        self.assertEqual(self.app.board.image.getpixel((50, 30)), (255, 255, 255))

    def test_two_open_hands_clear_action_skips_messagebox_and_undo_restores_ink(self):
        self.frame(point=(0.2, 0.5), segment=10)
        self.app._tick()
        self.frame(point=(0.8, 0.5), segment=10)
        self.app._tick()
        before = self.app.board.image.copy()
        self.action("clear")
        self.frame(point=None, pinch=False, hand_count=2,
                   control=ControlState(mode="clear_done", hand_count=2, progress=1,
                                        clear=True, blocked=True))
        with patch("lousa.app.messagebox.askyesno") as confirm:
            self.app._tick()
        confirm.assert_not_called()
        self.assertEqual(self.app.board.stroke_count, 0)
        self.assertEqual(self.app.board.image.getpixel((50, 30)), (255, 255, 255))
        self.assertIsNone(self.app.source)

        self.app.undo()
        self.assertEqual(self.app.board.stroke_count, 1)
        self.assertIsNone(ImageChops.difference(before, self.app.board.image).getbbox())

    def test_one_hand_five_finger_color_action_never_clears_existing_ink(self):
        self.app.board.begin((20, 30), "black", 3)
        self.app.board.end()
        before = self.app.board.image.copy()
        self.app.board.clear = Mock(wraps=self.app.board.clear)
        for finger_count in range(1, 6):
            with self.subTest(finger_count=finger_count):
                index = finger_count - 1
                self.action("color", index)
                self.frame(point=None, pinch=False, hand_count=1,
                           control=ControlState(mode="color", color_index=index,
                                                finger_count=finger_count, hand_count=1,
                                                progress=1, select_color=index, blocked=True))
                self.app._tick()
                self.assertEqual(self.app.color, COLORS[index][1])
                self.assertEqual(self.app.board.stroke_count, 1)
                self.assertIsNone(ImageChops.difference(before, self.app.board.image).getbbox())
        self.app.board.clear.assert_not_called()

    def test_control_blocked_ends_drawing_before_continuation(self):
        self.frame(point=(0.2, 0.5), segment=10)
        self.app._tick()
        self.frame(point=(0.5, 0.5), segment=10,
                   control=ControlState(mode="color", color_index=1, finger_count=2,
                                        hand_count=1, progress=0.5, blocked=True))
        self.app._tick()
        self.assertIsNone(self.app.source)
        self.frame(point=(0.8, 0.5), segment=10)
        self.app._tick()
        self.assertEqual(self.app.board.stroke_count, 2)
        self.assertBlankBetweenStrokes()

    def test_one_hand_pinch_uses_entire_board_height(self):
        self.frame(point=(0.2, 0.0))
        self.app._tick()
        self.assertEqual(self.app.board.image.getpixel((20, 0)), (0, 0, 0))
        self.frame(point=(0.2, 1.0))
        self.app._tick()
        self.assertEqual(self.app.board.stroke_count, 1)
        self.assertEqual(self.app.board.image.getpixel((20, 30)), (0, 0, 0))
        self.assertEqual(self.app.board.image.getpixel((20, 60)), (0, 0, 0))

    def test_two_hands_never_draw_even_with_inconsistent_point_and_pinch(self):
        self.frame(point=(0.2, 0.5), segment=10)
        self.app._tick()
        self.frame(point=(0.5, 0.5), pinch=True, segment=10, hand_count=2,
                   control=ControlState(hand_count=2))
        self.app._tick()
        self.assertIsNone(self.app.source)
        self.assertEqual(self.app.board.stroke_count, 1)
        self.assertEqual(self.app.board.image.getpixel((50, 30)), (255, 255, 255))
        self.frame(point=(0.8, 0.5), segment=11)
        self.app._tick()
        self.assertEqual(self.app.board.stroke_count, 2)
        self.assertBlankBetweenStrokes()

    def test_two_hands_control_state_blocks_drawing(self):
        self.frame(point=(0.5, 0.5), pinch=True, hand_count=2,
                   control=ControlState(mode="two_hands", hand_count=2, blocked=True))
        self.app._tick()
        self.assertEqual(self.app.board.stroke_count, 0)
        self.assertFalse(self.app.board.dirty)

    def test_actions_are_discarded_during_pause_dialog_and_mouse_drawing(self):
        self.app.board.begin((20, 30), "black", 3)
        self.app.board.end()
        before = self.app.board.image.copy()
        for mode in ("paused", "dialog", "mouse"):
            with self.subTest(mode=mode):
                self.app.paused = mode == "paused"
                self.app.dialog_open = mode == "dialog"
                self.app.source = "mouse" if mode == "mouse" else None
                enabled, epoch = self.app._sync_controls()
                self.assertFalse(enabled)
                self.action("color", 2, epoch=epoch)
                self.action("clear", epoch=epoch)
                self.app._tick()
                self.assertEqual(self.app.color, "black")
                self.assertEqual(self.app.board.stroke_count, 1)
                self.assertIsNone(ImageChops.difference(before, self.app.board.image).getbbox())
                self.assertTrue(self.app.worker.actions.empty())
                self.app.paused = self.app.dialog_open = False
                self.app.source = None
                self.app._sync_controls()

    def test_old_epoch_actions_cannot_apply_after_controls_are_reenabled(self):
        old_epoch = self.app.worker.control_context()[1]
        self.app.worker.set_controls_enabled(False)
        self.app.worker.set_controls_enabled(True)
        self.app.board.begin((20, 30), "black", 3)
        self.app.board.end()
        self.action("color", 3, epoch=old_epoch)
        self.action("clear", epoch=old_epoch)
        self.app._tick()
        self.assertEqual(self.app.color, "black")
        self.assertEqual(self.app.board.stroke_count, 1)
        self.assertTrue(self.app.worker.actions.empty())

    def test_stale_actions_are_discarded_but_half_second_boundary_is_accepted(self):
        self.app.board.begin((20, 30), "black", 3)
        self.app.board.end()
        self.action("color", 3, captured_at=self.now - 0.501)
        self.action("clear", captured_at=self.now - 0.501)
        self.app._tick()
        self.assertEqual(self.app.color, "black")
        self.assertEqual(self.app.board.stroke_count, 1)

        self.action("color", 2, captured_at=self.now - 0.5)
        self.app._tick()
        self.assertEqual(self.app.color, COLORS[2][1])
        self.assertEqual(self.app.board.stroke_count, 1)

    def test_control_action_survives_the_frame_that_carried_it_being_dropped(self):
        self.app.select_color = Mock(wraps=self.app.select_color)
        self.action("color", 3)
        self.frame(point=None, pinch=False,
                   control=ControlState(mode="color", color_index=3, finger_count=4,
                                        hand_count=1, progress=1, select_color=3, blocked=True))
        self.frame(point=None, pinch=False, hand_count=0)
        self.frame(point=None, pinch=False, hand_count=0)
        self.assertEqual(self.app.worker.events.qsize(), 2)
        self.app._tick()
        self.app._tick()
        self.assertEqual(self.app.color, COLORS[3][1])
        self.app.select_color.assert_called_once_with(3)
        self.assertEqual(self.app.board.stroke_count, 0)
        self.assertTrue(self.app.worker.actions.empty())

    def test_space_on_focused_button_keeps_only_native_button_action(self):
        self.app.pause = Mock()
        focused_button = object.__new__(tk.Button)
        event = SimpleNamespace(widget=focused_button, state=0, keysym="space")
        self.app._key(event)
        self.app.pause.assert_not_called()

    def test_space_on_canvas_runs_pause_shortcut(self):
        self.app.pause = Mock()
        event = SimpleNamespace(widget=object.__new__(tk.Canvas), state=0, keysym="space")
        self.app._key(event)
        self.app.pause.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
