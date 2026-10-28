"""Face/hand camera integration with synthetic frames and no hardware access."""

import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from lousa.camera import CameraWorker, create_face_tracker, pinch_released
from lousa.facial import FacialState, SIGNALS


def scores(**changes):
    values = dict.fromkeys(SIGNALS, 0.05)
    values.update(changes)
    return values


def face_result(values=None):
    if values is None:
        return SimpleNamespace(face_landmarks=[], face_blendshapes=[])
    nose = SimpleNamespace(x=0.5, y=0.5)
    categories = [SimpleNamespace(category_name=name, score=value)
                  for name, value in values.items()]
    return SimpleNamespace(face_landmarks=[[nose, nose]], face_blendshapes=[categories])


def hand(released=False):
    values = [SimpleNamespace(x=0.5, y=0.5) for _ in range(21)]
    values[0] = SimpleNamespace(x=0.5, y=0.7)
    values[5] = SimpleNamespace(x=0.4, y=0.5)
    values[17] = SimpleNamespace(x=0.6, y=0.5)
    values[8] = SimpleNamespace(x=0.64 if released else 0.54, y=0.5)
    return values


class FaceTrackerCreationTests(unittest.TestCase):
    def setUp(self):
        self.model = Path("synthetic-face-model.task")
        self.payload = b"synthetic face model for checksum validation"
        self.options, self.tracker = object(), object()
        self.base_options = Mock(return_value=object())
        self.face_options = Mock(return_value=self.options)
        self.factory = Mock(return_value=self.tracker)
        mp = SimpleNamespace(tasks=SimpleNamespace(
            BaseOptions=self.base_options,
            vision=SimpleNamespace(
                FaceLandmarkerOptions=self.face_options,
                RunningMode=SimpleNamespace(VIDEO="video"),
                FaceLandmarker=SimpleNamespace(create_from_options=self.factory))))
        self.enterContext(patch.dict(sys.modules, {"mediapipe": mp}))

    def test_valid_checksum_builds_single_face_video_detector_with_blendshapes(self):
        digest = hashlib.sha256(self.payload).hexdigest()
        with (patch.object(Path, "is_file", return_value=True),
              patch.object(Path, "read_bytes", return_value=self.payload),
              patch("lousa.camera.FACE_MODEL_SHA256", digest)):
            self.assertIs(create_face_tracker(self.model), self.tracker)
        self.base_options.assert_called_once_with(model_asset_path=str(self.model))
        options = self.face_options.call_args.kwargs
        self.assertEqual(options["running_mode"], "video")
        self.assertEqual(options["num_faces"], 1)
        self.assertIs(options["output_face_blendshapes"], True)
        self.factory.assert_called_once_with(self.options)

    def test_missing_or_corrupt_model_never_reaches_detector_factory(self):
        with patch.object(Path, "is_file", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "facial ausente"):
                create_face_tracker(self.model)
        with (patch.object(Path, "is_file", return_value=True),
              patch.object(Path, "read_bytes", return_value=self.payload),
              patch("lousa.camera.FACE_MODEL_SHA256", "0" * 64)):
            with self.assertRaisesRegex(RuntimeError, "facial inválido"):
                create_face_tracker(self.model)
        self.face_options.assert_not_called()
        self.factory.assert_not_called()


