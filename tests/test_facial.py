"""Facial zoom regressions with synthetic scores; no webcam or GUI required."""

from math import ceil, isfinite, prod
from types import SimpleNamespace
import unittest

from lousa.facial import (
    FacialState, FacialZoom, HOLD_SECONDS, SIGNALS, scores_from_result,
)


def face(**changes):
    values = dict.fromkeys(SIGNALS, 0.05)
    values.update(changes)
    return values


NEUTRAL = face()
LEFT = face(eyeBlinkLeft=0.9)
RIGHT = face(eyeBlinkRight=0.9)
BOTH = face(eyeBlinkLeft=0.9, eyeBlinkRight=0.9)
UP = face(browInnerUp=0.8)
DOWN = face(browDownLeft=0.8, browDownRight=0.8)


class FacialZoomTests(unittest.TestCase):
    def setUp(self):
        self.zoom = FacialZoom()

    def hold(self, values, start, duration, interval=0.1):
        steps = max(1, ceil(duration / interval))
        return [self.zoom.update(values, start + duration * i / steps)
                for i in range(steps + 1)]

    def activate(self):
        self.hold(NEUTRAL, 0.0, 0.2)
        states = self.hold(LEFT, 0.3, 2.0)
        self.assertTrue(states[-1].active)
        self.assertEqual(states[-1].mode, "zoom")
        return 2.3

    def ready_zoom(self):
        now = self.activate()
        states = self.hold(NEUTRAL, now + 0.1, 0.2)
        self.assertTrue(all(state.active and state.blocked for state in states))
        return now + 0.3

    def assert_idle(self, state):
        self.assertEqual(state.mode, "idle")
        self.assertFalse(state.active or state.blocked)
        self.assertEqual(state.progress, 0.0)
        self.assertEqual(state.zoom_factor, 1.0)

    def test_default_state_and_two_second_contract(self):
        self.assertEqual(HOLD_SECONDS, 2.0)
        self.assertEqual(len(SIGNALS), 7)
        self.assertEqual(len(set(SIGNALS)), 7)
        self.assert_idle(FacialState())
        self.assertEqual(FacialState().generation, 0)

    def test_activation_requires_neutral_face_before_left_wink(self):
        states = self.hold(LEFT, 0.0, 3.0)
        self.assertTrue(all(not state.blocked for state in states))
        self.hold(NEUTRAL, 3.1, 0.1)
        states = self.hold(LEFT, 3.3, 2.2)
        self.assertTrue(all(not state.active for state in states))
        self.hold(NEUTRAL, 5.6, 0.2)
        self.assertTrue(self.hold(LEFT, 5.9, 2.0)[-1].active)

    def test_left_wink_activates_at_exactly_two_continuous_seconds(self):
        self.hold(NEUTRAL, 0.0, 0.2)
        states = self.hold(LEFT, 0.3, 1.9)
        self.assertTrue(all(state.mode == "arming_zoom" for state in states))
        self.assertTrue(all(state.blocked and not state.active for state in states))
        self.assertEqual(states[0].progress, 0.0)
        self.assertAlmostEqual(states[10].progress, 0.5)
        before = self.zoom.update(LEFT, 2.299)
        self.assertEqual(before.mode, "arming_zoom")
        self.assertLess(before.progress, 1.0)
        done = self.zoom.update(LEFT, 2.3)
        self.assertEqual(done.mode, "zoom")
        self.assertTrue(done.active and done.blocked)

    def test_interrupted_activation_does_not_add_separate_wink_periods(self):
        self.hold(NEUTRAL, 0.0, 0.2)
        self.hold(LEFT, 0.3, 1.9)
        self.assert_idle(self.zoom.update(NEUTRAL, 2.3))
        # A brief reopening is not enough to rearm after an abandoned hold.
        self.assert_idle(self.zoom.update(LEFT, 2.4))
        self.hold(NEUTRAL, 2.5, 0.2)
        states = self.hold(LEFT, 2.8, 1.9)
        self.assertTrue(all(not state.active for state in states))
        self.assertTrue(self.zoom.update(LEFT, 4.8).active)

    def test_left_wink_hysteresis_tolerates_a_moderate_score_dip(self):
        self.hold(NEUTRAL, 0.0, 0.2)
        self.zoom.update(LEFT, 0.3)
        moderate = face(eyeBlinkLeft=0.5)
        states = self.hold(moderate, 0.4, 1.9)
        self.assertTrue(all(state.mode == "arming_zoom" for state in states[:-1]))
        self.assertTrue(states[-1].active)

    def test_score_below_release_threshold_breaks_left_wink_hold(self):
        self.hold(NEUTRAL, 0.0, 0.2)
        self.hold(LEFT, 0.3, 1.5)
        self.assert_idle(self.zoom.update(face(eyeBlinkLeft=0.39), 1.9))
        states = self.hold(face(eyeBlinkLeft=0.5), 2.0, 2.2)
        self.assertTrue(all(not state.active for state in states))

    def test_bilateral_blinks_and_right_winks_never_activate_zoom(self):
        for values in (BOTH, RIGHT, face(eyeBlinkLeft=0.9, eyeBlinkRight=0.3)):
            with self.subTest(values=values):
                self.zoom = FacialZoom()
                self.hold(NEUTRAL, 0.0, 0.2)
                states = self.hold(values, 0.3, 3.0)
                self.assertTrue(all(not state.active and not state.blocked
                                    and state.zoom_factor == 1.0 for state in states))

    def test_eyebrows_have_no_effect_outside_zoom_mode(self):
        for values in (UP, DOWN):
            with self.subTest(values=values):
                self.zoom = FacialZoom()
                states = self.hold(values, 0.0, 3.0)
                self.assertTrue(all(state.mode == "idle" and state.zoom_factor == 1.0
                                    for state in states))

    def test_entry_requires_neutral_release_before_adjustment_or_confirmation(self):
        self.activate()
        for values, start in ((UP, 2.4), (RIGHT, 3.5), (DOWN, 5.8)):
            states = self.hold(values, start, 1.0 if values != RIGHT else 2.2)
            self.assertTrue(all(state.mode == "zoom" and state.active
                                and state.zoom_factor == 1.0 for state in states))
        self.hold(NEUTRAL, 6.9, 0.2)
        states = self.hold(UP, 7.2, 0.5)
        self.assertGreater(states[-1].zoom_factor, 1.0)

    def test_brow_dwell_ignores_short_expression_and_then_changes_zoom(self):
        now = self.ready_zoom() + 0.1
        self.assertEqual(self.zoom.update(UP, now).zoom_factor, 1.0)
        self.assertEqual(self.zoom.update(UP, now + 0.14).zoom_factor, 1.0)
        self.assertEqual(self.zoom.update(NEUTRAL, now + 0.15).zoom_factor, 1.0)
        states = self.hold(UP, now + 0.25, 0.5)
        self.assertEqual(states[0].zoom_factor, 1.0)
        self.assertGreater(states[-1].zoom_factor, 1.0)
        self.zoom.update(NEUTRAL, now + 0.85)
        states = self.hold(DOWN, now + 0.95, 0.5)
        self.assertLess(states[-1].zoom_factor, 1.0)
        self.assertGreater(states[-1].zoom_factor, 0.0)

    def test_outer_brow_raise_also_increases_zoom(self):
        now = self.ready_zoom() + 0.1
        outer_up = face(browOuterUpLeft=0.8, browOuterUpRight=0.8)
        states = self.hold(outer_up, now, 0.5)
        self.assertGreater(states[-1].zoom_factor, 1.0)

    def test_brow_hysteresis_holds_direction_until_expression_is_released(self):
        now = self.ready_zoom() + 0.1
        self.hold(UP, now, 0.3)
        moderate = face(browInnerUp=0.3)
        self.assertGreater(self.zoom.update(moderate, now + 0.4).zoom_factor, 1.0)
        self.assertEqual(self.zoom.update(NEUTRAL, now + 0.5).zoom_factor, 1.0)
        states = self.hold(moderate, now + 0.6, 0.5)
        self.assertTrue(all(state.zoom_factor == 1.0 for state in states))

    def test_conflicting_brow_directions_do_not_adjust_zoom(self):
        now = self.ready_zoom() + 0.1
        conflicting = face(browInnerUp=0.8, browDownLeft=0.8, browDownRight=0.8)
        states = self.hold(conflicting, now, 1.0)
        self.assertTrue(all(state.active and state.zoom_factor == 1.0 for state in states))

    def test_closed_or_partly_closed_eyes_suspend_brow_adjustment(self):
        for changes in ({"eyeBlinkLeft": 0.9}, {"eyeBlinkLeft": 0.3},
                        {"eyeBlinkRight": 0.9},
                        {"eyeBlinkLeft": 0.9, "eyeBlinkRight": 0.9}):
            with self.subTest(eyes=changes):
                self.zoom = FacialZoom()
                now = self.ready_zoom() + 0.1
                values = dict(UP, **changes)
                states = self.hold(values, now, 0.5)
                self.assertTrue(all(state.active and state.zoom_factor == 1.0
                                    for state in states))
                # Opening the eyes starts a new brow dwell, without catching up.
                reopened = self.zoom.update(UP, now + 0.6)
                self.assertEqual(reopened.zoom_factor, 1.0)

    def test_zoom_change_is_independent_of_observation_rate(self):
        factors = []
        for interval in (0.05, 0.1, 0.2, 0.3):
            self.zoom = FacialZoom()
            now = self.ready_zoom() + 0.1
            states = self.hold(UP, now, 1.2, interval=interval)
            factors.append(prod(state.zoom_factor for state in states))
        self.assertGreater(factors[0], 1.0)
        for factor in factors[1:]:
            self.assertAlmostEqual(factor, factors[0], places=10)

    def test_right_wink_confirms_at_exactly_two_seconds_and_requires_rearming(self):
        now = self.ready_zoom() + 0.1
        states = self.hold(RIGHT, now, 1.9)
        self.assertTrue(all(state.mode == "confirming_zoom" and state.active
                            and state.blocked for state in states))
        before = self.zoom.update(RIGHT, now + 1.999)
        self.assertLess(before.progress, 1.0)
        self.assertEqual(before.mode, "confirming_zoom")
        done = self.zoom.update(RIGHT, now + 2.0)
        self.assert_idle(done)
        states = self.hold(LEFT, now + 2.1, 2.2)
        self.assertTrue(all(not state.active for state in states))
        self.hold(NEUTRAL, now + 4.4, 0.2)
        self.assertTrue(self.hold(LEFT, now + 4.7, 2.0)[-1].active)

    def test_confirmation_interruption_restarts_its_full_hold(self):
        now = self.ready_zoom() + 0.1
        self.hold(RIGHT, now, 1.9)
        interrupted = self.zoom.update(NEUTRAL, now + 2.0)
        self.assertEqual(interrupted.mode, "zoom")
        states = self.hold(RIGHT, now + 2.1, 1.9)
        self.assertTrue(all(state.active for state in states))
        self.assert_idle(self.zoom.update(RIGHT, now + 4.1))

    def test_confirmation_suppresses_brow_changes_for_entire_wink(self):
        now = self.ready_zoom() + 0.1
        confirming = dict(DOWN, eyeBlinkRight=0.9)
        states = self.hold(confirming, now, 2.0)
        self.assertTrue(all(state.zoom_factor == 1.0 for state in states))
        self.assertTrue(all(state.active for state in states[:-1]))
        self.assert_idle(states[-1])

    def test_bilateral_blink_cannot_confirm_and_breaks_a_pending_confirmation(self):
        now = self.ready_zoom() + 0.1
        self.hold(RIGHT, now, 1.5)
        bilateral = self.hold(BOTH, now + 1.6, 2.2)
        self.assertTrue(all(state.mode == "zoom" and state.active for state in bilateral))
        states = self.hold(RIGHT, now + 3.9, 1.9)
        self.assertTrue(all(state.active for state in states))
        self.assert_idle(self.zoom.update(RIGHT, now + 5.9))

    def test_missing_or_invalid_face_cancels_without_inheriting_a_hold(self):
        malformed = [None, [], {}, {key: 0.05 for key in SIGNALS[:-1]},
                     face(eyeBlinkLeft=float("nan")),
                     face(eyeBlinkRight=float("inf")),
                     face(browInnerUp=-0.01), face(browDownLeft=1.01),
                     face(browOuterUpRight="invalid"), face(browInnerUp=object())]
        for values in malformed:
            with self.subTest(values=values):
                self.zoom = FacialZoom()
                self.hold(NEUTRAL, 0.0, 0.2)
                self.hold(LEFT, 0.3, 1.9)
                self.assert_idle(self.zoom.update(values, 2.3))
                self.assert_idle(self.zoom.update(LEFT, 2.4))
                self.hold(NEUTRAL, 2.5, 0.2)
                self.assertTrue(self.hold(LEFT, 2.8, 2.0)[-1].active)

    def test_invalid_face_also_cancels_an_active_session(self):
        self.ready_zoom()
        self.assert_idle(self.zoom.update(None, 2.7))
        states = self.hold(RIGHT, 2.8, 2.1)
        self.assertTrue(all(not state.active for state in states))

    def test_valid_zero_and_one_scores_produce_finite_positive_factors(self):
        now = self.ready_zoom() + 0.1
        values = dict.fromkeys(SIGNALS, 0.0)
        values["browInnerUp"] = 1.0
        states = self.hold(values, now, 1.0)
        self.assertTrue(all(state.active and isfinite(state.zoom_factor)
                            and state.zoom_factor >= 1.0 for state in states))
        self.assertGreater(states[-1].zoom_factor, 1.0)

    def test_observation_gap_cancels_activation_instead_of_counting_missing_time(self):
        self.hold(NEUTRAL, 0.0, 0.2)
        self.hold(LEFT, 0.3, 1.9)
        self.assert_idle(self.zoom.update(LEFT, 2.551))
        states = self.hold(LEFT, 2.651, 2.2)
        self.assertTrue(all(not state.active for state in states))

    def test_gap_boundary_is_accepted_but_larger_gap_cancels_active_zoom(self):
        now = self.ready_zoom() + 0.1
        self.hold(UP, now, 0.2)
        boundary = self.zoom.update(UP, now + 0.55)
        self.assertTrue(boundary.active)
        self.assertGreater(boundary.zoom_factor, 1.0)
        self.assert_idle(self.zoom.update(UP, now + 0.901))

    def test_disabled_controls_cancel_and_require_a_new_neutral_observation(self):
        self.ready_zoom()
        self.assert_idle(self.zoom.update(LEFT, 2.7, enabled=False))
        states = self.hold(LEFT, 2.8, 2.2)
        self.assertTrue(all(not state.active for state in states))
        self.hold(NEUTRAL, 5.1, 0.2)
        self.assertTrue(self.hold(LEFT, 5.4, 2.0)[-1].active)

    def test_reset_cancels_pending_confirmation_and_requires_neutral_release(self):
        now = self.ready_zoom() + 0.1
        self.hold(RIGHT, now, 1.9)
        self.zoom.reset()
        self.assert_idle(self.zoom.update(RIGHT, now + 2.0))
        states = self.hold(LEFT, now + 2.1, 2.1)
        self.assertTrue(all(not state.active for state in states))

    def test_invalid_or_nonincreasing_clock_cancels_active_session(self):
        for timestamp in (None, "invalid", object(), float("nan"), float("inf"),
                          float("-inf"), 2.6, 2.5):
            with self.subTest(timestamp=timestamp):
                self.zoom = FacialZoom()
                self.ready_zoom()
                self.assert_idle(self.zoom.update(UP, timestamp))

    def test_generation_preserves_blocking_boundaries_when_frames_are_discarded(self):
        initial = self.zoom.update(NEUTRAL, 0.0)
        self.hold(NEUTRAL, 0.1, 0.2)
        states = self.hold(LEFT, 0.4, 2.0)
        armed_generation = states[0].generation
        self.assertGreater(armed_generation, initial.generation)
        self.assertTrue(all(state.generation == armed_generation for state in states))
        self.hold(NEUTRAL, 2.5, 0.2)
        final = self.hold(RIGHT, 2.8, 2.0)[-1]
        self.assert_idle(final)
        self.assertGreater(final.generation, armed_generation)
        # Receiving just the newest idle frame must still reveal the interruption.
        self.assertGreater(final.generation, initial.generation)
        idle = self.zoom.update(NEUTRAL, 4.9)
        self.assertEqual(idle.generation, final.generation)


class FacialResultTests(unittest.TestCase):
    def result(self, faces=1, shapes=1, values=None):
        categories = [SimpleNamespace(category_name=name, score=value)
                      for name, value in (NEUTRAL if values is None else values).items()]
        return SimpleNamespace(face_landmarks=[object()] * faces,
                               face_blendshapes=[categories] * shapes)

    def test_one_face_extracts_named_scores_without_left_right_swapping(self):
        extracted = scores_from_result(self.result(values=LEFT))
        self.assertEqual(extracted, LEFT)
        self.assertEqual(extracted["eyeBlinkLeft"], 0.9)
        self.assertEqual(extracted["eyeBlinkRight"], 0.05)

    def test_absent_multiple_or_malformed_results_are_rejected(self):
        for result in (None, SimpleNamespace(), self.result(faces=0),
                       self.result(faces=2), self.result(shapes=0),
                       self.result(shapes=2),
                       SimpleNamespace(face_landmarks=[object()],
                                       face_blendshapes=[[object()]])):
            with self.subTest(result=result):
                self.assertIsNone(scores_from_result(result))


if __name__ == "__main__":
    unittest.main()
