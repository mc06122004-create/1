"""
Stack Bot — Автоматический бот для браузерной игры Stack ("Башенки")
Версия: 1.0.4 (Stable MSS Screen Crop Edition)
Платформа: Windows 10 / 11 (x64)

Исправления в версии 1.0.4:
- Захват цветной картинки через MSS (без черных экранов и багов PrintWindow).
- Выделение интерактивной зоны калибровки мышкой (окно бота автоматически сворачивается на секунду и возвращается).
- Бот считывает только ту область экрана, которую вы выделили мышкой.
- Если окно бота не перекрывает выделенную рамкой игру, самозахват полностью отсутствует!
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
from PIL import Image, ImageTk

pyautogui.PAUSE = 0.0
pyautogui.FAILSAFE = True


class StackBotEngineV10:
    """Геометрический движок версии 1.0.4."""
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
            return None, False, {"status": "Нет изображения"}

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
            "platform_x": None,
            "base_x": None,
            "speed": self.current_speed,
            "direction": self.platform_direction,
            "distance": None,
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

            telemetry["platform_x"] = platform_center_x
            telemetry["base_x"] = base_center_x
            telemetry["speed"] = self.current_speed
            telemetry["direction"] = self.platform_direction
            telemetry["distance"] = distance_to_center
            telemetry["score"] = self.score_count

            moving_towards = (distance_to_center > 0 and self.platform_direction == 1) or                              (distance_to_center < 0 and self.platform_direction == -1)

            threshold = max(3.0, self.current_speed * click_offset_factor)
            
            if moving_towards and abs(distance_to_center) <= threshold:
                if (now - self.last_click_time) > 0.35:
                    should_click = True
                    self.last_click_time = now
                    self.score_count += 1

            cv2.rectangle(frame_bgr, (bx, by), (bx + bw, by + bh), (0, 255, 0), 2)
            cv2.rectangle(frame_bgr, (px, py), (px + pw, py + ph), (255, 0, 0), 2)
            cv2.circle(frame_bgr, (int(base_center_x), int(by + bh/2)), 4, (0, 0, 255), -1)
        else:
            self.lost_frames_count += 1
            if self.lost_frames_count > 15:
                telemetry["status"] = "Поиск платформы..."

        return frame_bgr, should_click, telemetry


class StackBotAppV10:
    """Интерфейс Stack Bot v1.0.4 с интерактивной зоной захвата."""
    def __init__(self, root):
        self.root = root
        self.root.title("Stack Bot v1.0.4 — Stable Crop Edition")
        self.root.geometry("980x720")
        self.root.minsize(850, 600)

        self.engine = StackBotEngineV10()
        self.is_running = False
        self.running_loop = True

        self.capture_area = {"top": 150, "left": 150, "width": 450, "height": 650}
        self.offset_var = tk.DoubleVar(value=0.6)
        
        self.photo = None

        self.build_ui()
        self.bind_hotkeys()

        self.worker_thread = threading.Thread(target=self.capture_loop, daemon=True)
        self.worker_thread.start()

    def build_ui(self):
        main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left_frame = ttk.Frame(main_pane, padding="10")
        main_pane.add(left_frame, weight=1)

        title_lbl = ttk.Label(left_frame, text="Stack Bot v1.0.4", font=("Segoe UI", 14, "bold"))
        title_lbl.pack(anchor=tk.W, pady=(0, 10))

        self.btn_toggle = ttk.Button(left_frame, text="Старт Бот (F6)", command=self.toggle_bot)
        self.btn_toggle.pack(fill=tk.X, pady=5)

        ttk.Button(left_frame, text="Выделить область мышкой", command=self.start_visual_calibration).pack(fill=tk.X, pady=5)

        self.status_var = tk.StringVar(value="Статус: Остановлен")
        status_lbl = ttk.Label(left_frame, textvariable=self.status_var, font=("Segoe UI", 10, "bold"), foreground="darkgreen")
        status_lbl.pack(anchor=tk.W, pady=10)

        settings_group = ttk.LabelFrame(left_frame, text=" Тонкая настройка ", padding="10")
        settings_group.pack(fill=tk.X, pady=5)

        ttk.Label(settings_group, text="Коэффициент упреждения:").pack(anchor=tk.W)
        offset_slider = ttk.Scale(settings_group, from_=0.2, to=1.2, variable=self.offset_var, orient=tk.HORIZONTAL)
        offset_slider.pack(fill=tk.X, pady=5)

        telemetry_group = ttk.LabelFrame(left_frame, text=" Телеметрия ", padding="10")
        telemetry_group.pack(fill=tk.X, pady=10)

        self.lbl_telemetry = ttk.Label(
            telemetry_group, 
            text="Этажей построено: 0\nПлатформа X: --\nОснование X: --\nДистанция: --\nСкорость: -- px/f\nСостояние: Ожидание", 
            font=("Consolas", 9),
            justify=tk.LEFT
        )
        self.lbl_telemetry.pack(anchor=tk.W)

        help_group = ttk.LabelFrame(left_frame, text=" Горячие клавиши ", padding="10")
        help_group.pack(fill=tk.X, pady=5)
        ttk.Label(help_group, text="F6 — Старт / Пауза\nEsc — Аварийный стоп", font=("Segoe UI", 9)).pack(anchor=tk.W)

        right_frame = ttk.LabelFrame(main_pane, text=" Игровой монитор области ", padding="5")
        main_pane.add(right_frame, weight=3)

        self.canvas = tk.Canvas(right_frame, bg="black")
        self.canvas.pack(fill=tk.BOTH, expand=True)

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
            self.btn_toggle.config(text="Пауза Бот (F6)")
        else:
            self.status_var.set("Статус: Пауза")
            self.btn_toggle.config(text="Старт Бот (F6)")

    def emergency_stop(self):
        if self.is_running:
            self.is_running = False
            self.status_var.set("Статус: АВАРИЙНЫЙ СТОП (Esc)")
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
                messagebox.showinfo("Успех", f"Область зафиксирована:\nX: {x1}, Y: {y1}, W: {w}, H: {h}")
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

                    current_offset = self.offset_var.get()
                    processed_frame, should_click, telemetry = self.engine.process_frame(frame_bgr, current_offset)

                    if self.is_running and should_click and telemetry["status"] != "Поиск платформы...":
                        pyautogui.click()

                    self.update_telemetry(telemetry)
                    self.render_canvas(processed_frame)

                except Exception as e:
                    print(f"[Capture Error]: {e}")

                dt = time.time() - t0
                if dt < 0.02:
                    time.sleep(0.02 - dt)

    def update_telemetry(self, t):
        score = t['score']
        p_x = f"{t['platform_x']:.1f}" if t['platform_x'] is not None else "--"
        b_x = f"{t['base_x']:.1f}" if t['base_x'] is not None else "--"
        dist = f"{t['distance']:.1f}" if t['distance'] is not None else "--"
        spd = f"{t['speed']:.1f}"
        status = t['status']

        text = (f"Этажей построено: {score}\n"
                f"Платформа X:      {p_x}\n"
                f"Основание X:      {b_x}\n"
                f"Дистанция:        {dist}\n"
                f"Скорость:         {spd} px/f\n"
                f"Состояние:        {status}")
        self.lbl_telemetry.config(text=text)

    def render_canvas(self, frame_bgr):
        if frame_bgr is None:
            return
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(frame_rgb)

        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()

        if cw > 10 and ch > 10:
            img = img.resize((cw, ch), Image.Resampling.LANCZOS)

        self.photo = ImageTk.PhotoImage(image=img)
        self.canvas.create_image(0, 0, image=self.photo, anchor=tk.NW)

    def on_close(self):
        self.running_loop = False
        try:
            keyboard.unhook_all()
        except:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = StackBotAppV10(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
