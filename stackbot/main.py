"""
Stack Bot — Автоматический бот для браузерной игры Stack ("Башенки")
Версия: 1.1.5 (Ultra-Stable Non-Flicker Edition)
Платформа: Windows 10 / 11 (x64)
"""

import sys
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import mss
import cv2
import numpy as np
import pyautogui
import keyboard
from PIL import Image, ImageTk

pyautogui.PAUSE = 0.0
pyautogui.FAILSAFE = False


class StackBotEngineV115:
    """Сверхстабильный движок без ложных срабатываний."""
    def __init__(self):
        self.score_count = 0
        self.last_click_time = 0
        self.last_mx = None

    def process_frame(self, frame_bgr):
        if frame_bgr is None or frame_bgr.size == 0:
            return None, False, {"score": self.score_count, "status": "Нет кадра"}

        debug_frame = frame_bgr.copy()
        height, width, _ = frame_bgr.shape

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 60, 255, cv2.THRESH_BINARY)
        
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        rectangles = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 180:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            if w > h * 1.1:
                rectangles.append((x, y, w, h))

        should_click = False
        status_text = "Ожидание блока..."

        if len(rectangles) >= 2:
            rectangles.sort(key=lambda r: r[1])

            moving = rectangles[0]
            base = rectangles[1]

            mx, my, mw, mh = moving
            bx, by, bw, bh = base

            if by >= my + mh - 8 and abs(mw - bw) < bw * 0.5:
                m_center = mx + mw / 2.0
                b_center = bx + bw / 2.0

                # Рисуем контуры для контроля
                cv2.rectangle(debug_frame, (bx, by), (bx + bw, by + bh), (0, 255, 0), 2)
                cv2.rectangle(debug_frame, (mx, my), (mx + mw, my + mh), (255, 150, 0), 2)

                diff = abs(b_center - m_center)
                status_text = f"Смещение: {diff:.1f}px"

                now = time.time()
                # Защита от дребезга и повторных кликов на одном этаже
                if (now - self.last_click_time) > 0.3:
                    # Идеальное совпадение центров с минимальным допуском
                    if diff <= 1.2:
                        should_click = True
                        self.last_click_time = now
                        self.score_count += 1

        return debug_frame, should_click, {"score": self.score_count, "status": status_text}


