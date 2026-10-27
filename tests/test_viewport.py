"""Shared input geometry and bounded, nondestructive zoom rendering."""

from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops

from lousa.drawing import Board
from lousa.viewport import Viewport


class ViewportTests(unittest.TestCase):
    def test_fit_and_half_zoom_reject_gray_areas(self):
        view = Viewport(1280, 800, 640, 500)
        self.assertEqual(view.image_box, (0, 50, 640, 400))
        self.assertIsNone(view.canvas_to_board(20, 49))
        self.assertEqual(view.canvas_to_board(320, 250), (640, 400))
        self.assertTrue(view.set_zoom(.5))
        self.assertEqual(view.image_box, (160, 150, 320, 200))
        self.assertIsNone(view.canvas_to_board(159, 250))
        self.assertIsNone(view.canvas_to_board(480, 250))
        self.assertEqual(view.canvas_to_board(320, 250), (640, 400))

    def test_zoom_300_clips_around_center(self):
        view = Viewport(1280, 800, 640, 400, 3)
        self.assertEqual(view.image_box, (-640, -400, 1920, 1200))
        self.assertEqual(view.visible_box, (1280 / 3, 800 / 3,
                                           2560 / 3, 1600 / 3))
        self.assertEqual(view.canvas_to_board(320, 200), (640, 400))
        self.assertEqual(view.canvas_to_board(0, 0), (1280 / 3, 800 / 3))
        self.assertIsNone(view.canvas_to_board(-1, 100))
        self.assertIsNone(view.canvas_to_board(640, 100))

    def test_mouse_and_normalized_gesture_share_inverse_for_every_zoom(self):
        for zoom in (.5, 1, 3):
            with self.subTest(zoom=zoom):
                view = Viewport(1280, 800, 701, 503, zoom)
                camera_point = (.5, .5)
                canvas_point = view.normalized_to_canvas(*camera_point)
                mouse_point = view.canvas_to_board(*canvas_point)
                gesture_point = view.canvas_to_board(*canvas_point)
                self.assertEqual(mouse_point, gesture_point)
                self.assertIsNotNone(mouse_point)
                projected = view.board_to_canvas(*mouse_point)
                self.assertAlmostEqual(projected[0], canvas_point[0])
                self.assertAlmostEqual(projected[1], canvas_point[1])

    def test_roundtrip_visible_board_points_and_resize(self):
        view = Viewport(1280, 800, 701, 503, 3)
        for point in ((640, 400), (500, 350), (750, 450)):
            inverted = view.canvas_to_board(*view.board_to_canvas(*point))
            self.assertAlmostEqual(inverted[0], point[0])
            self.assertAlmostEqual(inverted[1], point[1])
        self.assertTrue(view.set_size(500, 700))
        self.assertFalse(view.set_size(500, 700))
        self.assertEqual(view.zoom, 3)
        self.assertEqual(view.board_to_canvas(640, 400), (250, 350))

    def test_zoom_clamps_and_invalid_input_does_not_break_geometry(self):
        view = Viewport(1280, 800)
        self.assertTrue(view.set_zoom(99))
        self.assertEqual(view.zoom, 3)
        self.assertTrue(view.set_zoom(-99))
        self.assertEqual(view.zoom, .5)
        self.assertFalse(view.set_zoom(.5))
        for value in (float("nan"), float("inf"), None, "bad"):
            with self.assertRaises(ValueError):
                view.set_zoom(value)
        for x, y in ((float("nan"), 0), (0, float("inf")), (None, 0)):
            self.assertIsNone(view.canvas_to_board(x, y))
        with self.assertRaises(ValueError):
            view.set_size(0, 20)

    def test_render_allocates_only_visible_size_and_uses_source_crop(self):
        image = Image.new("RGB", (1280, 800), "white")
        view = Viewport(1280, 800, 640, 400, 3)
        original_resize = image.resize
        with patch.object(image, "resize", wraps=original_resize) as resize:
            result, origin = view.render(image)
        self.assertEqual(result.size, (640, 400))
        self.assertEqual(origin, (0, 0))
        self.assertEqual(resize.call_args.args[0], (640, 400))
        self.assertEqual(resize.call_args.kwargs["box"], view.visible_box)
        view.set_zoom(.5)
        result, origin = view.render(image)
        self.assertEqual(result.size, (320, 200))
        self.assertEqual(origin, (160, 100))

    def test_render_zoom_never_changes_board_png_undo_or_stroke_width(self):
        board = Board()
        board.begin((100, 100), "black", 8)
        board.move((300, 100))
        board.end()
        before = board.image.copy()
        png_before = BytesIO()
        board.image.save(png_before, format="PNG")
        undo_length = len(board._undo)
        view = Viewport(1280, 800, 640, 400)
        for zoom in (.5, 1, 3, 1):
            view.set_zoom(zoom)
            view.render(board.image)
            self.assertEqual(board._width, 8)
            self.assertEqual(len(board._undo), undo_length)
            self.assertEqual(board.stroke_count, 1)
            self.assertIsNone(ImageChops.difference(before, board.image).getbbox())
        png_after = BytesIO()
        board.image.save(png_after, format="PNG")
        self.assertEqual(png_before.getvalue(), png_after.getvalue())
        self.assertTrue(board.undo())
        self.assertEqual(board.image.getpixel((100, 100)), (255, 255, 255))

    def test_rendered_pixels_follow_the_central_visible_crop(self):
        image = Image.new("RGB", (100, 100), "black")
        image.paste("red", (30, 30, 70, 70))
        view = Viewport(100, 100, 100, 100, 3)
        result, origin = view.render(image)
        self.assertEqual(origin, (0, 0))
        self.assertEqual(result.getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(result.getpixel((99, 99)), (255, 0, 0))
        view.set_zoom(.5)
        result, origin = view.render(image)
        self.assertEqual(origin, (25, 25))
        self.assertEqual(result.getpixel((0, 0)), (0, 0, 0))
        self.assertEqual(result.getpixel((25, 25)), (255, 0, 0))

    def test_render_rejects_wrong_board_size(self):
        view = Viewport(1280, 800, 640, 400)
        with self.assertRaises(ValueError):
            view.render(Image.new("RGB", (100, 100)))


if __name__ == "__main__":
    unittest.main()
