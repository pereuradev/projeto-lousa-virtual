"""A centered, nondestructive view of a raster board.

Only presentation coordinates change: board pixels, stroke widths and exports
always remain in the original board coordinate system.
"""

from __future__ import annotations

from math import isfinite

from PIL import Image


class Viewport:
    """Fit the board at 100%, with centered zoom and no panning.

    ``image_box`` is the full (possibly clipped) image rectangle in canvas
    coordinates. ``render`` returns only its visible pixels and their canvas
    origin, so even maximum zoom never allocates a zoom-sized intermediate.
    """

    MIN_ZOOM = 0.5
    MAX_ZOOM = 3.0

    def __init__(self, board_width: int, board_height: int,
                 canvas_width: int = 1, canvas_height: int = 1,
                 zoom: float = 1.0) -> None:
        self.board_width = self._dimension(board_width)
        self.board_height = self._dimension(board_height)
        self.canvas_width = self._dimension(canvas_width)
        self.canvas_height = self._dimension(canvas_height)
        self.zoom = 1.0
        self.set_zoom(zoom)

    @staticmethod
    def _dimension(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("Viewport dimensions must be positive integers.")
        return value

    @property
    def scale(self) -> float:
        """Nominal fit scale multiplied by the requested zoom factor."""
        return min(self.canvas_width / self.board_width,
                   self.canvas_height / self.board_height) * self.zoom

    @property
    def image_box(self) -> tuple[int, int, int, int]:
        # Integer image edges keep sampling and coordinate mapping aligned.
        width = max(1, round(self.board_width * self.scale))
        height = max(1, round(self.board_height * self.scale))
        return ((self.canvas_width - width) // 2,
                (self.canvas_height - height) // 2, width, height)

    @property
    def visible_box(self) -> tuple[float, float, float, float]:
        """The visible source rectangle, expressed as board image edges."""
        x, y, width, height = self.image_box
        return (max(0.0, -x * self.board_width / width),
                max(0.0, -y * self.board_height / height),
                min(float(self.board_width),
                    (self.canvas_width - x) * self.board_width / width),
                min(float(self.board_height),
                    (self.canvas_height - y) * self.board_height / height))

    def set_size(self, width: int, height: int) -> bool:
        width, height = self._dimension(width), self._dimension(height)
        changed = (width, height) != (self.canvas_width, self.canvas_height)
        self.canvas_width, self.canvas_height = width, height
        return changed

    def set_zoom(self, zoom: float) -> bool:
        try:
            value = float(zoom)
        except (TypeError, ValueError) as exc:
            raise ValueError("Zoom must be finite.") from exc
        if not isfinite(value):
            raise ValueError("Zoom must be finite.")
        value = max(self.MIN_ZOOM, min(self.MAX_ZOOM, value))
        changed = value != self.zoom
        self.zoom = value
        return changed

    def canvas_to_board(self, x: float, y: float) -> tuple[float, float] | None:
        """Invert the displayed image, rejecting clipped and gray areas."""
        try:
            x, y = float(x), float(y)
        except (TypeError, ValueError):
            return None
        if not isfinite(x) or not isfinite(y):
            return None
        bx, by, width, height = self.image_box
        if not (0 <= x < self.canvas_width and 0 <= y < self.canvas_height
                and bx <= x < bx + width and by <= y < by + height):
            return None
        return (min(self.board_width - 1.0, (x - bx) * self.board_width / width),
                min(self.board_height - 1.0, (y - by) * self.board_height / height))

    def board_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        """Project a board point; points outside the view may be off canvas."""
        x, y = float(x), float(y)
        if not isfinite(x) or not isfinite(y):
            raise ValueError("Point coordinates must be finite.")
        bx, by, width, height = self.image_box
        return (bx + x * width / self.board_width,
                by + y * height / self.board_height)

    def normalized_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        """Map camera coordinates to the canvas before the shared inversion."""
        return (float(x) * (self.canvas_width - 1),
                float(y) * (self.canvas_height - 1))

    def render(self, image: Image.Image) -> tuple[Image.Image, tuple[int, int]]:
        """Resize only the visible source crop; never modify ``image``."""
        if image.size != (self.board_width, self.board_height):
            raise ValueError("Image dimensions do not match the viewport board.")
        x, y, width, height = self.image_box
        left, top = max(0, x), max(0, y)
        right = min(self.canvas_width, x + width)
        bottom = min(self.canvas_height, y + height)
        visible = image.resize((right - left, bottom - top),
                               Image.Resampling.LANCZOS, box=self.visible_box)
        return visible, (left, top)
