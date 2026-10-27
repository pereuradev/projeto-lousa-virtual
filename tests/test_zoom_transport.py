"""Safety regressions across the lossy frame queue and durable action channel."""
from types import SimpleNamespace
import unittest

from PIL import ImageChops

import test_app
from lousa.camera import CameraSafety
from lousa.facial import FacialState


def hand(released=False):
    points = [SimpleNamespace(x=0.5, y=0.5) for _ in range(21)]
    points[5].x, points[17].x = 0.25, 0.75
    points[4].x = 0.1 if released else 0.5
    return points


class ZoomTransportTests(unittest.TestCase):
    def setUp(self):
        test_app.AppGestureTests.setUp(self)
        self.app.facial_state = FacialState()
        self.app.safety_revision = 0
        self.held = hand()

    def frame(self, **kwargs):
        test_app.AppGestureTests.frame(self, **kwargs)

    def action(self, *args, **kwargs):
        test_app.AppGestureTests.action(self, *args, **kwargs)

    def face(self, mode="zoom", generation=1, hands=None):
        blocked = mode != "idle"
        state = FacialState(mode=mode, active=mode in ("zoom", "confirming_zoom"),
                            blocked=blocked, generation=generation)
        epoch = self.app.worker.control_context()[1]
        return self.app.worker._update_safety(state, [self.held] if hands is None else hands,
                                             self.now, epoch, "disponível")

    def test_activation_stops_an_existing_stroke_without_a_retained_video_frame(self):
        self.frame()
        self.app._tick()
        self.assertEqual(self.app.source, "gesture")
        self.face("arming_zoom")
        self.app._tick()
        self.assertIsNone(self.app.source)
        self.assertFalse(self.app.gesture_ready)
        self.assertEqual(self.app.board.stroke_count, 1)

    def test_activation_has_priority_over_already_queued_color_and_clear(self):
        self.app.board.begin((20, 30), "black", 3)
        self.app.board.end()
        before = self.app.board.image.copy()
        self.action("color", 2)
        self.action("clear")
        self.face("arming_zoom")
        self.app._tick()
        self.assertEqual(self.app.color, "black")
        self.assertIsNone(ImageChops.difference(before, self.app.board.image).getbbox())

    def test_finished_session_and_release_invalidate_preceding_hand_actions(self):
        self.app.board.begin((20, 30), "black", 3)
        self.app.board.end()
        before = self.app.board.image.copy()
        # These actions predate the facial boundary, whose frames can all be
        # omitted before the UI consumes its durable action queue.
        epoch = self.app.worker.control_context()[1]
        self.app.worker.actions.put((epoch, self.now, "color", 2, 0))
        self.app.worker.actions.put((epoch, self.now, "clear", None, 0))
        self.face("arming_zoom")
        current = self.face("idle", generation=2, hands=[hand(released=True)])
        self.assertFalse(current.facial.blocked or current.release_required)
        self.app._tick()
        self.assertEqual(self.app.color, "black")
        self.assertEqual(self.app.board.stroke_count, 1)
        self.assertIsNone(ImageChops.difference(before, self.app.board.image).getbbox())
        # Newly observed hand actions in the new revision remain usable.
        self.app.worker.actions.put((epoch, self.now, "color", 1, current.revision))
        self.app._tick()
        self.assertEqual(self.app.color, test_app.COLORS[1][1])

    def test_current_zoom_action_changes_only_the_view(self):
        self.app.board.begin((20, 30), "black", 3)
        self.app.board.end()
        before = self.app.board.image.copy()
        history = len(self.app.board._undo)
        self.face()
        self.action("zoom", (1, 1.1))
        self.app._tick()
        self.assertAlmostEqual(self.app.viewport.zoom, 1.1)
        self.assertEqual(len(self.app.board._undo), history)
        self.assertIsNone(ImageChops.difference(before, self.app.board.image).getbbox())

    def test_obsolete_session_and_future_or_stale_zoom_actions_are_rejected(self):
        self.face(generation=4)
        self.app._viewport()
        self.action("zoom", (3, 2))
        self.action("zoom", (4, 2), captured_at=self.now - 0.501)
        self.action("zoom", (4, 2), captured_at=self.now + 0.01)
        self.app._tick()
        self.assertEqual(self.app.viewport.zoom, 1)

    def test_confirmation_cannot_apply_a_queued_adjustment_from_the_finished_session(self):
        self.face(generation=4)
        self.action("zoom", (4, 2))
        self.face("idle", generation=5)
        self.app._tick()
        self.assertEqual(self.app._viewport().zoom, 1)

    def test_cancel_epoch_rejects_an_in_flight_zoom_action(self):
        self.face()
        old_epoch = self.app.worker.control_context()[1]
        self.app.worker.cancel_facial()
        self.action("zoom", (1, 2), epoch=old_epoch)
        self.app._tick()
        self.assertEqual(self.app._viewport().zoom, 1)

    def test_complete_session_dropped_from_video_still_requires_a_visible_pinch_release(self):
        self.frame(point=(0.2, 0.5))
        self.app._tick()
        self.face("arming_zoom")
        self.face()
        self.face("idle", generation=2)
        self.frame(point=(0.8, 0.5), segment=2)
        self.app._tick()
        self.assertEqual(self.app.board.stroke_count, 1)
        self.assertFalse(self.app.gesture_ready)
        # Losing hands is not evidence of a physically released pinch.
        self.face("idle", generation=2, hands=[])
        self.frame(point=None, pinch=False, hand_count=0)
        self.app._tick()
        self.assertFalse(self.app.gesture_ready)
        # The camera's valid release can itself be omitted from the video queue.
        self.face("idle", generation=2, hands=[hand(released=True)])
        self.frame(point=(0.8, 0.5), pinch=True, segment=3)
        self.app._tick()
        self.assertTrue(self.app.gesture_ready)
        self.assertEqual(self.app.board.stroke_count, 2)
        self.assertEqual(self.app.board.image.getpixel((50, 30)), (255, 255, 255))

    def test_frame_from_before_a_facial_transition_is_not_drawn(self):
        old_safety = self.app.worker.safety_context()
        self.face("arming_zoom")
        self.face("idle", generation=2, hands=[hand(released=True)])
        epoch = self.app.worker.control_context()[1]
        self.app.worker.publish(("frame", object(), [self.held], 30, (0.5, 0.5), True,
                                 1, self.app.control_state, epoch, self.now, old_safety))
        self.app._tick()
        self.assertEqual(self.app.board.stroke_count, 0)

    def test_pause_dialog_and_mouse_disable_facial_adjustments(self):
        for disabled in ("paused", "dialog_open", "mouse"):
            with self.subTest(disabled=disabled):
                self.app.paused = self.app.dialog_open = False
                self.app.source = None
                self.app._sync_controls()
                self.face()
                self.action("zoom", (1, 2))
                if disabled == "mouse":
                    self.app.source = "mouse"
                else:
                    setattr(self.app, disabled, True)
                self.app._tick()
                self.assertFalse(self.app.facial_state.active)
                self.assertEqual(self.app._viewport().zoom, 1)

    def test_stalled_face_session_exits_without_resetting_zoom(self):
        self.app._viewport().set_zoom(2)
        self.face()
        self.now += 0.501
        self.app._tick()
        self.assertFalse(self.app.facial_state.active)
        self.assertEqual(self.app.viewport.zoom, 2)
        self.assertTrue(self.app.worker.safety_context().release_required)


if __name__ == "__main__":
    unittest.main()
