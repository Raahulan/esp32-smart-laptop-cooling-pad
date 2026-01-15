import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import math
import random
import socket
import ipaddress
from queue import Queue, Empty

import requests

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

BG_COLOR       = "#050816"
CARD_BG        = "#111827"
ACCENT_YELLOW  = "#fbbf24"
TEXT_MAIN      = "#f9fafb"
TEXT_MUTED     = "#9ca3af"
DANGER_RED     = "#f97316"
OK_GREEN       = "#22c55e"
NEON_PURPLE    = "#a855f7"
LINE_BLUE      = "#38bdf8"
LINE_ORANGE    = "#f97316"
LINE_PURPLE    = "#a855f7"

POLL_BASE_INTERVAL_MS = 700
POLL_MAX_INTERVAL_MS  = 2500
HISTORY_SECONDS       = 300
SCAN_TIMEOUT_S        = 0.35
SCAN_THREADS          = 64
SCOPE_WINDOW_S = 30.0   

DEFAULT_ESP32_URL = "http://10.94.8.43"


def hsv_to_hex(h, s, v):
    h = float(h) % 360
    s = max(0.0, min(1.0, float(s)))
    v = max(0.0, min(1.0, float(v)))
    c = v * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = v - c
    if 0 <= h < 60:
        r, g, b = c, x, 0
    elif 60 <= h < 120:
        r, g, b = x, c, 0
    elif 120 <= h < 180:
        r, g, b = 0, c, x
    elif 180 <= h < 240:
        r, g, b = 0, x, c
    elif 240 <= h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    r = int((r + m) * 255)
    g = int((g + m) * 255)
    b = int((b + m) * 255)
    return f"#{r:02x}{g:02x}{b:02x}"


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_color(c1, c2, t):
    r1, g1, b1 = hex_to_rgb(c1)
    r2, g2, b2 = hex_to_rgb(c2)
    r = int(lerp(r1, r2, t))
    g = int(lerp(g1, g2, t))
    b = int(lerp(b1, b2, t))
    return rgb_to_hex((r, g, b))


