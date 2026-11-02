#!/usr/bin/env python3
"""
Torn Flip Finder - desktop dashboard for the item market flip finder.

Run:  python torn_flipper_gui.py   (or double-click torn_flipper_gui.pyw)

Uses the same logic as torn_flipper.py. Read-only: it suggests flips and links
to the market page, you buy and list in Torn yourself.
"""
import argparse
import ctypes
import queue
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

import torn_flipper as tf

# ------------------------------------------------------------------ look & feel

BG = "#0f1115"        # window
PANEL = "#171a20"     # cards
PANEL_ALT = "#1b1f26" # striped rows
FIELD = "#232831"     # inputs, buttons
HOVER = "#2d333e"
BORDER = "#2a2f39"
TEXT = "#e8eaee"
MUTED = "#8b93a1"
DIM = "#5b6270"
GREEN = "#3fb950"
GREEN_HI = "#52c963"
GREEN_TXT = "#7ee28a"
GREEN_SEL = "#22402b"
BLUE = "#58a6ff"
YELLOW = "#e3b341"
RED = "#f06a6a"
FONT = "Segoe UI"

SCALE = 1.0  # set in main() from the screen DPI


def px(n):
    return int(n * SCALE)


# (key, heading, width, anchor)
# List price, ROI and affordable quantity are in the detail panel to keep the table readable.
COLUMNS = [
    ("name", "ITEM", 165, "w"),
    ("low", "LOWEST", 100, "e"),
    ("qty", "QTY", 48, "e"),
    ("cost_all", "COST ALL", 108, "e"),
    ("second", "2ND LOWEST", 100, "e"),
    ("gap_pct", "GAP", 60, "e"),
    ("profit_yours", "YOUR PROFIT", 105, "e"),
    ("liquidity", "LIQUIDITY", 112, "w"),
]
MONEY_COLS = {"low", "cost_all", "second", "sell_at", "profit_yours"}
PCT_COLS = {"gap_pct", "roi_pct"}
CUSTOM_MONEY = "Custom amount"
REFRESH_CHOICES = {"1 min": 60, "2 min": 120, "5 min": 300, "10 min": 600, "30 min": 1800}


def cell(r, key):
    if not r["ok"]:
        if key == "name":
            return "  " + r["name"]
        return "  no 2nd price" if key == "liquidity" else "—  "
    v = r[key]
    if key == "name":
        return "  " + v
    if key in MONEY_COLS:
        return tf.money(v) + "  "
    if key in PCT_COLS:
        return f"{v:.1f}%  "
    if key == "liquidity":
        return "  " + v
    return f"{v:,}  "


def parse_number(text, kind, label, allow_blank=False):
    s = str(text).replace(",", "").replace("$", "").strip()
    if not s and allow_blank:
        return None
    try:
        return kind(s)
    except ValueError:
        raise ValueError(f"{label} must be a number.")


def dark_title_bar(win):
    """Ask Windows 10/11 for a dark title bar. Harmless elsewhere."""
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        on = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on),
                                                           ctypes.sizeof(on)) == 0:
                break
    except Exception:
        pass


def apply_theme(root):
    st = ttk.Style(root)
    st.theme_use("clam")
    root.configure(bg=BG)
    st.configure(".", background=BG, foreground=TEXT, fieldbackground=FIELD,
                 bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, troughcolor=PANEL,
                 focuscolor=BORDER, selectbackground=GREEN_SEL, selectforeground=TEXT,
                 insertcolor=TEXT, font=(FONT, 10))

    # Buttons
    st.configure("TButton", background=FIELD, foreground=TEXT, borderwidth=0, relief="flat",
                 padding=(px(14), px(7)), focusthickness=0)
    st.map("TButton", background=[("disabled", PANEL), ("pressed", BORDER), ("active", HOVER)],
           foreground=[("disabled", DIM)])
    st.configure("Accent.TButton", background=GREEN, foreground="#07130a", font=(FONT, 10, "bold"))
    st.map("Accent.TButton",
           background=[("disabled", "#24402b"), ("pressed", "#35a446"), ("active", GREEN_HI)],
           foreground=[("disabled", "#5f7d65")])
    st.configure("Danger.TButton", foreground=RED)
    st.map("Danger.TButton", foreground=[("disabled", DIM)])
    st.configure("Link.TButton", background=PANEL, foreground=MUTED, padding=(px(6), px(3)),
                 font=(FONT, 9))
    st.map("Link.TButton", background=[("active", PANEL)], foreground=[("active", RED)])

    # Inputs
    for name in ("TEntry", "Hint.TEntry"):
        st.configure(name, fieldbackground=FIELD, foreground=TEXT, bordercolor=BORDER,
                     lightcolor=FIELD, darkcolor=FIELD, padding=(px(8), px(6)), insertcolor=TEXT)
        st.map(name, bordercolor=[("focus", GREEN)], lightcolor=[("focus", GREEN)])
    st.configure("Hint.TEntry", foreground=DIM)
    st.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=TEXT,
                 arrowcolor=MUTED, bordercolor=BORDER, lightcolor=FIELD, darkcolor=FIELD,
                 padding=(px(6), px(4)))
    st.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)],
           selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", TEXT)],
           background=[("active", HOVER)])
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", GREEN_SEL)
    root.option_add("*TCombobox*Listbox.font", (FONT, 10))

    st.configure("TCheckbutton", background=BG, foreground=TEXT, indicatorbackground=FIELD,
                 indicatorforeground="#07130a", indicatorrelief="flat", indicatormargin=px(4),
                 padding=px(2))
    st.map("TCheckbutton", background=[("active", BG)],
           indicatorbackground=[("selected", GREEN), ("active", HOVER)])
    st.configure("Panel.TCheckbutton", background=PANEL)
    st.map("Panel.TCheckbutton", background=[("active", PANEL)])

    # Tables
    st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    st.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                 rowheight=px(34), borderwidth=0, relief="flat", font=(FONT, 10))
    st.map("Treeview", background=[("selected", GREEN_SEL)], foreground=[("selected", TEXT)])
    st.configure("Treeview.Heading", background=PANEL, foreground=MUTED, relief="flat",
                 borderwidth=0, font=(FONT, 8, "bold"), padding=(px(6), px(10)))
    st.map("Treeview.Heading", background=[("active", PANEL)], foreground=[("active", TEXT)])
    st.configure("Side.Treeview", rowheight=px(32))

    st.configure("Vertical.TScrollbar", background=FIELD, troughcolor=PANEL, bordercolor=PANEL,
                 arrowcolor=MUTED, lightcolor=FIELD, darkcolor=FIELD, gripcount=0,
                 arrowsize=px(11))
    st.map("Vertical.TScrollbar", background=[("active", HOVER)])
    st.configure("Accent.Horizontal.TProgressbar", background=GREEN, troughcolor=PANEL,
                 bordercolor=BG, lightcolor=GREEN, darkcolor=GREEN, thickness=px(5))


