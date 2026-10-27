"""Captura e inferência em uma thread, sem gravar frames da webcam."""
from __future__ import annotations

import queue
import threading
import time
from math import hypot
from pathlib import Path

from .drawing import GestureFilter
from .controls import ControlGestures

MODEL_SHA256 = "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1"


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

    def set_controls_enabled(self, enabled: bool) -> int:
        with self._control_lock:
            if enabled != self._controls_enabled:
                self._controls_enabled = enabled
                self._control_epoch += 1
            return self._control_epoch

    def control_context(self):
        with self._control_lock:
            return self._controls_enabled, self._control_epoch

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
        capture = tracker = None
        try:
            import cv2
            import mediapipe as mp

            tracker = create_tracker(self.model)
            if self.stop_event.is_set():
                return
            capture, frame = open_camera(self.index)
            previous_timestamp = -1
            previous_frame_time = time.monotonic()
            gestures = GestureFilter()
            controls = ControlGestures()
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
                    previous_epoch = epoch
                control = controls.update(hands, point, pinching, now, enabled=enabled)
                drawing = (enabled and len(hands) == 1 and pinching and not control.blocked
                           and point is not None)
                if drawing and not was_drawing:
                    segment += 1
                was_drawing = drawing
                if control.select_color is not None:
                    self.actions.put((epoch, now, "color", control.select_color))
                if control.clear:
                    self.actions.put((epoch, now, "clear", None))
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
                              control, epoch, now))
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
                capture.release()
            if tracker is not None:
                tracker.close()


def diagnose(index: int, model: Path, seconds: float = 3) -> dict:
    """Testa frames reais e inferência; retorna apenas métricas, nunca imagens."""
    worker = CameraWorker(index, model)
    worker.start()
    frames = hands = two_hands = 0
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
            "closed": not worker.is_alive(), "error": error}
