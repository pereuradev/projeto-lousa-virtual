"""Falhas de dispositivo verificadas sem abrir uma webcam real."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lousa.camera import CameraWorker, create_tracker, open_camera
from lousa.controls import ControlState


class CameraOpeningTests(unittest.TestCase):
    def test_absent_or_busy_camera_has_useful_error_and_releases_backends(self):
        captures = [Mock(), Mock()]
        for capture in captures:
            capture.isOpened.return_value = False
        cv = SimpleNamespace(CAP_DSHOW=1, CAP_MSMF=2, VideoCapture=Mock(side_effect=captures))
        with patch.dict(sys.modules, {"cv2": cv}):
            with self.assertRaisesRegex(RuntimeError, "câmera 7.*Feche Teams"):
                open_camera(7)
        for capture in captures:
            capture.release.assert_called_once_with()
        self.assertEqual(cv.VideoCapture.call_count, 2)

    def test_second_backend_recovers_when_first_cannot_open(self):
        first, second = Mock(), Mock()
        first.isOpened.return_value = False
        second.isOpened.return_value = True
        frame = SimpleNamespace(size=10)
        second.read.return_value = (True, frame)
        cv = SimpleNamespace(CAP_DSHOW=1, CAP_MSMF=2, CAP_PROP_FRAME_WIDTH=3,
                             CAP_PROP_FRAME_HEIGHT=4, CAP_PROP_FPS=5,
                             VideoCapture=Mock(side_effect=[first, second]))
        with patch.dict(sys.modules, {"cv2": cv}):
            capture, returned_frame = open_camera(0)
        self.assertIs(capture, second)
        self.assertIs(returned_frame, frame)
        first.release.assert_called_once_with()
        second.release.assert_not_called()

    def test_tracker_is_configured_to_detect_two_hands(self):
        options, tracker = object(), object()
        base_options = Mock(return_value=object())
        landmarker_options = Mock(return_value=options)
        create_from_options = Mock(return_value=tracker)
        mp = SimpleNamespace(tasks=SimpleNamespace(
            BaseOptions=base_options,
            vision=SimpleNamespace(
                HandLandmarkerOptions=landmarker_options,
                RunningMode=SimpleNamespace(VIDEO="video"),
                HandLandmarker=SimpleNamespace(create_from_options=create_from_options))))
        with (patch.dict(sys.modules, {"mediapipe": mp}),
              patch("lousa.camera.MODEL_SHA256", ""),
              patch.object(Path, "is_file", return_value=True)):
            result = create_tracker(Path("unused-test-model.task"))
        self.assertIs(result, tracker)
        self.assertEqual(landmarker_options.call_args.kwargs["num_hands"], 2)
        create_from_options.assert_called_once_with(options)


class CameraControlTransportTests(unittest.TestCase):
    def test_epoch_advances_only_when_control_enablement_changes(self):
        worker = CameraWorker(0, Path("unused-test-model.task"))
        self.assertEqual(worker.control_context(), (True, 0))
        self.assertEqual(worker.set_controls_enabled(True), 0)
        self.assertEqual(worker.set_controls_enabled(False), 1)
        self.assertEqual(worker.set_controls_enabled(False), 1)
        self.assertEqual(worker.control_context(), (False, 1))
        self.assertEqual(worker.set_controls_enabled(True), 2)
        self.assertEqual(worker.control_context(), (True, 2))
        self.assertFalse(worker.is_alive())

    def test_small_control_actions_survive_bounded_video_frame_replacement(self):
        worker = CameraWorker(0, Path("unused-test-model.task"))
        action = (0, 100.0, "color", 3)
        worker.actions.put(action)
        events = []
        for segment in range(5):
            event = ("frame", object(), [], 30.0, None, False, segment,
                     ControlState(), 0, 100.0)
            events.append(event)
            worker.publish(event)
        self.assertEqual(worker.events.qsize(), 2)
        self.assertEqual(worker.events.get_nowait(), events[-2])
        self.assertEqual(worker.events.get_nowait(), events[-1])
        self.assertEqual(worker.actions.get_nowait(), action)
        self.assertTrue(worker.actions.empty())
        self.assertFalse(worker.is_alive())

    def test_second_hand_restarts_segment_even_if_two_hand_frame_is_dropped(self):
        worker = CameraWorker(0, Path("unused-test-model.task"))
        frame = SimpleNamespace(size=640 * 480 * 3, shape=(480, 640, 3))
        capture, tracker = Mock(), Mock()
        capture.read.return_value = (True, frame)
        hand = [SimpleNamespace(x=0.5, y=0.5) for _ in range(21)]
        other_hand = [SimpleNamespace(x=0.7, y=0.5) for _ in range(21)]
        tracker.detect_for_video.side_effect = [
            SimpleNamespace(hand_landmarks=hands)
            for hands in ([hand], [hand, other_hand], [hand], [hand])]
        cv = SimpleNamespace(flip=Mock(return_value=frame),
                             cvtColor=Mock(return_value=frame),
                             COLOR_BGR2RGB=1, circle=Mock())
        mp = SimpleNamespace(Image=Mock(return_value=object()),
                             ImageFormat=SimpleNamespace(SRGB=1))
        gestures, controls = Mock(), Mock()
        gestures.update.side_effect = [((0.2, 0.5), True), ((0.8, 0.5), True),
                                       ((0.82, 0.5), True)]
        controls.update.side_effect = [ControlState(hand_count=1),
                                       ControlState(mode="two_hands", hand_count=2, blocked=True),
                                       ControlState(hand_count=1), ControlState(hand_count=1)]
        published, first_consumed = [], []
        publish = worker.publish

        def publish_and_stop(event):
            publish(event)
            published.append(event)
            if len(published) == 1:
                first_consumed.append(worker.events.get_nowait())
            if len(published) == 4:
                worker.stop()

        with (patch.dict(sys.modules, {"cv2": cv, "mediapipe": mp}),
              patch("lousa.camera.create_tracker", return_value=tracker),
              patch("lousa.camera.open_camera", return_value=(capture, frame)),
              patch("lousa.camera.GestureFilter", return_value=gestures),
              patch("lousa.camera.ControlGestures", return_value=controls),
              patch.object(worker, "publish", side_effect=publish_and_stop)):
            worker.run()

        self.assertEqual([event[0] for event in published], ["frame"] * 4)
        self.assertEqual([event[5] for event in published], [True, False, True, True])
        self.assertEqual([len(event[2]) for event in published], [1, 2, 1, 1])
        self.assertIsNone(published[1][4])
        self.assertEqual([event[6] for event in published], [1, 1, 2, 2])
        self.assertEqual(first_consumed[0][6], 1)
        # Only board B survives in the bounded queue; the UI need not receive
        # the two-hand frame to learn that the old stroke has ended.
        self.assertEqual(worker.events.qsize(), 2)
        retained = [worker.events.get_nowait(), worker.events.get_nowait()]
        self.assertEqual([event[6] for event in retained], [2, 2])
        self.assertEqual([event[4] for event in retained], [(0.8, 0.5), (0.82, 0.5)])
        self.assertEqual(gestures.update.call_count, 3)
        self.assertTrue(all(call.args == (hand,) for call in gestures.update.call_args_list))
        gestures.reset.assert_called_once_with()
        self.assertEqual([len(call.args[0]) for call in controls.update.call_args_list], [1, 2, 1, 1])
        capture.release.assert_called_once_with()
        tracker.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