class HintEntry(ttk.Entry):
    """Entry that shows grey hint text while empty."""

    def __init__(self, master, hint, **kw):
        self.var = tk.StringVar()
        super().__init__(master, textvariable=self.var, **kw)
        self.hint = hint
        self.showing_hint = False
        self.bind("<FocusIn>", self._focus_in, add="+")
        self.bind("<FocusOut>", self._focus_out, add="+")
        self._focus_out()

    def _focus_out(self, _e=None):
        if not self.var.get():
            self.showing_hint = True
            self.configure(style="Hint.TEntry")
            self.var.set(self.hint)

    def _focus_in(self, _e=None):
        if self.showing_hint:
            self.showing_hint = False
            self.var.set("")
            self.configure(style="TEntry")

    def value(self):
        return "" if self.showing_hint else self.var.get().strip()

    def clear(self):
        self.var.set("")
        if self.focus_get() is not self:
            self._focus_out()


class Tooltip:
    """Small popup shown while the mouse is over a widget (or its children)."""

    def __init__(self, widget, text_fn):
        self.widget, self.text_fn, self.tip = widget, text_fn, None
        for w in (widget, *widget.winfo_children()):
            w.bind("<Enter>", self.show, add="+")
            w.bind("<Leave>", self.hide, add="+")

    def show(self, _e=None):
        if self.tip:
            return
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.configure(bg=BORDER)
        tk.Label(self.tip, text=self.text_fn(), bg=FIELD, fg=TEXT, font=("Consolas", 9),
                 justify="left", padx=px(12), pady=px(8)).pack(padx=1, pady=1)
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + px(4)
        self.tip.wm_geometry(f"+{x}+{y}")

    def hide(self, _e=None):
        # Moving between the card and its labels fires Leave; only hide when really outside.
        x, y = self.widget.winfo_pointerxy()
        inside = self.widget.winfo_containing(x, y)
        while inside is not None and inside is not self.widget:
            inside = inside.master
        if inside is None and self.tip:
            self.tip.destroy()
            self.tip = None


# ------------------------------------------------------------------------ app

