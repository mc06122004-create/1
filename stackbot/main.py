"""
Stack Bot — Автоматический бот для браузерной игры Stack ("Башенки")
Версия: 1.1.2 (Top 2-Block Dynamic Edge-Matching & Cursor Click)
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


class StackBotEngineV112:
    """Геометрический движок версии 1.1.2."""
    def __init__(self):
        self.score_count = 0
        self.last_click_time = 0
        self.prev_moving_x = None
        self.direction = 1  # 1 — вправо, -1 — влево

    def process_frame(self, frame_bgr):
        if frame_bgr is None or frame_bgr.size == 0:
            return None, False, {"score": self.score_count, "status": "Нет кадра"}

        debug_frame = frame_bgr.copy()
        height, width, _ = frame_bgr.shape

        # Переводим в HSV/Gray для нахождения контрастных блоков
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        
        # Адаптивный порог для выделения блоков на темном фоне
        _, thresh = cv2.threshold(gray, 55, 255, cv2.THRESH_BINARY)
        
        # Морфология для удаления мелкого шума
        kernel = np.ones((3, 3), np.uint8)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        rectangles = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 150:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            # Отсекаем не пропорциональные мелкие детали
            if w > h * 1.1:
                rectangles.append((x, y, w, h))

        should_click = False
        status_text = "Поиск верхнего блока..."

        if len(rectangles) >= 2:
            # Сортируем все найденные блоки строго по Y (сверху вниз: от меньшего Y к большему Y)
            rectangles.sort(key=lambda r: r[1])

            # Самый ВЕРХНИЙ блок в области — это всегда летящий (moving_platform)
            moving_platform = rectangles[0]
            # ВТОРОЙ сверху блок — это опорный под ним (base_platform)
            base_platform = rectangles[1]

            mx, my, mw, mh = moving_platform
            bx, by, bw, bh = base_platform

            # Ограничиваем: опорный блок действительно должен находиться строго ПОД летящим
            if by >= my + mh - 5:
                # Координаты граней
                m_left, m_right = mx, mx + mw
                b_left, b_right = bx, bx + bw

                m_center = mx + mw / 2.0
                b_center = bx + bw / 2.0

                # Определяем направление движения летящей платформы
                if self.prev_moving_x is not None:
                    diff = m_center - self.prev_moving_x
                    if abs(diff) > 0.15:
                        self.direction = 1 if diff > 0 else -1
                self.prev_moving_x = m_center

                # Рисуем линии на отладочном экране
                # Зеленый — Опорный блок (который под ним)
                cv2.rectangle(debug_frame, (bx, by), (bx + bw, by + bh), (0, 255, 0), 2)
                cv2.line(debug_frame, (b_left, 0), (b_left, height), (0, 255, 0), 1)
                cv2.line(debug_frame, (b_right, 0), (b_right, height), (0, 255, 0), 1)

                # Синий — Движущийся летящий блок
                cv2.rectangle(debug_frame, (mx, my), (mx + mw, my + mh), (255, 150, 0), 2)
                cv2.line(debug_frame, (m_left, 0), (m_left, height), (255, 255, 0), 1)
                cv2.line(debug_frame, (m_right, 0), (m_right, height), (255, 255, 0), 1)

                # Вычисляем расхождение центров и граней
                center_diff = abs(b_center - m_center)
                status_text = f"Смещение граней: {center_diff:.1f}px"

                now = time.time()
                if (now - self.last_click_time) > 0.32:
                    # Идеальное условие соприкосновения граней: смещение не более 2 пикселей
                    if center_diff <= 2.2:
                        should_click = True
                        self.last_click_time = now
                        self.score_count += 1

        return debug_frame, should_click, {"score": self.score_count, "status": status_text}


class StackBotVisualApp:
    def __init__(self, root):
        self.root = root
        self.root.title("StackBot v1.1.2 — Perfect Edge Matching")
        self.root.geometry("440x620")
        self.root.wm_attributes("-topmost", True)
        
        self.engine = StackBotEngineV112()
        self.is_running = False
        self.running_loop = True

        self.use_cursor_click = tk.BooleanVar(value=True) # По умолчанию клик в позицию курсора!
        self.capture_area = {"top": 150, "left": 150, "width": 380, "height": 480}
        self.photo = None

        self.build_ui()
        self.bind_hotkeys()

        self.worker_thread = threading.Thread(target=self.capture_loop, daemon=True)
        self.worker_thread.start()

    def build_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_lbl = ttk.Label(main_frame, text="StackBot v1.1.2 (Top 2-Block Tracking)", font=("Segoe UI", 10, "bold"))
        title_lbl.pack(anchor=tk.W, pady=(0, 5))

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=5)

        self.btn_toggle = ttk.Button(btn_frame, text="Старт Бот (F6)", command=self.toggle_bot)
        self.btn_toggle.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))

        ttk.Button(btn_frame, text="Выделить область", command=self.start_visual_calibration).pack(side=tk.RIGHT, expand=True, fill=tk.X)

        # Режим клика
        chk_cursor = ttk.Checkbutton(main_frame, text="Кликать строго в текущую позицию курсора мыши", variable=self.use_cursor_click)
        chk_cursor.pack(anchor=tk.W, pady=3)

        self.status_var = tk.StringVar(value="Статус: Остановлен")
        self.status_lbl = ttk.Label(main_frame, textvariable=self.status_var, font=("Segoe UI", 9, "bold"), foreground="darkgreen")
        self.status_lbl.pack(anchor=tk.W, pady=3)

        self.score_var = tk.StringVar(value="Этажей построено: 0")
        ttk.Label(main_frame, textvariable=self.score_var, font=("Consolas", 10, "bold")).pack(anchor=tk.W, pady=2)

        preview_frame = ttk.LabelFrame(main_frame, text=" Монитор граней (Верхние 2 кирпичика) ", padding="5")
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.canvas = tk.Canvas(preview_frame, bg="black")
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
                        if self.use_cursor_click.get():
                            # Клик прямо туда, где находится курсор мыши
                            pyautogui.click()
                        else:
                            # Клик в центр области
                            cx = self.capture_area["left"] + self.capture_area["width"] // 2
                            cy = self.capture_area["top"] + self.capture_area["height"] // 2
                            pyautogui.click(cx, cy)

                    self.score_var.set(f"Этажей построено: {telemetry['score']}")
                    self.render_canvas(debug_frame)

                except Exception as e:
                    print(f"[Capture Error]: {e}")

                dt = time.time() - t0
                if dt < 0.015:
                    time.sleep(0.015 - dt)

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
    app = StackBotVisualApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