class FaceCameraPipelineTests(unittest.TestCase):
    def setUp(self):
        self.worker = CameraWorker(0, Path("synthetic-hand-model.task"))
        self.raw = SimpleNamespace(size=640 * 480 * 3, shape=(480, 640, 3))
        self.mirrored = object()
        self.hand_rgb = SimpleNamespace(shape=(480, 640, 3))
        self.face_rgb = object()
        self.capture, self.hands, self.face = Mock(), Mock(), Mock()
        self.capture.read.return_value = (True, self.raw)
        self.hands.detect_for_video.return_value = SimpleNamespace(hand_landmarks=[])
        self.face.detect_for_video.return_value = face_result(scores())
        self.cv = SimpleNamespace(
            flip=Mock(return_value=self.mirrored),
            cvtColor=Mock(side_effect=self.convert),
            COLOR_BGR2RGB=1, circle=Mock())
        self.mp = SimpleNamespace(
            Image=Mock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs)),
            ImageFormat=SimpleNamespace(SRGB="srgb"))
        self.published = []

    def convert(self, source, code):
        self.assertEqual(code, self.cv.COLOR_BGR2RGB)
        if source is self.mirrored:
            return self.hand_rgb
        self.assertIs(source, self.raw)
        return self.face_rgb

    def run_worker(self, frames=1, times=None, creation_error=None):
        publish = self.worker.publish

        def publish_and_stop(event):
            publish(event)
            self.published.append(event)
            if event[0] == "error" or len(self.published) >= frames:
                self.worker.stop()

        face_factory = Mock(return_value=self.face, side_effect=creation_error)
        with (patch.dict(sys.modules, {"cv2": self.cv, "mediapipe": self.mp}),
              patch("lousa.camera.create_tracker", return_value=self.hands),
              patch("lousa.camera.create_face_tracker", face_factory),
              patch("lousa.camera.open_camera", return_value=(self.capture, self.raw)) as opening,
              patch("lousa.camera.time.monotonic", side_effect=[0.0] + list(
                  times if times is not None else [i / 10 for i in range(frames)])),
              patch("lousa.camera.time.monotonic_ns", return_value=0),
              patch.object(self.worker, "publish", side_effect=publish_and_stop)):
            self.worker.run()
        opening.assert_called_once_with(0)
        return face_factory

    def test_one_capture_feeds_original_rgb_to_face_and_mirrored_rgb_to_hands(self):
        factory = self.run_worker(frames=2)
        self.assertEqual([event[0] for event in self.published], ["frame", "frame"])
        factory.assert_called_once_with(Path("face_landmarker.task"))
        self.assertEqual(self.capture.read.call_count, 1)
        self.assertEqual(self.cv.flip.call_count, 2)
        for call in self.cv.flip.call_args_list:
            self.assertIs(call.args[0], self.raw)
            self.assertEqual(call.args[1], 1)
        for call in self.hands.detect_for_video.call_args_list:
            self.assertIs(call.args[0].data, self.hand_rgb)
        for call in self.face.detect_for_video.call_args_list:
            self.assertIs(call.args[0].data, self.face_rgb)
        hand_times = [call.args[1] for call in self.hands.detect_for_video.call_args_list]
        face_times = [call.args[1] for call in self.face.detect_for_video.call_args_list]
        self.assertEqual(hand_times, face_times)
        self.assertGreater(hand_times[1], hand_times[0])
        self.assertTrue(all(event[1] is self.hand_rgb and event[10].face_present
                            for event in self.published))
        self.capture.release.assert_called_once_with()
        self.hands.close.assert_called_once_with()
        self.face.close.assert_called_once_with()

    def test_missing_face_model_keeps_hand_frames_and_releases_resources(self):
        self.hands.detect_for_video.return_value = SimpleNamespace(hand_landmarks=[hand()])
        self.run_worker(frames=2, creation_error=RuntimeError("modelo não encontrado"))
        self.assertEqual([event[0] for event in self.published], ["frame", "frame"])
        self.assertTrue(all(len(event[2]) == 1 for event in self.published))
        self.assertTrue(all("indisponível" in event[10].status
                            and not event[10].face_present for event in self.published))
        self.assertEqual(self.hands.detect_for_video.call_count, 2)
        self.face.detect_for_video.assert_not_called()
        self.capture.release.assert_called_once_with()
        self.hands.close.assert_called_once_with()

    def test_absent_face_reports_actionable_status_instead_of_available(self):
        self.face.detect_for_video.return_value = face_result()
        self.run_worker(frames=2)
        for event in self.published:
            safety = event[10]
            self.assertFalse(safety.face_present)
            self.assertEqual(safety.facial.status, "no_face")
            self.assertIn("Rosto não detectado", safety.status)
            self.assertNotIn("disponível", safety.status)

    def test_paused_pipeline_keeps_detecting_face_without_rearming(self):
        self.worker.set_controls_enabled(False)
        self.run_worker(frames=3)
        for event in self.published:
            safety = event[10]
            self.assertTrue(safety.face_present)
            self.assertEqual(safety.facial.status, "paused")
            self.assertFalse(safety.facial.active or safety.facial.blocked)
            self.assertIn("pausado", safety.status)

    def test_face_inference_failure_is_closed_once_and_hand_pipeline_continues(self):
        self.hands.detect_for_video.return_value = SimpleNamespace(hand_landmarks=[hand()])
        self.face.detect_for_video.side_effect = RuntimeError("falha de inferência")
        # A broken detector's close must not prevent graceful degradation.
        self.face.close.side_effect = RuntimeError("falha ao fechar")
        self.run_worker(frames=3)
        self.assertEqual([event[0] for event in self.published], ["frame"] * 3)
        self.assertEqual(self.hands.detect_for_video.call_count, 3)
        self.face.detect_for_video.assert_called_once()
        self.face.close.assert_called_once_with()
        self.assertTrue(all("falha de inferência" in event[10].status
                            and not event[10].facial.blocked for event in self.published))
        self.capture.release.assert_called_once_with()
        self.hands.close.assert_called_once_with()

    def test_hand_failure_reports_error_and_closes_both_detectors_even_if_close_fails(self):
        self.hands.detect_for_video.side_effect = RuntimeError("falha de mãos")
        self.hands.close.side_effect = RuntimeError("erro de encerramento")
        self.run_worker()
        self.assertEqual(self.published, [("error", "falha de mãos")])
        self.capture.release.assert_called_once_with()
        self.hands.close.assert_called_once_with()
        self.face.close.assert_called_once_with()

    def test_real_worker_retains_zoom_boundaries_and_waits_for_visible_pinch_release(self):
        times = [i / 10 for i in range(56)]
        observations = []
        for timestamp in times:
            if timestamp <= 0.2 or 2.4 <= timestamp <= 2.6:
                values = scores()
            elif timestamp <= 2.3:
                values = scores(eyeBlinkLeft=0.9)
            elif timestamp <= 2.9:
                values = scores(browInnerUp=0.8)
            elif timestamp <= 5.0:
                values = scores(eyeBlinkRight=0.9)
            else:
                values = None
            observations.append(face_result(values))
        self.face.detect_for_video.side_effect = observations
        self.hands.detect_for_video.side_effect = [
            SimpleNamespace(hand_landmarks=[] if timestamp == 5.1
                            else [hand(released=timestamp == 5.3)])
            for timestamp in times]
        self.run_worker(frames=len(times), times=times)
        by_time = {event[9]: event for event in self.published}
        self.assertFalse(by_time[2.2][10].facial.active)
        self.assertTrue(by_time[2.3][10].facial.active)
        self.assertEqual(by_time[4.9][10].facial.mode, "confirming_zoom")
        self.assertFalse(by_time[5.0][10].facial.active)
        self.assertTrue(all(by_time[t][10].release_required for t in (5.0, 5.1, 5.2)))
        self.assertFalse(by_time[5.3][10].release_required)
        self.assertTrue(by_time[5.5][5])
        self.assertEqual(by_time[0.2][6], 1)
        self.assertEqual(by_time[5.5][6], 2)
        self.assertGreater(by_time[5.5][10].revision, by_time[0.2][10].revision)
        # All activation, adjustment and confirmation frames have been dropped.
        self.assertEqual(self.worker.events.qsize(), 2)
        retained = [self.worker.events.get_nowait(), self.worker.events.get_nowait()]
        self.assertEqual([event[9] for event in retained], [5.4, 5.5])
        self.assertEqual(retained[-1][6], 2)
        self.assertGreater(retained[-1][10].revision, 0)
        actions = []
        while not self.worker.actions.empty():
            actions.append(self.worker.actions.get_nowait())
        self.assertTrue(actions)
        self.assertTrue(all(action[2] == "zoom" and action[3][1] > 1.0
                            for action in actions))
        self.capture.release.assert_called_once_with()
        self.hands.close.assert_called_once_with()
        self.face.close.assert_called_once_with()


