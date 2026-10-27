"""Drawing and hand-gesture primitives, independent from the camera and UI.

Coordinates passed to :class:`Board` are canvas pixels. ``GestureFilter`` returns
normalized coordinates, so callers can map them to any canvas size.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import hypot, isfinite
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageChops, ImageColor, ImageDraw


Point = tuple[float, float]


@dataclass
class _BoardState:
    image: Image.Image
    stroke_count: int


class Board:
    """An opaque drawing canvas with bounded, in-memory undo history.

    A stroke is one ``begin`` / ``move`` / ``end`` operation that changes pixels;
    eraser strokes count too. Undo restores this count, and clear resets it.
    Empty strokes and clearing an already white board do not consume undo slots.
    """

    UNDO_LIMIT = 25

    def __init__(
        self, width: int = 1280, height: int = 800, background: str = "white"
    ) -> None:
        if not isinstance(width, int) or not isinstance(height, int):
            raise TypeError("Canvas dimensions must be integers.")
        if width < 1 or height < 1:
            raise ValueError("Canvas dimensions must be positive.")
        self.image = Image.new("RGB", (width, height), background)
        self.dirty = False
        self._saved_image = self.image.copy()
        self._stroke_count = 0
        self._undo: list[_BoardState] = []
        self._pending: _BoardState | None = None
        self._last_point: Point | None = None
        self._stroke_changed = False
        self._color = (0, 0, 0)
        self._width = 1

    @property
    def stroke_count(self) -> int:
        return self._stroke_count

    def _point(self, point: Point) -> Point:
        x, y = float(point[0]), float(point[1])
        if not isfinite(x) or not isfinite(y):
            raise ValueError("Point coordinates must be finite.")
        return (
            max(0.0, min(self.image.width - 1.0, x)),
            max(0.0, min(self.image.height - 1.0, y)),
        )

    def _remember(self, state: _BoardState) -> None:
        self._undo.append(state)
        if len(self._undo) > self.UNDO_LIMIT:
            del self._undo[0]

    def _refresh_dirty(self) -> None:
        self.dirty = ImageChops.difference(self.image, self._saved_image).getbbox() is not None

    def _paint(self, start: Point, finish: Point) -> None:
        # Compare only the affected area, including both rounded caps. This also
        # avoids saving identical undo states when erasing empty canvas pixels.
        padding = self._width + 2
        left = max(0, int(min(start[0], finish[0]) - padding))
        top = max(0, int(min(start[1], finish[1]) - padding))
        right = min(self.image.width, int(max(start[0], finish[0]) + padding + 1))
        bottom = min(self.image.height, int(max(start[1], finish[1]) + padding + 1))
        box = (left, top, right, bottom)
        before = self.image.crop(box)
        draw = ImageDraw.Draw(self.image)
        draw.line((start, finish), fill=self._color, width=self._width, joint="curve")
        radius = (self._width - 1) / 2
        for x, y in (start, finish):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=self._color)
        if ImageChops.difference(before, self.image.crop(box)).getbbox() is None:
            return
        if self._pending is not None:
            self._remember(self._pending)
            self._pending = None
            self._stroke_count += 1
        self._stroke_changed = True
        self.dirty = True

    def begin(self, point: Point, color: str, width: int, erase: bool = False) -> None:
        """Start a stroke and immediately paint its first point."""
        point = self._point(point)
        if not isinstance(width, int):
            raise TypeError("Stroke width must be an integer.")
        if width < 1:
            raise ValueError("Stroke width must be positive.")
        stroke_color = ImageColor.getcolor("white" if erase else color, "RGB")
        self.end()
        self._color = stroke_color
        self._width = width
        self._pending = _BoardState(self.image.copy(), self._stroke_count)
        self._last_point = point
        self._stroke_changed = False
        self._paint(point, point)

    def move(self, point: Point) -> None:
        """Extend an active stroke; movement without begin is ignored."""
        if self._last_point is None:
            return
        point = self._point(point)
        self._paint(self._last_point, point)
        self._last_point = point

    def end(self) -> None:
        """End the active stroke so later movement cannot bridge to it."""
        if self._stroke_changed:
            self._refresh_dirty()
        self._last_point = None
        self._pending = None
        self._stroke_changed = False

    def undo(self) -> bool:
        self.end()
        if not self._undo:
            return False
        state = self._undo.pop()
        self.image = state.image
        self._stroke_count = state.stroke_count
        self._refresh_dirty()
        return True

    def clear(self) -> None:
        """Clear to white; a nonempty clear can itself be undone."""
        self.end()
        if all(low == high == 255 for low, high in self.image.getextrema()):
            self._stroke_count = 0
            return
        self._remember(_BoardState(self.image.copy(), self._stroke_count))
        self.image.paste("white", (0, 0, self.image.width, self.image.height))
        self._stroke_count = 0
        self._refresh_dirty()

    def save(self, directory: Path) -> Path:
        """Export only the RGB canvas to a unique PNG, including Unicode paths."""
        self.end()
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        stem = datetime.now().strftime("lousa_%Y-%m-%d_%H-%M-%S_%f")
        suffix = 0
        while True:
            filename = f"{stem}{f'_{suffix}' if suffix else ''}.png"
            target = directory / filename
            try:
                output = target.open("xb")
            except FileExistsError:
                suffix += 1
                continue
            try:
                with output:
                    self.image.save(output, format="PNG")
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            self._saved_image = self.image.copy()
            self.dirty = False
            return target


class GestureFilter:
    """Debounced pinch detection and normalized, smoothed index-tip position.

    Pinch distance is measured relative to the span between landmarks 5 and 17,
    making thresholds independent of distance to the camera. Two consecutive
    close frames start a pinch; a wider release threshold prevents chatter.
    """

    ALPHA = 0.38
    PINCH_START = 0.35
    PINCH_RELEASE = 0.50
    START_FRAMES = 2
    ACTIVE_MIN = 0.10
    ACTIVE_MAX = 0.90

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._point: Point | None = None
        self._pinching = False
        self._close_frames = 0

    @staticmethod
    def _landmark(landmarks: Sequence[object], index: int) -> Point:
        landmark = landmarks[index]
        x, y = float(landmark.x), float(landmark.y)
        if not isfinite(x) or not isfinite(y):
            raise ValueError("Landmark coordinates must be finite.")
        return x, y

    def update(self, landmarks: Sequence[object] | None) -> tuple[Point | None, bool]:
        """Return ``(position, pressed)``; lost/invalid hands reset all state."""
        if landmarks is None:
            self.reset()
            return None, False
        try:
            index = self._landmark(landmarks, 8)
            thumb = self._landmark(landmarks, 4)
            palm_a = self._landmark(landmarks, 5)
            palm_b = self._landmark(landmarks, 17)
        except (AttributeError, IndexError, TypeError, ValueError, OverflowError):
            self.reset()
            return None, False
        palm_size = hypot(palm_a[0] - palm_b[0], palm_a[1] - palm_b[1])
        if palm_size <= 1e-6:
            self.reset()
            return None, False
        ratio = hypot(index[0] - thumb[0], index[1] - thumb[1]) / palm_size
        if self._pinching:
            if ratio >= self.PINCH_RELEASE - 1e-12:
                self._pinching = False
                self._close_frames = 0
        elif ratio <= self.PINCH_START + 1e-12:
            self._close_frames += 1
            if self._close_frames >= self.START_FRAMES:
                self._pinching = True
                self._close_frames = 0
        else:
            self._close_frames = 0

        span = self.ACTIVE_MAX - self.ACTIVE_MIN
        point = tuple(max(0.0, min(1.0, (value - self.ACTIVE_MIN) / span)) for value in index)
        if self._point is None:
            self._point = point
        else:
            self._point = tuple(
                previous + self.ALPHA * (current - previous)
                for previous, current in zip(self._point, point)
            )
        return self._point, self._pinching
