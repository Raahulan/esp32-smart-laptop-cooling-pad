import tkinter as tk
from tkinter import ttk
import requests
import threading
import time
import math

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ================== CONFIG ==================
ESP32_IP = "http://10.10.2.64"   # <-- CHANGE THIS (e.g. "http://192.168.4.1")
POLL_INTERVAL_MS = 1000          # ms

# Theme colors (black + yellow)
BG_COLOR       = "#050816"
CARD_BG        = "#111827"
ACCENT_YELLOW  = "#fbbf24"
TEXT_MAIN      = "#f9fafb"
TEXT_MUTED     = "#9ca3af"
DANGER_RED     = "#f97316"
OK_GREEN       = "#22c55e"
NEON_PURPLE    = "#a855f7"

MAX_HISTORY_SECONDS = 300  # 5 minutes history


def hsv_to_hex(h, s, v):
    """Simple HSV->HEX converter for RGB border animation."""
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


class CoolingPadGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("ESP32 Smart Gaming Laptop Cooling Pad")
        self.root.configure(bg=BG_COLOR)

        # Full-screen
        try:
            self.root.state("zoomed")
        except tk.TclError:
            self.root.attributes("-zoomed", True)

        # State
        self.start_time = time.time()
        self.pulse_state = False
        self.breath_phase = 0.0
        self.rgb_hue = 0.0
        self.current_fan_percent = 0.0
        self.fan_angle = 0.0
        self.rgb_enabled = False
        self.rgb_mode = "AUTO"
        self.last_connected = None
        self.alert_visible = False
        self.current_mode = "--"

        self.time_hist = []
        self.lm35_hist = []
        self.dhtt_hist = []

        self.graph_mode = "Temperature"
        self.slider_dragging = False

        # for FAN test animation
        self.test_fan_animating = False
        self.test_fan_anim_start = 0.0

        # heading / mode color animation phases
        self.heading_color_phase = 0.0
        self.mode_pulse_phase = 0.0

        # gauge geometry for the big temp meter (FULL CIRCLE)
        self.gauge_cx = 190
        self.gauge_cy = 170
        self.gauge_radius = 130
        self.gauge_start_angle = 210      # full circle: 210 -> -150
        self.gauge_end_angle = -150

        self.build_style()
        self.build_outer_layout()
        self.build_content_layout()

        self.start_animations()
        self.poll_status()

    # =============== STYLES ===============
    def build_style(self):
        style = ttk.Style()
        style.theme_use("clam")

        digital_base = ("Consolas", 10)

        style.configure(
            "TLabel",
            background=BG_COLOR,
            foreground=TEXT_MAIN,
            font=digital_base
        )
        style.configure(
            "Title.TLabel",
            background=BG_COLOR,
            foreground=ACCENT_YELLOW,
            font=("Consolas", 26, "bold")
        )
        style.configure(
            "Card.TFrame",
            background=CARD_BG,
            relief="flat"
        )
        style.configure(
            "Muted.TLabel",
            background=CARD_BG,
            foreground=TEXT_MUTED,
            font=("Consolas", 9, "bold")
        )
        style.configure(
            "Value.TLabel",
            background=CARD_BG,
            foreground=TEXT_MAIN,
            font=("Consolas", 13, "bold")
        )
        style.configure(
            "Mode.TLabel",
            background=CARD_BG,
            foreground=ACCENT_YELLOW,
            font=("Consolas", 13, "bold")
        )

        style.configure(
            "Accent.TButton",
            font=("Consolas", 10, "bold"),
            padding=8,
            background=ACCENT_YELLOW,
            foreground="#111827",
            borderwidth=0
        )
        style.map("Accent.TButton", background=[("active", "#fde047")])

        style.configure(
            "Secondary.TButton",
            font=("Consolas", 10, "bold"),
            padding=8,
            background="#1f2937",
            foreground=TEXT_MAIN,
            borderwidth=0
        )
        style.map("Secondary.TButton", background=[("active", "#374151")])

        style.configure(
            "Grey.TButton",
            font=("Consolas", 9, "bold"),
            padding=5,
            background="#111827",
            foreground=TEXT_MUTED,
            borderwidth=0
        )
        style.map("Grey.TButton", background=[("active", "#1f2937")])

        style.configure(
            "Yellow.Horizontal.TProgressbar",
            troughcolor="#020617",
            bordercolor="#020617",
            background=ACCENT_YELLOW,
            lightcolor=ACCENT_YELLOW,
            darkcolor=ACCENT_YELLOW
        )

    # =============== RGB BORDER ===============
    def build_outer_layout(self):
        self.content_root = tk.Frame(self.root, bg=BG_COLOR)
        self.content_root.pack(fill="both", expand=True)

        self.border_top = tk.Frame(self.root, bg="#020617", height=4)
        self.border_bottom = tk.Frame(self.root, bg="#020617", height=4)
        self.border_left = tk.Frame(self.root, bg="#020617", width=4)
        self.border_right = tk.Frame(self.root, bg="#020617", width=4)

        self.border_top.place(relx=0, rely=0, relwidth=1, height=4)
        self.border_bottom.place(relx=0, rely=1.0, anchor="sw",
                                 relwidth=1, height=4)
        self.border_left.place(relx=0, rely=0, relheight=1, width=4)
        self.border_right.place(relx=1.0, rely=0, anchor="ne",
                                relheight=1, width=4)

    # =============== MAIN LAYOUT ===============
    def build_content_layout(self):
        # Top heading row
        top_frame = tk.Frame(self.content_root, bg=BG_COLOR)
        top_frame.pack(fill="x", padx=20, pady=(15, 5))

        self.heading_full_text = "ESP32 SMART GAMING LAPTOP COOLING PAD"
        self.heading_label = ttk.Label(
            top_frame,
            text="",
            style="Title.TLabel"
        )
        self.heading_label.pack(side="left")

        self.ip_label = ttk.Label(
            top_frame,
            text=f"ESP32: {ESP32_IP}",
            foreground=TEXT_MUTED,
            background=BG_COLOR,
            font=("Consolas", 9, "bold")
        )
        self.ip_label.pack(side="right")

        self.animate_heading(0)

        # Over-temp alert (hidden initially)
        self.alert_frame = tk.Frame(self.content_root, bg=DANGER_RED)
        self.alert_label = tk.Label(
            self.alert_frame,
            text="⚠ OVER TEMPERATURE! FAN AT MAX – CHECK LAPTOP COOLING",
            bg=DANGER_RED,
            fg="#111827",
            font=("Consolas", 10, "bold")
        )
        self.alert_label.pack(padx=10, pady=2)

        # Content row: left toolbar + main panels
        side_and_main = tk.Frame(self.content_root, bg=BG_COLOR)
        side_and_main.pack(fill="both", expand=True, padx=20, pady=(10, 8))

        # ---------- SIDE TOOLBAR ----------
        toolbar = tk.Frame(side_and_main, bg="#020617", width=70)
        toolbar.pack(side="left", fill="y", padx=(0, 10))
        toolbar.pack_propagate(False)

        tk.Label(
            toolbar, text="TEST",
            bg="#020617",
            fg=ACCENT_YELLOW,
            font=("Consolas", 9, "bold")
        ).pack(pady=(12, 10))

        self.make_tool_button(
            toolbar,
            text="🌀\nFAN",
            command=lambda: self.send_test("fan"),
            bg="#020617",
            fg="#38bdf8"
        )
        self.make_tool_button(
            toolbar,
            text="🔊\nBUZZER",
            command=lambda: self.send_test("buzzer"),
            bg="#020617",
            fg="#f97316"
        )
        self.make_tool_button(
            toolbar,
            text="💡\nRGB",
            command=lambda: self.send_test("rgb"),
            bg="#020617",
            fg="#a855f7"
        )

        tk.Label(
            toolbar, text="MAN",
            bg="#020617",
            fg=TEXT_MUTED,
            font=("Consolas", 8, "bold")
        ).pack(side="bottom", pady=8)

        # ---------- MAIN PANEL ----------
        main_frame = tk.Frame(side_and_main, bg=BG_COLOR)
        main_frame.pack(side="left", fill="both", expand=True)
        self.main_frame = main_frame

        # Top row inside main: left column + right panel
        top_row = tk.Frame(main_frame, bg=BG_COLOR)
        top_row.pack(side="top", fill="both", expand=False)

        # ===== LEFT COLUMN =====
        left_column = tk.Frame(top_row, bg=BG_COLOR)
        left_column.pack(side="left", fill="y", expand=False, padx=(0, 8))

        # Full-circle CPU temp gauge
        gauge_card = tk.Frame(left_column, bg=CARD_BG)
        gauge_card.pack(side="top", fill="both", expand=False)

        self.gauge_canvas = tk.Canvas(
            gauge_card,
            width=380,
            height=320,
            bg=CARD_BG,
            highlightthickness=0
        )
        self.gauge_canvas.pack(padx=12, pady=12)

        self.draw_temp_gauge_static()

        # Fan speed meter
        fan_card_left = tk.Frame(left_column, bg=CARD_BG)
        fan_card_left.pack(side="top", fill="x", expand=False, pady=(4, 0))

        self.fan_canvas = tk.Canvas(
            fan_card_left,
            width=380,
            height=110,
            bg=CARD_BG,
            highlightthickness=0
        )
        self.fan_canvas.pack(padx=12, pady=8)

        self.fan_canvas.create_text(
            190, 20,
            text="FAN SPEED",
            fill=TEXT_MUTED,
            font=("Consolas", 9, "bold")
        )
        self.fan_meter_outline = self.fan_canvas.create_rectangle(
            40, 36, 340, 58,
            outline="#4b5563", width=2
        )
        self.fan_meter_fill = self.fan_canvas.create_rectangle(
            42, 38, 42, 56,
            fill=ACCENT_YELLOW,
            outline=""
        )
        self.fan_meter_needle = self.fan_canvas.create_line(
            42, 62, 42, 68,
            fill=ACCENT_YELLOW,
            width=2
        )
        self.fan_seven_label = self.fan_canvas.create_text(
            190, 90,
            text="FAN 000 %",
            fill=ACCENT_YELLOW,
            font=("Consolas", 14, "bold")
        )

        # DHT Env temp + humidity
        amb_card_left = tk.Frame(left_column, bg=CARD_BG)
        amb_card_left.pack(side="top", fill="x", expand=False, pady=(4, 0))

        amb_inner = tk.Frame(amb_card_left, bg=CARD_BG)
        amb_inner.pack(padx=12, pady=8, fill="x")

        self.lbl_digital_dht = tk.Label(
            amb_inner,
            text="00.0°C",
            bg=CARD_BG,
            fg=ACCENT_YELLOW,
            font=("Consolas", 20, "bold")
        )
        self.lbl_digital_dht.pack(anchor="w")

        tk.Label(
            amb_inner,
            text="ENVIRONMENTAL TEMP",
            bg=CARD_BG,
            fg=TEXT_MUTED,
            font=("Consolas", 9)
        ).pack(anchor="w", pady=(0, 4))

        self.lbl_digital_hum = tk.Label(
            amb_inner,
            text="00%",
            bg=CARD_BG,
            fg=ACCENT_YELLOW,
            font=("Consolas", 20, "bold")
        )
        self.lbl_digital_hum.pack(anchor="w")

        tk.Label(
            amb_inner,
            text="AMBIENT HUMIDITY",
            bg=CARD_BG,
            fg=TEXT_MUTED,
            font=("Consolas", 9)
        ).pack(anchor="w", pady=(0, 0))

        # ===== RIGHT PANEL =====
        right_panel = tk.Frame(top_row, bg=BG_COLOR)
        right_panel.pack(side="left", fill="both", expand=True)

        # Mode / connection card
        self.card_mode = self.make_card(right_panel, title="Mode / Connection")
        mode_row = tk.Frame(self.card_mode, bg=CARD_BG)
        mode_row.pack(fill="x", padx=10, pady=(8, 4))

        self.lbl_mode = ttk.Label(mode_row, text="MODE: --",
                                  style="Mode.TLabel")
        self.lbl_mode.pack(side="left")

        conn_frame = tk.Frame(mode_row, bg=CARD_BG)
        conn_frame.pack(side="right")

        self.conn_canvas = tk.Canvas(
            conn_frame,
            width=26,
            height=26,
            bg=CARD_BG,
            highlightthickness=0
        )
        self.conn_canvas.pack(side="left", padx=(0, 4))
        self.conn_outer = self.conn_canvas.create_oval(
            3, 3, 23, 23,
            outline=ACCENT_YELLOW,
            width=2
        )
        self.conn_dot = self.conn_canvas.create_oval(
            7, 7, 19, 19,
            fill=TEXT_MUTED,
            outline=""
        )
        self.lbl_conn_text = ttk.Label(
            conn_frame,
            text="OFFLINE",
            style="Muted.TLabel"
        )
        self.lbl_conn_text.pack(side="left")

        # Sensor info card
        self.card_info = self.make_card(right_panel, title="Sensor Readings")

        info_grid = tk.Frame(self.card_info, bg=CARD_BG)
        info_grid.pack(fill="x", padx=10, pady=(6, 10))

        tk.Label(info_grid, text="LM35 Temp",
                 bg=CARD_BG, fg=TEXT_MUTED,
                 font=("Consolas", 9)).grid(row=0, column=0, sticky="w")
        self.lbl_lm35 = tk.Label(info_grid, text="--.- °C",
                                 bg=CARD_BG, fg=TEXT_MAIN,
                                 font=("Consolas", 11, "bold"))
        self.lbl_lm35.grid(row=1, column=0, sticky="w", pady=(0, 4))

        tk.Label(info_grid, text="DHT22 Temp",
                 bg=CARD_BG, fg=TEXT_MUTED,
                 font=("Consolas", 9)).grid(row=0, column=1, sticky="w", padx=10)
        self.lbl_dht_t = tk.Label(info_grid, text="--.- °C",
                                  bg=CARD_BG, fg=TEXT_MAIN,
                                  font=("Consolas", 11, "bold"))
        self.lbl_dht_t.grid(row=1, column=1, sticky="w", padx=10, pady=(0, 4))

        tk.Label(info_grid, text="Humidity",
                 bg=CARD_BG, fg=TEXT_MUTED,
                 font=("Consolas", 9)).grid(row=0, column=2, sticky="w")
        self.lbl_dht_h = tk.Label(info_grid, text="-- %",
                                  bg=CARD_BG, fg=TEXT_MAIN,
                                  font=("Consolas", 11, "bold"))
        self.lbl_dht_h.grid(row=1, column=2, sticky="w", pady=(0, 4))

        tk.Label(info_grid, text="Distance (IR)",
                 bg=CARD_BG, fg=TEXT_MUTED,
                 font=("Consolas", 9)).grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.lbl_dist = tk.Label(info_grid, text="-- cm",
                                 bg=CARD_BG, fg=TEXT_MAIN,
                                 font=("Consolas", 10, "bold"))
        self.lbl_dist.grid(row=3, column=0, sticky="w")

        self.lbl_connected_status = tk.Label(
            info_grid, text="Laptop: --",
            bg=CARD_BG, fg=TEXT_MUTED, font=("Consolas", 9)
        )
        self.lbl_connected_status.grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )

        tk.Label(info_grid, text="Light Level",
                 bg=CARD_BG, fg=TEXT_MUTED,
                 font=("Consolas", 9)).grid(row=2, column=1, sticky="w", padx=10, pady=(6, 0))
        self.lbl_lux = tk.Label(info_grid, text="-- lx",
                                bg=CARD_BG, fg=TEXT_MAIN,
                                font=("Consolas", 10, "bold"))
        self.lbl_lux.grid(row=3, column=1, sticky="w", padx=10)

        self.lbl_lux_mode = tk.Label(
            info_grid, text="RGB: --",
            bg=CARD_BG, fg=TEXT_MUTED, font=("Consolas", 9)
        )
        self.lbl_lux_mode.grid(row=4, column=1, columnspan=2,
                               sticky="w", padx=10, pady=(4, 0))

        # Fan & RGB control card
        self.card_fan = self.make_card(right_panel, title="Fan & RGB Controls")

        fan_top = tk.Frame(self.card_fan, bg=CARD_BG)
        fan_top.pack(fill="x", padx=10, pady=(8, 4))

        self.fan_anim_canvas = tk.Canvas(
            fan_top,
            width=70,
            height=70,
            bg=CARD_BG,
            highlightthickness=0
        )
        self.fan_anim_canvas.pack(side="left", padx=(0, 10))
        self.fan_anim_canvas.create_oval(
            29, 29, 41, 41, fill="#020617",
            outline=ACCENT_YELLOW, width=2
        )
        self.fan_blades = []
        self.init_fan_blades()

        fan_info = tk.Frame(fan_top, bg=CARD_BG)
        fan_info.pack(side="left", fill="both", expand=True)

        tk.Label(
            fan_info, text="Fan Duty",
            bg=CARD_BG, fg=TEXT_MUTED,
            font=("Consolas", 9)
        ).pack(anchor="w")

        self.lbl_fan_duty = tk.Label(
            fan_info, text="0 %",
            bg=CARD_BG, fg=TEXT_MAIN,
            font=("Consolas", 11, "bold")
        )
        self.lbl_fan_duty.pack(anchor="w", pady=(2, 2))

        self.fan_bar = ttk.Progressbar(
            fan_info,
            style="Yellow.Horizontal.TProgressbar",
            orient="horizontal",
            mode="determinate",
            length=240,
            maximum=100
        )
        self.fan_bar.pack(pady=(0, 4))

        self.lbl_temp_warn = tk.Label(
            fan_info,
            text="Temperature OK",
            bg=CARD_BG,
            fg=OK_GREEN,
            font=("Consolas", 9, "bold")
        )
        self.lbl_temp_warn.pack(anchor="w")

        # MODE buttons
        ctrl_row = tk.Frame(self.card_fan, bg=CARD_BG)
        ctrl_row.pack(fill="x", padx=10, pady=(6, 4))

        self.btn_auto = ttk.Button(
            ctrl_row, text="AUTO MODE",
            style="Accent.TButton",
            command=lambda: self.send_mode("AUTO")
        )
        self.btn_auto.pack(side="left", expand=True, fill="x", padx=(0, 4))

        self.btn_manual = ttk.Button(
            ctrl_row, text="MANUAL MODE",
            style="Secondary.TButton",
            command=lambda: self.send_mode("MANUAL")
        )
        self.btn_manual.pack(side="left", expand=True, fill="x", padx=(4, 0))

        # Manual fan slider
        slider_frame = tk.Frame(self.card_fan, bg=CARD_BG)
        slider_frame.pack(fill="x", padx=10, pady=(4, 2))

        tk.Label(
            slider_frame,
            text="Manual Fan Control (GUI)",
            bg=CARD_BG, fg=TEXT_MUTED,
            font=("Consolas", 9)
        ).pack(anchor="w")

        self.fan_slider = tk.Scale(
            slider_frame,
            from_=0,
            to=100,
            orient="horizontal",
            bg=CARD_BG,
            troughcolor="#020617",
            highlightthickness=0,
            showvalue=False,
            fg=TEXT_MAIN,
            relief="flat",
            length=260,
            sliderrelief="flat",
            sliderlength=16,
            font=("Consolas", 9)
        )
        self.fan_slider.set(0)
        self.fan_slider.pack(fill="x", pady=(2, 4))
        self.fan_slider.bind("<ButtonPress-1>", self.on_slider_press)
        self.fan_slider.bind("<ButtonRelease-1>", self.on_slider_release)

        # RGB mode buttons
        rgb_ctrl = tk.Frame(self.card_fan, bg=CARD_BG)
        rgb_ctrl.pack(fill="x", padx=10, pady=(2, 10))

        tk.Label(
            rgb_ctrl, text="RGB Strip Mode",
            bg=CARD_BG, fg=TEXT_MUTED,
            font=("Consolas", 9, "bold")
        ).pack(anchor="w")

        rgb_btns = tk.Frame(rgb_ctrl, bg=CARD_BG)
        rgb_btns.pack(fill="x", pady=(4, 0))

        self.btn_rgb_auto = ttk.Button(
            rgb_btns, text="AUTO", style="Accent.TButton",
            command=lambda: self.set_rgb_mode("AUTO")
        )
        self.btn_rgb_auto.pack(side="left", expand=True, fill="x", padx=(0, 3))

        self.btn_rgb_on = ttk.Button(
            rgb_btns, text="ON", style="Grey.TButton",
            command=lambda: self.set_rgb_mode("ON")
        )
        self.btn_rgb_on.pack(side="left", expand=True, fill="x", padx=3)

        self.btn_rgb_off = ttk.Button(
            rgb_btns, text="OFF", style="Grey.TButton",
            command=lambda: self.set_rgb_mode("OFF")
        )
        self.btn_rgb_off.pack(side="left", expand=True, fill="x", padx=(3, 0))

        self.lbl_status = ttk.Label(
            self.card_fan,
            text="Waiting for ESP32...",
            background=CARD_BG,
            foreground=TEXT_MUTED,
            font=("Consolas", 8)
        )
        self.lbl_status.pack(anchor="w", padx=10, pady=(0, 6))

        # ==== LIVE GRAPH UNDER RIGHT PANEL (slightly smaller) ====
        graph_card = tk.Frame(right_panel, bg=CARD_BG)
        graph_card.pack(side="top", fill="both", expand=True, pady=(8, 0))

        self.graph_title_label = tk.Label(
            graph_card,
            text="Live Temperature Graph",
            bg=CARD_BG,
            fg=TEXT_MUTED,
            font=("Consolas", 9, "bold")
        )
        self.graph_title_label.pack(anchor="w", padx=10, pady=(6, 0))

        # Reduced height so values fit nicely
        self.fig = Figure(figsize=(7.5, 2.4), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor("#020617")
        self.fig.patch.set_facecolor(CARD_BG)

        self.ax.set_xlabel("Time (s)", color=TEXT_MUTED, fontname="Consolas")
        self.ax.set_ylabel("Temperature (°C)", color=TEXT_MUTED,
                           fontname="Consolas")
        # slightly smaller tick font size
        self.ax.tick_params(colors=TEXT_MUTED, labelsize=8)
        for spine in self.ax.spines.values():
            spine.set_color("#374151")
        self.ax.grid(True, color="#1f2937", linestyle="--",
                     linewidth=0.6, alpha=0.7)

        self.line_lm35, = self.ax.plot([], [], label="LM35",
                                       linewidth=2.0, color="#38bdf8")
        self.line_dhtt, = self.ax.plot([], [], label="DHT Temp",
                                       linewidth=2.0, linestyle="--",
                                       color="#f97316")

        self.ax.legend(facecolor="#020617", edgecolor="#4b5563",
                       labelcolor=TEXT_MUTED, fontsize=8)

        self.canvas = FigureCanvasTkAgg(self.fig, master=graph_card)
        self.canvas.get_tk_widget().pack(fill="both", expand=True,
                                         padx=10, pady=8)

        # bottom tabs
        tabs_frame = tk.Frame(graph_card, bg=CARD_BG)
        tabs_frame.pack(fill="x", padx=10, pady=(0, 6))

        tab_kwargs = dict(
            bg="#020617",
            fg=TEXT_MUTED,
            activebackground="#020617",
            activeforeground=ACCENT_YELLOW,
            bd=0,
            relief="flat",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=4
        )

        self.btn_tab_temp = tk.Button(
            tabs_frame, text="Temperature",
            command=lambda: self.set_graph_mode("Temperature"),
            **tab_kwargs
        )
        self.btn_tab_temp.pack(side="left")

        self.btn_tab_usage = tk.Button(
            tabs_frame, text="Usage",
            command=lambda: self.set_graph_mode("Usage"),
            **tab_kwargs
        )
        self.btn_tab_usage.pack(side="left", padx=(4, 0))

        self.btn_tab_fan = tk.Button(
            tabs_frame, text="Fan",
            command=lambda: self.set_graph_mode("Fan"),
            **tab_kwargs
        )
        self.btn_tab_fan.pack(side="left", padx=(4, 0))

        self.btn_tab_voltage = tk.Button(
            tabs_frame, text="Voltage",
            command=lambda: self.set_graph_mode("Voltage"),
            **tab_kwargs
        )
        self.btn_tab_voltage.pack(side="left", padx=(4, 0))

        self.set_graph_mode("Temperature")

    # ---------- static big temp gauge ----------
    def draw_temp_gauge_static(self):
        cx = self.gauge_cx
        cy = self.gauge_cy
        r = self.gauge_radius

        n_segments = 90
        start = self.gauge_start_angle
        end = self.gauge_end_angle
        total_extent = end - start     # -360
        step = total_extent / n_segments

        green = "#22c55e"
        yellow = "#facc15"
        red = "#ef4444"

        for i in range(n_segments):
            t = i / (n_segments - 1)
            if t < 0.5:
                local_t = t / 0.5
                color = lerp_color(green, yellow, local_t)
            else:
                local_t = (t - 0.5) / 0.5
                color = lerp_color(yellow, red, local_t)

            start_i = start + i * step
            self.gauge_canvas.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=start_i,
                extent=step,
                style="arc",
                outline=color,
                width=20
            )

        inner_r = 70
        self.gauge_canvas.create_oval(
            cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r,
            fill="#020617", outline="#111827", width=2
        )

        self.temp_label = self.gauge_canvas.create_text(
            cx, cy - 6,
            text="0.0°C",
            fill=ACCENT_YELLOW,
            font=("Consolas", 18, "bold")
        )
        self.gauge_canvas.create_text(
            cx, cy + 22,
            text="CPU TEMPERATURE",
            fill=TEXT_MUTED,
            font=("Consolas", 9, "bold")
        )

        for frac, label in [(0.0, "0°"), (0.5, "40°"), (1.0, "80°")]:
            angle = self.gauge_start_angle + frac * (self.gauge_end_angle - self.gauge_start_angle)
            theta = math.radians(angle)
            r_text = r + 8
            x = cx + r_text * math.cos(theta)
            y = cy - r_text * math.sin(theta)
            self.gauge_canvas.create_text(
                x, y,
                text=label,
                fill=TEXT_MUTED,
                font=("Consolas", 8)
            )

        self.temp_needle = self.gauge_canvas.create_line(
            cx, cy, cx, cy - (r - 30),
            fill="#f9fafb",
            width=3,
            capstyle="round"
        )

    # ---------- small helpers ----------
    def make_card(self, parent, title=""):
        wrapper = tk.Frame(parent, bg=BG_COLOR)
        wrapper.pack(fill="x", expand=False, pady=4)

        card = ttk.Frame(wrapper, style="Card.TFrame")
        card.pack(fill="x", expand=True)

        ttk.Label(card, text=title, style="Muted.TLabel").pack(
            anchor="w", padx=10, pady=(6, 0)
        )
        return card

    def make_tool_button(self, parent, text, command, bg="#020617", fg=TEXT_MUTED):
        btn = tk.Button(
            parent,
            text=text,
            justify="center",
            bg=bg,
            fg=fg,
            activebackground="#111827",
            activeforeground=ACCENT_YELLOW,
            bd=0,
            relief="flat",
            font=("Consolas", 9, "bold"),
            command=command
        )
        btn.pack(fill="x", padx=6, pady=6, ipady=6)

    # =============== HEADING & MODE ANIMATION ===============
    def animate_heading(self, index):
        if index <= len(self.heading_full_text):
            self.heading_label.configure(
                text=self.heading_full_text[:index]
            )
            self.root.after(40, lambda: self.animate_heading(index + 1))
        else:
            self.animate_heading_color()

    def animate_heading_color(self):
        self.heading_color_phase += 0.08
        t = (math.sin(self.heading_color_phase) + 1) / 2
        light_yellow = "#fef9c3"
        dark_yellow = "#f59e0b"
        color = lerp_color(light_yellow, dark_yellow, t)
        self.heading_label.configure(foreground=color)
        self.root.after(80, self.animate_heading_color)

    def animate_mode_pulse(self):
        # Pulsating MODE: label
        self.mode_pulse_phase += 0.12
        t = (math.sin(self.mode_pulse_phase) + 1) / 2
        light = "#fef9c3"
        dark = "#f59e0b"
        color = lerp_color(light, dark, t)
        self.lbl_mode.configure(foreground=color)
        self.root.after(90, self.animate_mode_pulse)

    # =============== FAN SHAPES (right mini fan) ===============
    def init_fan_blades(self):
        cx, cy = 35, 35
        r_outer = 22
        r_inner = 10
        blade_width = 9
        self.fan_blades = []
        for base_angle in (0, 120, 240):
            blade = self.create_blade(
                self.fan_anim_canvas, cx, cy,
                r_inner, r_outer, blade_width, base_angle
            )
            self.fan_blades.append(blade)

    def create_blade(self, canvas, cx, cy, r_inner, r_outer, width, angle_deg):
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

    def rotate_blades(self, delta_angle):
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

    # =============== ANIMATIONS ===============
    def start_animations(self):
        self.animate_breath()
        self.animate_rgb_border()
        self.animate_fan()
        self.animate_mode_pulse()   # new pulse

    def animate_breath(self):
        self.breath_phase += 0.18
        scale = (math.sin(self.breath_phase) + 1) / 2
        width = 1.5 + scale * 2.0
        color = ACCENT_YELLOW if scale > 0.4 else NEON_PURPLE
        self.conn_canvas.itemconfig(self.conn_outer, width=width, outline=color)
        self.root.after(80, self.animate_breath)

    def animate_rgb_border(self):
        if self.rgb_mode == "ON":
            effective_on = True
        elif self.rgb_mode == "OFF":
            effective_on = False
        else:
            effective_on = self.rgb_enabled

        if effective_on:
            self.rgb_hue = (self.rgb_hue + 3) % 360
            color = hsv_to_hex(self.rgb_hue, 1.0, 1.0)
        else:
            color = "#020617"

        for border in (self.border_top, self.border_bottom,
                       self.border_left, self.border_right):
            border.configure(bg=color)

        self.root.after(60, self.animate_rgb_border)

    def animate_fan(self):
        if self.current_fan_percent < 3:
            delta = 0
            delay = 120
            blade_color = "#1f2937"
        else:
            delta = 6 + self.current_fan_percent * 0.3
            delay = max(20, int(120 - self.current_fan_percent))
            blade_color = ACCENT_YELLOW

        for blade_id in self.fan_blades:
            self.fan_anim_canvas.itemconfig(blade_id, fill=blade_color)

        if delta != 0:
            self.rotate_blades(delta)

        self.root.after(delay, self.animate_fan)

    # =============== FAN TEST SLIDER ANIMATION ===============
    def start_fan_test_animation(self, duration=4.0):
        """Start a short animation on the Manual Fan slider / bar."""
        self.test_fan_animating = True
        self.test_fan_anim_start = time.time()
        # block auto-updates from poll_status while animating
        self.slider_dragging = True
        self._fan_test_step(duration)

    def _fan_test_step(self, duration):
        if not self.test_fan_animating:
            return

        elapsed = time.time() - self.test_fan_anim_start
        if elapsed >= duration:
            # stop animation, return control to normal updates
            self.test_fan_animating = False
            self.slider_dragging = False
            return

        # triangle wave between 0 and 100 %
        cycle = (elapsed % 1.0) / 1.0          # 0..1 each second
        if cycle < 0.5:
            val = cycle * 2 * 100             # 0 → 100
        else:
            val = (1.0 - cycle) * 2 * 100     # 100 → 0

        # update slider + fan meter
        self.fan_slider.set(val)
        self.update_fan_meter(val)

        # schedule next frame
        self.root.after(70, lambda: self._fan_test_step(duration))

    # =============== RGB MODE BUTTONS (HTTP /rgb) ===============
    def set_rgb_mode(self, mode):
        self.rgb_mode = mode
        if mode == "AUTO":
            self.btn_rgb_auto.configure(style="Accent.TButton")
            self.btn_rgb_on.configure(style="Grey.TButton")
            self.btn_rgb_off.configure(style="Grey.TButton")
        elif mode == "ON":
            self.btn_rgb_auto.configure(style="Grey.TButton")
            self.btn_rgb_on.configure(style="Accent.TButton")
            self.btn_rgb_off.configure(style="Grey.TButton")
        else:
            self.btn_rgb_auto.configure(style="Grey.TButton")
            self.btn_rgb_on.configure(style="Grey.TButton")
            self.btn_rgb_off.configure(style="Accent.TButton")

        def worker():
            try:
                if mode == "AUTO":
                    url = f"{ESP32_IP}/rgb?release=1"
                elif mode == "ON":
                    url = f"{ESP32_IP}/rgb?state=ON"
                else:
                    url = f"{ESP32_IP}/rgb?state=OFF"

                r = requests.get(url, timeout=1.0)
                if r.status_code == 200:
                    txt = r.text.strip()
                    msg = f"RGB mode → {mode} ({txt})"
                else:
                    msg = f"RGB mode {mode} failed ({r.status_code})"
            except Exception as e:
                msg = f"RGB mode error: {e}"
            self.root.after(0, lambda: self.set_status(msg))

        threading.Thread(target=worker, daemon=True).start()

    # =============== GRAPH TABS ===============
    def set_graph_mode(self, mode):
        self.graph_mode = mode

        inactive_bg = "#020617"
        inactive_fg = TEXT_MUTED
        active_bg = "#020617"
        active_fg = ACCENT_YELLOW

        for btn in (
            self.btn_tab_temp,
            self.btn_tab_usage,
            self.btn_tab_fan,
            self.btn_tab_voltage,
        ):
            btn.configure(bg=inactive_bg, fg=inactive_fg)

        if mode == "Temperature":
            self.btn_tab_temp.configure(bg=active_bg, fg=active_fg)
            title = "Live Temperature Graph"
            ylabel = "Temperature (°C)"
            lm_label = "LM35"
            dht_label = "DHT Temp"
        elif mode == "Usage":
            self.btn_tab_usage.configure(bg=active_bg, fg=active_fg)
            title = "CPU Usage View (scaled)"
            ylabel = "Value (arb. units)"
            lm_label = "CPU Load"
            dht_label = "Ambient Load"
        elif mode == "Fan":
            self.btn_tab_fan.configure(bg=active_bg, fg=active_fg)
            title = "Fan Response View"
            ylabel = "Value (arb. units)"
            lm_label = "Base Temp"
            dht_label = "Ambient Temp"
        else:
            self.btn_tab_voltage.configure(bg=active_bg, fg=active_fg)
            title = "Sensor Voltage View (scaled)"
            ylabel = "Value (arb. units)"
            lm_label = "LM35 Channel"
            dht_label = "DHT Channel"

        self.graph_title_label.configure(text=title)
        self.ax.set_ylabel(ylabel, color=TEXT_MUTED, fontname="Consolas")
        self.line_lm35.set_label(lm_label)
        self.line_dhtt.set_label(dht_label)
        self.ax.legend(facecolor="#020617", edgecolor="#4b5563",
                       labelcolor=TEXT_MUTED, fontsize=8)
        self.canvas.draw_idle()

    # =============== SLIDER EVENTS ===============
    def on_slider_press(self, event):
        self.slider_dragging = True

    def on_slider_release(self, event):
        self.slider_dragging = False
        if self.current_mode.upper() == "MANUAL":
            percent = self.fan_slider.get()
            self.send_fan_set(int(percent))

    # =============== NETWORK =================
    def poll_status(self):
        def worker():
            try:
                r = requests.get(f"{ESP32_IP}/status", timeout=0.8)
                if r.status_code == 200:
                    data = r.json()
                    self.root.after(0, lambda: self.update_ui(data, True))
                else:
                    self.root.after(0, lambda: self.update_ui(None, False))
            except Exception:
                self.root.after(0, lambda: self.update_ui(None, False))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(POLL_INTERVAL_MS, self.poll_status)

    def send_mode(self, mode):
        def worker():
            try:
                r = requests.get(f"{ESP32_IP}/setMode?mode={mode}", timeout=0.8)
                if r.status_code == 200:
                    txt = r.text.strip()
                    msg = f"Set mode → {mode} ({txt})"
                else:
                    msg = f"Failed to set mode ({r.status_code})"
            except Exception as e:
                msg = f"Error setting mode: {e}"
            self.root.after(0, lambda: self.set_status(msg))

        threading.Thread(target=worker, daemon=True).start()

    def send_fan_set(self, percent):
        duty = int(max(0, min(100, percent)) * 255 / 100)

        def worker():
            try:
                r = requests.get(f"{ESP32_IP}/fan?duty={duty}", timeout=1.0)
                if r.status_code == 200:
                    txt = r.text.strip()
                    msg = f"Manual fan set to {percent}% ({txt})"
                else:
                    msg = f"Set fan failed ({r.status_code})"
            except Exception as e:
                msg = f"Set fan error: {e}"
            self.root.after(0, lambda: self.set_status(msg))
        threading.Thread(target=worker, daemon=True).start()

    # ---- TEST BUTTONS: ONLY IN MANUAL, 4s pulse + slider animation ----
    def send_test(self, device):
        if self.current_mode.upper() != "MANUAL":
            self.set_status("Test controls are available only in MANUAL MODE")
            return

        def worker():
            try:
                if device == "fan":
                    url_on = f"{ESP32_IP}/fan?duty=200"
                    url_off = f"{ESP32_IP}/fan?duty=0"
                elif device == "buzzer":
                    url_on = f"{ESP32_IP}/buzzer?pattern=2"
                    url_off = None
                elif device == "rgb":
                    url_on = f"{ESP32_IP}/rgb?state=ON"
                    url_off = f"{ESP32_IP}/rgb?state=OFF"
                else:
                    self.root.after(0, lambda: self.set_status("Unknown test device"))
                    return

                # Turn ON
                r = requests.get(url_on, timeout=1.0)
                if r.status_code == 200:
                    txt = r.text.strip()
                    msg = f"Test {device}: ON ({txt})"
                    # start GUI animation when FAN test begins
                    if device == "fan":
                        self.root.after(0, self.start_fan_test_animation)
                else:
                    msg = f"Test {device} ON failed ({r.status_code})"
                self.root.after(0, lambda: self.set_status(msg))

                # keep ON for 4 seconds
                time.sleep(4.0)

                # Turn OFF (if we have an OFF command)
                if url_off is not None:
                    try:
                        r2 = requests.get(url_off, timeout=1.0)
                        if r2.status_code == 200:
                            txt2 = r2.text.strip()
                            msg2 = f"Test {device}: OFF ({txt2})"
                        else:
                            msg2 = f"Test {device} OFF failed ({r2.status_code})"
                        self.root.after(0, lambda: self.set_status(msg2))
                    except Exception as e2:
                        self.root.after(
                            0,
                            lambda: self.set_status(f"Test {device} OFF error: {e2}")
                        )

            except Exception as e:
                msg = f"Test {device} error: {e}"
                self.root.after(0, lambda: self.set_status(msg))

        threading.Thread(target=worker, daemon=True).start()

    # =============== UI UPDATE ===============
    def set_status(self, msg):
        self.lbl_status.configure(text=msg)

    def show_connect_popup(self, connected: bool):
        msg = "Laptop Connected" if connected else "Laptop Disconnected"
        color = OK_GREEN if connected else DANGER_RED

        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg="#020617")

        w, h = 260, 80
        sw = popup.winfo_screenwidth()
        sh = popup.winfo_screenheight()
        x = sw - w - 40
        y_start = sh
        y_end = sh - h - 80
        popup.geometry(f"{w}x{h}+{x}+{y_start}")

        frame = tk.Frame(popup, bg=CARD_BG)
        frame.pack(fill="both", expand=True)

        bar = tk.Frame(frame, bg=color, height=3)
        bar.pack(fill="x", side="top")

        tk.Label(
            frame, text=msg,
            bg=CARD_BG, fg=color,
            font=("Consolas", 11, "bold")
        ).pack(pady=(12, 4))

        tk.Label(
            frame, text="Smart Cooling Pad",
            bg=CARD_BG, fg=TEXT_MUTED,
            font=("Consolas", 9)
        ).pack()

        steps = 18
        dy = (y_start - y_end) / steps

        def slide(step=0):
            new_y = int(y_start - dy * step)
            popup.geometry(f"{w}x{h}+{x}+{new_y}")
            if step < steps:
                popup.after(16, lambda: slide(step + 1))
            else:
                popup.after(1500, popup.destroy)

        slide()

    def update_ui(self, data, online: bool):
        if online and data is not None:
            self.pulse_state = not self.pulse_state
            fill_color = ACCENT_YELLOW if self.pulse_state else OK_GREEN
            self.conn_canvas.itemconfig(self.conn_dot, fill=fill_color)
            self.lbl_conn_text.configure(text="ONLINE", foreground=OK_GREEN)
            self.set_status("Connected to ESP32")
        else:
            self.conn_canvas.itemconfig(self.conn_dot, fill=TEXT_MUTED)
            self.lbl_conn_text.configure(text="OFFLINE", foreground=DANGER_RED)
            self.set_status("ESP32 offline / no response")
            return

        mode      = data.get("mode", "--")
        self.current_mode = mode
        lm35      = float(data.get("lm35", 0.0))
        dht_t     = float(data.get("dhtTemp", 0.0))
        dht_h     = float(data.get("dhtHum", 0.0))
        dist      = float(data.get("dist", 0.0))
        lux       = float(data.get("lux", 0.0))
        fan_duty  = int(data.get("fanDuty", 0))
        connected = bool(data.get("connected", False))

        if self.last_connected is not None and connected != self.last_connected:
            self.show_connect_popup(connected)
        self.last_connected = connected

        self.lbl_mode.configure(text=f"MODE: {mode}")
        if mode.upper() == "AUTO":
            self.btn_auto.configure(style="Accent.TButton")
            self.btn_manual.configure(style="Secondary.TButton")
            self.fan_slider.configure(state="disabled")
        else:
            self.btn_auto.configure(style="Secondary.TButton")
            self.btn_manual.configure(style="Accent.TButton")
            self.fan_slider.configure(state="normal")

        self.lbl_lm35.configure(text=f"{lm35:.1f} °C")
        self.lbl_dht_t.configure(text=f"{dht_t:.1f} °C")
        self.lbl_dht_h.configure(text=f"{dht_h:.0f} %")
        self.lbl_dist.configure(text=f"{dist:.0f} cm")
        self.lbl_lux.configure(text=f"{lux:.0f} lx")

        self.lbl_digital_dht.configure(text=f"{dht_t:4.1f}°C")
        self.lbl_digital_hum.configure(text=f"{dht_h:3.0f}%")

        if connected:
            self.lbl_connected_status.configure(
                text="Laptop: CONNECTED", fg=OK_GREEN
            )
        else:
            self.lbl_connected_status.configure(
                text="Laptop: NOT CONNECTED", fg=TEXT_MUTED
            )

        if lm35 > 50.0:
            self.lbl_temp_warn.configure(
                text="⚠ OVER-TEMPERATURE!", fg=DANGER_RED
            )
            if not self.alert_visible:
                self.alert_frame.pack(
                    in_=self.content_root,
                    fill="x",
                    padx=20,
                    pady=(0, 4),
                    before=self.main_frame
                )
                self.alert_visible = True
        elif lm35 > 40.0:
            self.lbl_temp_warn.configure(
                text="High temperature, fan at MAX", fg=ACCENT_YELLOW
            )
            if self.alert_visible:
                self.alert_frame.pack_forget()
                self.alert_visible = False
        else:
            self.lbl_temp_warn.configure(
                text="Temperature OK", fg=OK_GREEN
            )
            if self.alert_visible:
                self.alert_frame.pack_forget()
                self.alert_visible = False

        sensor_rgb_on = False
        if mode.upper() == "AUTO":
            if connected and lux < 99.0:
                sensor_rgb_on = True
        else:
            if connected:
                sensor_rgb_on = True
        self.rgb_enabled = sensor_rgb_on

        if self.rgb_mode == "OFF":
            self.lbl_lux_mode.configure(
                text="RGB: FORCED OFF", fg=TEXT_MUTED
            )
        elif self.rgb_mode == "ON":
            self.lbl_lux_mode.configure(
                text="RGB: MANUAL ON", fg=ACCENT_YELLOW
            )
        else:
            if connected and lux < 99.0:
                self.lbl_lux_mode.configure(
                    text="RGB: CHASING (AUTO)", fg=ACCENT_YELLOW
                )
            elif connected:
                self.lbl_lux_mode.configure(
                    text="RGB: OFF (bright, AUTO)", fg=TEXT_MUTED
                )
            else:
                self.lbl_lux_mode.configure(
                    text="RGB: OFF (no laptop, AUTO)", fg=TEXT_MUTED
                )

        fan_percent = (fan_duty / 255.0) * 100.0
        self.current_fan_percent = fan_percent
        self.fan_bar["value"] = fan_percent
        self.lbl_fan_duty.configure(text=f"{fan_percent:.0f} %")

        if not self.slider_dragging:
            self.fan_slider.set(fan_percent)

        self.update_gauge(lm35)
        self.update_fan_meter(fan_percent)
        self.update_graph(lm35, dht_t)

    # =============== GAUGE & FAN METER ===============
    def update_gauge(self, lm35):
        cx = self.gauge_cx
        cy = self.gauge_cy
        r = self.gauge_radius - 30
        lm35_clamped = max(0.0, min(80.0, lm35))
        angle = self.gauge_start_angle + (lm35_clamped / 80.0) * (self.gauge_end_angle - self.gauge_start_angle)
        theta = math.radians(angle)
        x_end = cx + r * math.cos(theta)
        y_end = cy - r * math.sin(theta)
        self.gauge_canvas.coords(self.temp_needle, cx, cy, x_end, y_end)
        self.gauge_canvas.itemconfig(self.temp_label, text=f"{lm35:.1f}°C")

    def update_fan_meter(self, percent):
        p = max(0.0, min(100.0, percent))
        x_min = 42
        x_max = 338
        x_fill = x_min + (x_max - x_min) * (p / 100.0)
        self.fan_canvas.coords(
            self.fan_meter_fill,
            x_min, 38, x_fill, 56
        )
        self.fan_canvas.coords(
            self.fan_meter_needle,
            x_fill, 62, x_fill, 68
        )
        self.fan_canvas.itemconfig(
            self.fan_seven_label,
            text=f"FAN {int(p):03d} %"
        )

    # =============== GRAPH ===============
    def update_graph(self, lm35, dhtt):
        now = time.time() - self.start_time
        self.time_hist.append(now)
        self.lm35_hist.append(lm35)
        self.dhtt_hist.append(dhtt)

        while self.time_hist and (now - self.time_hist[0]) > MAX_HISTORY_SECONDS:
            self.time_hist.pop(0)
            self.lm35_hist.pop(0)
            self.dhtt_hist.pop(0)

        self.line_lm35.set_data(self.time_hist, self.lm35_hist)
        self.line_dhtt.set_data(self.time_hist, self.dhtt_hist)

        if self.time_hist:
            t_min = max(0, self.time_hist[-1] - MAX_HISTORY_SECONDS)
            t_max = self.time_hist[-1] + 1
            self.ax.set_xlim(t_min, t_max)

            all_temp = self.lm35_hist + self.dhtt_hist
            ymin = min(all_temp) - 2
            ymax = max(all_temp) + 2
            if ymin == ymax:
                ymin -= 1
                ymax += 1
            self.ax.set_ylim(ymin, ymax)

        self.canvas.draw_idle()