class CameraSafetyEpochTests(unittest.TestCase):
    def test_invalid_or_partial_hand_cannot_release_the_safety_latch(self):
        for malformed in (None, [], hand(released=True)[:18], [object()] * 21):
            with self.subTest(malformed=malformed):
                self.assertFalse(pinch_released(malformed))
        for value in (float("nan"), float("inf")):
            malformed = hand(released=True)
            malformed[4].x = value
            self.assertFalse(pinch_released(malformed))

    def test_epoch_changes_reject_inflight_face_state_and_preserve_release_requirement(self):
        worker = CameraWorker(0, Path("unused.task"))
        active = FacialState(mode="zoom", active=True, blocked=True, generation=1)
        begun = worker._update_safety(active, [hand()], 1.0, 0, "disponível", True)
        self.assertTrue(begun.release_required)
        self.assertFalse(pinch_released(hand()))
        self.assertTrue(pinch_released(hand(released=True)))
        worker.set_controls_enabled(False)
        disabled = worker.safety_context()
        self.assertTrue(disabled.release_required)
        self.assertFalse(disabled.facial.blocked)
        self.assertGreater(disabled.epoch, begun.epoch)
        stale = worker._update_safety(active, [hand(released=True)], 1.1, 0, "atrasado", True)
        self.assertIs(stale, disabled)
        worker.set_controls_enabled(True)
        worker.cancel_facial()
        current = worker.safety_context()
        self.assertGreater(current.epoch, disabled.epoch)
        self.assertGreater(current.revision, disabled.revision)
        self.assertTrue(current.release_required)
        absent = worker._update_safety(FacialState(), [], 1.2, current.epoch, "disponível")
        self.assertTrue(absent.release_required)
        ambiguous = worker._update_safety(FacialState(), [[object()] * 21], 1.3,
                                          current.epoch, "disponível")
        self.assertTrue(ambiguous.release_required)
        released = worker._update_safety(FacialState(), [hand(released=True)], 1.4,
                                         current.epoch, "disponível")
        self.assertFalse(released.release_required)
        self.assertEqual(released.epoch, current.epoch)


if __name__ == "__main__":
    unittest.main()
