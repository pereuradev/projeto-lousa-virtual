"""Camera-independent, observation-timed hand controls for the whiteboard.

Landmarks use MediaPipe's 21-point order. Coordinates may be objects with
``x/y[/z]`` or 2/3-item sequences. Pose checks use joint angles and distances,
so they do not depend on a finger pointing toward the top of the image.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import acos, degrees, dist, isfinite, sqrt
from typing import Sequence


COLOR_ARM_SECONDS = 1.0
COLOR_DWELL_SECONDS = 5.0
CLEAR_HOLD_SECONDS = 2.0
CLEAR_COOLDOWN_SECONDS = 3.0
MAX_OBSERVATION_GAP = 0.35
COLOR_COUNT = 5

Vector = tuple[float, float, float]


@dataclass(frozen=True)
class ControlState:
    mode: str = "idle"
    color_index: int | None = None
    progress: float = 0.0
    select_color: int | None = None
    clear: bool = False
    blocked: bool = False
    finger_count: int | None = None
    hand_count: int = 0
    color_mode: bool = False


def _subtract(a: Vector, b: Vector) -> Vector:
    return tuple(x - y for x, y in zip(a, b))


def _angle(a: Vector, vertex: Vector, b: Vector) -> float:
    first, second = _subtract(a, vertex), _subtract(b, vertex)
    divisor = sqrt(sum(value * value for value in first) * sum(value * value for value in second))
    if divisor <= 1e-12:
        return 0.0
    cosine = sum(x * y for x, y in zip(first, second)) / divisor
    return degrees(acos(max(-1.0, min(1.0, cosine))))


def _landmarks(values: Sequence[object] | None) -> list[Vector] | None:
    if values is None:
        return None
    try:
        if len(values) < 21:
            return None
        points = []
        for landmark in values[:21]:
            if hasattr(landmark, "x"):
                point = (float(landmark.x), float(landmark.y), float(getattr(landmark, "z", 0.0)))
            else:
                point = (float(landmark[0]), float(landmark[1]),
                         float(landmark[2]) if len(landmark) > 2 else 0.0)
            if not all(isfinite(value) for value in point):
                return None
            points.append(point)
        if min(dist(points[5], points[17]), dist(points[0], points[9])) <= 1e-6:
            return None
        return points
    except (AttributeError, IndexError, TypeError, ValueError, OverflowError):
        return None


def _finger(points: list[Vector], base: int, palm_size: float) -> tuple[bool, bool]:
    mcp, pip, dip, tip = points[base:base + 4]
    lengths = [dist(mcp, pip), dist(pip, dip), dist(dip, tip)]
    length = sum(lengths)
    if min(lengths) <= palm_size * 0.025:
        return False, False
    pip_angle, dip_angle = _angle(mcp, pip, dip), _angle(pip, dip, tip)
    extended = (
        pip_angle >= 148.0 and dip_angle >= 145.0
        and dist(tip, mcp) >= length * 0.80
        and dist(tip, points[0]) >= dist(mcp, points[0]) + palm_size * 0.30
        and dist(tip, points[0]) >= dist(pip, points[0]) + palm_size * 0.08
    )
    folded = (
        (pip_angle <= 125.0 or dip_angle <= 125.0)
        and dist(tip, mcp) <= max(lengths[0] * 1.25, length * 0.55)
        and dist(tip, points[0]) <= dist(pip, points[0]) + palm_size * 0.20
    )
    return extended, folded


def _pose_details(points: list[Vector]):
    width = dist(points[5], points[17])
    palm_size = max(width, dist(points[0], points[9]))
    fingers = [_finger(points, base, palm_size) for base in (5, 9, 13, 17)]
    center = tuple(sum(points[index][axis] for index in (0, 5, 9, 13, 17)) / 5
                   for axis in range(3))
    thumb_length = sum(dist(points[a], points[b]) for a, b in ((1, 2), (2, 3), (3, 4)))
    thumb_extended = (
        thumb_length > palm_size * 0.25
        and dist(points[1], points[4]) >= thumb_length * 0.75
        and _angle(points[1], points[2], points[3]) >= 130.0
        and _angle(points[2], points[3], points[4]) >= 130.0
        and dist(points[4], points[5]) >= palm_size * 0.55
        and dist(points[4], center) >= palm_size * 0.60
    )
    thumb_folded = not thumb_extended and (
        dist(points[4], center) <= palm_size * 0.65
        or dist(points[1], points[4]) <= thumb_length * 0.60
        or _angle(points[2], points[3], points[4]) <= 120.0
    )
    raw_pinch = dist(points[4], points[8]) <= width * 0.35
    return fingers, thumb_extended, thumb_folded, raw_pinch


def count_fingers(points: list[Vector]) -> tuple[int | None, bool]:
    """Count extended fingers by joint geometry; no left/right x-coordinate rule."""
    fingers, thumb_extended, thumb_folded, raw_pinch = _pose_details(points)
    if not (thumb_extended or thumb_folded) or any(not (up or down) for up, down in fingers):
        return None, raw_pinch
    return int(thumb_extended) + sum(up for up, _ in fingers), raw_pinch


def thumb_only(points: list[Vector]) -> bool:
    """Recognize a straight thumb with all four other fingers visibly folded."""
    fingers, thumb_extended, _, _ = _pose_details(points)
    return thumb_extended and all(folded for _, folded in fingers)


class ControlGestures:
    """A 1 s thumbs-up arms 5 s color counts; TWO open hands clear after 2 s.

    Drawing is the default. Release the activation thumb before counting colors.
    Pinches, tracking loss, pauses, observation gaps and multiple hands leave
    color mode. Count changes restart its hold. Completed clear and thumb
    latches survive tracking loss/reset until a valid release is observed.
    """

    def __init__(self):
        self._last_observation = None
        self._last_hand_count = None
        self._arming_started = None
        self._color_mode = False
        self._wait_for_thumb_release = False
        self._thumb_needs_release = False
        self._target = None
        self._color_started = None
        self._clear_started = None
        self._clear_needs_release = False
        self._clear_ready_at = float('-inf')

    def reset(self):
        self._last_observation = None
        self._last_hand_count = None
        self._leave_color()
        self._clear_started = None

    def _leave_color(self):
        self._arming_started = None
        self._color_mode = False
        self._wait_for_thumb_release = False
        self._target = None
        self._color_started = None

    @staticmethod
    def _progress(now, start, duration):
        value = max(0.0, min(1.0, (now - start) / duration))
        return 1.0 if value >= 1.0 - 1e-9 else value

    def update(self, hands, point, pinching, now, enabled=True):
        try:
            now = float(now)
        except (TypeError, ValueError, OverflowError):
            self.reset()
            return ControlState()
        if not isfinite(now) or not enabled:
            self.reset()
            return ControlState()
        if hands is None:
            hands = []
        try:
            hand_count = len(hands)
            points = [_landmarks(hand) for hand in hands]
        except TypeError:
            self.reset()
            return ControlState()
        if not hand_count or any(hand is None for hand in points):
            self.reset()
            return ControlState(hand_count=hand_count)
        if self._last_observation is not None and (
            now < self._last_observation or now - self._last_observation > MAX_OBSERVATION_GAP + 1e-12
        ):
            self.reset()
        if self._last_hand_count != hand_count:
            self._color_started = self._clear_started = None
        self._last_observation, self._last_hand_count = now, hand_count
        poses = [count_fingers(hand) for hand in points]
        # A fully visible, genuinely changed pose releases a completed clear.
        # Losing a hand alone is not proof that the person released the pose.
        if any(count is not None and count < 5 for count, _ in poses):
            self._clear_needs_release = False
        if hand_count != 1:
            self._leave_color()
            if hand_count != 2 or not all(count == 5 and not raw for count, raw in poses):
                self._clear_started = None
                return ControlState(mode='two_hands', hand_count=hand_count, blocked=True)
            if self._clear_needs_release:
                return ControlState(mode='clear_done', progress=1.0, blocked=True, hand_count=2)
            if now < self._clear_ready_at:
                self._clear_started = None
                return ControlState(mode='clear_wait', blocked=True, hand_count=2)
            if self._clear_started is None:
                self._clear_started = now
            progress = self._progress(now, self._clear_started, CLEAR_HOLD_SECONDS)
            clear = progress == 1.0
            if clear:
                self._clear_started = None
                self._clear_needs_release = True
                self._clear_ready_at = now + CLEAR_COOLDOWN_SECONDS
            return ControlState(mode='clear_done' if clear else 'clear', progress=progress,
                                clear=clear, blocked=True, hand_count=2)
        self._clear_started = None
        count, raw_pinch = poses[0]
        is_thumb = thumb_only(points[0])
        if count is not None and not is_thumb:
            self._thumb_needs_release = False
        if pinching or raw_pinch:
            self._leave_color()
            return ControlState(finger_count=count, hand_count=1)

        if not self._color_mode:
            if not is_thumb or self._thumb_needs_release:
                self._arming_started = None
                return ControlState(finger_count=count, hand_count=1)
            if self._arming_started is None:
                self._arming_started = now
            progress = self._progress(now, self._arming_started, COLOR_ARM_SECONDS)
            if progress < 1.0:
                return ControlState(mode='arming_color', progress=progress, blocked=True,
                                    finger_count=count, hand_count=1)
            self._arming_started = None
            self._color_mode = True
            self._wait_for_thumb_release = True
            self._thumb_needs_release = True

        if self._wait_for_thumb_release:
            if count is None or is_thumb:
                return ControlState(mode='color_ready', blocked=True, color_mode=True,
                                    finger_count=count, hand_count=1)
            self._wait_for_thumb_release = False
        if count is None or count == 0:
            self._target = self._color_started = None
            return ControlState(mode='color_ready', blocked=True, color_mode=True,
                                finger_count=count, hand_count=1)
        if count != self._target:
            self._target = count
            self._color_started = now
        progress = self._progress(now, self._color_started, COLOR_DWELL_SECONDS)
        selected = count - 1 if progress == 1.0 else None
        if selected is not None:
            self._leave_color()
            self._thumb_needs_release = is_thumb
            return ControlState(mode='color_done', color_index=selected, progress=1.0,
                                select_color=selected, blocked=True,
                                finger_count=count, hand_count=1)
        return ControlState(mode='color', color_index=count - 1, progress=progress,
                            blocked=True, color_mode=True, finger_count=count, hand_count=1)