class App:
    def __init__(self, root):
        self.root = root
        self.cfg = tf.load_config()
        self.cfg.setdefault("money_override", None)
        self.cfg.setdefault("scan_items", 200)
        self.history = tf.load_json(tf.HISTORY_PATH, {})
        self.items = None          # item catalog
        self.names = []            # tradable item names, for autocomplete
        self.catalog_loading = False
        self.results = {}          # item id -> analysis
        self.seen_this_run = set()
        self.msgs = queue.Queue()
        self.stop_event = threading.Event()
        self.running = False
        self.last_mode = "check"
        self.after_id = None
        self.run_settings = None
        self.wallet = None         # money to spend, from the chosen balance source
        self.wallet_source = ""
        self.balance = None        # last /user/money result
        self.balance_error = None
        self.last_update = None
        self.current_id = None
        self.sort_key, self.sort_desc = "profit_yours", True

        root.title("Torn Flip Finder")
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = min(px(1500), sw - 40), min(px(900), sh - 80)
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 3)}")
        root.minsize(min(px(1100), sw - 40), min(px(680), sh - 80))
        if sw < px(1500) or sh < px(900):
            root.state("zoomed")  # small screen: use all of it

        self._build_header()
        self._build_statusbar()
        self._build_body()
        self.apply_money_source()

        root.bind("<F5>", lambda e: self.start("check"))
        root.bind("<Control-r>", lambda e: self.start("check"))
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self.poll)
        if self.cfg["api_key"]:
            self.load_catalog_async()
            self.refresh_balance()
        else:
            root.after(400, lambda: self.open_settings(first_run=True))

    # ================================================================ layout

    def _build_header(self):
        hdr = tk.Frame(self.root, bg=BG)
        hdr.pack(fill="x", padx=px(20), pady=(px(16), px(10)))

        logo = tk.Canvas(hdr, width=px(34), height=px(34), bg=BG, highlightthickness=0)
        logo.pack(side="left", padx=(0, px(10)))
        logo.create_oval(px(2), px(2), px(32), px(32), fill=GREEN, outline="")
        logo.create_text(px(17), px(17), text="$", fill="#07130a", font=(FONT, 13, "bold"))

        tk.Label(hdr, text="Torn Flip Finder", bg=BG, fg=TEXT,
                 font=(FONT, 18, "bold")).pack(side="left")
        tk.Label(hdr, text="buy the cheapest stack  ·  relist just under the next price",
                 bg=BG, fg=MUTED, font=(FONT, 9)).pack(side="left", padx=(px(14), 0), pady=(px(6), 0))

        ttk.Button(hdr, text="⚙   Settings", command=self.open_settings).pack(side="right")

        stats = tk.Frame(self.root, bg=BG)
        stats.pack(fill="x", padx=px(20), pady=(0, px(12)))
        self.st_wallet = self._stat(stats, "Money to spend  ↻", BLUE)
        card = self.st_wallet[0].master
        for w in (card, *card.winfo_children()):
            w.bind("<Button-1>", lambda e: self.refresh_balance())
            w.config(cursor="hand2")
        Tooltip(card, self.balance_tooltip)
        self.st_flips = self._stat(stats, "Flips found", GREEN)
        self.st_best = self._stat(stats, "Best flip", GREEN)
        self.st_cash = self._stat(stats, "Cash for all flips", YELLOW)
        self.st_time = self._stat(stats, "Last update", MUTED, last=True)

    def _stat(self, parent, caption, color, last=False):
        outer = tk.Frame(parent, bg=color)
        outer.pack(side="left", fill="both", expand=True, padx=(0, 0 if last else px(12)))
        card = tk.Frame(outer, bg=PANEL, padx=px(14), pady=px(7))
        card.pack(fill="both", expand=True, padx=(px(3), 0))
        tk.Label(card, text=caption.upper(), bg=PANEL, fg=MUTED,
                 font=(FONT, 8, "bold")).pack(anchor="w")
        value = tk.Label(card, text="—", bg=PANEL, fg=TEXT, font=(FONT, 15, "bold"))
        value.pack(anchor="w")
        sub = tk.Label(card, text=" ", bg=PANEL, fg=DIM, font=(FONT, 9))
        sub.pack(anchor="w")
        return value, sub

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(side="bottom", fill="x", padx=px(20), pady=(px(6), px(12)))
        self.progress = ttk.Progressbar(bar, style="Accent.Horizontal.TProgressbar",
                                        length=px(240), mode="determinate")
        self.progress.pack(side="left")
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(bar, textvariable=self.status_var, bg=BG, fg=MUTED,
                 font=(FONT, 9)).pack(side="left", padx=px(12))
        tk.Label(bar, text="Read-only  ·  you buy and list in Torn yourself  ·  F5 = refresh",
                 bg=BG, fg=DIM, font=(FONT, 9)).pack(side="right")

    def _build_body(self):
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=px(20))
        self._build_sidebar(body)
        self._build_detail(body)
        self._build_main(body)

    # ---------------------------------------------------------- watchlist

    def _build_sidebar(self, parent):
        side = tk.Frame(parent, bg=PANEL, width=px(232))
        side.pack(side="left", fill="y", padx=(0, px(12)))
        side.pack_propagate(False)
        self.sidebar = side

        top = tk.Frame(side, bg=PANEL)
        top.pack(fill="x", padx=px(14), pady=(px(14), px(8)))
        tk.Label(top, text="WATCHLIST", bg=PANEL, fg=MUTED, font=(FONT, 8, "bold")).pack(side="left")
        self.watch_count = tk.Label(top, text="", bg=FIELD, fg=TEXT, font=(FONT, 8, "bold"),
                                    padx=px(7))
        self.watch_count.pack(side="left", padx=px(8))

        self.watch_entry = HintEntry(side, "＋  Add an item…")
        self.watch_entry.pack(fill="x", padx=px(14))
        self.watch_entry.bind("<KeyRelease>", self.on_watch_typing)
        self.watch_entry.bind("<Return>", self.on_watch_enter)
        self.watch_entry.bind("<Down>", self.focus_suggestions)
        self.watch_entry.bind("<Escape>", lambda e: self.hide_suggestions())
        self.watch_entry.bind("<FocusOut>", lambda e: self.root.after(150, self._maybe_hide_suggestions),
                              add="+")

        self.suggest = tk.Listbox(side, bg=FIELD, fg=TEXT, selectbackground=GREEN_SEL,
                                  selectforeground=TEXT, activestyle="none", borderwidth=0,
                                  highlightthickness=1, highlightbackground=GREEN,
                                  highlightcolor=GREEN, font=(FONT, 10), height=8)
        self.suggest.bind("<ButtonRelease-1>", self.on_suggestion_pick)
        self.suggest.bind("<Return>", self.on_suggestion_pick)
        self.suggest.bind("<Escape>", lambda e: (self.hide_suggestions(), self.watch_entry.focus_set()))

        wrap = tk.Frame(side, bg=PANEL)
        wrap.pack(fill="both", expand=True, padx=px(6), pady=px(10))
        self.watch_tree = ttk.Treeview(wrap, style="Side.Treeview", columns=("name", "profit"),
                                       show="", selectmode="browse")
        self.watch_tree.column("name", width=px(140), anchor="w")
        self.watch_tree.column("profit", width=px(74), anchor="e")
        self.watch_tree.pack(fill="both", expand=True)
        self.watch_tree.tag_configure("flip", foreground=GREEN_TXT)
        self.watch_tree.tag_configure("noflip", foreground=TEXT)
        self.watch_tree.tag_configure("loss", foreground=MUTED)
        self.watch_tree.tag_configure("pending", foreground=MUTED)
        self.watch_tree.bind("<<TreeviewSelect>>", self.on_watch_select)
        self.watch_tree.bind("<Delete>", lambda e: self.remove_selected_watch())

        self.watch_empty = tk.Label(wrap, text="Your watchlist is empty.\n\nType an item name above,\ne.g. Xanax or Erotic DVD.",
                                    bg=PANEL, fg=DIM, font=(FONT, 9), justify="center")

        bottom = tk.Frame(side, bg=PANEL)
        bottom.pack(fill="x", padx=px(14), pady=(0, px(12)))
        ttk.Button(bottom, text="Remove selected", style="Link.TButton",
                   command=self.remove_selected_watch).pack(side="right")
        self.refresh_watch_tree()

    # ------------------------------------------------------------- main table

    def _build_main(self, parent):
        main = tk.Frame(parent, bg=BG)
        main.pack(side="left", fill="both", expand=True)

        bar = tk.Frame(main, bg=BG)
        bar.pack(fill="x", pady=(0, px(10)))
        self.check_btn = ttk.Button(bar, text="▶   Check watchlist", style="Accent.TButton",
                                    command=lambda: self.start("check"))
        self.check_btn.pack(side="left")
        self.scan_btn = ttk.Button(bar, text="⌕   Scan market", command=lambda: self.start("scan"))
        self.scan_btn.pack(side="left", padx=(px(8), 0))
        self.stop_btn = ttk.Button(bar, text="■   Stop", style="Danger.TButton",
                                   command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(px(8), 0))

        self.interval_var = tk.StringVar(value="2 min")
        ttk.Combobox(bar, textvariable=self.interval_var, values=list(REFRESH_CHOICES),
                     state="readonly", width=7).pack(side="right")
        self.auto_var = tk.BooleanVar()
        ttk.Checkbutton(bar, text="Auto-refresh", variable=self.auto_var,
                        command=self.on_auto_toggle).pack(side="right", padx=(px(12), px(4)))

        card = tk.Frame(main, bg=PANEL)
        card.pack(fill="both", expand=True)

        # Card header: title, count, filter
        ch = tk.Frame(card, bg=PANEL)
        ch.pack(fill="x", padx=px(14), pady=(px(12), px(4)))
        tk.Label(ch, text="RESULTS", bg=PANEL, fg=MUTED, font=(FONT, 8, "bold")).pack(side="left")
        self.result_count = tk.Label(ch, text="0", bg=FIELD, fg=TEXT, font=(FONT, 8, "bold"),
                                     padx=px(7))
        self.result_count.pack(side="left", padx=px(8))
        self.filter_entry = HintEntry(ch, "⌕  Filter by name", width=20)
        self.filter_entry.pack(side="right")
        self.filter_entry.var.trace_add("write", lambda *a: self.refresh_tree())
        self.only_flips = tk.BooleanVar()
        ttk.Checkbutton(ch, text="Only flips", style="Panel.TCheckbutton", variable=self.only_flips,
                        command=self.refresh_tree).pack(side="right", padx=(0, px(12)))

        table = tk.Frame(card, bg=PANEL)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=[c[0] for c in COLUMNS], show="headings",
                                 selectmode="browse")
        for key, head, width, anchor in COLUMNS:
            self.tree.heading(key, text=("   " + head) if anchor == "w" else head + "  ",
                              anchor=anchor, command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=px(width), minwidth=px(30), anchor=anchor, stretch=False)
        self.tree.bind("<Configure>", self.fit_columns)
        ysb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(px(6), 0), pady=(0, px(6)))
        ysb.pack(side="left", fill="y", pady=(0, px(6)))
        self.tree.tag_configure("flip", foreground=GREEN_TXT)
        self.tree.tag_configure("noflip", foreground=TEXT)
        self.tree.tag_configure("loss", foreground=MUTED)
        self.tree.tag_configure("bad", foreground=DIM)
        self.tree.tag_configure("odd", background=PANEL_ALT)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", lambda e: self.open_market())
        self.tree.bind("<Return>", lambda e: self.open_market())

        self.table_empty = tk.Label(
            card, bg=PANEL, fg=DIM, font=(FONT, 11), justify="center",
            text="No results yet\n\nAdd items to your watchlist and press  ▶ Check watchlist\n"
                 "or press  ⌕ Scan market  to search the whole market.")
        self.update_table_empty()

    # ---------------------------------------------------------- detail panel

    def _build_detail(self, parent):
        card = tk.Frame(parent, bg=PANEL, width=px(345))
        card.pack(side="right", fill="y", padx=(px(12), 0))
        card.pack_propagate(False)

        self.detail_empty = tk.Label(card, bg=PANEL, fg=DIM, font=(FONT, 11), justify="center",
                                     text="Select an item\nto see its trade plan")
        self.detail_empty.pack(expand=True)

        d = self.detail = tk.Frame(card, bg=PANEL, padx=px(18), pady=px(14))

        # Buttons pinned to the bottom, one row
        btns = tk.Frame(d, bg=PANEL)
        btns.pack(side="bottom", fill="x")
        self.d_open = ttk.Button(btns, text="Open market  ↗", style="Accent.TButton",
                                 command=self.open_market)
        self.d_open.pack(side="left", fill="x", expand=True)
        self.d_copy = ttk.Button(btns, text="Copy price", command=self.copy_sell_price)
        self.d_copy.pack(side="left", padx=(px(6), 0))
        self.d_watch = ttk.Button(btns, text="☆", width=3, command=self.toggle_watch_current)
        self.d_watch.pack(side="left", padx=(px(6), 0))

        head = tk.Frame(d, bg=PANEL)
        head.pack(fill="x")
        self.d_badge = tk.Label(head, text="", font=(FONT, 8, "bold"), padx=px(9), pady=px(2))
        self.d_badge.pack(side="right", anchor="n", pady=(px(5), 0))
        self.d_name = tk.Label(head, bg=PANEL, fg=TEXT, font=(FONT, 15, "bold"), anchor="w",
                               justify="left", wraplength=px(240))
        self.d_name.pack(side="left", anchor="w")
        self.d_sub = tk.Label(d, bg=PANEL, fg=DIM, font=(FONT, 9), anchor="w")
        self.d_sub.pack(fill="x")

        tk.Label(d, text="YOUR PROFIT", bg=PANEL, fg=MUTED, font=(FONT, 8, "bold"),
                 anchor="w").pack(fill="x", pady=(px(10), 0))
        self.d_profit = tk.Label(d, bg=PANEL, fg=GREEN_TXT, font=(FONT, 21, "bold"), anchor="w")
        self.d_profit.pack(fill="x")
        self.d_profit_sub = tk.Label(d, bg=PANEL, fg=MUTED, font=(FONT, 9), anchor="w")
        self.d_profit_sub.pack(fill="x")

        tk.Frame(d, bg=BORDER, height=1).pack(fill="x", pady=px(9))

        kv = self.d_kv_frame = tk.Frame(d, bg=PANEL)
        kv.pack(fill="x")
        kv.columnconfigure(1, weight=1)
        self.d_kv = {}
        rows = [("low", "Lowest price"), ("qty", "Quantity at lowest"), ("cost_all", "Cost to buy all"),
                ("second", "Second lowest"), ("sell_at", "List yours at"),
                ("receive", "You receive / unit"), ("net", "Profit / unit"),
                ("afford", "You can afford"), ("liq", "Liquidity")]
        for i, (key, label) in enumerate(rows):
            tk.Label(kv, text=label, bg=PANEL, fg=MUTED, font=(FONT, 9)).grid(
                row=i, column=0, sticky="w", pady=px(1))
            v = tk.Label(kv, text="—", bg=PANEL, fg=TEXT, font=(FONT, 9, "bold"))
            v.grid(row=i, column=1, sticky="e", pady=px(1))
            self.d_kv[key] = v

        # Warnings: only packed when there is something to say (see set_warning).
        self.d_warn = tk.Label(d, bg=PANEL, fg=YELLOW, font=(FONT, 9), justify="left",
                               anchor="w", wraplength=px(300))

        tk.Frame(d, bg=BORDER, height=1).pack(fill="x", pady=px(9))
        ob = tk.Frame(d, bg=PANEL)
        ob.pack(fill="x")
        tk.Label(ob, text="ORDER BOOK", bg=PANEL, fg=MUTED, font=(FONT, 8, "bold")).pack(side="left")
        for color, text in ((BLUE, "list under"), (GREEN, "buy")):
            tk.Label(ob, text=text, bg=PANEL, fg=DIM, font=(FONT, 8)).pack(side="right",
                                                                        padx=(px(2), px(8)))
            tk.Label(ob, text="■", bg=PANEL, fg=color, font=(FONT, 8)).pack(side="right")
        # The order book fills whatever height is left and shows as many levels as fit.
        self.ladder = tk.Canvas(d, bg=PANEL, highlightthickness=0, width=px(310), height=px(40))
        self.ladder.pack(fill="both", expand=True, pady=(px(4), px(8)))
        self.ladder.bind("<Configure>", lambda e: self.draw_ladder(self.selected_result()))

    # ============================================================== settings

    def open_settings(self, first_run=False):
        d = tk.Toplevel(self.root)
        d.title("Settings")
        d.configure(bg=BG)
        d.transient(self.root)
        d.resizable(False, False)
        frm = tk.Frame(d, bg=BG, padx=px(26), pady=px(22))
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        tk.Label(frm, text="Welcome!" if first_run else "Settings", bg=BG, fg=TEXT,
                 font=(FONT, 16, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        intro = ("Paste your Torn API key to get started. Create one in Torn under\n"
                 "Settings → API Keys. Use a Limited Access key so the app can read your balance.\n"
                 f"The key is saved in the {tf.API_KEY_ENV} environment variable, not in a file."
                 if first_run else
                 f"The API key is saved in the {tf.API_KEY_ENV} environment variable.\n"
                 "Other settings are saved to config.json next to the app.")
        tk.Label(frm, text=intro, bg=BG, fg=MUTED, font=(FONT, 9), justify="left").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(px(2), px(16)))

        money_now = self.cfg.get("money_override")
        fields = [
            ("api_key", "API key", "Torn → Settings → API Keys", self.cfg["api_key"]),
            ("money", "Money to spend", "Read live from your Torn account",
             "" if money_now is None else f"{money_now:,}"),
            ("fee", "Market fee %", "Torn takes 5% of item market sales", self.cfg["fee_percent"]),
            ("min_profit", "Minimum profit $", "Hide flips that make less than this",
             f"{self.cfg['min_profit']:,}"),
            ("min_roi", "Minimum ROI %", "Hide flips with a lower return per unit",
             self.cfg["min_roi_percent"]),
            ("scan", "Items to scan", "Scan checks the N most valuable items (0 = all, slow)",
             self.cfg.get("scan_items", 200)),
        ]
        vars_ = {}
        r = 2
        for key, label, hint, value in fields:
            box = tk.Frame(frm, bg=BG)
            box.grid(row=r, column=0, sticky="w", pady=px(6), padx=(0, px(24)))
            tk.Label(box, text=label, bg=BG, fg=TEXT, font=(FONT, 10, "bold")).pack(anchor="w")
            tk.Label(box, text=hint, bg=BG, fg=DIM, font=(FONT, 8)).pack(anchor="w")
            var = tk.StringVar(value=str(value))
            if key == "money":
                # Balance source picker + a custom amount box that is only active for "Custom".
                holder = tk.Frame(frm, bg=BG)
                holder.grid(row=r, column=1, sticky="ew")
                choices = list(tf.MONEY_SOURCES.values()) + [CUSTOM_MONEY]
                current = (CUSTOM_MONEY if money_now is not None else
                           tf.MONEY_SOURCES.get(self.cfg.get("money_source"), choices[0]))
                source_var = tk.StringVar(value=current)
                combo = ttk.Combobox(holder, textvariable=source_var, values=choices,
                                     state="readonly", width=32)
                combo.pack(fill="x")
                ent = ttk.Entry(holder, textvariable=var, width=30)

                def sync_custom(*_):
                    if source_var.get() == CUSTOM_MONEY:
                        ent.pack(fill="x", pady=(px(6), 0))
                        if not var.get():
                            var.set(f"{self.wallet:,}" if self.wallet is not None else "")
                        ent.focus_set()
                    else:
                        ent.pack_forget()
                combo.bind("<<ComboboxSelected>>", sync_custom)
                sync_custom()
            else:
                ent = ttk.Entry(frm, textvariable=var, width=30, show="•" if key == "api_key" else "")
                ent.grid(row=r, column=1, sticky="ew")
            vars_[key] = (var, ent)
            r += 1

        show = tk.BooleanVar()
        key_entry = vars_["api_key"][1]
        ttk.Checkbutton(frm, text="Show API key", variable=show,
                        command=lambda: key_entry.config(show="" if show.get() else "•")
                        ).grid(row=r, column=1, sticky="e", pady=(px(10), 0))
        skip_var = tk.BooleanVar(value=bool(self.cfg["skip_types"]))
        ttk.Checkbutton(frm, text="Skip weapons and armor (each one is unique, gaps mislead)",
                        variable=skip_var).grid(row=r, column=0, sticky="w", pady=(px(10), 0))

        btns = tk.Frame(frm, bg=BG)
        btns.grid(row=r + 1, column=0, columnspan=2, sticky="e", pady=(px(22), 0))

        def save():
            try:
                key = vars_["api_key"][0].get().strip()
                if not key:
                    raise ValueError("Enter your Torn API key.")
                source_label = source_var.get()
                if source_label == CUSTOM_MONEY:
                    money_val = parse_number(vars_["money"][0].get(), int, "Custom amount")
                    source = self.cfg.get("money_source", "wallet")
                else:
                    money_val = None
                    source = next(k for k, v in tf.MONEY_SOURCES.items() if v == source_label)
                fee = parse_number(vars_["fee"][0].get(), float, "Market fee %")
                min_profit = parse_number(vars_["min_profit"][0].get(), int, "Minimum profit")
                min_roi = parse_number(vars_["min_roi"][0].get(), float, "Minimum ROI %")
                scan = parse_number(vars_["scan"][0].get(), int, "Items to scan")
            except ValueError as e:
                messagebox.showerror("Settings", str(e), parent=d)
                return
            key_changed = key != self.cfg["api_key"]
            if key_changed and not tf.set_api_key(key):
                messagebox.showwarning(
                    "Settings", f"The key is used for this session only. Set the {tf.API_KEY_ENV}\n"
                    "environment variable to keep it between runs.", parent=d)
            self.cfg.update({
                "api_key": key, "money_override": money_val, "money_source": source,
                "fee_percent": fee,
                "min_profit": min_profit, "min_roi_percent": min_roi, "scan_items": max(0, scan),
                "skip_types": ["Weapon", "Armor"] if skip_var.get() else [],
            })
            self.save_config()
            self.apply_money_source()
            d.destroy()
            self.refresh_tree()
            self.refresh_watch_tree()
            self.update_stats()
            if key_changed:
                self.items = None
                self.load_catalog_async()
            self.status_var.set("Settings saved.")
            self.refresh_balance()

        ttk.Button(btns, text="Cancel", command=d.destroy).pack(side="left")
        ttk.Button(btns, text="Save", style="Accent.TButton", command=save).pack(
            side="left", padx=(px(8), 0))
        d.bind("<Return>", lambda e: save())
        d.bind("<Escape>", lambda e: d.destroy())

        d.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - d.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - d.winfo_height()) // 3
        d.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dark_title_bar(d)
        d.grab_set()
        (key_entry if first_run else combo).focus_set()

    def save_config(self):
        tf.save_config(self.cfg)  # api_key is left out; it lives in YOUR_TORN_API_KEY

    # ============================================================= watchlist

    def watch_names(self):
        return self.cfg["watchlist"]

    def canonical_name(self, text):
        if self.items:
            low = text.lower()
            for it in self.items:
                if it["name"].lower() == low or str(it["id"]) == text:
                    return it["name"]
        return text

    def add_watch(self, text):
        name = self.canonical_name(text.strip())
        if not name:
            return
        if name.lower() not in (n.lower() for n in self.watch_names()):
            self.cfg["watchlist"].append(name)
            self.save_config()
            self.refresh_watch_tree()
            self.status_var.set(f"Added {name} to the watchlist.")
        self.watch_entry.clear()
        self.hide_suggestions()
        if self.current_id in self.results:
            self.show_details(self.results[self.current_id])

    def remove_watch(self, name):
        self.cfg["watchlist"] = [n for n in self.watch_names() if n.lower() != name.lower()]
        self.save_config()
        self.refresh_watch_tree()
        if self.current_id in self.results:
            self.show_details(self.results[self.current_id])

    def remove_selected_watch(self):
        sel = self.watch_tree.selection()
        if sel:
            self.remove_watch(sel[0])

    def result_by_name(self):
        return {r["name"].lower(): r for r in self.results.values()}

    def refresh_watch_tree(self):
        by_name = self.result_by_name()
        self.watch_tree.delete(*self.watch_tree.get_children())
        for name in self.watch_names():
            r = by_name.get(name.lower())
            if r is None:
                profit, tag = "—", "pending"
            elif not r["ok"]:
                profit, tag = "no data", "loss"
            elif self.is_flip(r):
                profit, tag = "+" + tf.money(r["profit_yours"]), "flip"
            elif r["net_per_unit"] <= 0:
                profit, tag = "no gap", "loss"
            else:
                profit, tag = tf.money(r["profit_yours"]), "noflip"
            shown = name if len(name) <= 19 else name[:18] + "…"
            self.watch_tree.insert("", "end", iid=name, values=("  " + shown, profit + "  "), tags=(tag,))
        n = len(self.watch_names())
        self.watch_count.config(text=str(n))
        if n:
            self.watch_empty.place_forget()
        else:
            self.watch_empty.place(relx=0.5, rely=0.3, anchor="center")

    def on_watch_select(self, _e=None):
        sel = self.watch_tree.selection()
        if not sel:
            return
        r = self.result_by_name().get(sel[0].lower())
        if r:
            iid = str(r["id"])
            if self.tree.exists(iid):
                self.tree.selection_set(iid)
                self.tree.see(iid)
            else:
                self.show_details(r)

    # autocomplete ------------------------------------------------------------

    def on_watch_typing(self, event):
        if event.keysym in ("Return", "Down", "Up", "Escape"):
            return
        q = self.watch_entry.value().lower()
        if len(q) < 2 or not self.names:
            self.hide_suggestions()
            return
        starts = [n for n in self.names if n.lower().startswith(q)]
        contains = [n for n in self.names if q in n.lower() and n not in starts]
        matches = (starts + contains)[:8]
        if not matches:
            self.hide_suggestions()
            return
        self.suggest.delete(0, "end")
        for m in matches:
            self.suggest.insert("end", "  " + m)
        self.suggest.config(height=len(matches))
        self.suggest.place(in_=self.watch_entry, relx=0, rely=1, relwidth=1, y=px(2))
        self.suggest.lift()

    def hide_suggestions(self):
        self.suggest.place_forget()

    def _maybe_hide_suggestions(self):
        if self.root.focus_get() is not self.suggest:
            self.hide_suggestions()

    def focus_suggestions(self, _e=None):
        if self.suggest.winfo_ismapped():
            self.suggest.focus_set()
            self.suggest.selection_clear(0, "end")
            self.suggest.selection_set(0)
            self.suggest.activate(0)
        return "break"

    def on_watch_enter(self, _e=None):
        if self.suggest.winfo_ismapped() and self.suggest.size():
            self.add_watch(self.suggest.get(0).strip())
        else:
            self.add_watch(self.watch_entry.value())

    def on_suggestion_pick(self, _e=None):
        sel = self.suggest.curselection()
        if sel:
            self.add_watch(self.suggest.get(sel[0]).strip())
            self.watch_entry.focus_set()

    # ================================================================ worker

    def load_catalog_async(self):
        if self.catalog_loading or not self.cfg["api_key"]:
            return
        self.catalog_loading = True
        key, delay = self.cfg["api_key"], self.cfg["request_delay"]
        self.status_var.set("Loading item list…")

        def job():
            try:
                self.msgs.put(("catalog", tf.load_items(tf.TornClient(key, delay))))
            except Exception as e:
                self.msgs.put(("catalog_error", str(e)))
        threading.Thread(target=job, daemon=True).start()

    def refresh_balance(self):
        """Read your balances from Torn in the background."""
        if not self.cfg["api_key"]:
            return
        key, delay = self.cfg["api_key"], self.cfg["request_delay"]
        self.st_wallet[1].config(text="reading your balance…")

        def job():
            try:
                self.msgs.put(("balance", tf.TornClient(key, delay).money()))
            except Exception as e:
                self.msgs.put(("balance_error", str(e)))
        threading.Thread(target=job, daemon=True).start()

    def apply_money_source(self):
        """Work out the money to spend from the chosen source and the last balance read."""
        override = self.cfg.get("money_override")
        source = self.cfg.get("money_source", "wallet")
        if override is not None:
            self.wallet, self.wallet_source = override, "custom amount"
        elif self.balance is not None:
            self.wallet = tf.spendable(self.balance, source)
            self.wallet_source = tf.MONEY_SOURCES.get(source, source)
        else:
            self.wallet = None
            self.wallet_source = "needs a Limited Access key" if self.balance_error else ""
        self.update_stats()

    def balance_tooltip(self):
        if self.balance is None:
            return self.balance_error or "Click to read your balance from Torn."
        p = tf.balance_parts(self.balance)
        bank = (self.balance.get("city_bank") or {}).get("amount") or 0
        source = self.cfg.get("money_source", "wallet")
        used = {"wallet": {"wallet"}, "wallet_vault": {"wallet", "vault"},
                "all_cash": {"wallet", "vault", "cayman", "faction"}}.get(source, {"wallet"})
        if self.cfg.get("money_override") is not None:
            used = set()
        rows = [("Wallet", p["wallet"], "wallet"), ("Property vault", p["vault"], "vault"),
                ("Cayman bank", p["cayman"], "cayman"), ("Faction", p["faction"], "faction")]
        lines = [f"{'✔' if k in used else ' '}  {name:<15}{tf.money(v):>16}" for name, v, k in rows]
        lines.append(f"   {'City bank':<15}{tf.money(bank):>16}  (locked)")
        lines.append("")
        lines.append("✔ = counted. Change it in Settings → Money to spend.")
        lines.append("Market buys use wallet cash, so withdraw first. Click to refresh.")
        return "\n".join(lines)

    def start(self, mode):
        if self.running:
            return
        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        if not self.cfg["api_key"]:
            self.open_settings(first_run=True)
            return
        if mode == "check" and not self.watch_names():
            self.status_var.set("Add at least one item to the watchlist first.")
            self.watch_entry.focus_set()
            return
        s = {
            "api_key": self.cfg["api_key"],
            "money": self.cfg.get("money_override"),
            "money_source": self.cfg.get("money_source", "wallet"),
            "fee_percent": self.cfg["fee_percent"],
            "min_profit": self.cfg["min_profit"],
            "min_roi_percent": self.cfg["min_roi_percent"],
            "max_items": self.cfg.get("scan_items", 200),
            "watchlist": list(self.watch_names()),
        }
        self.last_mode = mode
        self.run_settings = s
        self.running = True
        self.stop_event.clear()
        self.seen_this_run = set()
        if mode == "scan" and not self.auto_var.get():
            self.results.clear()
            self.refresh_tree()
        self.set_buttons()
        threading.Thread(target=self.work, args=(mode, s), daemon=True).start()

    def work(self, mode, s):
        post = self.msgs.put
        try:
            client = tf.TornClient(s["api_key"], self.cfg["request_delay"])
            if self.items is None:
                post(("status", "Loading item list…"))
                post(("catalog", tf.load_items(client)))
                while self.items is None:  # wait for the UI thread to store it
                    time.sleep(0.05)

            wallet = s["money"]
            if wallet is None:
                post(("status", "Reading your balance…"))
                try:
                    m = client.money()
                    post(("balance", m))
                    wallet = tf.spendable(m, s["money_source"])
                except tf.TornAPIError as e:
                    post(("balance_error", str(e)))
                    wallet = None

            args = argparse.Namespace(command=mode, items=s["watchlist"],
                                      max_items=s["max_items"] or None)
            targets = tf.pick_items(args, self.cfg, self.items)
            post(("begin", len(targets)))
            for i, item in enumerate(targets, 1):
                if self.stop_event.is_set():
                    break
                post(("status", f"Checking {item['name']}  ({i}/{len(targets)})"))
                try:
                    market = client.item_market(item["id"])
                except tf.TornAPIError as e:
                    post(("status", f"Skipped {item['name']}: {e}"))
                    continue
                post(("row", tf.analyze(item, market, wallet, s["fee_percent"], self.history)))
                post(("progress", i))
            tf.save_json(tf.HISTORY_PATH, self.history)
        except tf.TornAPIError as e:
            post(("error", str(e)))
        except SystemExit as e:  # unknown item names in the watchlist
            post(("error", str(e)))
        except Exception as e:
            post(("error", f"Unexpected error: {e!r}"))
        finally:
            post(("finished",))

    def stop(self):
        self.stop_event.set()
        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None
            self.status_var.set("Auto-refresh stopped.")
        self.set_buttons()

    def on_auto_toggle(self):
        if not self.auto_var.get() and self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None
            self.status_var.set("Auto-refresh off.")
            self.set_buttons()
            self.update_stats()

    def set_buttons(self):
        state = "disabled" if self.running else "normal"
        self.check_btn.config(state=state)
        self.scan_btn.config(state=state)
        self.stop_btn.config(state="normal" if self.running or self.after_id else "disabled")

    # ----------------------------------------------------------- messages

    def poll(self):
        rows = 0
        try:
            while True:
                msg = self.msgs.get_nowait()
                self.handle(msg)
                rows += msg[0] == "row"
        except queue.Empty:
            pass
        if rows:
            self.update_stats()
        self.root.after(100, self.poll)

    def handle(self, msg):
        kind = msg[0]
        if kind == "status":
            self.status_var.set(msg[1])
        elif kind == "catalog":
            self.items = msg[1]
            self.names = sorted(it["name"] for it in self.items if it.get("is_tradable"))
            self.catalog_loading = False
            if not self.running:
                self.status_var.set(f"Ready  ·  {len(self.names):,} tradable items loaded")
        elif kind == "catalog_error":
            self.catalog_loading = False
            self.status_var.set("Could not load the item list: " + msg[1])
        elif kind == "error":
            self.status_var.set("Error: " + msg[1])
            messagebox.showerror("Torn Flip Finder", msg[1], parent=self.root)
        elif kind == "balance":
            self.balance = msg[1]
            self.balance_error = None
            self.apply_money_source()
        elif kind == "balance_error":
            self.balance_error = msg[1]
            self.apply_money_source()
            if not self.running:
                self.status_var.set(msg[1])
        elif kind == "begin":
            self.progress.config(maximum=max(msg[1], 1), value=0)
        elif kind == "progress":
            self.progress.config(value=msg[1])
        elif kind == "row":
            r = msg[1]
            self.results[r["id"]] = r
            self.seen_this_run.add(r["id"])
            self.upsert_row(r)
        elif kind == "finished":
            self.finish_run()

    def finish_run(self):
        self.running = False
        stopped = self.stop_event.is_set()
        if not stopped and self.seen_this_run:
            for item_id in list(self.results):
                if item_id not in self.seen_this_run:
                    del self.results[item_id]
        if self.seen_this_run:
            self.last_update = time.time()
        self.refresh_tree()
        self.refresh_watch_tree()
        if self.current_id in self.results:
            self.show_details(self.results[self.current_id])
        now = time.strftime("%H:%M:%S")
        if self.auto_var.get() and not stopped:
            secs = REFRESH_CHOICES[self.interval_var.get()]
            self.after_id = self.root.after(secs * 1000, lambda: self.start(self.last_mode))
            nxt = time.strftime("%H:%M:%S", time.localtime(time.time() + secs))
            self.status_var.set(f"Updated {now}  ·  next refresh at {nxt}")
        elif not self.status_var.get().startswith("Error"):
            self.status_var.set(f"{'Stopped' if stopped else 'Updated'} at {now}")
        self.set_buttons()
        self.update_stats()

    # ============================================================== table

    def is_flip(self, r):
        return tf.is_opportunity(r, self.cfg["min_profit"], self.cfg["min_roi_percent"])

    def row_tag(self, r):
        if not r["ok"]:
            return "bad"
        if self.is_flip(r):
            return "flip"
        return "loss" if r["net_per_unit"] <= 0 else "noflip"

    def visible(self, r):
        if self.only_flips.get() and not self.is_flip(r):
            return False
        q = self.filter_entry.value().lower()
        return not q or q in r["name"].lower()

    def upsert_row(self, r):
        iid = str(r["id"])
        values = [cell(r, c[0]) for c in COLUMNS]
        if not self.visible(r):
            if self.tree.exists(iid):
                self.tree.delete(iid)
        elif self.tree.exists(iid):
            stripe = ("odd",) if "odd" in self.tree.item(iid, "tags") else ()
            self.tree.item(iid, values=values, tags=(self.row_tag(r),) + stripe)
        else:
            stripe = ("odd",) if len(self.tree.get_children()) % 2 else ()
            self.tree.insert("", "end", iid=iid, values=values, tags=(self.row_tag(r),) + stripe)
        if self.current_id == r["id"]:
            self.show_details(r)
        self.update_table_empty()

    def fit_columns(self, event):
        """Scale every column so the table always fills its width exactly."""
        total = sum(c[2] for c in COLUMNS)
        avail = event.width - 2
        used = 0
        for i, (key, _, width, _) in enumerate(COLUMNS):
            w = avail - used if i == len(COLUMNS) - 1 else int(avail * width / total)
            self.tree.column(key, width=max(w, px(30)))
            used += w

    def sort_by(self, key):
        if self.sort_key == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = key, key not in ("name", "liquidity")
        self.refresh_tree()

    def refresh_tree(self):
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        key = self.sort_key

        def sort_value(r):
            v = r.get(key)
            return v.lower() if isinstance(v, str) else (v if v is not None else 0)

        ok = sorted((r for r in self.results.values() if r["ok"]), key=sort_value,
                    reverse=self.sort_desc)
        bad = sorted((r for r in self.results.values() if not r["ok"]), key=lambda r: r["name"])
        n = 0
        for r in ok + bad:
            if self.visible(r):
                self.tree.insert("", "end", iid=str(r["id"]), values=[cell(r, c[0]) for c in COLUMNS],
                                 tags=(self.row_tag(r),) + (("odd",) if n % 2 else ()))
                n += 1
        for k, head, _, anchor in COLUMNS:
            arrow = (" ▼" if self.sort_desc else " ▲") if k == key else ""
            self.tree.heading(k, text=("   " + head + arrow) if anchor == "w" else head + arrow + "  ")
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
        self.update_table_empty()

    def update_table_empty(self):
        self.result_count.config(text=str(len(self.tree.get_children())))
        if self.tree.get_children():
            self.table_empty.place_forget()
        else:
            if self.results:
                self.table_empty.config(text="Nothing matches your filters")
            else:
                self.table_empty.config(
                    text="No results yet\n\nAdd items to your watchlist and press  ▶ Check watchlist\n"
                         "or press  ⌕ Scan market  to search the whole market.")
            self.table_empty.place(relx=0.5, rely=0.45, anchor="center")

    # ============================================================== stats

    def update_stats(self):
        flips = [r for r in self.results.values() if self.is_flip(r)]

        v, s = self.st_wallet
        if self.wallet is not None:
            v.config(text=tf.money(self.wallet), fg=TEXT)
            s.config(text=self.wallet_source)
        else:
            v.config(text="—", fg=DIM)
            s.config(text=self.wallet_source or "click to read your balance")

        v, s = self.st_flips
        v.config(text=str(len(flips)), fg=GREEN_TXT if flips else TEXT)
        s.config(text=f"of {len(self.results)} items checked" if self.results else "nothing checked yet")

        v, s = self.st_best
        if flips:
            best = max(flips, key=lambda r: r["profit_yours"])
            v.config(text="+" + tf.money(best["profit_yours"]), fg=GREEN_TXT)
            s.config(text=best["name"])
        else:
            v.config(text="—", fg=DIM)
            s.config(text="no flips right now" if self.results else " ")

        v, s = self.st_cash
        cash = sum(r["cost_yours"] for r in flips)
        v.config(text=tf.money(cash) if flips else "—",
                 fg=YELLOW if self.wallet is not None and cash > self.wallet else (TEXT if flips else DIM))
        s.config(text="more than you have, pick the best"
                 if self.wallet is not None and cash > self.wallet else "to buy every flip")

        v, s = self.st_time
        if self.last_update:
            v.config(text=time.strftime("%H:%M:%S", time.localtime(self.last_update)), fg=TEXT)
        else:
            v.config(text="—", fg=DIM)
        s.config(text=f"auto every {self.interval_var.get()}" if self.auto_var.get() else
                 ("market scan" if self.last_mode == "scan" and self.last_update else "manual"))

    # ============================================================= detail

    def selected_result(self):
        return self.results.get(self.current_id)

    def on_select(self, _e=None):
        sel = self.tree.selection()
        if sel and int(sel[0]) in self.results:
            self.show_details(self.results[int(sel[0])])

    def show_details(self, r):
        self.current_id = r["id"]
        self.detail_empty.pack_forget()
        self.detail.pack(fill="both", expand=True)

        self.d_name.config(text=r["name"])
        sub = f"#{r['id']}  ·  {r['listings']} listings"
        if r.get("avg_price"):
            sub += f"  ·  avg sale {tf.money(r['avg_price'])}"
        self.d_sub.config(text=sub)
        watched = r["name"].lower() in (n.lower() for n in self.watch_names())
        self.d_watch.config(text="★" if watched else "☆")

        if not r["ok"]:
            self.d_badge.config(text="NO DATA", bg=FIELD, fg=MUTED)
            self.d_profit.config(text="—", fg=DIM)
            self.d_profit_sub.config(text=r.get("note", ""))
            for v in self.d_kv.values():
                v.config(text="—", fg=DIM)
            self.set_warning("")
            self.d_copy.config(state="disabled")
            self.draw_ladder(r)
            return

        fee = self.cfg["fee_percent"]
        if self.is_flip(r):
            self.d_badge.config(text="BUY", bg=GREEN, fg="#07130a")
        elif r["net_per_unit"] <= 0:
            self.d_badge.config(text="NO GAP", bg="#3a1f22", fg=RED)
        else:
            self.d_badge.config(text="SKIP", bg=FIELD, fg=MUTED)

        profit = r["profit_yours"]
        self.d_profit.config(text=("+" if profit > 0 else "") + tf.money(profit),
                             fg=GREEN_TXT if profit > 0 else RED)
        units = r["can_buy"]
        self.d_profit_sub.config(
            text=f"{units:,} unit{'s' if units != 1 else ''}  ·  {r['roi_pct']:.1f}% ROI  ·  "
                 f"{r['gap_pct']:.1f}% price gap  ·  after {fee:g}% fee")

        receive = int(r["sell_at"] * (1 - fee / 100))
        net = r["net_per_unit"]
        afford_txt = f"{r['can_buy']:,} of {r['qty']:,}"
        vals = {
            "low": (tf.money(r["low"]), GREEN_TXT),
            "qty": (f"{r['qty']:,}", TEXT),
            "cost_all": (tf.money(r["cost_all"]), TEXT),
            "second": (tf.money(r["second"]), BLUE),
            "sell_at": (tf.money(r["sell_at"]), BLUE),
            "receive": (tf.money(receive), TEXT),
            "net": (tf.money(net), GREEN_TXT if net > 0 else RED),
            "afford": (afford_txt, TEXT if r["can_buy"] == r["qty"] else YELLOW),
            "liq": (r["liquidity"], self.liquidity_color(r["liquidity"])),
        }
        for k, (text, color) in vals.items():
            self.d_kv[k].config(text=text, fg=color)
        self.set_warning("\n".join("⚠  " + w[0].upper() + w[1:] for w in r["warnings"]))
        self.d_copy.config(state="normal")
        self.draw_ladder(r)

    def set_warning(self, text):
        self.d_warn.config(text=text)
        if text:
            self.d_warn.pack(fill="x", pady=(px(8), 0), after=self.d_kv_frame)
        else:
            self.d_warn.pack_forget()

    @staticmethod
    def liquidity_color(text):
        if text.startswith("fast") or text.startswith("busy"):
            return GREEN_TXT
        if text.startswith("medium") or text.startswith("some"):
            return YELLOW
        return RED

    def draw_ladder(self, r):
        c = self.ladder
        c.delete("all")
        if r is None:
            return
        levels = r.get("levels") or []
        if not levels:
            c.create_text(0, px(12), text="No listings", anchor="w", fill=DIM, font=(FONT, 9))
            return
        row = px(22)
        fit = max(1, c.winfo_height() // row)
        levels = levels[:min(fit, 8)]
        x_bar, bar_w = px(105), px(145)
        max_q = max(q for _, q in levels)
        for i, (price, qty) in enumerate(levels):
            y = i * row
            if i == 0:
                color, tcolor = GREEN, GREEN_TXT
            elif i == 1:
                color, tcolor = BLUE, BLUE
            else:
                color, tcolor = BORDER, MUTED
            c.create_text(0, y + row / 2, text=tf.money(price), anchor="w", fill=tcolor,
                          font=(FONT, 9, "bold" if i < 2 else "normal"))
            w = max(px(3), int(bar_w * qty / max_q))
            c.create_rectangle(x_bar, y + px(6), x_bar + w, y + row - px(6), fill=color, outline="")
            c.create_text(x_bar + w + px(6), y + row / 2, text=f"× {qty:,}", anchor="w",
                          fill=MUTED, font=(FONT, 9))

    def open_market(self):
        r = self.selected_result()
        if r:
            webbrowser.open(tf.MARKET_LINK.format(id=r["id"]))

    def copy_sell_price(self):
        r = self.selected_result()
        if r and r["ok"]:
            self.root.clipboard_clear()
            self.root.clipboard_append(str(r["sell_at"]))
            self.status_var.set(f"Copied {r['sell_at']} to the clipboard. Paste it as your listing price.")

    def toggle_watch_current(self):
        r = self.selected_result()
        if not r:
            return
        if r["name"].lower() in (n.lower() for n in self.watch_names()):
            self.remove_watch(r["name"])
        else:
            self.add_watch(r["name"])

    def on_close(self):
        self.stop_event.set()
        self.root.destroy()


def main():
    global SCALE
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on high-DPI screens
    except Exception:
        pass
    root = tk.Tk()
    SCALE = max(1.0, root.winfo_fpixels("1i") / 96)
    apply_theme(root)
    App(root)
    dark_title_bar(root)
    root.mainloop()


if __name__ == "__main__":
    main()
