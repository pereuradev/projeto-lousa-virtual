"""Thumb-armed colors and two-hand control regressions; no camera or GUI."""
from math import cos, sin
from types import SimpleNamespace
import unittest

from lousa.controls import (
    COLOR_ARM_SECONDS, COLOR_DWELL_SECONDS, CLEAR_HOLD_SECONDS,
    ControlGestures, ControlState, count_fingers, thumb_only,
)


def hand(count=5, mirror=1, angle=0, scale=1, offset=(0.5, 0.65), subset=None):
    points = [(0., 0., 0.)] * 21
    points[0] = (0., .11, 0.)
    thumb_up = count == 5 if subset is None else 0 in subset
    points[1:5] = ([(-.065,.065,0),(-.11,.025,0),(-.15,-.005,0),(-.19,-.025,0)]
                   if thumb_up else [(-.065,.065,0),(-.10,.025,0),(-.06,.005,0),(-.015,.02,0)])
    for finger, (base,x,y) in enumerate(((5,-.06,-.015),(9,-.015,-.03),(13,.035,-.02),(17,.08,.005)),1):
        up = finger <= min(count,4) if subset is None else finger in subset
        points[base:base+4] = ([(x,y,0),(x,y-.065,0),(x+.002,y-.108,0),(x+.003,y-.14,0)]
                              if up else [(x,y,0),(x,y-.047,0),(x,y-.032,-.033),(x,y+.005,-.025)])
    result=[]
    for x,y,z in points:
        x *= mirror
        x,y = x*cos(angle)-y*sin(angle),x*sin(angle)+y*cos(angle)
        result.append(SimpleNamespace(x=offset[0]+scale*x,y=offset[1]+scale*y,z=scale*z))
    return result


def vectors(pose):
    return [(point.x, point.y, point.z) for point in pose]