# =============== SPLASH ===============
def show_splash(root, on_done):
    BG = BG_COLOR
    splash = tk.Toplevel(root)
    splash.overrideredirect(True)
    splash.configure(bg=BG)

    sw = splash.winfo_screenwidth()
    sh = splash.winfo_screenheight()
    w, h = 520, 250
    x = int(sw / 2 - w / 2)
    y = int(sh / 2 - h / 2)
    splash.geometry(f"{w}x{h}+{x}+{y}")

    frame = tk.Frame(splash, bg=CARD_BG)
    frame.pack(fill="both", expand=True)

    tk.Label(
        frame,
        text="Smart Laptop Cooling Pad",
        bg=CARD_BG,
        fg=ACCENT_YELLOW,
        font=("Consolas", 18, "bold"),
    ).pack(pady=(35, 6))

    tk.Label(
        frame,
        text="Starting system...",
        bg=CARD_BG,
        fg=TEXT_MUTED,
        font=("Consolas", 10),
    ).pack()

    bar_frame = tk.Frame(frame, bg=CARD_BG)
    bar_frame.pack(pady=(30, 10))

    pb = ttk.Progressbar(
        bar_frame,
        orient="horizontal",
        mode="indeterminate",
        length=340,
        maximum=120,
    )
    pb.pack()

    tk.Label(
        frame,
        text="Initializing ESP32, sensors and GUI...",
        bg=CARD_BG,
        fg=TEXT_MUTED,
        font=("Consolas", 9),
    ).pack(pady=(4, 0))

    pb.start(10)

    def finish():
        pb.stop()
        splash.destroy()
        root.deiconify()
        on_done()

    root.after(2400, finish)


if __name__ == "__main__":
    root = tk.Tk()
    root.configure(bg=BG_COLOR)
    root.withdraw()

    def start_app():
        CoolingPadGUI(root)

    show_splash(root, start_app)
    root.mainloop()
