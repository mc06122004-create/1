"""
Stack Bot — Автоматический бот для браузерной игры Stack ("Башенки")
Версия: 1.0.9 (Perfect Edge-Match Edition)
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

pyautogui.PAUSE = 0.0
pyautogui.FAILSAFE = False


class StackBotEngineV109:
    """Движок идеального соприкосновения краев платформы и основания."""
    def __init__(self):
        self.score_count = 0
        self.last_click_time = 0
        self.prev_platform_x = None
        self.direction = 1

    def process_frame(self, frame_bgr):
        if frame_bgr is None or frame_bgr.size == 0:
            return False, {"score": self.score_count, "status": "Нет кадра"}

        height, width, _ = frame_bgr.shape
        
        # Переводим в градации серого и находим контрастные блоки
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 60, 255, cv2.THRESH_BINARY)
        
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        rectangles = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 200:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            # Отбираем только горизонтальные игровые блоки
            if w > h * 1.1:
                rectangles.append((x, y, w, h))

        should_click = False

        if len(rectangles) >= 2:
            # Сортируем снизу вверх по координате Y
            rectangles.sort(key=lambda r: r[1], reverse=True)
            
            base = rectangles[0]       # Нижнее основание
            platform = rectangles[1]   # Летящая платформа

            bx, by, bw, bh = base
            px, py, pw, ph = platform

            base_left = bx
            base_right = bx + bw
            base_center = bx + bw / 2.0

            plat_left = px
            plat_right = px + pw
            plat_center = px + pw / 2.0

            # Определяем направление движения платформы
            if self.prev_platform_x is not None:
                diff = plat_center - self.prev_platform_x
                if abs(diff) > 0.2:
                    self.direction = 1 if diff > 0 else -1
            self.prev_platform_x = plat_center

            # Условие идеального соприкосновения краев:
            # Кликаем, когда центр летящей платформы максимально близок к центру основания
            distance_to_center = abs(base_center - plat_center)

            now = time.time()
            if (now - self.last_click_time) > 0.35:
                # Если расстояние центров сократилось до минимума (идеальное перекрытие)
                if distance_to_center <= 2.5:
                    should_click = True
                    self.last_click_time = now
                    self.score_count += 1

        return should_click, {"score": self.score_count, "status": "Режим ювелирного клика"}


class StackBotFloatingPanel:
    def __init__(self, root):
        self.root = root
        self.root.title("StackBot v1.0.9")
        self.root.wm_attributes("-topmost", True)
        
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        panel_w, panel_h = 280, 210
        pos_x = screen_w - panel_w - 40
        pos_y = screen_h - panel_h - 100
        self.root.geometry(f"{panel_w}x{panel_h}+{pos_x}+{pos_y}")
        self.root.resizable(False, False)

        self.engine = StackBotEngineV109()
        self.is_running = False
        self.running_loop = True

        self.capture_area = {"top": 150, "left": 150, "width": 400, "height": 550}
        
        self.build_ui()
        self.bind_hotkeys()

        self.worker_thread = threading.Thread(target=self.capture_loop, daemon=True)
        self.worker_thread.start()

    def build_ui(self):
        style = ttk.Style()
        style.theme_use('clam')

        main_frame = ttk.Frame(self.root, padding="8")
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_lbl = ttk.Label(main_frame, text="Stack Bot v1.0.9 (Edge-Match)", font=("Segoe UI", 9, "bold"))
        title_lbl.pack(anchor=tk.W, pady=(0, 4))

        self.btn_toggle = ttk.Button(main_frame, text="Старт Бот (F6)", command=self.toggle_bot)
        self.btn_toggle.pack(fill=tk.X, pady=3)

        ttk.Button(main_frame, text="Выделить область мышкой", command=self.start_visual_calibration).pack(fill=tk.X, pady=3)

        self.status_var = tk.StringVar(value="Статус: Остановлен")
        self.status_lbl = ttk.Label(main_frame, textvariable=self.status_var, font=("Segoe UI", 9, "bold"), foreground="darkgreen")
        self.status_lbl.pack(anchor=tk.W, pady=(5, 2))

        self.score_var = tk.StringVar(value="Этажей построено: 0")
        ttk.Label(main_frame, textvariable=self.score_var, font=("Consolas", 9)).pack(anchor=tk.W, pady=2)

        ttk.Label(main_frame, text="F6 — Старт/Пауза | Esc — Стоп", font=("Segoe UI", 8), foreground="gray").pack(anchor=tk.W, pady=(4, 0))

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

                    should_click, telemetry = self.engine.process_frame(frame_bgr)

                    if self.is_running and should_click:
                        cx = self.capture_area["left"] + self.capture_area["width"] // 2
                        cy = self.capture_area["top"] + self.capture_area["height"] // 2
                        pyautogui.click(cx, cy)

                    self.score_var.set(f"Этажей построено: {telemetry['score']}")

                except Exception as e:
                    print(f"[Capture Error]: {e}")

                dt = time.time() - t0
                if dt < 0.015:
                    time.sleep(0.015 - dt)

    def on_close(self):
        self.running_loop = False
        try:
            keyboard.unhook_all()
        except:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = StackBotFloatingPanel(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