def get_local_ipv4():
    """Best-effort local IP discover without internet calls."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def normalize_base_url(text: str) -> str:
    t = text.strip()
    if not t:
        return ""
    if not t.startswith("http://") and not t.startswith("https://"):
        t = "http://" + t
    return t.rstrip("/")


class StableHttpClient:
    """
    Advanced stable HTTP:
    - persistent session
    - adaptive timeout
    - exponential backoff + jitter on failure
    """
    def __init__(self):
        self.session = requests.Session()
        self.base_url = ""
        self.lock = threading.Lock()

        self.ok_streak = 0
        self.fail_streak = 0
        self.poll_interval_ms = POLL_BASE_INTERVAL_MS
        self.timeout_s = 0.9

        self.session.headers.update({"Connection": "keep-alive"})

    def set_base_url(self, base_url: str):
        with self.lock:
            self.base_url = base_url
            self.ok_streak = 0
            self.fail_streak = 0
            self.poll_interval_ms = POLL_BASE_INTERVAL_MS
            self.timeout_s = 0.9

    def get(self, path: str, timeout=None):
        with self.lock:
            url = self.base_url + path
            to = self.timeout_s if timeout is None else timeout
        return self.session.get(url, timeout=to)

    def mark_ok(self):
        self.ok_streak += 1
        self.fail_streak = 0
        self.poll_interval_ms = max(POLL_BASE_INTERVAL_MS, int(self.poll_interval_ms * 0.88))
        self.timeout_s = max(0.7, self.timeout_s * 0.92)

    def mark_fail(self):
        self.fail_streak += 1
        self.ok_streak = 0
        self.poll_interval_ms = min(POLL_MAX_INTERVAL_MS, int(self.poll_interval_ms * 1.35) + 60)
        self.timeout_s = min(2.5, self.timeout_s * 1.18 + 0.05)

    def next_sleep_s(self):
        jitter = random.uniform(0.0, 0.10)
        return (self.poll_interval_ms / 1000.0) + jitter


class CoolingPadGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("ESP32 Smart Gaming Laptop Cooling Pad (Stable)")
        self.root.configure(bg=BG_COLOR)

        try:
            self.root.state("zoomed")
        except tk.TclError:
            self.root.attributes("-zoomed", True)

        # Networking
        self.http = StableHttpClient()
        self.connected_online = False
        self.stop_flag = False
        self.ui_queue = Queue()

        # Data history
        self.start_time = time.time()
        self.time_hist = []
        self.lm35_hist = []
        self.dhtt_hist = []

        # Analog oscilloscope buffers
        self.ir_hist = []
        self.pot_hist = []

        # UI state
        self.rgb_hue = 0.0
        self.breath_phase = 0.0
        self.heading_color_phase = 0.0
        self.mode_pulse_phase = 0.0
        self.pulse_state = False
        self.slider_dragging = False
        self.current_mode = "--"
        self.alert_visible = False

        self.rgb_mode = "AUTO"
        self.rgb_enabled_sensor = False
        self.current_fan_percent = 0.0
        self.fan_angle = 0.0

        # Gauge geometry
        self.gauge_cx = 190
        self.gauge_cy = 170
        self.gauge_radius = 130
        self.gauge_start_angle = 210
        self.gauge_end_angle = -150

        # Scope window handle
        self.scope_win = None

        self.build_style()
        self.build_layout()

        self.root.after(50, self._process_ui_queue)
        self.start_animations()

        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()

    # ================== STYLES ==================
    def build_style(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("TLabel", background=BG_COLOR, foreground=TEXT_MAIN, font=("Consolas", 10))
        style.configure("Title.TLabel", background=BG_COLOR, foreground=ACCENT_YELLOW, font=("Consolas", 24, "bold"))
        style.configure("Card.TFrame", background=CARD_BG, relief="flat")
        style.configure("Muted.TLabel", background=CARD_BG, foreground=TEXT_MUTED, font=("Consolas", 9, "bold"))
        style.configure("Value.TLabel", background=CARD_BG, foreground=TEXT_MAIN, font=("Consolas", 13, "bold"))
        style.configure("Mode.TLabel", background=CARD_BG, foreground=ACCENT_YELLOW, font=("Consolas", 13, "bold"))

        style.configure("Accent.TButton",
                        font=("Consolas", 10, "bold"),
                        padding=8, background=ACCENT_YELLOW, foreground="#111827", borderwidth=0)
        style.map("Accent.TButton", background=[("active", "#fde047")])

        style.configure("Secondary.TButton",
                        font=("Consolas", 10, "bold"),
                        padding=8, background="#1f2937", foreground=TEXT_MAIN, borderwidth=0)
        style.map("Secondary.TButton", background=[("active", "#374151")])

        style.configure("Grey.TButton",
                        font=("Consolas", 9, "bold"),
                        padding=6, background="#111827", foreground=TEXT_MUTED, borderwidth=0)
        style.map("Grey.TButton", background=[("active", "#1f2937")])

        style.configure("Yellow.Horizontal.TProgressbar",
                        troughcolor="#020617",
                        bordercolor="#020617",
                        background=ACCENT_YELLOW,
                        lightcolor=ACCENT_YELLOW,
                        darkcolor=ACCENT_YELLOW)

    # ================== LAYOUT ==================
    def build_layout(self):
        self.content_root = tk.Frame(self.root, bg=BG_COLOR)
        self.content_root.pack(fill="both", expand=True)

        # RGB breathing border
        self.border_top = tk.Frame(self.root, bg="#020617", height=4)
        self.border_bottom = tk.Frame(self.root, bg="#020617", height=4)
        self.border_left = tk.Frame(self.root, bg="#020617", width=4)
        self.border_right = tk.Frame(self.root, bg="#020617", width=4)
        self.border_top.place(relx=0, rely=0, relwidth=1, height=4)
        self.border_bottom.place(relx=0, rely=1.0, anchor="sw", relwidth=1, height=4)
        self.border_left.place(relx=0, rely=0, relheight=1, width=4)
        self.border_right.place(relx=1.0, rely=0, anchor="ne", relheight=1, width=4)

        # Top heading + connect
        top_frame = tk.Frame(self.content_root, bg=BG_COLOR)
        top_frame.pack(fill="x", padx=18, pady=(14, 6))

        self.heading_full_text = "SMART GAMING LAPTOP COOLING PAD"
        self.heading_label = ttk.Label(top_frame, text="", style="Title.TLabel")
        self.heading_label.pack(side="left")

        right_box = tk.Frame(top_frame, bg=BG_COLOR)
        right_box.pack(side="right")

        connect_card = tk.Frame(right_box, bg=CARD_BG)
        connect_card.pack()

        tk.Label(connect_card, text="ESP32 CONNECT",
                 bg=CARD_BG, fg=TEXT_MUTED, font=("Consolas", 9, "bold")).grid(row=0, column=0, columnspan=5, sticky="w", padx=10, pady=(8, 0))

        tk.Label(connect_card, text="URL / IP",
                 bg=CARD_BG, fg=TEXT_MUTED, font=("Consolas", 9)).grid(row=1, column=0, sticky="w", padx=10, pady=(6, 6))

        self.url_var = tk.StringVar(value=DEFAULT_ESP32_URL)
        self.entry_url = tk.Entry(connect_card, textvariable=self.url_var,
                                  bg="#020617", fg=TEXT_MAIN, insertbackground=TEXT_MAIN,
                                  relief="flat", width=22, font=("Consolas", 10))
        self.entry_url.grid(row=1, column=1, padx=(0, 6), pady=(6, 6))

        self.btn_connect = ttk.Button(connect_card, text="CONNECT", style="Accent.TButton", command=self.on_connect)
        self.btn_connect.grid(row=1, column=2, padx=(0, 6), pady=(6, 6))

        self.btn_scan = ttk.Button(connect_card, text="SCAN", style="Secondary.TButton", command=self.on_scan)
        self.btn_scan.grid(row=1, column=3, padx=(0, 6), pady=(6, 6))

        # NEW: oscilloscope window button (separate screen)
        self.btn_scope = ttk.Button(connect_card, text="ANALOG METERS", style="Secondary.TButton",
                                    command=self.open_scope_window)
        self.btn_scope.grid(row=1, column=4, padx=(0, 10), pady=(6, 6))

        self.lbl_small = tk.Label(connect_card, text="Status: not connected",
                                  bg=CARD_BG, fg=TEXT_MUTED, font=("Consolas", 8))
        self.lbl_small.grid(row=2, column=0, columnspan=5, sticky="w", padx=10, pady=(0, 10))

        # Over-temp banner
        self.alert_frame = tk.Frame(self.content_root, bg=DANGER_RED)
        self.alert_label = tk.Label(self.alert_frame,
                                    text="⚠ OVER TEMPERATURE! FAN AT MAX – CHECK LAPTOP COOLING",
                                    bg=DANGER_RED, fg="#111827", font=("Consolas", 10, "bold"))
        self.alert_label.pack(padx=10, pady=2)

        # Main area
        side_and_main = tk.Frame(self.content_root, bg=BG_COLOR)
        side_and_main.pack(fill="both", expand=True, padx=18, pady=(10, 10))

        # Toolbar
        toolbar = tk.Frame(side_and_main, bg="#020617", width=70)
        toolbar.pack(side="left", fill="y", padx=(0, 10))
        toolbar.pack_propagate(False)

        tk.Label(toolbar, text="TEST", bg="#020617", fg=ACCENT_YELLOW, font=("Consolas", 9, "bold")).pack(pady=(12, 10))
        self.make_tool_button(toolbar, "🌀\nFAN", lambda: self.send_test("fan"), fg=LINE_BLUE)
        self.make_tool_button(toolbar, "🔊\nBUZZER", lambda: self.send_test("buzzer"), fg=DANGER_RED)
        self.make_tool_button(toolbar, "💡\nRGB", lambda: self.send_test("rgb"), fg=NEON_PURPLE)

        # Main layout columns
        main = tk.Frame(side_and_main, bg=BG_COLOR)
        main.pack(side="left", fill="both", expand=True)

        top_row = tk.Frame(main, bg=BG_COLOR)
        top_row.pack(side="top", fill="both", expand=False)

        # LEFT COL
        left_col = tk.Frame(top_row, bg=BG_COLOR)
        left_col.pack(side="left", fill="y", padx=(0, 8))

        gauge_card = tk.Frame(left_col, bg=CARD_BG)
        gauge_card.pack(fill="x")
        self.gauge_canvas = tk.Canvas(gauge_card, width=380, height=320, bg=CARD_BG, highlightthickness=0)
        self.gauge_canvas.pack(padx=12, pady=12)
        self.draw_temp_gauge_static()

        fan_card_left = tk.Frame(left_col, bg=CARD_BG)
        fan_card_left.pack(fill="x", pady=(6, 0))
        self.fan_canvas = tk.Canvas(fan_card_left, width=380, height=110, bg=CARD_BG, highlightthickness=0)
        self.fan_canvas.pack(padx=12, pady=8)
        self.fan_canvas.create_text(190, 20, text="FAN SPEED", fill=TEXT_MUTED, font=("Consolas", 9, "bold"))
        self.fan_meter_outline = self.fan_canvas.create_rectangle(40, 36, 340, 58, outline="#4b5563", width=2)
        self.fan_meter_fill = self.fan_canvas.create_rectangle(42, 38, 42, 56, fill=ACCENT_YELLOW, outline="")
        self.fan_meter_needle = self.fan_canvas.create_line(42, 62, 42, 68, fill=ACCENT_YELLOW, width=2)
        self.fan_seven_label = self.fan_canvas.create_text(190, 90, text="FAN 000 %", fill=ACCENT_YELLOW, font=("Consolas", 14, "bold"))

        amb_card = tk.Frame(left_col, bg=CARD_BG)
        amb_card.pack(fill="x", pady=(6, 0))
        amb_inner = tk.Frame(amb_card, bg=CARD_BG)
        amb_inner.pack(padx=12, pady=10, fill="x")
        self.lbl_digital_dht = tk.Label(amb_inner, text="00.0°C", bg=CARD_BG, fg=ACCENT_YELLOW, font=("Consolas", 20, "bold"))
        self.lbl_digital_dht.pack(anchor="w")
        tk.Label(amb_inner, text="ENVIRONMENTAL TEMP", bg=CARD_BG, fg=TEXT_MUTED, font=("Consolas", 9)).pack(anchor="w", pady=(0, 6))
        self.lbl_digital_hum = tk.Label(amb_inner, text="00%", bg=CARD_BG, fg=ACCENT_YELLOW, font=("Consolas", 20, "bold"))
        self.lbl_digital_hum.pack(anchor="w")
        tk.Label(amb_inner, text="AMBIENT HUMIDITY", bg=CARD_BG, fg=TEXT_MUTED, font=("Consolas", 9)).pack(anchor="w")

        # RIGHT PANEL
        right_panel = tk.Frame(top_row, bg=BG_COLOR)
        right_panel.pack(side="left", fill="both", expand=True)

        # Mode/Connection card
        self.card_mode = self.make_card(right_panel, "Mode / Connection")
        mode_row = tk.Frame(self.card_mode, bg=CARD_BG)
        mode_row.pack(fill="x", padx=10, pady=(8, 6))
        self.lbl_mode = ttk.Label(mode_row, text="MODE: --", style="Mode.TLabel")
        self.lbl_mode.pack(side="left")

        conn_frame = tk.Frame(mode_row, bg=CARD_BG)
        conn_frame.pack(side="right")
        self.conn_canvas = tk.Canvas(conn_frame, width=26, height=26, bg=CARD_BG, highlightthickness=0)
        self.conn_canvas.pack(side="left", padx=(0, 6))
        self.conn_outer = self.conn_canvas.create_oval(3, 3, 23, 23, outline=ACCENT_YELLOW, width=2)
        self.conn_dot = self.conn_canvas.create_oval(7, 7, 19, 19, fill=TEXT_MUTED, outline="")
        self.lbl_conn_text = ttk.Label(conn_frame, text="OFFLINE", style="Muted.TLabel")
        self.lbl_conn_text.pack(side="left")

        # Sensor Readings card
        self.card_info = self.make_card(right_panel, "Sensor Readings")
        info_grid = tk.Frame(self.card_info, bg=CARD_BG)
        info_grid.pack(fill="x", padx=10, pady=(8, 10))

        def label_val(col, row, title):
            tk.Label(info_grid, text=title, bg=CARD_BG, fg=TEXT_MUTED, font=("Consolas", 9)).grid(row=row, column=col, sticky="w", padx=(0 if col == 0 else 10, 0))
            val = tk.Label(info_grid, text="--", bg=CARD_BG, fg=TEXT_MAIN, font=("Consolas", 11, "bold"))
            val.grid(row=row+1, column=col, sticky="w", padx=(0 if col == 0 else 10, 0), pady=(0, 6))
            return val

        self.lbl_lm35 = label_val(0, 0, "LM35 Temp")
        self.lbl_dht_t = label_val(1, 0, "DHT22 Temp")
        self.lbl_dht_h = label_val(2, 0, "Humidity")

        self.lbl_dist = label_val(0, 2, "Distance (IR)")
        self.lbl_lux  = label_val(1, 2, "Light Level")
        self.lbl_pot  = label_val(2, 2, "Potentiometer")

        self.lbl_connected_status = tk.Label(info_grid, text="Laptop: --", bg=CARD_BG, fg=TEXT_MUTED, font=("Consolas", 9))
        self.lbl_connected_status.grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 0))

        self.lbl_lux_mode = tk.Label(info_grid, text="RGB: --", bg=CARD_BG, fg=TEXT_MUTED, font=("Consolas", 9))
        self.lbl_lux_mode.grid(row=4, column=1, columnspan=2, sticky="w", padx=(10, 0))

        # Controls card
        self.card_ctrl = self.make_card(right_panel, "Fan & RGB Controls")

        ctrl_top = tk.Frame(self.card_ctrl, bg=CARD_BG)
        ctrl_top.pack(fill="x", padx=10, pady=(8, 6))

        self.fan_anim_canvas = tk.Canvas(ctrl_top, width=70, height=70, bg=CARD_BG, highlightthickness=0)
        self.fan_anim_canvas.pack(side="left", padx=(0, 10))
        self.fan_anim_canvas.create_oval(29, 29, 41, 41, fill="#020617", outline=ACCENT_YELLOW, width=2)
        self.fan_blades = []
        self.init_fan_blades()

        fan_info = tk.Frame(ctrl_top, bg=CARD_BG)
        fan_info.pack(side="left", fill="both", expand=True)

        tk.Label(fan_info, text="Fan Duty", bg=CARD_BG, fg=TEXT_MUTED, font=("Consolas", 9)).pack(anchor="w")
        self.lbl_fan_duty = tk.Label(fan_info, text="0 %", bg=CARD_BG, fg=TEXT_MAIN, font=("Consolas", 11, "bold"))
        self.lbl_fan_duty.pack(anchor="w", pady=(2, 3))

        self.fan_bar = ttk.Progressbar(fan_info, style="Yellow.Horizontal.TProgressbar",
                                       orient="horizontal", mode="determinate", length=240, maximum=100)
        self.fan_bar.pack(pady=(0, 6))

        self.lbl_temp_warn = tk.Label(fan_info, text="Temperature OK", bg=CARD_BG, fg=OK_GREEN, font=("Consolas", 9, "bold"))
        self.lbl_temp_warn.pack(anchor="w")

        mode_btn_row = tk.Frame(self.card_ctrl, bg=CARD_BG)
        mode_btn_row.pack(fill="x", padx=10, pady=(2, 6))

        self.btn_auto = ttk.Button(mode_btn_row, text="AUTO MODE", style="Accent.TButton",
                                   command=lambda: self.send_mode("AUTO"))
        self.btn_auto.pack(side="left", expand=True, fill="x", padx=(0, 4))

        self.btn_manual = ttk.Button(mode_btn_row, text="MANUAL MODE", style="Secondary.TButton",
                                     command=lambda: self.send_mode("MANUAL"))
        self.btn_manual.pack(side="left", expand=True, fill="x", padx=(4, 0))

        slider_frame = tk.Frame(self.card_ctrl, bg=CARD_BG)
        slider_frame.pack(fill="x", padx=10, pady=(0, 4))

        tk.Label(slider_frame, text="Manual Fan Control (GUI)", bg=CARD_BG, fg=TEXT_MUTED, font=("Consolas", 9)).pack(anchor="w")

        self.fan_slider = tk.Scale(slider_frame, from_=0, to=100, orient="horizontal",
                                   bg=CARD_BG, troughcolor="#020617", highlightthickness=0, showvalue=False,
                                   fg=TEXT_MAIN, relief="flat", length=260, sliderrelief="flat", sliderlength=16,
                                   font=("Consolas", 9))
        self.fan_slider.set(0)
        self.fan_slider.pack(fill="x", pady=(2, 4))
        self.fan_slider.bind("<ButtonPress-1>", lambda e: self._slider_set_drag(True))
        self.fan_slider.bind("<ButtonRelease-1>", self._on_slider_release)

        rgb_ctrl = tk.Frame(self.card_ctrl, bg=CARD_BG)
        rgb_ctrl.pack(fill="x", padx=10, pady=(2, 10))

        tk.Label(rgb_ctrl, text="RGB Strip Mode", bg=CARD_BG, fg=TEXT_MUTED, font=("Consolas", 9, "bold")).pack(anchor="w")

        rgb_btns = tk.Frame(rgb_ctrl, bg=CARD_BG)
        rgb_btns.pack(fill="x", pady=(4, 0))

        self.btn_rgb_auto = ttk.Button(rgb_btns, text="AUTO", style="Accent.TButton", command=lambda: self.set_rgb_mode("AUTO"))
        self.btn_rgb_auto.pack(side="left", expand=True, fill="x", padx=(0, 3))

        self.btn_rgb_on = ttk.Button(rgb_btns, text="ON", style="Grey.TButton", command=lambda: self.set_rgb_mode("ON"))
        self.btn_rgb_on.pack(side="left", expand=True, fill="x", padx=3)

        self.btn_rgb_off = ttk.Button(rgb_btns, text="OFF", style="Grey.TButton", command=lambda: self.set_rgb_mode("OFF"))
        self.btn_rgb_off.pack(side="left", expand=True, fill="x", padx=(3, 0))

        self.lbl_status = tk.Label(self.card_ctrl, text="Not connected. Enter IP and press CONNECT.",
                                   bg=CARD_BG, fg=TEXT_MUTED, font=("Consolas", 8))
        self.lbl_status.pack(anchor="w", padx=10, pady=(0, 8))

        # Graph card (original temp graph)
        graph_card = tk.Frame(right_panel, bg=CARD_BG)
        graph_card.pack(side="top", fill="both", expand=True, pady=(8, 0))

        self.graph_title = tk.Label(graph_card, text="Live Temperature Graph",
                                    bg=CARD_BG, fg=TEXT_MUTED, font=("Consolas", 9, "bold"))
        self.graph_title.pack(anchor="w", padx=10, pady=(8, 0))

        self.fig = Figure(figsize=(7.5, 2.5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor("#020617")
        self.fig.patch.set_facecolor(CARD_BG)
        self.ax.set_xlabel("Time (s)", color=TEXT_MUTED, fontname="Consolas")
        self.ax.set_ylabel("Temperature (°C)", color=TEXT_MUTED, fontname="Consolas")
        self.ax.tick_params(colors=TEXT_MUTED, labelsize=8)
        for spine in self.ax.spines.values():
            spine.set_color("#374151")
        self.ax.grid(True, color="#1f2937", linestyle="--", linewidth=0.6, alpha=0.7)

        self.line_lm35, = self.ax.plot([], [], label="LM35", linewidth=2.0, color=LINE_BLUE)
        self.line_dht,  = self.ax.plot([], [], label="DHT Temp", linewidth=2.0, linestyle="--", color=LINE_ORANGE)
        self.ax.legend(facecolor="#020617", edgecolor="#4b5563", labelcolor=TEXT_MUTED, fontsize=8)

        self.canvas = FigureCanvasTkAgg(self.fig, master=graph_card)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

        self._animate_heading(0)
        self._refresh_rgb_button_styles()
        self.fan_slider.configure(state="disabled")

    def make_card(self, parent, title):
        wrapper = tk.Frame(parent, bg=BG_COLOR)
        wrapper.pack(fill="x", pady=4)
        card = ttk.Frame(wrapper, style="Card.TFrame")
        card.pack(fill="x")
        ttk.Label(card, text=title, style="Muted.TLabel").pack(anchor="w", padx=10, pady=(6, 0))
        return card

    def make_tool_button(self, parent, text, command, fg=TEXT_MUTED):
        btn = tk.Button(parent, text=text, justify="center",
                        bg="#020617", fg=fg,
                        activebackground="#111827", activeforeground=ACCENT_YELLOW,
                        bd=0, relief="flat", font=("Consolas", 9, "bold"),
                        command=command)
        btn.pack(fill="x", padx=6, pady=6, ipady=6)

    # ================== ANIMATIONS ==================
    def start_animations(self):
        self._animate_heading_color()
        self._animate_mode_pulse()
        self._animate_breath()
        self._animate_rgb_border()
        self._animate_fan_spin()

    def _animate_heading(self, idx):
        if idx <= len(self.heading_full_text):
            self.heading_label.configure(text=self.heading_full_text[:idx])
            self.root.after(28, lambda: self._animate_heading(idx + 1))

    def _animate_heading_color(self):
        self.heading_color_phase += 0.08
        t = (math.sin(self.heading_color_phase) + 1) / 2
        color = lerp_color("#fef9c3", "#f59e0b", t)
        self.heading_label.configure(foreground=color)
        self.root.after(70, self._animate_heading_color)

    def _animate_mode_pulse(self):
        self.mode_pulse_phase += 0.12
        t = (math.sin(self.mode_pulse_phase) + 1) / 2
        color = lerp_color("#fef9c3", "#f59e0b", t)
        self.lbl_mode.configure(foreground=color)
        self.root.after(85, self._animate_mode_pulse)

    def _animate_breath(self):
        self.breath_phase += 0.18
        scale = (math.sin(self.breath_phase) + 1) / 2
        width = 1.5 + scale * 2.0
        color = ACCENT_YELLOW if scale > 0.4 else NEON_PURPLE
        self.conn_canvas.itemconfig(self.conn_outer, width=width, outline=color)
        self.root.after(80, self._animate_breath)

    def _animate_rgb_border(self):
        if self.rgb_mode == "ON":
            effective_on = True
        elif self.rgb_mode == "OFF":
            effective_on = False
        else:
            effective_on = self.rgb_enabled_sensor

        if effective_on:
            self.rgb_hue = (self.rgb_hue + 3) % 360
            color = hsv_to_hex(self.rgb_hue, 1.0, 1.0)
        else:
            color = "#020617"

        for border in (self.border_top, self.border_bottom, self.border_left, self.border_right):
            border.configure(bg=color)

        self.root.after(60, self._animate_rgb_border)

    def init_fan_blades(self):
        cx, cy = 35, 35
        r_outer = 22
        r_inner = 10
        blade_width = 9
        for base_angle in (0, 120, 240):
            blade = self._create_blade(self.fan_anim_canvas, cx, cy, r_inner, r_outer, blade_width, base_angle)
            self.fan_blades.append(blade)

    def _create_blade(self, canvas, cx, cy, r_inner, r_outer, width, angle_deg):
        theta = math.radians(angle_deg)
        dx = math.cos(theta)
        dy = math.sin(theta)
        px = -dy
        py = dx
        x_inner = cx + dx * r_inner
        y_inner = cy + dy * r_inner
        x_outer = cx + dx * r_outer
        y_outer = cy + dy * r_outer
        w = width / 2
        points = [
            x_inner + px * w, y_inner + py * w,
            x_outer + px * w, y_outer + py * w,
            x_outer - px * w, y_outer - py * w,
            x_inner - px * w, y_inner - py * w,
        ]
        return canvas.create_polygon(points, fill="#1f2937", outline="")

    def _rotate_blades(self, delta_angle):
        self.fan_angle = (self.fan_angle + delta_angle) % 360
        cx, cy = 35, 35
        r_outer = 22
        r_inner = 10
        blade_width = 9
        angles = [self.fan_angle + a for a in (0, 120, 240)]
        for blade_id, angle_deg in zip(self.fan_blades, angles):
            theta = math.radians(angle_deg)
            dx = math.cos(theta)
            dy = math.sin(theta)
            px = -dy
            py = dx
            x_inner = cx + dx * r_inner
            y_inner = cy + dy * r_inner
            x_outer = cx + dx * r_outer
            y_outer = cy + dy * r_outer
            w = blade_width / 2
            points = [
                x_inner + px * w, y_inner + py * w,
                x_outer + px * w, y_outer + py * w,
                x_outer - px * w, y_outer - py * w,
                x_inner - px * w, y_inner - py * w,
            ]
            self.fan_anim_canvas.coords(blade_id, *points)

    def _animate_fan_spin(self):
        p = self.current_fan_percent
        if p < 3:
            delta = 0
            delay = 120
            blade_color = "#1f2937"
        else:
            delta = 6 + p * 0.3
            delay = max(18, int(120 - p))
            blade_color = ACCENT_YELLOW

        for blade_id in self.fan_blades:
            self.fan_anim_canvas.itemconfig(blade_id, fill=blade_color)

        if delta:
            self._rotate_blades(delta)

        self.root.after(delay, self._animate_fan_spin)

    # ================== GAUGE ==================
    def draw_temp_gauge_static(self):
        cx = self.gauge_cx
        cy = self.gauge_cy
        r = self.gauge_radius

        n_segments = 90
        start = self.gauge_start_angle
        end = self.gauge_end_angle
        total_extent = end - start
        step = total_extent / n_segments

        green, yellow, red = "#22c55e", "#facc15", "#ef4444"
        for i in range(n_segments):
            t = i / (n_segments - 1)
            if t < 0.5:
                color = lerp_color(green, yellow, t / 0.5)
            else:
                color = lerp_color(yellow, red, (t - 0.5) / 0.5)

            start_i = start + i * step
            self.gauge_canvas.create_arc(cx - r, cy - r, cx + r, cy + r,
                                         start=start_i, extent=step,
                                         style="arc", outline=color, width=20)

        inner_r = 70
        self.gauge_canvas.create_oval(cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r,
                                      fill="#020617", outline="#111827", width=2)

        self.temp_label = self.gauge_canvas.create_text(cx, cy - 6, text="0.0°C",
                                                        fill=ACCENT_YELLOW, font=("Consolas", 18, "bold"))
        self.gauge_canvas.create_text(cx, cy + 22, text="CPU TEMPERATURE",
                                      fill=TEXT_MUTED, font=("Consolas", 9, "bold"))

        for frac, label in [(0.0, "0°"), (0.5, "40°"), (1.0, "80°")]:
            angle = self.gauge_start_angle + frac * (self.gauge_end_angle - self.gauge_start_angle)
            theta = math.radians(angle)
            rt = r + 8
            x = cx + rt * math.cos(theta)
            y = cy - rt * math.sin(theta)
            self.gauge_canvas.create_text(x, y, text=label, fill=TEXT_MUTED, font=("Consolas", 8))

        self.temp_needle = self.gauge_canvas.create_line(cx, cy, cx, cy - (r - 30),
                                                         fill="#f9fafb", width=3, capstyle="round")

    def update_gauge(self, lm35):
        cx, cy = self.gauge_cx, self.gauge_cy
        r = self.gauge_radius - 30
        v = max(0.0, min(80.0, lm35))
        angle = self.gauge_start_angle + (v / 80.0) * (self.gauge_end_angle - self.gauge_start_angle)
        theta = math.radians(angle)
        x_end = cx + r * math.cos(theta)
        y_end = cy - r * math.sin(theta)
        self.gauge_canvas.coords(self.temp_needle, cx, cy, x_end, y_end)
        self.gauge_canvas.itemconfig(self.temp_label, text=f"{lm35:.1f}°C")

    def update_fan_meter(self, percent):
        p = max(0.0, min(100.0, percent))
        x_min, x_max = 42, 338
        x_fill = x_min + (x_max - x_min) * (p / 100.0)
        self.fan_canvas.coords(self.fan_meter_fill, x_min, 38, x_fill, 56)
        self.fan_canvas.coords(self.fan_meter_needle, x_fill, 62, x_fill, 68)
        self.fan_canvas.itemconfig(self.fan_seven_label, text=f"FAN {int(p):03d} %")

    def update_graph(self, lm35, dht_t):
        now = time.time() - self.start_time
        self.time_hist.append(now)
        self.lm35_hist.append(lm35)
        self.dhtt_hist.append(dht_t)

        while self.time_hist and (now - self.time_hist[0]) > HISTORY_SECONDS:
            self.time_hist.pop(0)
            self.lm35_hist.pop(0)
            self.dhtt_hist.pop(0)
            if self.ir_hist: self.ir_hist.pop(0)
            if self.pot_hist: self.pot_hist.pop(0)

        self.line_lm35.set_data(self.time_hist, self.lm35_hist)
        self.line_dht.set_data(self.time_hist, self.dhtt_hist)

        if self.time_hist:
            t_min = max(0, self.time_hist[-1] - HISTORY_SECONDS)
            t_max = self.time_hist[-1] + 1
            self.ax.set_xlim(t_min, t_max)

            all_vals = self.lm35_hist + self.dhtt_hist
            ymin = min(all_vals) - 2
            ymax = max(all_vals) + 2
            if ymin == ymax:
                ymin -= 1
                ymax += 1
            self.ax.set_ylim(ymin, ymax)

        self.canvas.draw_idle()

    # ================== CONNECT / SCAN ==================
    def on_connect(self):
        url = normalize_base_url(self.url_var.get())
        if not url:
            messagebox.showwarning("Connect", "Please enter ESP32 IP or URL.")
            return
        self.http.set_base_url(url)
        self._set_status(f"Connecting to {url} ...")
        self.lbl_small.configure(text=f"Status: connecting to {url}")

    def on_scan(self):
        self._set_status("Scanning local network for ESP32...")
        self.lbl_small.configure(text="Status: scanning local /24 network ...")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        local_ip = get_local_ipv4()
        if not local_ip:
            self.ui_queue.put(("scan_result", None, "Could not determine local IP for scan. Enter ESP32 IP manually."))
            return

        net = ipaddress.ip_network(local_ip + "/24", strict=False)
        hosts = [str(h) for h in net.hosts()]

        found = {"url": None}
        q = Queue()
        for h in hosts:
            q.put(h)

        def probe_host():
            s = requests.Session()
            while not q.empty() and found["url"] is None:
                try:
                    ip_ = q.get_nowait()
                except Empty:
                    return
                try:
                    url = f"http://{ip_}"
                    r = s.get(url + "/status", timeout=SCAN_TIMEOUT_S)
                    if r.status_code == 200:
                        j = r.json()
                        if "mode" in j and "lm35" in j and "fanDuty" in j:
                            found["url"] = url
                except Exception:
                    pass
                finally:
                    q.task_done()

        for _ in range(SCAN_THREADS):
            threading.Thread(target=probe_host, daemon=True).start()

        t0 = time.time()
        while found["url"] is None and not q.empty() and (time.time() - t0) < 12.0:
            time.sleep(0.05)

        if found["url"]:
            self.ui_queue.put(("scan_result", found["url"], f"Found ESP32 at {found['url']}"))
        else:
            self.ui_queue.put(("scan_result", None, "ESP32 not found. Please type the IP shown on Serial Monitor."))

    # ================== CONTROL COMMANDS ==================
    def send_mode(self, mode):
        mode = mode.upper()
        if not self.http.base_url:
            self._set_status("Not connected. Enter IP and press CONNECT.")
            return

        def worker():
            try:
                r = self.http.get(f"/setMode?mode={mode}", timeout=1.2)
                if r.status_code == 200:
                    self.ui_queue.put(("status", f"Set mode → {mode} ({r.text.strip()})"))
                else:
                    self.ui_queue.put(("status", f"Set mode failed ({r.status_code})"))
            except Exception as e:
                self.ui_queue.put(("status", f"Set mode error: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def send_fan_set(self, percent):
        if not self.http.base_url:
            return
        duty = int(max(0, min(100, percent)) * 255 / 100)

        def worker():
            try:
                r = self.http.get(f"/fan?duty={duty}", timeout=1.2)
                if r.status_code == 200:
                    self.ui_queue.put(("status", f"Manual fan set {int(percent)}% ({r.text.strip()})"))
                else:
                    self.ui_queue.put(("status", f"Set fan failed ({r.status_code})"))
            except Exception as e:
                self.ui_queue.put(("status", f"Set fan error: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def set_rgb_mode(self, mode):
        mode = mode.upper()
        self.rgb_mode = mode
        self._refresh_rgb_button_styles()

        if not self.http.base_url:
            self._set_status("Not connected. RGB command queued (connect first).")
            return

        def worker():
            try:
                if mode == "AUTO":
                    r = self.http.get("/rgb?release=1", timeout=1.2)
                elif mode == "ON":
                    r = self.http.get("/rgb?state=ON", timeout=1.2)
                else:
                    r = self.http.get("/rgb?state=OFF", timeout=1.2)

                if r.status_code == 200:
                    self.ui_queue.put(("status", f"RGB mode → {mode} ({r.text.strip()})"))
                else:
                    self.ui_queue.put(("status", f"RGB mode {mode} failed ({r.status_code})"))
            except Exception as e:
                self.ui_queue.put(("status", f"RGB mode error: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def send_test(self, device):
        if self.current_mode.upper() != "MANUAL":
            self._set_status("Test controls only in MANUAL MODE")
            return
        if not self.http.base_url:
            self._set_status("Not connected.")
            return

        def worker():
            try:
                if device == "fan":
                    url_on = "/fan?duty=200"
                    url_off = "/fan?duty=0"
                elif device == "buzzer":
                    url_on = "/buzzer?pattern=2"
                    url_off = None
                elif device == "rgb":
                    url_on = "/rgb?state=ON"
                    url_off = "/rgb?state=OFF"
                else:
                    self.ui_queue.put(("status", "Unknown test device"))
                    return

                r = self.http.get(url_on, timeout=1.2)
                if r.status_code == 200:
                    self.ui_queue.put(("status", f"Test {device}: ON ({r.text.strip()})"))
                else:
                    self.ui_queue.put(("status", f"Test {device} ON failed ({r.status_code})"))

                t0 = time.time()
                while time.time() - t0 < 4.0:
                    time.sleep(0.05)

                if url_off is not None:
                    r2 = self.http.get(url_off, timeout=1.2)
                    if r2.status_code == 200:
                        self.ui_queue.put(("status", f"Test {device}: OFF ({r2.text.strip()})"))
                    else:
                        self.ui_queue.put(("status", f"Test {device} OFF failed ({r2.status_code})"))

            except Exception as e:
                self.ui_queue.put(("status", f"Test {device} error: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    # ================== SLIDER EVENTS ==================
    def _slider_set_drag(self, dragging: bool):
        self.slider_dragging = dragging

    def _on_slider_release(self, event):
        self.slider_dragging = False
        if self.current_mode.upper() == "MANUAL":
            percent = self.fan_slider.get()
            self.send_fan_set(int(percent))

    # ================== POLLING LOOP ==================
    def _poll_loop(self):
        while not self.stop_flag:
            if not self.http.base_url:
                time.sleep(0.2)
                continue

            try:
                r = self.http.get("/status")
                if r.status_code == 200:
                    data = r.json()
                    self.http.mark_ok()
                    self.ui_queue.put(("status_data", data))
                else:
                    self.http.mark_fail()
                    self.ui_queue.put(("offline", f"HTTP {r.status_code}"))
            except Exception as e:
                self.http.mark_fail()
                self.ui_queue.put(("offline", str(e)))

            time.sleep(self.http.next_sleep_s())

    # ================== UI QUEUE PROCESSOR ==================
    def _process_ui_queue(self):
        try:
            while True:
                item = self.ui_queue.get_nowait()
                kind = item[0]

                if kind == "status":
                    self._set_status(item[1])

                elif kind == "offline":
                    self._set_online(False, item[1])

                elif kind == "status_data":
                    self._set_online(True, "OK")
                    self._update_ui_from_status(item[1])

                elif kind == "scan_result":
                    url, msg = item[1], item[2]
                    self._set_status(msg)
                    self.lbl_small.configure(text=f"Status: {msg}")
                    if url:
                        self.url_var.set(url)
                        self.http.set_base_url(url)
                        self._set_status(f"Connected target set to {url} (polling...)")

                self.ui_queue.task_done()

        except Empty:
            pass

        self.root.after(50, self._process_ui_queue)

    # ================== UI UPDATES ==================
    def _set_status(self, msg):
        self.lbl_status.configure(text=msg)

    def _set_online(self, online: bool, reason: str):
        if online:
            self.pulse_state = not self.pulse_state
            fill = ACCENT_YELLOW if self.pulse_state else OK_GREEN
            self.conn_canvas.itemconfig(self.conn_dot, fill=fill)
            self.lbl_conn_text.configure(text="ONLINE", foreground=OK_GREEN)
            base = self.http.base_url if self.http.base_url else "-"
            self.lbl_small.configure(text=f"Status: online | {base} | poll={self.http.poll_interval_ms}ms | to={self.http.timeout_s:.2f}s")
            self.connected_online = True
        else:
            self.conn_canvas.itemconfig(self.conn_dot, fill=TEXT_MUTED)
            self.lbl_conn_text.configure(text="OFFLINE", foreground=DANGER_RED)
            base = self.http.base_url if self.http.base_url else "-"
            self.lbl_small.configure(text=f"Status: offline ({reason}) | {base} | retry={self.http.poll_interval_ms}ms")
            self.connected_online = False

    def _extract_pot_percent(self, data: dict, fan_duty: int) -> float:
        """
        If ESP32 sends pot value in /status => use it.
        If not, fallback to proxy = fanDuty%.
        Keys supported: potPercent, pot, potValue, potAdc, potADC
        """
        for k in ("potPercent", "pot", "potValue", "potAdc", "potADC"):
            if k in data:
                try:
                    v = float(data.get(k))
                    if v > 100.0:
                        return max(0.0, min(100.0, (v / 4095.0) * 100.0))
                    return max(0.0, min(100.0, v))
                except Exception:
                    break
        return (fan_duty / 255.0) * 100.0

    def _update_ui_from_status(self, data: dict):
        mode = str(data.get("mode", "--"))
        self.current_mode = mode

        lm35 = float(data.get("lm35", 0.0))
        dht_t = float(data.get("dhtTemp", 0.0))
        dht_h = float(data.get("dhtHum", 0.0))
        dist = float(data.get("dist", 0.0))
        lux = float(data.get("lux", 0.0))
        fan_duty = int(data.get("fanDuty", 0))
        connected = bool(data.get("connected", False))

        pot_percent = self._extract_pot_percent(data, fan_duty)

        # Mode UI
        self.lbl_mode.configure(text=f"MODE: {mode}")
        if mode.upper() == "AUTO":
            self.btn_auto.configure(style="Accent.TButton")
            self.btn_manual.configure(style="Secondary.TButton")
            self.fan_slider.configure(state="disabled")
        else:
            self.btn_auto.configure(style="Secondary.TButton")
            self.btn_manual.configure(style="Accent.TButton")
            self.fan_slider.configure(state="normal")

        # Digital sensor labels
        self.lbl_lm35.configure(text=f"{lm35:.1f} °C")
        self.lbl_dht_t.configure(text=f"{dht_t:.1f} °C")
        self.lbl_dht_h.configure(text=f"{dht_h:.0f} %")
        self.lbl_dist.configure(text=f"{dist:.0f} cm")
        self.lbl_lux.configure(text=f"{lux:.0f} lx")
        self.lbl_pot.configure(text=f"{pot_percent:.0f} %")

        self.lbl_digital_dht.configure(text=f"{dht_t:4.1f}°C")
        self.lbl_digital_hum.configure(text=f"{dht_h:3.0f}%")

        if connected:
            self.lbl_connected_status.configure(text="Laptop: CONNECTED", fg=OK_GREEN)
        else:
            self.lbl_connected_status.configure(text="Laptop: NOT CONNECTED", fg=TEXT_MUTED)

        # Overtemp banner
        if lm35 > 50.0:
            self.lbl_temp_warn.configure(text="⚠ OVER-TEMPERATURE!", fg=DANGER_RED)
            if not self.alert_visible:
                self.alert_frame.pack(in_=self.content_root, fill="x", padx=18, pady=(0, 6))
                self.alert_visible = True
        elif lm35 > 40.0:
            self.lbl_temp_warn.configure(text="High temperature, fan at MAX", fg=ACCENT_YELLOW)
            if self.alert_visible:
                self.alert_frame.pack_forget()
                self.alert_visible = False
        else:
            self.lbl_temp_warn.configure(text="Temperature OK", fg=OK_GREEN)
            if self.alert_visible:
                self.alert_frame.pack_forget()
                self.alert_visible = False

        # RGB sensor-driven enable logic
        sensor_rgb_on = False
        if mode.upper() == "AUTO":
            if connected and lux < 99.0:
                sensor_rgb_on = True
        else:
            if connected:
                sensor_rgb_on = True
        self.rgb_enabled_sensor = sensor_rgb_on

        if self.rgb_mode == "OFF":
            self.lbl_lux_mode.configure(text="RGB: FORCED OFF", fg=TEXT_MUTED)
        elif self.rgb_mode == "ON":
            self.lbl_lux_mode.configure(text="RGB: MANUAL ON", fg=ACCENT_YELLOW)
        else:
            if connected and lux < 99.0:
                self.lbl_lux_mode.configure(text="RGB: CHASING (AUTO)", fg=ACCENT_YELLOW)
            elif connected:
                self.lbl_lux_mode.configure(text="RGB: OFF (bright, AUTO)", fg=TEXT_MUTED)
            else:
                self.lbl_lux_mode.configure(text="RGB: OFF (no laptop, AUTO)", fg=TEXT_MUTED)

        # Fan percent
        fan_percent = (fan_duty / 255.0) * 100.0
        self.current_fan_percent = fan_percent
        self.fan_bar["value"] = fan_percent
        self.lbl_fan_duty.configure(text=f"{fan_percent:.0f} %")

        if not self.slider_dragging:
            self.fan_slider.set(fan_percent)

        # Gauge / meter / main graph
        self.update_gauge(lm35)
        self.update_fan_meter(fan_percent)
        self.update_graph(lm35, dht_t)

        # oscilloscope buffers update + redraw if window open
        self._scope_push(dist, pot_percent)
        self._scope_redraw()

    def _refresh_rgb_button_styles(self):
        if self.rgb_mode == "AUTO":
            self.btn_rgb_auto.configure(style="Accent.TButton")
            self.btn_rgb_on.configure(style="Grey.TButton")
            self.btn_rgb_off.configure(style="Grey.TButton")
        elif self.rgb_mode == "ON":
            self.btn_rgb_auto.configure(style="Grey.TButton")
            self.btn_rgb_on.configure(style="Accent.TButton")
            self.btn_rgb_off.configure(style="Grey.TButton")
        else:
            self.btn_rgb_auto.configure(style="Grey.TButton")
            self.btn_rgb_on.configure(style="Grey.TButton")
            self.btn_rgb_off.configure(style="Accent.TButton")

    # ================== OSCILLOSCOPE WINDOW (SEPARATE) ==================
    def open_scope_window(self):
        if self.scope_win and self.scope_win.winfo_exists():
            self.scope_win.lift()
            return

        self.scope_win = tk.Toplevel(self.root)
        self.scope_win.title("Oscilloscope - Analog Sensors (Serial Monitor Style)")
        self.scope_win.configure(bg=BG_COLOR)
        self.scope_win.geometry("1300x900")

        wrap = tk.Frame(self.scope_win, bg=CARD_BG)
        wrap.pack(fill="both", expand=True, padx=12, pady=12)

        header = tk.Frame(wrap, bg=CARD_BG)
        header.pack(fill="x")
        tk.Label(header, text="LIVE GRAPH", bg=CARD_BG, fg=ACCENT_YELLOW,
                 font=("Consolas", 14, "bold")).pack(side="left", padx=8, pady=8)
        tk.Label(header, text="LM35 / Sharp IR / Potentiometer", bg=CARD_BG, fg=TEXT_MUTED,
                 font=("Consolas", 10)).pack(side="left", padx=10)

        def mk_plot(parent, title, ylab, line_color, fixed_ylim=None):
            box = tk.Frame(parent, bg=CARD_BG)
            box.pack(fill="both", expand=True, pady=(10, 0))

            tk.Label(box, text=title, bg=CARD_BG, fg=TEXT_MUTED,
                     font=("Consolas", 11, "bold")).pack(anchor="w", padx=8)

            fig = Figure(figsize=(12, 2.6), dpi=100)
            ax = fig.add_subplot(111)
            ax.set_facecolor("#020617")
            fig.patch.set_facecolor(CARD_BG)

            ax.grid(True, color="#1f2937", linestyle="--", linewidth=0.9, alpha=0.85)
            ax.tick_params(colors=TEXT_MUTED, labelsize=9)
            for sp in ax.spines.values():
                sp.set_color("#374151")
            ax.set_xlabel("Time (s)", color=TEXT_MUTED, fontname="Consolas")
            ax.set_ylabel(ylab, color=TEXT_MUTED, fontname="Consolas")

            line, = ax.plot([], [], linewidth=3.5, color=line_color)
            if fixed_ylim:
                ax.set_ylim(fixed_ylim[0], fixed_ylim[1])

            canv = FigureCanvasTkAgg(fig, master=box)
            canv.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=(4, 8))
            return ax, line, canv

        self.scope_ax_lm35, self.scope_line_lm35, self.scope_canvas_lm35 = mk_plot(wrap, "LM35 (°C)", "°C", LINE_BLUE)
        self.scope_ax_ir,   self.scope_line_ir,   self.scope_canvas_ir   = mk_plot(wrap, "Sharp IR Distance (cm)", "cm", LINE_ORANGE)
        self.scope_ax_pot,  self.scope_line_pot,  self.scope_canvas_pot  = mk_plot(wrap, "Potentiometer (%)", "%", LINE_PURPLE, fixed_ylim=(0, 100))

        self._scope_redraw()

    def _scope_push(self, dist_cm, pot_percent):
        # Keep buffers aligned with time_hist
        self.ir_hist.append(dist_cm)
        self.pot_hist.append(pot_percent)

        # If buffers grew more than time, trim
        if len(self.ir_hist) > len(self.time_hist):
            self.ir_hist = self.ir_hist[-len(self.time_hist):]
        if len(self.pot_hist) > len(self.time_hist):
            self.pot_hist = self.pot_hist[-len(self.time_hist):]

    def _scope_redraw(self):
        if not (self.scope_win and self.scope_win.winfo_exists()):
            return
        if len(self.time_hist) < 2:
            return

        t_end = self.time_hist[-1]
        t_start = t_end - SCOPE_WINDOW_S

        start_idx = 0
        for i, t in enumerate(self.time_hist):
            if t >= t_start:
                start_idx = i
                break

        vt = self.time_hist[start_idx:]
        vlm = self.lm35_hist[start_idx:]
        vir = self.ir_hist[start_idx:] if self.ir_hist else []
        vpot = self.pot_hist[start_idx:] if self.pot_hist else []

        if not vt:
            return

        t0 = vt[0]
        shifted = [x - t0 for x in vt]

        self.scope_line_lm35.set_data(shifted, vlm)
        self.scope_line_ir.set_data(shifted, vir if vir else [0]*len(shifted))
        self.scope_line_pot.set_data(shifted, vpot if vpot else [0]*len(shifted))

        for ax in (self.scope_ax_lm35, self.scope_ax_ir, self.scope_ax_pot):
            ax.set_xlim(0, SCOPE_WINDOW_S)

        if vlm:
            self.scope_ax_lm35.set_ylim(min(vlm) - 2, max(vlm) + 2)
        if vir:
            self.scope_ax_ir.set_ylim(min(vir) - 5, max(vir) + 5)

        self.scope_canvas_lm35.draw_idle()
        self.scope_canvas_ir.draw_idle()
        self.scope_canvas_pot.draw_idle()

    # =============== OTHER UI HELPERS ===============
    def _animate_heading_color(self):
        self.heading_color_phase += 0.08
        t = (math.sin(self.heading_color_phase) + 1) / 2
        color = lerp_color("#fef9c3", "#f59e0b", t)
        self.heading_label.configure(foreground=color)
        self.root.after(70, self._animate_heading_color)


# =============== SPLASH ===============
def show_splash(root, on_done):
    splash = tk.Toplevel(root)
    splash.overrideredirect(True)
    splash.configure(bg=BG_COLOR)

    sw = splash.winfo_screenwidth()
    sh = splash.winfo_screenheight()
    w, h = 520, 250
    x = int(sw / 2 - w / 2)
    y = int(sh / 2 - h / 2)
    splash.geometry(f"{w}x{h}+{x}+{y}")

    frame = tk.Frame(splash, bg=CARD_BG)
    frame.pack(fill="both", expand=True)

    tk.Label(frame, text="Smart Laptop Cooling Pad",
             bg=CARD_BG, fg=ACCENT_YELLOW, font=("Consolas", 18, "bold")).pack(pady=(35, 6))
    tk.Label(frame, text="Starting system...",
             bg=CARD_BG, fg=TEXT_MUTED, font=("Consolas", 10)).pack()

    bar_frame = tk.Frame(frame, bg=CARD_BG)
    bar_frame.pack(pady=(30, 10))
    pb = ttk.Progressbar(bar_frame, orient="horizontal", mode="indeterminate", length=340, maximum=120)
    pb.pack()

    tk.Label(frame, text="Tip: use SCAN or type ESP32 IP shown in Serial Monitor.",
             bg=CARD_BG, fg=TEXT_MUTED, font=("Consolas", 9)).pack(pady=(6, 0))

    pb.start(10)

    def finish():
        pb.stop()
        splash.destroy()
        root.deiconify()
        on_done()

    root.after(1800, finish)


if __name__ == "__main__":
    root = tk.Tk()
    root.configure(bg=BG_COLOR)
    root.withdraw()

    def start_app():
        CoolingPadGUI(root)

    show_splash(root, start_app)
    root.mainloop()
