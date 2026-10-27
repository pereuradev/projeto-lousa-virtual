"""Captura e inferência em uma thread, sem gravar frames da webcam."""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from math import hypot, isfinite
from pathlib import Path

from .drawing import GestureFilter
from .controls import ControlGestures
from .facial import FacialState, FacialZoom, scores_from_result

MODEL_SHA256 = "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1"
FACE_MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"


@dataclass(frozen=True)
class CameraSafety:
    facial: FacialState = FacialState()
    release_required: bool = False
    revision: int = 0
    epoch: int = 0
    captured_at: float = 0.0
    status: str = "Zoom facial iniciando"
    face_present: bool = False


def pinch_released(hand):
    """Only a visible, physically separated pinch can release the safety latch."""
    try:
        if len(hand) != 21:
            return False
        points = [(float(hand[index].x), float(hand[index].y)) for index in (4, 8, 5, 17)]
        if not all(isfinite(value) for point in points for value in point):
            return False
        palm = hypot(points[2][0] - points[3][0], points[2][1] - points[3][1])
        gap = hypot(points[0][0] - points[1][0], points[0][1] - points[1][1])
        return palm > 1e-6 and gap / palm >= GestureFilter.PINCH_RELEASE
    except (TypeError, AttributeError, IndexError, ValueError, OverflowError):
        return False


def open_camera(index: int):
    import cv2

    for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF):
        capture = cv2.VideoCapture(index, backend)
        if capture.isOpened():
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            capture.set(cv2.CAP_PROP_FPS, 30)
            for _ in range(8):
                ok, frame = capture.read()
                if ok and frame is not None and frame.size:
                    return capture, frame
                time.sleep(0.04)
        capture.release()
    raise RuntimeError(
        f"Não foi possível abrir a câmera {index}. Feche Teams, Zoom, navegador ou "
        "outro aplicativo que a esteja usando. Confira a conexão USB e a permissão "
        "de câmera para aplicativos da área de trabalho nas Configurações do Windows. "
        "Experimente outro número de câmera e clique em Conectar."
    )


def create_tracker(model: Path):
    import hashlib
    import mediapipe as mp

    if not model.is_file():
        raise RuntimeError("Modelo de mãos ausente. Execute Instalar ou reparar.cmd.")
    if MODEL_SHA256 and hashlib.sha256(model.read_bytes()).hexdigest() != MODEL_SHA256:
        raise RuntimeError("Modelo de mãos inválido. Execute Instalar ou reparar.cmd.")
    options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_hands=2,
        min_hand_detection_confidence=0.6,
        min_hand_presence_confidence=0.6,
        min_tracking_confidence=0.6,
    )
    return mp.tasks.vision.HandLandmarker.create_from_options(options)


def create_face_tracker(model: Path):
    import hashlib
    import mediapipe as mp

    if not model.is_file():
        raise RuntimeError("Modelo facial ausente; execute Instalar ou reparar.cmd.")
    if hashlib.sha256(model.read_bytes()).hexdigest() != FACE_MODEL_SHA256:
        raise RuntimeError("Modelo facial inválido; execute Instalar ou reparar.cmd.")
    options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_faces=1, output_face_blendshapes=True,
        min_face_detection_confidence=0.6, min_face_presence_confidence=0.6,
        min_tracking_confidence=0.6,
    )
    return mp.tasks.vision.FaceLandmarker.create_from_options(options)


