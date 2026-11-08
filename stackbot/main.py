"""
Stack Bot — Автоматический бот для браузерной игры Stack ("Башенки")
Версия: 1.0.5 (Compact Overlay Floating Panel Edition)
Платформа: Windows 10 / 11 (x64)

Особенности версии 1.0.5:
- Компактная мини-панель (плашка) поверх всех окон.
- Никакого громоздкого интерфейса и монитора предпросмотра — самозахват физически невозможен!
- Интерактивное выделение области игры мышкой.
- Горячие клавиши (F6 — Старт/Пауза, Esc — Стоп).
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
from collections import deque

pyautogui.PAUSE = 0.0
pyautogui.FAILSAFE = True


class StackBotEngineV10:
    """Геометрический движок версии 1.0.5."""
    def __init__(self):
        self.prev_platform_x = None
        self.platform_direction = 0
        self.current_speed = 0.0
        self.last_frame_time = time.time()
        self.lost_frames_count = 0
        self.history_x = deque(maxlen=4)
        self.score_count = 0
        self.last_click_time = 0
        self.previous_base_width = None

    def process_frame(self, frame_bgr, click_offset_factor=0.6):
        if frame_bgr is None or frame_bgr.size == 0:
            return False, {"status": "Нет кадра"}

        height, width, _ = frame_bgr.shape
        now = time.time()
        dt = now - self.last_frame_time
        self.last_frame_time = now if dt > 0 else 0.033

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        thresh = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 11, 2
        )

        kernel = np.ones((3, 3), np.uint8)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        rectangles = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 250:
                continue
            
            x, y, w, h = cv2.boundingRect(cnt)
            aspect_ratio = w / float(h)
            
            if aspect_ratio > 1.05:
                rectangles.append((x, y, w, h, area))

        base_rect = None
        platform_rect = None

        if rectangles:
            rectangles.sort(key=lambda r: r[1], reverse=True)
            base_rect = rectangles[0][:4]

            bx, by, bw, bh = base_rect
            if self.previous_base_width is not None:
                if bw > self.previous_base_width * 1.5:
                    self.score_count = 0
            self.previous_base_width = bw

            for r in rectangles[1:]:
                if r[1] < base_rect[1] - 3:
                    if r[2] >= base_rect[2] * 0.3:
                        platform_rect = r[:4]
                        break

        should_click = False
        telemetry = {
            "score": self.score_count,
            "status": "Активен"
        }

        if base_rect and platform_rect:
            self.lost_frames_count = 0
            bx, by, bw, bh = base_rect
            px, py, pw, ph = platform_rect

            raw_platform_center_x = px + pw / 2.0
            self.history_x.append(raw_platform_center_x)
            platform_center_x = sum(self.history_x) / len(self.history_x)
            base_center_x = bx + bw / 2.0

            if self.prev_platform_x is not None:
                dx = platform_center_x - self.prev_platform_x
                if abs(dx) > 0.2:
                    self.platform_direction = 1 if dx > 0 else -1
                    self.current_speed = abs(dx)
            
            self.prev_platform_x = platform_center_x
            distance_to_center = base_center_x - platform_center_x

            moving_towards = (distance_to_center > 0 and self.platform_direction == 1) or \
                             (distance_to_center < 0 and self.platform_direction == -1)

            threshold = max(3.0, self.current_speed * click_offset_factor)
            
            if moving_towards and abs(distance_to_center) <= threshold:
                if (now - self.last_click_time) > 0.35:
                    should_click = True
                    self.last_click_time = now
                    self.score_count += 1
                    telemetry["score"] = self.score_count
        else:
            self.lost_frames_count += 1
            if self.lost_frames_count > 15:
                telemetry["status"] = "Поиск платформы..."

        return should_click, telemetry


class StackBotFloatingPanel:
    """Компактная плавающая мини-панель управления v1.0.5."""
    def __init__(self, root):
        self.root = root
        self.root.title("StackBot Overlay")
        
        # Делаем окно поверх всех окон, компактным без рамки Windows (или с минимальной)
        self.root.wm_attributes("-topmost", True)
        
        # Располагаем в правом нижнем углу экрана
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        panel_w, panel_h = 280, 210
        pos_x = screen_w - panel_w - 40
        pos_y = screen_h - panel_h - 100
        self.root.geometry(f"{panel_w}x{panel_h}+{pos_x}+{pos_y}")
        self.root.resizable(False, False)

        self.engine = StackBotEngineV10()
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

        # Заголовок
        title_lbl = ttk.Label(main_frame, text="Stack Bot v1.0.5 (Overlay)", font=("Segoe UI", 9, "bold"))
        title_lbl.pack(anchor=tk.W, pady=(0, 4))

        # Кнопка старта
        self.btn_toggle = ttk.Button(main_frame, text="Старт Бот (F6)", command=self.toggle_bot)
        self.btn_toggle.pack(fill=tk.X, pady=3)

        # Кнопка калибровки
        ttk.Button(main_frame, text="Выделить область мышкой", command=self.start_visual_calibration).pack(fill=tk.X, pady=3)

        # Статус
        self.status_var = tk.StringVar(value="Статус: Остановлен")
        self.status_lbl = ttk.Label(main_frame, textvariable=self.status_var, font=("Segoe UI", 9, "bold"), foreground="darkgreen")
        self.status_lbl.pack(anchor=tk.W, pady=(5, 2))

        # Счетчик этажей
        self.score_var = tk.StringVar(value="Этажей построено: 0")
        ttk.Label(main_frame, textvariable=self.score_var, font=("Consolas", 9)).pack(anchor=tk.W, pady=2)

        # Подсказка по горячим клавишам
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

                    if self.is_running and should_click and telemetry["status"] != "Поиск платформы...":
                        pyautogui.click()

                    self.score_var.set(f"Этажей построено: {telemetry['score']}")

                except Exception as e:
                    print(f"[Capture Error]: {e}")

                dt = time.time() - t0
                if dt < 0.02:
                    time.sleep(0.02 - dt)

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