class StackBotVisualApp:
    def __init__(self, root):
        self.root = root
        self.root.title("StackBot v1.1.5")
        self.root.geometry("440x560")
        self.root.wm_attributes("-topmost", True)
        
        self.engine = StackBotEngineV115()
        self.is_running = False
        self.running_loop = True

        self.capture_area = {"top": 150, "left": 150, "width": 380, "height": 450}
        self.latest_frame = None
        self.photo = None

        self.build_ui()
        self.bind_hotkeys()

        # Поток захвата экрана
        self.worker_thread = threading.Thread(target=self.capture_loop, daemon=True)
        self.worker_thread.start()

        # Отдельный плавный поток отрисовки интерфейса (убирает мигание)
        self.update_gui_loop()

    def build_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_lbl = ttk.Label(main_frame, text="StackBot v1.1.5 (Non-Flicker)", font=("Segoe UI", 10, "bold"))
        title_lbl.pack(anchor=tk.W, pady=(0, 5))

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=5)

        self.btn_toggle = ttk.Button(btn_frame, text="Старт Бот (F6)", command=self.toggle_bot)
        self.btn_toggle.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))

        ttk.Button(btn_frame, text="Выделить область", command=self.start_visual_calibration).pack(side=tk.RIGHT, expand=True, fill=tk.X)

        self.status_var = tk.StringVar(value="Статус: Остановлен")
        self.status_lbl = ttk.Label(main_frame, textvariable=self.status_var, font=("Segoe UI", 9, "bold"), foreground="darkgreen")
        self.status_lbl.pack(anchor=tk.W, pady=3)

        self.score_var = tk.StringVar(value="Этажей построено: 0")
        ttk.Label(main_frame, textvariable=self.score_var, font=("Consolas", 10, "bold")).pack(anchor=tk.W, pady=2)

        preview_frame = ttk.LabelFrame(main_frame, text=" Монитор стабильности ", padding="5")
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.canvas = tk.Canvas(preview_frame, bg="black", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="F6 — Старт/Пауза | Esc — Стоп", font=("Segoe UI", 8), foreground="gray").pack(anchor=tk.W, pady=(5, 0))

    def bind_hotkeys(self):
        try:
            keyboard.add_hotkey('F6', self.toggle_bot)
            keyboard.add_hotkey('Esc', self.emergency_stop)
        except Exception as e:
            print(f"[Hotkeys Error]: {e}")

    def toggle_bot(self):
        self.is_running = not self.is_running
        if self.is_running:
            self.status_var.set("Статус: РАБОТАЕТ")
            self.status_lbl.config(foreground="blue")
            self.btn_toggle.config(text="Пауза Бот (F6)")
        else:
            self.status_var.set("Статус: Пауза")
            self.status_lbl.config(foreground="darkgreen")
            self.btn_toggle.config(text="Старт Бот (F6)")

    def emergency_stop(self):
        if self.is_running:
            self.is_running = False
            self.status_var.set("Статус: СТОП")
            self.status_lbl.config(foreground="red")
            self.btn_toggle.config(text="Старт Бот (F6)")

    def start_visual_calibration(self):
        self.root.withdraw()
        time.sleep(0.3)

        calib_overlay = tk.Toplevel(self.root)
        calib_overlay.attributes("-fullscreen", True)
        calib_overlay.attributes("-alpha", 0.35)
        calib_overlay.config(cursor="cross")

        canvas_sel = tk.Canvas(calib_overlay, cursor="cross", bg="black")
        canvas_sel.pack(fill=tk.BOTH, expand=True)

        start_x = [0]
        start_y = [0]
        rect_id = [None]

        def on_button_press(event):
            start_x[0] = event.x
            start_y[0] = event.y
            rect_id[0] = canvas_sel.create_rectangle(start_x[0], start_y[0], 1, 1, outline='red', width=2)

        def on_move_press(event):
            cur_x, cur_y = event.x, event.y
            canvas_sel.coords(rect_id[0], start_x[0], start_y[0], cur_x, cur_y)

        def on_button_release(event):
            end_x, end_y = event.x, event.y
            x1, y1 = min(start_x[0], end_x), min(start_y[0], end_y)
            x2, y2 = max(start_x[0], end_x), max(start_y[0], end_y)
            w, h = x2 - x1, y2 - y1

            if w > 30 and h > 30:
                self.capture_area = {"top": y1, "left": x1, "width": w, "height": h}
                messagebox.showinfo("Успех", f"Область сохранена:\nX: {x1}, Y: {y1}, W: {w}, H: {h}")
            else:
                messagebox.showwarning("Warning", "Area is too small! Please select a larger region.")

            calib_overlay.destroy()
            self.root.deiconify()

        canvas_sel.bind("<ButtonPress-1>", on_button_press)
        canvas_sel.bind("<B1-Motion>", on_move_press)
        canvas_sel.bind("<ButtonRelease-1>", on_button_release)

    def capture_loop(self):
        with mss.mss() as sct:
            while self.running_loop:
                t0 = time.time()
                try:
                    screenshot = sct.grab(self.capture_area)
                    frame = np.array(screenshot)
                    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

                    debug_frame, should_click, telemetry = self.engine.process_frame(frame_bgr)

                    if self.is_running and should_click:
                        pyautogui.click()

                    self.score_var.set(f"Этажей построено: {telemetry['score']}")
                    self.latest_frame = debug_frame

                except Exception as e:
                    print(f"[Capture Error]: {e}")

                dt = time.time() - t0
                if dt < 0.015:
                    time.sleep(0.015 - dt)

    def update_gui_loop(self):
        """Плавное обновление интерфейса без мерцания раз в 30 мс."""
        if self.running_loop:
            if self.latest_frame is not None:
                try:
                    frame_rgb = cv2.cvtColor(self.latest_frame, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(frame_rgb)
                    cw = self.canvas.winfo_width()
                    ch = self.canvas.winfo_height()
                    if cw > 10 and ch > 10:
                        img = img.resize((cw, ch), Image.Resampling.NEAREST)
                    self.photo = ImageTk.PhotoImage(image=img)
                    self.canvas.delete("all")
                    self.canvas.create_image(0, 0, image=self.photo, anchor=tk.NW)
                except Exception:
                    pass
            self.root.after(30, self.update_gui_loop)

    def on_close(self):
        self.running_loop = False
        try:
            keyboard.unhook_all()
        except:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = StackBotVisualApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
