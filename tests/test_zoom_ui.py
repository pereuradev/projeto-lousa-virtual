"""Real Tk smoke tests without capture devices or model inference.

Tk may require desktop execution on Windows: a sandbox can hide its Tcl
runtime. Only creation of the Tk root is skippable; App failures are failures.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageChops

from lousa.app import App, tk
from lousa.camera import CameraSafety, CameraWorker
from lousa.controls import ControlState
from lousa.facial import FacialState


class ZoomUiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Desktop Tk runtime unavailable: {exc}")
        self.root.withdraw()
        self.app = App(self.root, no_camera=True)
        # Lay out a real minimum-sized window outside the visible desktop,
        # then hide it. Withdraw alone leaves every child at 1x1 pixels.
        self.root.geometry("1000x640+10000+10000")
        self.root.deiconify()
        self.root.update()
        self.root.update_idletasks()
        self.root.withdraw()
        self.app.render()
        self.addCleanup(self._shutdown)

    def _shutdown(self):
        # Test transport workers are deliberately never started.
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.app.worker = None
        self.app.retired = []
        self.app.shutdown()

    def _worker(self):
        self.app.worker = CameraWorker(0, Path("unused-hand-model.task"))
        return self.app.worker

    def _frame(self, point, segment=1, pinch=True, now=100.0):
        worker = self.app.worker
        epoch = worker.control_context()[1]
        rgb = np.full((8, 8, 3), 255, dtype=np.uint8)
        hands = [[object() for _ in range(21)]]
        worker.publish(("frame", rgb, hands, 30., point, pinch, segment,
                        ControlState(hand_count=1), epoch, now))
        with patch("lousa.app.time.monotonic", return_value=now):
            self.app._tick()

    def assertImagesEqual(self, first, second):
        self.assertEqual(first.size, second.size)
        self.assertEqual(first.mode, second.mode)
        self.assertIsNone(ImageChops.difference(first, second).getbbox())

    def test_real_render_and_export_preserve_board_pixels_width_and_undo(self):
        app = self.app
        app.width.set(12)
        app._draw((120, 200), "mouse")
        app._draw((700, 400), "mouse")
        app.end_stroke()
        before = app.board.image.copy()
        undo_count = len(app.board._undo)
        with TemporaryDirectory() as directory:
            original_path = app.board.save(Path(directory))
            original_png = original_path.read_bytes()
            for zoom in (.5, 1, 3, 1):
                with self.subTest(zoom=zoom):
                    app.set_zoom(zoom)
                    app.render()
                    self.assertEqual(app.viewport.zoom, zoom)
                    self.assertEqual(app.zoom_label.get(), f"{zoom:.0%}")
                    self.assertLessEqual(app.photo.width(), app.canvas.winfo_width())
                    self.assertLessEqual(app.photo.height(), app.canvas.winfo_height())
                    self.assertImagesEqual(before, app.board.image)
                    self.assertEqual(app.board._width, 12)
                    self.assertEqual(len(app.board._undo), undo_count)
                    self.assertEqual(app.board.stroke_count, 1)
                    self.assertEqual(app.board.image.size, (1280, 800))
            output_path = app.board.save(Path(directory))
            self.assertEqual(output_path.read_bytes(), original_png)
            with Image.open(output_path) as exported:
                self.assertImagesEqual(before, exported)
        self.assertTrue(app.board.undo())
        self.assertEqual(app.board.image.getpixel((120, 200)), (255, 255, 255))

    def test_real_mouse_and_gesture_frames_use_the_same_inverse_at_all_zooms(self):
        app = self.app
        self._worker()
        for index, zoom in enumerate((.5, 1, 3), 1):
            with self.subTest(zoom=zoom):
                app.set_zoom(zoom)
                canvas_point = app.viewport.normalized_to_canvas(.5, .5)
                expected = app.viewport.canvas_to_board(*canvas_point)
                event = SimpleNamespace(x=canvas_point[0], y=canvas_point[1])
                with patch.object(app.board, "begin", wraps=app.board.begin) as begin:
                    app.mouse_begin(event)
                self.assertEqual(begin.call_args.args[0], expected)
                app.mouse_end()
                app.gesture_ready = True
                with patch.object(app.board, "begin", wraps=app.board.begin) as begin:
                    self._frame((.5, .5), segment=index, now=100. + index)
                self.assertEqual(begin.call_args.args[0], expected)
                app.end_stroke()

    def test_gray_area_rejects_mouse_and_gesture_drawing(self):
        app = self.app
        app.set_zoom(.5)
        self._worker()
        self.assertIsNone(app.point(0, 0))
        app.mouse_begin(SimpleNamespace(x=0, y=0))
        self.assertEqual(app.board.stroke_count, 0)
        app.mouse_end()
        app.gesture_ready = True
        self._frame((0, 0))
        self.assertEqual(app.board.stroke_count, 0)
        self.assertEqual(app.canvas.itemcget(app.cursor, "state"), "hidden")

    def test_zoom_and_real_resize_end_active_strokes(self):
        app = self.app
        point = app.viewport.board_to_canvas(640, 400)
        app.mouse_begin(SimpleNamespace(x=point[0], y=point[1]))
        self.assertEqual(app.source, "mouse")
        app.set_zoom(2)
        self.assertIsNone(app.source)
        self.assertIsNone(app.board._last_point)
        app.mouse_end()
        app._draw((640, 400), "gesture")
        self.assertEqual(app.source, "gesture")
        self.root.geometry("1120x720+10000+10000")
        self.root.deiconify()
        self.root.update()
        self.root.update_idletasks()
        self.root.withdraw()
        self.assertIsNone(app.source)
        self.assertIsNone(app.board._last_point)
        self.assertEqual(app.viewport.zoom, 2)

    def test_pause_cancels_facial_session_keeps_zoom_and_requires_release(self):
        app = self.app
        worker = self._worker()
        app.set_zoom(1.8, facial=True)
        active = FacialState(mode="zoom", active=True, blocked=True, generation=1)
        app.facial_state = active
        worker._update_safety(active, [], 100., worker.control_context()[1], "disponível")
        old_epoch = worker.control_context()[1]
        app.pause()
        self.assertTrue(app.paused)
        self.assertEqual(app.viewport.zoom, 1.8)
        self.assertFalse(app.facial_state.active)
        self.assertFalse(app.facial_state.blocked)
        self.assertFalse(app.gesture_ready)
        self.assertGreater(worker.control_context()[1], old_epoch)
        self.assertFalse(worker.safety_context().facial.active)
        self.assertTrue(worker.safety_context().release_required)
        app.pause()
        self.assertFalse(app.paused)
        self.assertEqual(app.viewport.zoom, 1.8)
        self.assertFalse(app.gesture_ready)

    def test_help_cancels_facial_session_and_describes_person_sides(self):
        app = self.app
        self._worker()
        app.set_zoom(2, facial=True)
        app.facial_state = FacialState(mode="zoom", active=True, blocked=True)
        with patch("lousa.app.messagebox.showinfo") as showinfo:
            app.show_help()
        text = showinfo.call_args.args[1]
        self.assertIn("ESQUERDO", text)
        self.assertIn("DIREITO", text)
        self.assertIn("2 s", text)
        self.assertIn("franza/retraia", text)
        self.assertIn("50% a 300%", text)
        self.assertEqual(app.viewport.zoom, 2)
        self.assertFalse(app.facial_state.active)
        self.assertFalse(app.gesture_ready)

    def test_mouse_explicitly_ends_facial_mode_and_suspends_worker_controls(self):
        app = self.app
        worker = self._worker()
        app.set_zoom(2, facial=True)
        app.facial_state = FacialState(mode="zoom", active=True, blocked=True)
        point = app.viewport.board_to_canvas(640, 400)
        app.mouse_begin(SimpleNamespace(x=point[0], y=point[1]))
        self.assertEqual(app.viewport.zoom, 2)
        self.assertFalse(app.facial_state.active)
        self.assertFalse(worker.control_context()[0])
        self.assertEqual(app.source, "mouse")
        app.mouse_end()
        self.assertTrue(worker.control_context()[0])
        self.assertFalse(app.gesture_ready)

    def test_missing_face_and_activation_readiness_have_distinct_visible_feedback(self):
        app = self.app
        worker = self._worker()
        epoch = worker.control_context()[1]
        for status, present, expected in (
                ("no_face", False, "Rosto não detectado"),
                ("preparing", True, "dois olhos abertos"),
                ("ready", True, "Pronto para ativar"),
                ("right_not_open", True, "DIREITO aberto")):
            with self.subTest(status=status):
                worker._update_safety(FacialState(status=status), [], 100., epoch,
                                      "Zoom facial disponível", face_present=present)
                with patch("lousa.app.time.monotonic", return_value=100.):
                    app._tick()
                self.assertIn(expected, app.face_status.get())
                self.assertNotIn("disponível", app.face_status.get())

    def test_post_entry_feedback_matches_the_gate_and_ready_adjustments(self):
        app = self.app
        worker = self._worker()
        epoch = worker.control_context()[1]
        for status, expected, mode in (
                ("eyes_need_open", "Abra os dois olhos", "Preparando ajustes"),
                ("relax_brows", "Relaxe as sobrancelhas", "Preparando ajustes"),
                ("wait_neutral", "sobrancelhas relaxadas", "Preparando ajustes"),
                ("adjust", "Ajustes prontos", "Ajustando zoom")):
            with self.subTest(status=status):
                face = FacialState(mode="zoom", active=True, blocked=True, status=status)
                worker._update_safety(face, [], 100., epoch, "Zoom facial disponível", face_present=True)
                with patch("lousa.app.time.monotonic", return_value=100.):
                    app._tick()
                self.assertEqual(app.mode_name.get(), mode)
                self.assertIn(expected, app.control_message.get())

    def test_pause_reports_pause_and_preserves_a_useful_model_error(self):
        app = self.app
        worker = self._worker()
        epoch = worker.control_context()[1]
        worker._update_safety(FacialState(status="ready"), [], 100., epoch,
                              "Zoom facial disponível", face_present=True)
        app.pause()
        self.assertIn("pausado", app.face_status.get())
        self.assertNotIn("Pronto", app.face_status.get())
        error = "Zoom facial indisponível: Modelo facial ausente; execute Instalar ou reparar.cmd."
        worker._update_safety(FacialState(status="paused"), [], 100.,
                              worker.control_context()[1], error)
        with patch("lousa.app.time.monotonic", return_value=100.):
            app._tick()
        self.assertEqual(app.face_status.get(), error)
        app.pause()
        self.assertEqual(app.face_status.get(), error)
        app.disconnect()
        self.assertEqual(app.face_status.get(), "Zoom facial: conecte a câmera")

    def test_idle_feedback_expires_and_rejects_future_observations(self):
        app = self.app
        worker = self._worker()
        epoch = worker.control_context()[1]
        for status in ("ready", "preparing", "eyes_need_open", "right_not_open", "no_face"):
            for now in (100.501, 110., 99.999):
                with self.subTest(status=status, now=now):
                    worker._update_safety(FacialState(status=status), [], 100., epoch,
                                          "Zoom facial disponível", face_present=status != "no_face")
                    with patch("lousa.app.time.monotonic", return_value=now):
                        app._tick()
                    self.assertIn("Aguardando leitura", app.face_status.get())
                    self.assertIn("reconecte a câmera", app.face_status.get())
                    self.assertNotIn("Pronto", app.face_status.get())

    def test_fresh_face_feedback_accepts_both_age_boundaries(self):
        for status, expected, present in (("ready", "Pronto para ativar", True),
                                           ("preparing", "dois olhos abertos", True),
                                           ("no_face", "Rosto não detectado", False)):
            safety = CameraSafety(facial=FacialState(status=status), captured_at=100.,
                                  status="Zoom facial disponível", face_present=present)
            for now in (100., 100.5):
                with self.subTest(status=status, now=now):
                    self.app._face_feedback(safety, enabled=True, now=now)
                    self.assertIn(expected, self.app.face_status.get())

    def test_feedback_prioritizes_model_error_pause_and_startup_over_freshness(self):
        app = self.app
        app.paused = True
        error = "Zoom facial indisponível: Modelo facial ausente; execute Instalar ou reparar.cmd."
        unavailable = CameraSafety(status=error)
        app._face_feedback(unavailable, enabled=False, now=110.)
        self.assertEqual(app.face_status.get(), error)
        startup = CameraSafety(status="Zoom facial iniciando")
        app._face_feedback(startup, enabled=False, now=110.)
        self.assertIn("pausado", app.face_status.get())
        app.paused = False
        app._face_feedback(startup, enabled=False, now=110.)
        self.assertIn("suspenso", app.face_status.get())
        app._face_feedback(startup, enabled=True, now=110.)
        self.assertEqual(app.face_status.get(), "Zoom facial iniciando")

    def test_facial_feedback_text_fits_reserved_lines_at_minimum_window_size(self):
        app = self.app
        self.root.deiconify()
        sidebar = app.preview.master
        face_label = next(widget for widget in sidebar.winfo_children()
                          if isinstance(widget, tk.Label)
                          and str(widget.cget("textvariable")) == str(app.face_status))
        cases = [(FacialState(status=status), status != "no_face") for status in
                 ("no_face", "preparing", "ready", "eyes_need_open", "right_not_open", "paused")]
        cases += [(FacialState(mode="zoom", active=True, blocked=True, status=status), True)
                  for status in ("eyes_need_open", "relax_brows", "wait_neutral", "adjust", "left_not_open")]
        cases += [(FacialState(mode=mode, active=mode == "confirming_zoom", blocked=True,
                               progress=0.5, status=status), True)
                  for mode, status in (("arming_zoom", "hold_left"), ("confirming_zoom", "hold_right"))]

        def assert_text_fits(label):
            probe = tk.Label(self.root, text=label.cget("text") if not label.cget("textvariable")
                             else self.root.getvar(label.cget("textvariable")),
                             font=label.cget("font"), wraplength=label.cget("wraplength"),
                             justify=label.cget("justify"), padx=label.cget("padx"),
                             pady=label.cget("pady"))
            try:
                self.assertLessEqual(probe.winfo_reqheight(), label.winfo_height())
            finally:
                probe.destroy()

        for state, present in cases:
            with self.subTest(status=state.status, mode=state.mode):
                safety = CameraSafety(facial=state, captured_at=100., status="Zoom facial disponível", face_present=present)
                app._face_feedback(safety, enabled=True, now=100.)
                app.facial_state = state
                app._control_feedback(ControlState())
                self.root.update_idletasks()
                assert_text_fits(face_label)
                assert_text_fits(app.control_label)
        for error in ("Modelo facial ausente", "Modelo facial inválido"):
            with self.subTest(error=error):
                safety = CameraSafety(status=f"Zoom facial indisponível: {error}; execute Instalar ou reparar.cmd.")
                app._face_feedback(safety, enabled=False)
                self.root.update_idletasks()
                assert_text_fits(face_label)
        app._face_feedback(CameraSafety(status="Zoom facial disponível"), enabled=True, now=110.)
        self.root.update_idletasks()
        assert_text_fits(face_label)
        self.root.withdraw()

    def test_window_sizes_keep_sidebar_and_buttons_fully_visible(self):
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        for geometry in ("1000x640", "1180x780", "1920x1080"):
            with self.subTest(geometry=geometry):
                self.root.geometry(geometry + "+10000+10000")
                self.root.deiconify()
                self.root.update()
                self.root.update_idletasks()
                self.assertGreater(self.app.canvas.winfo_width(), 200)
                self.assertGreater(self.app.canvas.winfo_height(), 200)
                self.app.face_status.set(
                    "Zoom facial indisponível: Modelo facial ausente; execute Instalar ou reparar.cmd.")
                self.app.pause()
                self.root.update_idletasks()
                buttons = [widget for widget in descendants(self.root)
                           if isinstance(widget, tk.Button)]
                self.assertTrue(any(button.cget("text") == "Restaurar visão" for button in buttons))
                sidebar = self.app.preview.master
                widgets = buttons + list(sidebar.winfo_children())
                for widget in widgets:
                    with self.subTest(widget=widget):
                        self.assertGreater(widget.winfo_width(), 1)
                        self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth()
                                                if isinstance(widget, tk.Button) else 1)
                        self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight())
                        self.assertGreaterEqual(widget.winfo_x(), 0)
                        self.assertGreaterEqual(widget.winfo_y(), 0)
                        self.assertLessEqual(widget.winfo_x() + widget.winfo_width(),
                                             widget.master.winfo_width())
                        self.assertLessEqual(widget.winfo_y() + widget.winfo_height(),
                                             widget.master.winfo_height())
                self.app.pause()
                self.root.withdraw()


if __name__ == "__main__":
    unittest.main()