class CameraWorker(threading.Thread):
    def __init__(self, index: int, model: Path):
        super().__init__(name="webcam-local", daemon=True)
        self.index = index
        self.model = model
        self.stop_event = threading.Event()
        self.events: queue.Queue = queue.Queue(maxsize=2)
        # Somente comandos pequenos; imagens continuam na fila limitada acima.
        self.actions: queue.SimpleQueue = queue.SimpleQueue()
        self._control_lock = threading.Lock()
        self._controls_enabled = True
        self._control_epoch = 0
        self._safety = CameraSafety()

    def set_controls_enabled(self, enabled: bool) -> int:
        with self._control_lock:
            if enabled != self._controls_enabled:
                self._controls_enabled = enabled
                self._control_epoch += 1
                old = self._safety
                self._safety = CameraSafety(release_required=old.release_required or old.facial.blocked,
                                            revision=old.revision + 1, epoch=self._control_epoch,
                                            status=old.status)
            return self._control_epoch

    def control_context(self):
        with self._control_lock:
            return self._controls_enabled, self._control_epoch

    def safety_context(self):
        with self._control_lock:
            return self._safety

    def cancel_facial(self):
        """Invalidate in-flight observations/actions, even if already enabled."""
        with self._control_lock:
            self._control_epoch += 1
            old = self._safety
            self._safety = CameraSafety(release_required=old.release_required or old.facial.blocked,
                                        revision=old.revision + 1, epoch=self._control_epoch,
                                        status=old.status)

    def _update_safety(self, face, hands, now, epoch, status, face_present=False):
        with self._control_lock:
            if epoch != self._control_epoch:
                return self._safety
            old = self._safety
            transition = old.facial.blocked != face.blocked
            release = old.release_required or face.blocked or transition
            if release and not face.blocked and len(hands) == 1 and pinch_released(hands[0]):
                release = False
            self._safety = CameraSafety(face, release, old.revision + int(transition),
                                        epoch, now, status, face_present)
            return self._safety

    def publish(self, event):
        try:
            self.events.put_nowait(event)
        except queue.Full:
            try:
                self.events.get_nowait()
            except queue.Empty:
                pass
            self.events.put_nowait(event)

    def stop(self):
        self.stop_event.set()

    def run(self):
        capture = tracker = face_tracker = None
        try:
            import cv2
            import mediapipe as mp

            tracker = create_tracker(self.model)
            face_status = "Zoom facial disponível"
            try:
                face_tracker = create_face_tracker(self.model.with_name("face_landmarker.task"))
            except Exception as exc:
                face_status = f"Zoom facial indisponível: {exc}"
            if self.stop_event.is_set():
                return
            capture, frame = open_camera(self.index)
            previous_timestamp = -1
            previous_frame_time = time.monotonic()
            gestures = GestureFilter()
            controls = ControlGestures()
            facial = FacialZoom()
            previous_face_center = None
            previous_epoch = -1
            segment = 0
            was_drawing = False
            previous_wrist = None
            previous_label = None
            while not self.stop_event.is_set():
                mirrored = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(mirrored, cv2.COLOR_BGR2RGB)
                timestamp = max(previous_timestamp + 1, time.monotonic_ns() // 1_000_000)
                previous_timestamp = timestamp
                result = tracker.detect_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp
                )
                hands = result.hand_landmarks
                if len(hands) == 1:
                    hand = hands[0]
                    wrist = (hand[0].x, hand[0].y)
                    categories = getattr(result, "handedness", None)
                    label = categories[0][0].category_name if categories and categories[0] else None
                    switched = previous_wrist is not None and (
                        hypot(wrist[0] - previous_wrist[0], wrist[1] - previous_wrist[1]) > 0.28
                        or (label is not None and previous_label is not None and label != previous_label)
                    )
                    if switched:
                        gestures.reset()
                        controls.reset()
                        was_drawing = False
                    previous_wrist, previous_label = wrist, label
                    point, pinching = gestures.update(hand)
                else:
                    gestures.reset()
                    previous_wrist = previous_label = None
                    point, pinching = None, False
                now = time.monotonic()
                enabled, epoch = self.control_context()
                if epoch != previous_epoch:
                    controls.reset()
                    facial.reset()
                    previous_epoch = epoch
                face_scores = None
                if face_tracker is not None:
                    try:
                        # Face names are anatomical: mirroring would reverse
                        # the person's left/right, unlike the hand preview.
                        face_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        face_result = face_tracker.detect_for_video(
                            mp.Image(image_format=mp.ImageFormat.SRGB, data=face_rgb), timestamp)
                        face_scores = scores_from_result(face_result)
                        if face_scores is not None:
                            nose = face_result.face_landmarks[0][1]
                            center = (float(nose.x), float(nose.y))
                            if not all(isfinite(value) for value in center):
                                raise ValueError("Rosto com coordenadas inválidas")
                            if previous_face_center is not None and hypot(
                                    center[0] - previous_face_center[0], center[1] - previous_face_center[1]) > 0.20:
                                facial.reset()
                            previous_face_center = center
                        else:
                            previous_face_center = None
                    except Exception as exc:
                        face_scores = None
                        failed_tracker, face_tracker = face_tracker, None
                        try:
                            failed_tracker.close()
                        except Exception:
                            pass
                        face_status = f"Zoom facial indisponível: {exc}"
                        previous_face_center = None
                face = facial.update(face_scores, now, enabled=enabled)
                safety = self._update_safety(face, hands, now, epoch, face_status,
                                             face_present=face_scores is not None)
                face_blocks = safety.facial.blocked or safety.release_required
                if face_blocks:
                    controls.reset()
                control = controls.update(hands, point, pinching, now, enabled=enabled and not face_blocks)
                drawing = (enabled and not face_blocks and len(hands) == 1 and pinching and not control.blocked
                           and point is not None)
                if drawing and not was_drawing:
                    segment += 1
                was_drawing = drawing
                if control.select_color is not None:
                    self.actions.put((epoch, now, "color", control.select_color, safety.revision))
                if control.clear:
                    self.actions.put((epoch, now, "clear", None, safety.revision))
                if face.zoom_factor != 1.0 and safety.epoch == epoch and safety.facial.active:
                    self.actions.put((epoch, now, "zoom", (face.generation, face.zoom_factor)))
                fps = 1 / max(now - previous_frame_time, 0.001)
                previous_frame_time = now
                if hands:
                    h, w = rgb.shape[:2]
                    for tracked_hand in hands:
                        for i in (4, 8):
                            p = tracked_hand[i]
                            cv2.circle(rgb, (int(p.x * w), int(p.y * h)), 6, (34, 211, 153), 2)
                # O segmento preserva solturas mesmo se frames antigos forem descartados.
                self.publish(("frame", rgb, hands, fps, point, pinching, segment,
                              control, epoch, now, safety))
                for _ in range(5):
                    if self.stop_event.is_set():
                        return
                    ok, frame = capture.read()
                    if ok and frame is not None and frame.size:
                        break
                    time.sleep(0.08)
                else:
                    raise RuntimeError("A câmera parou de enviar imagens. Confira o cabo e reconecte.")
        except Exception as exc:
            if not self.stop_event.is_set():
                self.publish(("error", str(exc)))
        finally:
            if capture is not None:
                try:
                    capture.release()
                except Exception:
                    pass
            for detector in (tracker, face_tracker):
                if detector is not None:
                    try:
                        detector.close()
                    except Exception:
                        pass


