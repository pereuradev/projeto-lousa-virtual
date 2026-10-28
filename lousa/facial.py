"""Observation-timed facial zoom controls; independent from MediaPipe and Tk.

Left and right always refer to the person. Feed unmirrored face blendshapes.
No frames, face descriptors or identities are retained.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, log
from collections.abc import Mapping

HOLD_SECONDS = 2.0
MAX_OBSERVATION_GAP = 0.35
NEUTRAL_SECONDS = 0.20
BROW_DWELL_SECONDS = 0.15
ZOOM_RATE = log(1.35)  # At most 35% per second, independent of frame rate.
SIGNALS = ("eyeBlinkLeft", "eyeBlinkRight", "browInnerUp", "browOuterUpLeft",
           "browOuterUpRight", "browDownLeft", "browDownRight")


@dataclass(frozen=True)
class FacialState:
    mode: str = "idle"
    progress: float = 0.0
    active: bool = False
    blocked: bool = False
    zoom_factor: float = 1.0
    generation: int = 0
    status: str = "preparing"


def facial_status_message(state, face_present=True):
    """Short, actionable camera feedback, fitting the reserved three lines."""
    if state.status == "paused":
        return "Zoom facial pausado.\nRetome os gestos para usar."
    if not face_present or state.status == "no_face":
        return "Rosto não detectado.\nOlhe de frente para a câmera."
    messages = {
        "preparing": "Preparando zoom facial.\nMantenha os dois olhos abertos.",
        "ready": "Pronto para ativar o zoom.\nFeche só o ESQUERDO por 2 s.",
        "right_not_open": "Mantenha o DIREITO aberto.\nFeche só o ESQUERDO por 2 s.",
        "left_not_open": "Para confirmar, abra o ESQUERDO.\nFeche só o DIREITO por 2 s.",
        "hold_left": "Ativando zoom facial.\nMantenha só o ESQUERDO fechado.",
        "hold_right": "Confirmando zoom facial.\nMantenha só o DIREITO fechado.",
        "relax_brows": "Zoom ativo: relaxe as sobrancelhas.\nMantenha os dois olhos abertos.",
        "wait_neutral": "Preparando os ajustes do zoom.\nMantenha olhos abertos e\nsobrancelhas relaxadas.",
        "adjust": "Ajustes do zoom prontos.\nUse as sobrancelhas.\nDIREITO por 2 s confirma.",
    }
    if state.status == "eyes_need_open":
        return ("Zoom ativo: abra os dois olhos.\nOs ajustes aguardam essa abertura." if state.active
                else "Preparando zoom facial.\nAbra os dois olhos para começar.")
    return messages.get(state.status, messages["preparing"])


def scores_from_result(result):
    """Reject absent/multiple faces and partial or malformed model results."""
    try:
        if len(result.face_landmarks) != 1 or len(result.face_blendshapes) != 1:
            return None
        return {item.category_name: item.score for item in result.face_blendshapes[0]}
    except (AttributeError, TypeError, IndexError):
        return None


class FacialZoom:
    def __init__(self):
        self.generation = 0
        self._blocked = False
        self.reset()

    def reset(self):
        """Cancel a session, requiring newly observed open eyes to rearm."""
        if self._blocked:
            self.generation += 1
        self._blocked = self._active = self._armed = self._zoom_ready = False
        self._last = self._neutral_since = self._hold_since = None
        self._brow_since = None
        self._brow_direction = 0
        self._left_closed = self._right_closed = False

    def _state(self, mode="idle", progress=0.0, factor=1.0, status="preparing"):
        blocked = self._active or mode == "arming_zoom"
        if blocked != self._blocked:
            self.generation += 1
        self._blocked = blocked
        return FacialState(mode, progress, self._active, blocked, factor, self.generation, status)

    @staticmethod
    def _scores(values):
        try:
            if not isinstance(values, Mapping):
                return None
            scores = {key: float(values[key]) for key in SIGNALS}
            return scores if all(isfinite(v) and 0 <= v <= 1 for v in scores.values()) else None
        except (KeyError, TypeError, ValueError, OverflowError):
            return None

    def update(self, values, now, enabled=True):
        try:
            now = float(now)
        except (TypeError, ValueError, OverflowError):
            self.reset()
            return self._state()
        scores = self._scores(values)
        if not enabled or not isfinite(now) or scores is None:
            self.reset()
            return self._state(status="paused" if not enabled else "no_face")
        previous = self._last
        if previous is not None and (now <= previous or now - previous > MAX_OBSERVATION_GAP + 1e-12):
            self.reset()
            previous = None
        self._last = now
        left, right = scores["eyeBlinkLeft"], scores["eyeBlinkRight"]
        # Schmitt thresholds tolerate small fluctuations during an intentional wink.
        self._left_closed = left >= (0.40 if self._left_closed else 0.65)
        self._right_closed = right >= (0.40 if self._right_closed else 0.65)
        eyes_open = left <= 0.25 and right <= 0.25
        left_wink = self._left_closed and right <= 0.25
        right_wink = self._right_closed and left <= 0.25
        up = max(scores["browInnerUp"],
                 (scores["browOuterUpLeft"] + scores["browOuterUpRight"]) / 2)
        down = (scores["browDownLeft"] + scores["browDownRight"]) / 2
        brows_neutral = up <= 0.22 and down <= 0.22
        # Starting a wink needs only an observed release of both eyes.
        # Eyebrow neutrality is required after entry, before any adjustments.
        neutral = eyes_open and (brows_neutral if self._active else True)
        if neutral:
            if self._neutral_since is None:
                self._neutral_since = now
        else:
            self._neutral_since = None
        neutral_held = self._neutral_since is not None and now - self._neutral_since >= NEUTRAL_SECONDS - 1e-9

        if not self._active:
            if neutral_held:
                self._armed = True
            if not self._armed or not left_wink:
                if self._hold_since is not None:
                    self._armed = False
                self._hold_since = None
                status = ("eyes_need_open" if not eyes_open and not self._armed
                          else "right_not_open" if self._left_closed and right > 0.25
                          else "eyes_need_open" if right > 0.25
                          else "ready" if self._armed else "preparing")
                return self._state(status=status)
            if self._hold_since is None:
                self._hold_since = now
            progress = min(1.0, max(0.0, (now - self._hold_since) / HOLD_SECONDS))
            if progress < 1 - 1e-9:
                return self._state("arming_zoom", progress, status="hold_left")
            self._active, self._armed, self._zoom_ready = True, False, False
            self._hold_since = self._neutral_since = None
            return self._state("zoom", status="eyes_need_open")

        # First reopen both eyes and relax the eyebrows. No adjustment or
        # confirmation can inherit a gesture that predates entry into the mode.
        if not self._zoom_ready:
            if neutral_held:
                self._zoom_ready = True
            status = ("eyes_need_open" if not eyes_open else "relax_brows" if not brows_neutral
                      else "adjust" if self._zoom_ready else "wait_neutral")
            return self._state("zoom", status=status)
        if right_wink:
            self._brow_since, self._brow_direction = None, 0
            if self._hold_since is None:
                self._hold_since = now
            progress = min(1.0, max(0.0, (now - self._hold_since) / HOLD_SECONDS))
            if progress >= 1 - 1e-9:
                self.reset()
                self._last = now
                return self._state(status="eyes_need_open")
            return self._state("confirming_zoom", progress, status="hold_right")
        self._hold_since = None
        if not eyes_open:
            self._brow_since, self._brow_direction = None, 0
            return self._state("zoom", status="left_not_open" if self._right_closed and left > 0.25
                               else "eyes_need_open")
        direction = (1 if up >= (0.25 if self._brow_direction == 1 else 0.45) and down < 0.25
                     else -1 if down >= (0.25 if self._brow_direction == -1 else 0.45) and up < 0.25
                     else 0)
        if direction != self._brow_direction:
            self._brow_direction = direction
            self._brow_since = now if direction else None
        factor = 1.0
        if direction and self._brow_since is not None and previous is not None:
            elapsed = max(0.0, now - max(previous, self._brow_since + BROW_DWELL_SECONDS))
            factor = exp(direction * ZOOM_RATE * elapsed)
        return self._state("zoom", factor=factor, status="adjust")
