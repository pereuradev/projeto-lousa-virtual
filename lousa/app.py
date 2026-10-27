"""Interface desktop em português para desenhar com a mão ou o mouse."""
from __future__ import annotations

import argparse
import json
import queue
import time
import tkinter as tk
from contextlib import contextmanager
from pathlib import Path
from tkinter import messagebox

from PIL import Image, ImageTk

from .camera import CameraWorker, diagnose
from .drawing import Board, GestureFilter
from .controls import ControlState
from .facial import FacialState
from .viewport import Viewport

ROOT = Path(__file__).resolve().parents[1]
BG, PANEL, TEXT, MUTED, ACCENT = "#f3f3ef", "#ffffff", "#252a27", "#68716b", "#32694e"
LINE, SELECTED, PREVIEW_BG = "#d7dcd6", "#e3ece5", "#202724"
PREVIEW_SIZE = (208, 156)
COLORS = [("Preto", "#182333"), ("Azul", "#2563eb"), ("Vermelho", "#e23b53"),
          ("Verde", "#159b70"), ("Roxo", "#8b4ce0")]


class App:
    def __init__(self, root: tk.Tk, camera: int = 0, no_camera: bool = False):
        self.root = root
        root.title("Projeto Lousa Virtual")
        root.geometry("1180x780")
        root.minsize(1000, 640)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.board = Board()
        self.viewport = Viewport(self.board.image.width, self.board.image.height)
        self.facial_state = FacialState()
        self.safety_revision = 0
        self.mouse_active = False
        self.gesture = GestureFilter()
        self.worker: CameraWorker | None = None
        self.retired: list[CameraWorker] = []
        self.color = COLORS[0][1]
        self.eraser = False
        self.paused = False
        self.source = None
        self.last_hand_time = 0.0
        self.closed = False
        self.dialog_open = False
        self.gesture_segment = None
        self.gesture_ready = True
        self.photo = self.preview_photo = None
        self.image_box = (0, 0, 1, 1)
        self.status = tk.StringVar(value="Pronto para desenhar com o mouse")
        self.hand_status = tk.StringVar(value="Câmera desconectada")
        self.face_status = tk.StringVar(value="Zoom facial: conecte a câmera")
        self.zoom_label = tk.StringVar(value="100%")
        self.tool_label = tk.StringVar(value="Caneta · Preto")
        self.width = tk.IntVar(value=8)
        self.camera_index = tk.StringVar(value=str(camera))
        self.control_message = tk.StringVar(value="Pinça para desenhar. Joinha por 1 s para escolher cor.")
        self.mode_name = tk.StringVar(value="Desenho")
        self.control_state = ControlState()
        self._ui()
        root.bind("<KeyPress>", self._key)
        root.bind("<Control-z>", lambda _: self.undo())
        self.root.after(30, self._tick)
        if not no_camera:
            self.root.after(350, self.connect)

    def button(self, parent, text, command, accent=False, **kwargs):
        return tk.Button(parent, text=text, command=command,
                         bg=ACCENT if accent else PANEL, fg="white" if accent else TEXT,
                         activebackground="#28563f" if accent else SELECTED,
                         activeforeground="white" if accent else TEXT,
                         relief="flat", borderwidth=0, highlightthickness=1,
                         highlightbackground=ACCENT if accent else LINE,
                         highlightcolor=ACCENT, padx=10, pady=7, cursor="hand2",
                         font=("Segoe UI", 10), **kwargs)

    def _ui(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=20, pady=(15, 12))
        tk.Label(header, text="Lousa", font=("Segoe UI", 18, "bold"), fg=TEXT, bg=BG).pack(side="left")
        tk.Label(header, textvariable=self.mode_name, font=("Segoe UI", 9, "bold"), fg=ACCENT, bg=SELECTED, padx=8, pady=4).pack(side="left", padx=(16, 0))
        tk.Label(header, textvariable=self.tool_label, font=("Segoe UI", 10), fg=MUTED, bg=BG).pack(side="left", padx=18)
        self.button(header, "Salvar PNG", self.save, True).pack(side="right")
        self.button(header, "Ajuda", self.show_help).pack(side="right", padx=8)
        toolbar = tk.Frame(self.root, bg=PANEL, padx=10, pady=8,
                           highlightbackground=LINE, highlightthickness=1)
        toolbar.pack(fill="x", padx=20)
        self.pen_button = self.button(toolbar, "Caneta", self.use_pen)
        self.pen_button.pack(side="left")
        self.eraser_button = self.button(toolbar, "Borracha", self.toggle_eraser)
        self.eraser_button.pack(side="left", padx=(5, 12))
        self.palette_buttons = []
        self.gesture_palette = tk.Canvas(toolbar, bg=PANEL, width=400, height=36,
                                         highlightthickness=0, cursor="hand2", takefocus=0)
        self.gesture_palette.pack(side="left", padx=(0, 12))
        self.gesture_palette.bind("<Configure>", lambda _: self._render_control_feedback())
        self.gesture_palette.bind("<ButtonPress-1>", self.palette_click)
        tk.Label(toolbar, text="Traço", fg=MUTED, bg=PANEL, font=("Segoe UI", 9)).pack(side="left")
        tk.Scale(toolbar, from_=2, to=40, orient="horizontal", variable=self.width,
                 length=80, showvalue=True, bg=PANEL, fg=TEXT, troughcolor=LINE,
                 highlightthickness=0, activebackground=ACCENT, borderwidth=0,
                 font=("Segoe UI", 8)).pack(side="left", padx=(3, 8))
        self.button(toolbar, "Limpar", self.clear).pack(side="right")
        self.button(toolbar, "Desfazer", self.undo).pack(side="right", padx=(0, 5))
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=20, pady=(14, 8))
        side = tk.Frame(body, bg=BG, width=224)
        side.pack(side="right", fill="y", padx=(18, 0))
        side.pack_propagate(False)
        tk.Label(side, text="Câmera", fg=TEXT, bg=BG, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))
        self.preview_photo = ImageTk.PhotoImage(Image.new("RGB", PREVIEW_SIZE, PREVIEW_BG))
        self.preview = tk.Label(side, image=self.preview_photo, text="Câmera desligada",
                                compound="center", bg=PREVIEW_BG, fg="#c9d1cb",
                                font=("Segoe UI", 10), width=PREVIEW_SIZE[0], height=PREVIEW_SIZE[1])
        self.preview.pack(anchor="w")
        tk.Label(side, textvariable=self.hand_status, fg=MUTED, bg=BG,
                 font=("Segoe UI", 9), wraplength=208, height=2, anchor="nw",
                 justify="left").pack(anchor="w", fill="x", pady=(6, 2))
        camrow = tk.Frame(side, bg=BG)
        camrow.pack(fill="x", pady=(0, 4))
        tk.Label(camrow, text="Fonte", bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")
        tk.Spinbox(camrow, from_=0, to=9, textvariable=self.camera_index, width=3,
                   font=("Segoe UI", 10), relief="solid", borderwidth=1).pack(side="left", padx=7)
        self.connect_button = self.button(camrow, "Conectar", self.connect)
        self.connect_button.pack(side="left")
        zoomrow = tk.Frame(side, bg=BG)
        zoomrow.pack(fill="x", padx=(0, 16), pady=(0, 4))
        zoom_minus = self.button(zoomrow, "−", lambda: self.set_zoom(self.viewport.zoom / 1.1))
        zoom_minus.configure(pady=3)
        zoom_minus.pack(side="left")
        tk.Label(zoomrow, textvariable=self.zoom_label, fg=TEXT, bg=BG,
                 font=("Segoe UI", 10, "bold"), width=6).pack(side="left", expand=True)
        zoom_plus = self.button(zoomrow, "+", lambda: self.set_zoom(self.viewport.zoom * 1.1))
        zoom_plus.configure(pady=3)
        zoom_plus.pack(side="right")
        viewrow = tk.Frame(side, bg=BG)
        viewrow.pack(fill="x", padx=(0, 16), pady=(0, 4))
        self.pause_button = self.button(viewrow, "Pausar gestos", self.pause)
        self.pause_button.configure(font=("Segoe UI", 9), padx=4, pady=4)
        self.pause_button.pack(side="left")
        restore_view = self.button(viewrow, "Restaurar visão", lambda: self.set_zoom(1.0))
        restore_view.configure(font=("Segoe UI", 9), padx=4, pady=4)
        restore_view.pack(side="right")
        tk.Label(side, textvariable=self.face_status, fg=MUTED, bg=BG,
                 font=("Segoe UI", 8), wraplength=208, height=3, anchor="nw",
                 justify="left").pack(anchor="w", pady=(2, 4))
        tk.Frame(side, bg=LINE, height=1).pack(fill="x", padx=(0, 16), pady=(0, 6))
        tk.Label(side, text="Cores: joinha 1 s; dedos 5 s.\nLimpar: 2 mãos abertas, 2 s.\nZoom facial: Ajuda (F1).",
                 fg=MUTED, bg=BG, font=("Segoe UI", 9), justify="left",
                 wraplength=208).pack(anchor="w")
        board_frame = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        board_frame.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(board_frame, bg="#e9ece7", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.board_item = self.canvas.create_image(0, 0, anchor="nw")
        self.cursor = self.canvas.create_oval(0, 0, 0, 0, outline=ACCENT, width=3, state="hidden")
        self.canvas.bind("<Configure>", lambda _: self.render())
        self.canvas.bind("<ButtonPress-1>", self.mouse_begin)
        self.canvas.bind("<B1-Motion>", self.mouse_move)
        self.root.bind("<ButtonRelease-1>", self.mouse_end)
        self.control_progress = tk.Canvas(board_frame, bg=LINE, height=4, highlightthickness=0)
        self.control_progress.pack(fill="x")
        self.control_progress.bind("<Configure>", lambda _: self._render_control_feedback())
        self.control_label = tk.Label(board_frame, textvariable=self.control_message,
                                     bg=PANEL, fg=MUTED, font=("Segoe UI", 9),
                                     anchor="w", height=2, justify="left", wraplength=700)
        self.control_label.pack(fill="x", padx=12, pady=4)
        self.canvas.bind("<Configure>", self._resize_board)
        self.status_label = tk.Label(self.root, textvariable=self.status, bg=BG, fg=MUTED,
                                     font=("Segoe UI", 9), anchor="w", wraplength=1120, justify="left")
        self.status_label.pack(fill="x", padx=20, pady=(0, 10))
        self.root.bind("<Configure>", lambda event: self.status_label.configure(wraplength=max(360, event.width - 40)) if event.widget is self.root else None)
        self.select_color(0)

    def _resize_board(self, event):
        self.end_stroke()
        self.render()
        self.control_label.configure(wraplength=max(200, event.width - 24))

    def use_pen(self):
        if self.eraser:
            self.toggle_eraser()

    def show_help(self):
        text = ("DESENHO\nUna polegar e indicador para desenhar. Separe para parar.\n"
                "O mouse também funciona: clique e arraste na área branca.\n\n"
                "CORES — JOINHA POR 1 SEGUNDO PARA ATIVAR\n"
                "Só o polegar estendido, com os outros quatro dedos dobrados.\n"
                "Solte o joinha; depois mantenha 1–5 dedos por 5 segundos.\n"
                "1 dedo: Preto     2: Azul     3: Vermelho     4: Verde     5: Roxo\n"
                "Escolheu a cor: volta automaticamente ao desenho.\n"
                "A pinça cancela a escolha e volta ao desenho.\n"
                "A barra mostra o tempo; mudar a contagem reinicia.\n\n"
                "LIMPEZA — DUAS MÃOS ABERTAS POR 2 SEGUNDOS\n"
                "Feche ou retire uma mão antes de completar para cancelar.\n"
                "No modo Cores, uma mão aberta escolhe Roxo; não limpa. Desfazer recupera o desenho.\n\n"
                "ZOOM FACIAL — ESQUERDA E DIREITA DA PESSOA\n"
                "Relaxe o rosto e mantenha só o olho ESQUERDO fechado por 2 s.\n"
                "Reabra os olhos e relaxe as sobrancelhas antes de ajustar.\n"
                "Levante as sobrancelhas para ampliar; franza/retraia (aproxime e abaixe) para reduzir.\n"
                "Ajustes funcionam com os dois olhos abertos.\n"
                "Mantenha só o olho DIREITO fechado por 2 s para confirmar.\n"
                "Dois olhos fechados não ativam nem confirmam.\n"
                "O desenho, as cores e a limpeza aguardam desde o início da ativação.\n"
                "Solte a pinça após entrar e sair. Perder o rosto, pausar, abrir Ajuda ou usar\n"
                "o mouse encerra o modo e mantém o zoom. A visão vai de 50% a 300%;\n"
                "Restaurar visão = 100% (encaixar). Zoom não altera o PNG nem os traços.\n\n"
                "ATALHOS\n1–5: cores   E: borracha   B: caneta   +/−: espessura\n"
                "Z ou Ctrl+Z: desfazer   C: limpar   S: salvar\n"
                "Espaço: pausar gestos   Esc: fechar   F1: ajuda\n\n"
                "O PNG é salvo na pasta desenhos do projeto.\n"
                "Não há gravação ou upload de imagens da câmera.")
        with self.dialog():
            messagebox.showinfo("Como usar a lousa", text, parent=self.root)

    def render(self):
        if self.closed:
            return
        cw, ch = max(self.canvas.winfo_width(), 2), max(self.canvas.winfo_height(), 2)
        viewport = self._viewport()
        if viewport.set_size(cw, ch):
            self.end_stroke()
        self.image_box = viewport.image_box
        visible, (x, y) = viewport.render(self.board.image)
        self.photo = ImageTk.PhotoImage(visible)
        self.canvas.itemconfigure(self.board_item, image=self.photo)
        self.canvas.coords(self.board_item, x, y)

    def point(self, x, y):
        return self._viewport().canvas_to_board(x, y)

    def _viewport(self):
        if not hasattr(self, "viewport"):
            # Also supports headless callers that construct only drawing state.
            _, _, width, height = self.image_box
            self.viewport = Viewport(self.board.image.width, self.board.image.height,
                                     max(1, int(width)), max(1, int(height)))
        return self.viewport

    def _cancel_facial(self):
        self.facial_state = FacialState()
        if self.worker:
            self.worker.cancel_facial()
        if hasattr(self, "mode_name"):
            self._control_feedback(ControlState())

    def set_zoom(self, value, facial=False):
        if not facial:
            self._cancel_facial()
        if self._viewport().set_zoom(value):
            self.end_stroke()
            self.canvas.itemconfigure(self.cursor, state="hidden")
            self.render()
        if hasattr(self, "zoom_label"):
            self.zoom_label.set(f"{self.viewport.zoom:.0%}")

    def mouse_end(self, event=None):
        if getattr(self, "mouse_active", False):
            self.mouse_active = False
            self.gesture_ready = False
        self.end_stroke()
        self._sync_controls()

    def end_stroke(self):
        self.board.end()
        self.source = None

    def _draw(self, point, source):
        if self.source != source:
            self.end_stroke()
            self.board.begin(point, self.color, self.width.get() * (3 if self.eraser else 1), self.eraser)
            self.source = source
        else:
            self.board.move(point)
        self.render()

    def mouse_begin(self, event):
        self.mouse_active = True
        self._cancel_facial()
        self._sync_controls()
        self.canvas.focus_set()
        self.gesture.reset()
        self.end_stroke()
        p = self.point(event.x, event.y)
        if p:
            self._draw(p, "mouse")
        self._sync_controls()

    def mouse_move(self, event):
        p = self.point(event.x, event.y)
        if self.source == "mouse" and p:
            self._draw(p, "mouse")
        elif self.source == "mouse":
            self.end_stroke()

    def select_color(self, index):
        self.end_stroke()
        self.eraser = False
        name, self.color = COLORS[index]
        for i, button in enumerate(self.palette_buttons):
            button.configure(relief="sunken" if i == index else "flat")
        self.eraser_button.configure(bg=PANEL)
        if hasattr(self, "pen_button"):
            self.pen_button.configure(bg=SELECTED)
        self.tool_label.set(f"Caneta · {name}")
        if hasattr(self, "gesture_palette"):
            self._render_control_feedback()

    def palette_click(self, event):
        width = max(self.gesture_palette.winfo_width(), 1)
        self.select_color(min(4, max(0, int(event.x / width * 5))))
        self.canvas.focus_set()

    def _render_control_feedback(self):
        if not hasattr(self, "gesture_palette"):
            return
        state, palette = self.control_state, self.gesture_palette
        face = getattr(self, "facial_state", FacialState())
        progress = face.progress if face.blocked else state.progress
        width = max(palette.winfo_width(), 5)
        bar_width = self.control_progress.winfo_width() if hasattr(self, "control_progress") else 0
        signature = (state.mode, face.mode, state.color_index, round(progress, 2), self.color,
                     self.eraser, width, bar_width)
        if getattr(self, "_palette_signature", None) == signature:
            return
        self._palette_signature = signature
        palette.delete("all")
        for i, (name, color) in enumerate(COLORS):
            left, right = i * width / 5, (i + 1) * width / 5
            focused = state.mode in ("color", "color_done") and state.color_index == i
            active = color == self.color and not self.eraser
            palette.create_oval(left + 3, 8, left + 23, 28, fill=color,
                                outline=ACCENT if focused else (TEXT if active else LINE),
                                width=3 if focused or active else 1)
            palette.create_text(left + 13, 18, text=str(i + 1), fill="white", font=("Segoe UI", 8, "bold"))
            palette.create_text(left + 29, 18, anchor="w", text=name,
                                fill=TEXT if active else MUTED,
                                font=("Segoe UI", 9, "bold" if active else "normal"))
            if focused:
                palette.create_line(left + 3, 34, left + 3 + (right - left - 8) * state.progress,
                                    34, fill=ACCENT, width=2)
        if hasattr(self, "control_progress"):
            bar = self.control_progress
            bar.delete("all")
            if progress:
                bar.create_rectangle(0, 0, bar_width * progress, 4,
                                     fill="#b24e36" if state.mode.startswith("clear") else ACCENT, outline="")

    def _control_feedback(self, state):
        self.control_state = state
        face = getattr(self, "facial_state", FacialState())
        if face.blocked:
            name = {"arming_zoom": "Ativando zoom", "zoom": "Ajustando zoom",
                    "confirming_zoom": "Confirmando zoom"}[face.mode]
            self.mode_name.set(name)
            if face.mode == "zoom":
                message = "Reabra os olhos e relaxe o rosto. Sobrancelhas: levante para ampliar; franza para reduzir. Direito 2 s confirma."
            else:
                eye = "esquerdo" if face.mode == "arming_zoom" else "direito"
                message = f"{name} · olho {eye}: {face.progress * 2:.1f} de 2 segundos · outro olho aberto"
            self.control_message.set(message)
            self._render_control_feedback()
            return
        self.mode_name.set("Ativando cores" if state.mode == "arming_color" else
                           "Cores ativadas" if state.color_mode else
                           "Limpeza" if state.mode.startswith("clear") else "Desenho")
        if state.mode == "arming_color":
            message = f"Joinha reconhecido · mantenha por 1 segundo: {state.progress:.0%}"
        elif state.mode == "color_ready":
            message = ("Cores ativadas. Solte o joinha e mostre 1–5 dedos por 5 s." if state.finger_count == 1
                       else "Cores ativadas. Mostre 1–5 dedos e mantenha por 5 segundos.")
        elif state.mode in ("color", "color_done"):
            name = COLORS[state.color_index][0]
            message = (f"Cor escolhida: {name} · Faça a pinça para desenhar" if state.progress >= 1
                       else f"{state.finger_count} dedo(s) · {name} · {state.progress * 5:.1f} de 5 segundos")
        elif state.mode == "clear":
            message = f"Limpando · {state.progress * 2:.1f} de 2 segundos. Feche uma mão para cancelar."
        elif state.mode == "clear_done":
            message = "Lousa limpa · Feche ao menos uma mão para liberar · Z desfaz"
        elif state.mode == "clear_wait":
            message = "Intervalo de segurança: 3 s após limpar · Depois, DUAS mãos abertas por 2 s"
        elif state.mode == "two_hands":
            message = "Duas mãos visíveis: desenho e cores suspensos · Para limpar, abra as DUAS mãos"
        else:
            message = "Pinça para desenhar. Joinha por 1 s para escolher cor."
        self.control_message.set(message)
        self._render_control_feedback()

    def _sync_controls(self):
        enabled = not (self.paused or self.dialog_open or self.closed or self.source == "mouse"
                       or getattr(self, "mouse_active", False))
        if not enabled:
            self.facial_state = FacialState()
        if self.worker:
            return enabled, self.worker.set_controls_enabled(enabled)
        return enabled, None

    def _apply_control_actions(self, enabled, epoch, now):
        if not self.worker:
            return
        while True:
            try:
                queued = self.worker.actions.get_nowait()
                action_epoch, captured_at, action, value = queued[:4]
            except queue.Empty:
                break
            if not enabled or action_epoch != epoch or not 0 <= now - captured_at <= 0.5:
                continue
            safety = self.worker.safety_context()
            if action == "zoom":
                generation, factor = value
                if (safety.epoch == epoch and safety.facial.active
                        and safety.facial.generation == generation
                        and 0 <= now - safety.captured_at <= 0.5):
                    self.set_zoom(self._viewport().zoom * factor, facial=True)
                continue
            action_revision = queued[4] if len(queued) > 4 else 0
            if safety.facial.blocked or safety.release_required or action_revision != safety.revision:
                continue
            self.end_stroke()
            self.gesture_ready = False
            if action == "color":
                self.select_color(value)
                self.status.set(f"Cor escolhida pela câmera: {COLORS[value][0]}")
            elif action == "clear":
                self.board.clear()
                self.render()
                self.status.set("Lousa limpa por gesto · Z ou Desfazer recupera o desenho")

    def toggle_eraser(self):
        self.end_stroke()
        self.eraser = not self.eraser
        self.eraser_button.configure(bg=SELECTED if self.eraser else PANEL)
        if hasattr(self, "pen_button"):
            self.pen_button.configure(bg=PANEL if self.eraser else SELECTED)
        name = next(name for name, color in COLORS if color == self.color)
        self.tool_label.set("Borracha · largura 3×" if self.eraser else f"Caneta · {name}")
        self._render_control_feedback()

    def undo(self):
        self.end_stroke()
        self.gesture.reset()
        if self.board.undo():
            self.status.set("Última ação desfeita")
            self.render()

    @contextmanager
    def dialog(self):
        self.end_stroke()
        self.dialog_open = True
        self._sync_controls()
        try:
            yield
        finally:
            self.dialog_open = False
            self.gesture_ready = False
            self.gesture.reset()
            self._sync_controls()

    def clear(self):
        self.end_stroke()
        if not self.board.stroke_count:
            return
        with self.dialog():
            confirmed = messagebox.askyesno("Limpar lousa", "Limpar todos os traços? Você pode desfazer com Z.", parent=self.root)
        if confirmed:
            self.board.clear()
            self.gesture.reset()
            self.render()
            self.status.set("Lousa limpa · Z para desfazer")

    def save(self):
        self.end_stroke()
        try:
            path = self.board.save(ROOT / "desenhos")
            self.status.set(f"PNG salvo: {path.name} · pasta desenhos do projeto")
            return True
        except OSError as exc:
            with self.dialog():
                messagebox.showerror("Não foi possível salvar", str(exc), parent=self.root)
            return False

    def pause(self):
        self.paused = not self.paused
        self.end_stroke()
        self.gesture.reset()
        self.gesture_ready = False
        self._sync_controls()
        self._control_feedback(ControlState())
        self.canvas.itemconfigure(self.cursor, state="hidden")
        self.pause_button.configure(text="Retomar gestos" if self.paused else "Pausar gestos")
        self.status.set("Gestos pausados · o mouse continua disponível" if self.paused else "Gestos ativados")

    def disconnect(self):
        if self.worker:
            self.worker.stop()
            self.retired.append(self.worker)
            self.worker = None
        self.end_stroke()
        self.gesture.reset()
        self.facial_state = FacialState()
        self.gesture_ready = False
        self.canvas.itemconfigure(self.cursor, state="hidden")
        self.preview_photo = ImageTk.PhotoImage(Image.new("RGB", PREVIEW_SIZE, PREVIEW_BG))
        self.preview.configure(image=self.preview_photo, text="Câmera desconectada")
        self.connect_button.configure(text="Conectar")
        self.hand_status.set("Câmera desconectada")
        if hasattr(self, "face_status"):
            self.face_status.set("Zoom facial: conecte a câmera")
        self._control_feedback(ControlState())

    def connect(self):
        if self.worker:
            self.disconnect()
            return
        self.retired = [w for w in self.retired if w.is_alive()]
        if self.retired:
            self.status.set("Aguarde a câmera anterior encerrar e tente novamente")
            return
        try:
            index = int(self.camera_index.get())
            if not 0 <= index <= 9:
                raise ValueError
        except ValueError:
            messagebox.showerror("Câmera inválida", "Escolha um número de câmera entre 0 e 9.", parent=self.root)
            return
        self.worker = CameraWorker(index, ROOT / "models" / "hand_landmarker.task")
        self.gesture_segment = None
        self.safety_revision = 0
        self.facial_state = FacialState()
        self.worker.start()
        self.last_hand_time = time.monotonic()
        self.hand_status.set("Iniciando câmera e detector…")
        self.connect_button.configure(text="Desconectar")
        self.status.set("Abrindo câmera · o mouse já pode ser usado")

    def _tick(self):
        if self.closed:
            return
        now = time.monotonic()
        enabled, epoch = self._sync_controls()
        safety = self.worker.safety_context() if self.worker else None
        if safety:
            if safety.facial.blocked and now - safety.captured_at > 0.5:
                self._cancel_facial()
                enabled, epoch = self._sync_controls()
                safety = self.worker.safety_context()
            if safety.revision != getattr(self, "safety_revision", 0):
                self.safety_revision = safety.revision
                if self.source == "gesture":
                    self.end_stroke()
                if safety.release_required or safety.facial.blocked:
                    self.facial_release_wait = True
                    self.gesture_ready = False
            if getattr(self, "facial_release_wait", False) and not safety.release_required and not safety.facial.blocked:
                # The worker saw a real separated pinch after the session.
                # This durable latch survives video queue replacement.
                self.facial_release_wait = False
                self.gesture_ready = True
            self.facial_state = safety.facial if enabled else FacialState()
            if hasattr(self, "face_status"):
                self.face_status.set(safety.status)
        self._apply_control_actions(enabled, epoch, now)
        latest = None
        if self.worker:
            while True:
                try:
                    latest = self.worker.events.get_nowait()
                except queue.Empty:
                    break
        if latest is None and safety is not None:
            self._control_feedback(self.control_state)
        if latest and latest[0] == "error":
            self.disconnect()
            self.status.set(latest[1])
            self.hand_status.set("Câmera indisponível · use o mouse")
        elif latest and latest[0] == "frame":
            _, rgb, hands, fps, point, pinch, segment, control, frame_epoch, captured_at = latest[:10]
            self.last_hand_time = captured_at
            preview = Image.fromarray(rgb)
            preview.thumbnail(PREVIEW_SIZE)
            self.preview_photo = ImageTk.PhotoImage(preview)
            self.preview.configure(image=self.preview_photo, text="")
            face_blocks = bool(safety and (safety.facial.blocked or safety.release_required))
            if not pinch and not face_blocks and not getattr(self, "facial_release_wait", False):
                self.gesture_ready = True
            valid_control = (enabled and epoch == frame_epoch and 0 <= now - captured_at <= 0.5
                             and (len(latest) <= 10 or not safety or latest[10].revision == safety.revision))
            self._control_feedback(control if valid_control else ControlState())
            if (self.paused or self.source == "mouse" or self.dialog_open or not self.gesture_ready
                    or not valid_control or face_blocks):
                self.gesture.reset()
                if self.source == "gesture":
                    self.end_stroke()
                self.canvas.itemconfigure(self.cursor, state="hidden")
            else:
                if segment != self.gesture_segment:
                    if self.source == "gesture":
                        self.end_stroke()
                    self.gesture_segment = segment
                if control.blocked or len(hands) != 1:
                    if self.source == "gesture":
                        self.end_stroke()
                    self.canvas.itemconfigure(self.cursor, state="hidden")
                elif point:
                    viewport = self._viewport()
                    x, y = viewport.normalized_to_canvas(*point)
                    board_point = self.point(x, y)
                    if board_point is None:
                        if self.source == "gesture":
                            self.end_stroke()
                        self.canvas.itemconfigure(self.cursor, state="hidden")
                    else:
                        r = max(6, self.width.get() * viewport.scale / 2)
                        self.canvas.coords(self.cursor, x - r, y - r, x + r, y + r)
                        self.canvas.itemconfigure(self.cursor, state="normal", outline="#ef476f" if pinch else "#159b70")
                        if pinch:
                            self._draw(board_point, "gesture")
                        elif self.source == "gesture":
                            self.end_stroke()
                else:
                    if self.source == "gesture":
                        self.end_stroke()
                    self.canvas.itemconfigure(self.cursor, state="hidden")
            if self.paused:
                state = "Gestos pausados"
            elif face_blocks:
                state = ("Solte a pinça para voltar ao desenho" if not self.facial_state.blocked
                         else "Zoom facial · controles das mãos suspensos")
            elif valid_control and control.mode == "arming_color":
                state = "Joinha reconhecido · ativando cores"
            elif valid_control and control.color_mode:
                state = "Modo cores · mostre a quantidade de dedos"
            elif valid_control and control.mode.startswith("clear"):
                state = "DUAS mãos abertas · controle de limpeza"
            elif len(hands) == 2:
                state = "Duas mãos · mostre só uma para desenhar ou escolher cor"
            else:
                state = "Modo desenho · pinça para riscar" if hands else "Mostre uma mão inteira à câmera"
            self.hand_status.set(state)
        if now - self.last_hand_time > 0.5:
            if self.source == "gesture":
                self.end_stroke()
                self.gesture.reset()
            self.canvas.itemconfigure(self.cursor, state="hidden")
            self._control_feedback(ControlState())
        self.root.after(30, self._tick)

    def _key(self, event):
        if isinstance(event.widget, (tk.Spinbox, tk.Entry)) or event.state & 0x4:
            return
        key = event.keysym.lower()
        if key == "space" and isinstance(event.widget, tk.Button):
            # O botão focado já responde a Espaço pelo binding nativo do Tk.
            return
        if key in "12345" and len(key) == 1:
            self.select_color(int(key) - 1)
        elif key == "e": self.toggle_eraser()
        elif key == "b":
            if self.eraser: self.toggle_eraser()
        elif key == "z": self.undo()
        elif key == "s": self.save()
        elif key == "c": self.clear()
        elif key == "space": self.pause()
        elif key in ("plus", "equal", "kp_add"): self.width.set(min(40, self.width.get() + 2))
        elif key in ("minus", "kp_subtract"): self.width.set(max(2, self.width.get() - 2))
        elif key == "escape": self.close()
        elif key == "f1": self.show_help()

    def close(self):
        self.end_stroke()
        if self.board.dirty:
            with self.dialog():
                answer = messagebox.askyesnocancel("Fechar lousa", "Salvar o desenho em PNG antes de sair?", parent=self.root)
            if answer is None or (answer and not self.save()):
                return
        self.shutdown()

    def shutdown(self):
        if self.closed:
            return
        self.closed = True
        workers = self.retired + ([self.worker] if self.worker else [])
        for worker in workers:
            worker.stop()
        for worker in workers:
            worker.join(timeout=2)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="Lousa virtual com webcam e mouse")
    parser.add_argument("--camera", type=int, default=0, help="Índice da câmera (padrão: 0)")
    parser.add_argument("--no-camera", action="store_true", help="Iniciar só com mouse, sem abrir a webcam")
    parser.add_argument("--diagnose", action="store_true", help="Testar câmera e detector sem salvar imagens")
    parser.add_argument("--smoke-seconds", type=float, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 0 <= args.camera <= 9:
        parser.error("--camera deve estar entre 0 e 9")
    if args.diagnose:
        result = diagnose(args.camera, ROOT / "models" / "hand_landmarker.task")
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["frames"] > 0 and not result["error"] and result["closed"] else 1
    root = tk.Tk()
    app = App(root, args.camera, args.no_camera)
    if args.smoke_seconds > 0:
        root.after(int(args.smoke_seconds * 1000), app.shutdown)
    root.mainloop()
    return 0