def diagnose(index: int, model: Path, seconds: float = 3) -> dict:
    """Testa frames reais e inferência; retorna apenas métricas, nunca imagens."""
    worker = CameraWorker(index, model)
    worker.start()
    frames = hands = two_hands = faces = 0
    face_available = None
    started = time.monotonic()
    error = None
    deadline = started + max(seconds, 1) + 15
    first_frame = None
    try:
        while time.monotonic() < deadline:
            try:
                event = worker.events.get(timeout=0.5)
            except queue.Empty:
                if not worker.is_alive():
                    break
                continue
            if event[0] == "error":
                error = event[1]
                break
            if event[0] == "frame":
                frames += 1
                hands += int(bool(event[2]))
                two_hands += int(len(event[2]) == 2)
                if len(event) > 10:
                    faces += int(event[10].face_present)
                    face_available = "indisponível" not in event[10].status
                first_frame = first_frame or time.monotonic()
                if time.monotonic() - first_frame >= seconds:
                    break
    finally:
        worker.stop()
        worker.join(timeout=5)
    if not frames and error is None:
        error = "A câmera não respondeu dentro do tempo limite."
    return {"camera": index, "frames": frames, "frames_with_hand": hands,
            "frames_with_two_hands": two_hands,
            "frames_with_face": faces, "face_model_available": face_available,
            "closed": not worker.is_alive(), "error": error}
