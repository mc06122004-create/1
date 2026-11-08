"""
Stack Bot — Автоматический бот для браузерной игры Stack ("Башенки")
Версия: 1.0.3 (Window-Target Capture Edition)
Платформа: Windows 10 / 11 (x64)

Новое в версии 1.0.3:
- Захват конкретного окна по его заголовку (никакого самозахвата и мигания!).
- Кнопка "Обновить список окон" для поиска игры (браузера).
- Бот больше не зависит от координат экрана: окно игры может двигаться или перекрываться.
"""

import sys
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import cv2
import numpy as np
import pyautogui
import keyboard
from collections import deque
from PIL import Image, ImageTk

# Импорты для работы с окнами Windows
import win32gui
import win32ui
import win32con
import win32api
import ctypes

pyautogui.PAUSE = 0.0
pyautogui.FAILSAFE = True


class StackBotEngineV10:
    """Геометрический движок версии 1.0.3."""
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
            return None, False, {"status": "Нет кадра окна"}

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
            if area < 200:
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

            moving_towards = (distance_to_center > 0 and self.platform_direction == 1) or \
                             (distance_to_center < 0 and self.platform_direction == -1)

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
    """Интерфейс Stack Bot v1.0.3 с выбором целевого окна."""
    def __init__(self, root):
        self.root = root
        self.root.title("Stack Bot v1.0.3 — Window Target Edition")
        self.root.geometry("980x720")
        self.root.minsize(850, 600)

        self.engine = StackBotEngineV10()
        self.is_running = False
        self.running_loop = True

        self.offset_var = tk.DoubleVar(value=0.6)
        self.target_hwnd = None
        self.window_titles_map = {}

        self.photo = None

        self.build_ui()
        self.bind_hotkeys()
        self.refresh_window_list()

        self.worker_thread = threading.Thread(target=self.capture_loop, daemon=True)
        self.worker_thread.start()

    def build_ui(self):
        main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left_frame = ttk.Frame(main_pane, padding="10")
        main_pane.add(left_frame, weight=1)

        title_lbl = ttk.Label(left_frame, text="Stack Bot v1.0.3", font=("Segoe UI", 14, "bold"))
        title_lbl.pack(anchor=tk.W, pady=(0, 10))

        self.btn_toggle = ttk.Button(left_frame, text="Старт Бот (F6)", command=self.toggle_bot)
        self.btn_toggle.pack(fill=tk.X, pady=5)

        target_group = ttk.LabelFrame(left_frame, text=" Выбор игрового окна ", padding="10")
        target_group.pack(fill=tk.X, pady=5)

        ttk.Label(target_group, text="Целевое окно (Браузер / Игра):").pack(anchor=tk.W)
        
        self.window_combo = ttk.Combobox(target_group, state="readonly")
        self.window_combo.pack(fill=tk.X, pady=5)
        self.window_combo.bind("<<ComboboxSelected>>", self.on_window_selected)

        ttk.Button(target_group, text="Обновить список окон", command=self.refresh_window_list).pack(fill=tk.X, pady=2)

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

        right_frame = ttk.LabelFrame(main_pane, text=" Игровой монитор захвата окна ", padding="5")
        main_pane.add(right_frame, weight=3)

        self.canvas = tk.Canvas(right_frame, bg="black")
        self.canvas.pack(fill=tk.BOTH, expand=True)

    def refresh_window_list(self):
        self.window_titles_map.clear()
        titles = []

        def enum_windows_callback(hwnd, extra):
            if win32gui.IsWindowVisible(hwnd):
                text = win32gui.GetWindowText(hwnd)
                if text and len(text.strip()) > 0:
                    if text not in ["Default IME", "MSCTFIME UI", "GDI+ Window"]:
                        titles.append(text)
                        self.window_titles_map[text] = hwnd

        win32gui.EnumWindows(enum_windows_callback, None)
        titles = sorted(list(set(titles)))
        self.window_combo['values'] = titles
        
        for t in titles:
            if any(browser in t.lower() for browser in ["chrome", "edge", "firefox", "opera", "brave", "stack"]):
                self.window_combo.set(t)
                self.target_hwnd = self.window_titles_map[t]
                break

    def on_window_selected(self, event):
        selected_title = self.window_combo.get()
        if selected_title in self.window_titles_map:
            self.target_hwnd = self.window_titles_map[selected_title]

    def capture_window_bgr(self, hwnd):
        try:
            if not hwnd or not win32gui.IsWindow(hwnd):
                return None
            
            left, top, right, bottom = win32gui.GetClientRect(hwnd)
            width = right - left
            height = bottom - top

            if width <= 0 or height <= 0:
                return None

            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()

            save_bitmap = win32ui.CreateBitmap()
            save_bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(save_bitmap)

            result = ctypes_print_window(hwnd, save_dc.GetSafeHdc())

            signed_ints = save_bitmap.GetBitmapBits(True)
            img = np.frombuffer(signed_ints, dtype='uint8')
            img.shape = (height, width, 4)

            win32gui.ReleaseDC(hwnd, hwnd_dc)
            win32gui.DeleteObject(save_bitmap.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()

            frame_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            return frame_bgr

        except Exception as e:
            return None

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

    def capture_loop(self):
        while self.running_loop:
            t0 = time.time()
            try:
                if self.target_hwnd:
                    frame_bgr = self.capture_window_bgr(self.target_hwnd)
                    if frame_bgr is not None:
                        current_offset = self.offset_var.get()
                        processed_frame, should_click, telemetry = self.engine.process_frame(frame_bgr, current_offset)

                        if self.is_running and should_click and telemetry["status"] != "Поиск платформы...":
                            pyautogui.click()

                        self.update_telemetry(telemetry)
                        self.render_canvas(processed_frame)
                    else:
                        self.status_var.set("Статус: Окно не найдено / свернуто")
                else:
                    self.status_var.set("Статус: Выберите игровое окно!")

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


def ctypes_print_window(hwnd, hdc):
    user32 = ctypes.windll.user32
    return user32.PrintWindow(hwnd, hdc, 2)


if __name__ == "__main__":
    root = tk.Tk()
    app = StackBotAppV10(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