class CountControlTests(unittest.TestCase):
    def setUp(self):
        self.controls=ControlGestures()

    def hold(self,hands,start=0,duration=5,pinching=False,enabled=True,point=(.5,.5)):
        steps=max(1,round(duration/.1))
        return [self.controls.update(hands,point,pinching,start+duration*i/steps,enabled=enabled)
                for i in range(steps+1)]

    def arm_color(self,start=0,thumb=None):
        states=self.hold([thumb or hand(subset={0})],start=start,duration=1)
        self.assertEqual(states[-1].mode,'color_ready')
        self.assertTrue(states[-1].color_mode)
        released=self.controls.update([hand(0)],None,False,start+1.1)
        self.assertEqual(released.mode,'color_ready')
        self.assertTrue(released.color_mode)
        return start+1.1

    def test_exact_durations_and_default_drawing_mode(self):
        self.assertEqual(COLOR_ARM_SECONDS,1.)
        self.assertEqual(COLOR_DWELL_SECONDS,5.)
        self.assertEqual(CLEAR_HOLD_SECONDS,2.)
        self.assertEqual(ControlState().hand_count,0)
        self.assertFalse(ControlState().color_mode)
        self.assertFalse(ControlState().blocked)

    def test_normal_counts_never_arm_colors_or_block_drawing(self):
        for count in range(1,6):
            with self.subTest(count=count):
                self.controls=ControlGestures()
                states=self.hold([hand(count)],duration=6)
                self.assertTrue(all(s.mode=='idle' and not s.blocked and not s.color_mode
                                    and s.select_color is None and not s.clear for s in states))
                self.assertTrue(all(s.finger_count==count and s.hand_count==1 for s in states))

    def test_single_open_hand_never_selects_or_clears_without_arming(self):
        states=self.hold([hand(5)],duration=15)
        self.assertTrue(all(s.select_color is None and not s.clear and not s.blocked for s in states))

    def test_thumb_arms_at_exactly_one_continuous_second(self):
        states=self.hold([hand(subset={0})],duration=.9)
        self.assertTrue(all(s.mode=='arming_color' and s.blocked and not s.color_mode for s in states))
        self.assertAlmostEqual(states[5].progress,.5)
        before=self.controls.update([hand(subset={0})],None,False,.999)
        self.assertEqual(before.mode,'arming_color')
        self.assertLess(before.progress,1)
        ready=self.controls.update([hand(subset={0})],None,False,1.)
        self.assertEqual(ready.mode,'color_ready')
        self.assertTrue(ready.color_mode and ready.blocked)
        self.assertEqual(ready.finger_count,1)
        self.assertIsNone(ready.select_color)

    def test_changed_pose_restarts_thumb_activation(self):
        self.hold([hand(subset={0})],duration=.9)
        self.assertEqual(self.controls.update([hand(1)],None,False,1.).mode,'idle')
        states=self.hold([hand(subset={0})],start=1.1,duration=.9)
        self.assertEqual(states[0].progress,0)
        self.assertTrue(all(s.mode=='arming_color' for s in states))
        self.assertTrue(self.controls.update([hand(subset={0})],None,False,2.1).color_mode)

    def test_thumb_held_after_activation_never_counts_as_black(self):
        states=self.hold([hand(subset={0})],duration=15)
        self.assertTrue(all(s.select_color is None for s in states))
        self.assertTrue(all(s.mode=='color_ready' and s.color_mode and s.blocked
                            and s.progress==0 for s in states[10:]))
        states=self.hold([hand(1)],start=15.1,duration=5)
        self.assertTrue(all(s.select_color is None for s in states[:-1]))
        self.assertEqual(states[-1].select_color,0)

    def test_all_five_counts_map_exactly_after_arming_and_five_seconds(self):
        for count in range(1,6):
            with self.subTest(count=count):
                self.controls=ControlGestures()
                start=self.arm_color()+.1
                states=self.hold([hand(count)],start=start)
                self.assertTrue(all(s.select_color is None and s.color_mode and s.blocked
                                    for s in states[:-1]))
                done=states[-1]
                self.assertEqual(done.select_color,count-1)
                self.assertEqual(done.finger_count,count)
                self.assertEqual(done.color_index,count-1)
                self.assertEqual(done.mode,'color_done')
                self.assertEqual(done.progress,1)
                self.assertTrue(done.blocked)
                self.assertFalse(done.color_mode)
                self.assertTrue(all(not s.clear for s in states))
                self.assertAlmostEqual(states[25].progress,.5)
                resumed=self.controls.update([hand(count)],None,False,start+5.1)
                self.assertEqual(resumed.mode,'idle')
                self.assertFalse(resumed.blocked or resumed.color_mode)
                self.assertIsNone(resumed.select_color)

    def test_color_event_is_one_shot_and_returns_to_drawing(self):
        start=self.arm_color()+.1
        states=self.hold([hand(5)],start=start,duration=15)
        self.assertEqual([s.select_color for s in states if s.select_color is not None],[4])
        self.assertTrue(all(not s.clear for s in states))
        self.assertTrue(all(s.mode=='idle' and not s.blocked for s in states[51:]))

    def test_thumb_selected_black_requires_release_before_rearming(self):
        start=self.arm_color()+.1
        thumb=hand(subset={0})
        states=self.hold([thumb],start=start,duration=12)
        self.assertEqual([s.select_color for s in states if s.select_color is not None],[0])
        self.assertTrue(all(s.mode=='idle' and not s.blocked and not s.color_mode for s in states[51:]))
        self.controls.update([hand(0)],None,False,start+12.1)
        self.assertTrue(self.hold([thumb],start=start+12.2,duration=1)[-1].color_mode)

    def test_count_change_restarts_five_seconds(self):
        start=self.arm_color()+.1
        self.hold([hand(1)],start=start,duration=4.9)
        changed=self.controls.update([hand(2)],None,False,start+5.)
        self.assertEqual(changed.progress,0)
        self.assertTrue(changed.color_mode)
        states=self.hold([hand(2)],start=start+5,duration=5)
        self.assertTrue(all(s.select_color is None for s in states[:-1]))
        self.assertEqual(states[-1].select_color,1)

    @staticmethod
    def ambiguous_hand():
        pose=hand(5)
        pose[6]=pose[5]
        return pose

    def test_fist_or_ambiguous_count_restarts_timer_but_keeps_color_mode(self):
        for pose in (hand(0),self.ambiguous_hand()):
            with self.subTest(count=count_fingers(vectors(pose))[0]):
                self.controls=ControlGestures()
                start=self.arm_color()+.1
                self.hold([hand(3)],start=start,duration=4.9)
                waiting=self.controls.update([pose],None,False,start+5)
                self.assertEqual(waiting.mode,'color_ready')
                self.assertTrue(waiting.color_mode and waiting.blocked)
                states=self.hold([hand(3)],start=start+5.1,duration=5)
                self.assertTrue(all(s.select_color is None for s in states[:-1]))
                self.assertEqual(states[-1].select_color,2)

    def test_lost_or_invalid_hand_cancels_color_mode_until_rearmed(self):
        for missing in ([],[[]]):
            with self.subTest(missing=missing):
                self.controls=ControlGestures()
                start=self.arm_color()+.1
                self.hold([hand(3)],start=start,duration=4.9)
                self.controls.update(missing,None,False,start+5.)
                states=self.hold([hand(3)],start=start+5.1,duration=6)
                self.assertTrue(all(s.mode=='idle' and not s.color_mode and not s.blocked
                                    and s.select_color is None for s in states))
                rearmed=self.arm_color(start=start+11.2)+.1
                self.assertEqual(self.hold([hand(3)],start=rearmed)[-1].select_color,2)

    def test_observation_gap_cancels_color_mode_instead_of_resuming_count(self):
        start=self.arm_color()+.1
        self.hold([hand(4)],start=start,duration=4.9)
        states=self.hold([hand(4)],start=start+5.5,duration=6)
        self.assertTrue(all(s.mode=='idle' and not s.blocked and s.select_color is None for s in states))

    def test_gap_and_hand_loss_cancel_thumb_arming_progress(self):
        for lost in (False,True):
            with self.subTest(lost=lost):
                self.controls=ControlGestures()
                self.hold([hand(subset={0})],duration=.9)
                if lost:
                    self.controls.update([],None,False,1.)
                restart=1.1 if lost else 1.3
                states=self.hold([hand(subset={0})],start=restart,duration=.9)
                self.assertEqual(states[0].progress,0)
                self.assertTrue(all(not s.color_mode for s in states))

    def test_active_thumb_latch_survives_tracking_loss_and_reset(self):
        thumb=hand(subset={0})
        self.hold([thumb],duration=1)
        self.controls.reset()
        self.controls.update([],None,False,1.1)
        states=self.hold([thumb],start=1.2,duration=6)
        self.assertTrue(all(s.mode=='idle' and not s.color_mode and not s.blocked for s in states))
        self.controls.update([hand(0)],None,False,7.3)
        self.assertTrue(self.hold([thumb],start=7.4,duration=1)[-1].color_mode)

    def test_pinching_cancels_color_and_immediately_allows_drawing(self):
        start=self.arm_color()+.1
        self.hold([hand(2)],start=start,duration=4.9)
        states=self.hold([hand(2)],start=start+5,duration=6,pinching=True)
        self.assertTrue(all(s.mode=='idle' and not s.blocked and not s.color_mode
                            and s.select_color is None and not s.clear for s in states))
        self.assertEqual(self.controls.update([hand(2)],None,False,start+11.1).mode,'idle')

    def test_pinching_prevents_thumb_activation(self):
        states=self.hold([hand(subset={0})],duration=6,pinching=True)
        self.assertTrue(all(s.mode=='idle' and not s.blocked and not s.color_mode for s in states))

    def test_raw_physical_pinch_cancels_before_debounce_and_never_blocks(self):
        pose=hand(1)
        pose[4]=SimpleNamespace(x=pose[8].x,y=pose[8].y,z=pose[8].z)
        for armed in (False,True):
            with self.subTest(armed=armed):
                self.controls=ControlGestures()
                start=self.arm_color()+.1 if armed else 0
                states=self.hold([pose],start=start,duration=6)
                self.assertTrue(all(s.mode=='idle' and not s.blocked and not s.color_mode
                                    and s.select_color is None for s in states))

    def test_two_hands_cancel_color_without_resuming_old_time(self):
        start=self.arm_color()+.1
        self.hold([hand(1)],start=start,duration=4.9)
        self.controls.update([hand(1),hand(1)],None,False,start+5.)
        states=self.hold([hand(1)],start=start+5.1,duration=6)
        self.assertTrue(all(s.mode=='idle' and not s.color_mode and not s.blocked
                            and s.select_color is None for s in states))

    def test_two_open_hands_clear_only_once_never_select_color(self):
        states=self.hold([hand(),hand(mirror=-1)],duration=10)
        self.assertTrue(all(not s.clear for s in states[:20]))
        self.assertTrue(states[20].clear)
        self.assertEqual(sum(s.clear for s in states),1)
        self.assertTrue(all(s.select_color is None and s.blocked and not s.color_mode for s in states))

    def test_two_open_hands_have_priority_over_pending_color_selection(self):
        start=self.arm_color()+.1
        self.hold([hand(5)],start=start,duration=4.9)
        states=self.hold([hand(),hand(mirror=-1)],start=start+5,duration=2)
        self.assertEqual(states[0].mode,'clear')
        self.assertEqual(states[0].progress,0)
        self.assertTrue(states[-1].clear)
        self.assertTrue(all(s.select_color is None and not s.color_mode for s in states))

    def test_two_other_hands_are_not_added_or_used_for_drawing(self):
        for a,b in ((1,1),(2,3),(4,1),(5,4),(0,0)):
            with self.subTest(a=a,b=b):
                self.controls=ControlGestures()
                states=self.hold([hand(a),hand(b)],duration=6)
                self.assertTrue(all(s.mode=='two_hands' and s.hand_count==2 and s.blocked
                                    and not s.clear and s.select_color is None for s in states))

    def test_clear_cancels_if_either_hand_closes(self):
        self.hold([hand(),hand()],duration=1.9)
        state=self.controls.update([hand(),hand(4)],None,False,2.)
        self.assertEqual(state.mode,'two_hands')
        self.assertFalse(state.clear)
        self.assertFalse(self.hold([hand(),hand()],start=2.1,duration=1.9)[-1].clear)
        self.assertTrue(self.controls.update([hand(),hand()],None,False,4.1).clear)

    def test_clear_cancels_if_either_hand_is_lost(self):
        self.hold([hand(),hand()],duration=1.9)
        state=self.controls.update([hand()],None,False,2.)
        self.assertEqual(state.mode,'idle')
        self.assertFalse(state.blocked or state.clear)
        self.assertEqual(self.controls.update([hand(),hand()],None,False,2.1).progress,0)

    def test_clear_latch_survives_tracking_loss_and_reset(self):
        self.assertTrue(self.hold([hand(),hand()],duration=2)[-1].clear)
        self.controls.reset()
        self.controls.update([],None,False,2.1)
        states=self.hold([hand(),hand()],start=2.2,duration=10)
        self.assertTrue(all(not s.clear for s in states))

    def test_release_and_cooldown_required_for_another_clear(self):
        self.assertTrue(self.hold([hand(),hand()],duration=2)[-1].clear)
        self.controls.update([hand(),hand(4)],None,False,2.1)
        states=self.hold([hand(),hand()],start=2.2,duration=2.8)
        self.assertTrue(all(not s.clear for s in states))
        self.assertTrue(self.hold([hand(),hand()],start=5,duration=2)[-1].clear)

    def test_disabled_controls_and_reset_cancel_color_mode_and_timers(self):
        for reset in (False,True):
            with self.subTest(reset=reset):
                self.controls=ControlGestures()
                start=self.arm_color()+.1
                self.hold([hand(3)],start=start,duration=4.9)
                if reset:
                    self.controls.reset()
                else:
                    self.controls.update([hand(3)],None,False,start+5,enabled=False)
                states=self.hold([hand(3)],start=start+5.1,duration=6)
                self.assertTrue(all(s.mode=='idle' and not s.color_mode and not s.blocked
                                    and s.select_color is None for s in states))
        self.controls=ControlGestures()
        self.hold([hand(),hand()],duration=1.9)
        self.controls.update([hand(),hand()],None,False,2,enabled=False)
        self.assertEqual(self.controls.update([hand(),hand()],None,False,2.1).progress,0)

    def test_geometry_is_mirror_rotation_and_scale_invariant(self):
        for subset in ({0},{1},{2},{4},{0,2},{1,3},{0,2,4},{0,1,2,3,4}):
            for mirror in (-1,1):
                for angle in (-1.1,0,.8):
                    for scale in (.6,1.5):
                        with self.subTest(subset=subset,mirror=mirror,angle=angle,scale=scale):
                            pose=hand(subset=subset,mirror=mirror,angle=angle,scale=scale)
                            self.assertEqual(count_fingers(vectors(pose))[0],len(subset))
                            self.assertEqual(thumb_only(vectors(pose)),subset=={0})
                            state=ControlGestures().update([pose],None,False,0)
                            self.assertEqual(state.finger_count,len(subset))
                            self.assertEqual(state.mode,'arming_color' if subset=={0} else 'idle')

    def test_mirrored_rotated_thumb_arms_and_rotated_counts_select(self):
        for mirror in (-1,1):
            for count in range(1,6):
                with self.subTest(mirror=mirror,count=count):
                    self.controls=ControlGestures()
                    start=self.arm_color(thumb=hand(subset={0},mirror=mirror,angle=.8,scale=.6))+.1
                    done=self.hold([hand(count,mirror=mirror,angle=-1.1,scale=1.5)],start=start)[-1]
                    self.assertEqual(done.select_color,count-1)

    def test_other_single_finger_subsets_never_arm_colors(self):
        for subset in ({1},{2},{3},{4}):
            with self.subTest(subset=subset):
                self.controls=ControlGestures()
                states=self.hold([hand(subset=subset)],duration=6)
                self.assertTrue(all(s.mode=='idle' and not s.blocked and not s.color_mode for s in states))

    def test_location_is_irrelevant_to_selection(self):
        for point in ((0,0),(1,1),(.5,.5),None):
            with self.subTest(point=point):
                self.controls=ControlGestures()
                start=self.arm_color()+.1
                state=self.hold([hand(2)],start=start,point=point)[-1]
                self.assertEqual(state.select_color,1)

    def test_empty_malformed_and_nonfinite_observations_are_safe(self):
        for hands in (None,[],[[]],[[SimpleNamespace(x=float('nan'),y=0) for _ in range(21)]]):
            state=self.controls.update(hands,None,False,0)
            self.assertIsNone(state.select_color)
            self.assertFalse(state.clear or state.color_mode or state.blocked)
        self.assertEqual(self.controls.update([hand()],None,False,float('nan')),ControlState())


if __name__=='__main__':
    unittest.main()
