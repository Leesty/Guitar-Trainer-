#!/usr/bin/env python3
"""Guitar Trainer — macOS-native rebuild.

Single-file Tkinter app. Data files (exercises.json, settings.json,
"Guitar Exercises.md", untitled.wav) live next to this script and are resolved
relative to it, so the app can be launched from any working directory.
"""

import os
import json
import time
import threading
import webbrowser
from pathlib import Path
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import tkinter.font as tkfont

try:
    import pygame
except Exception:
    pygame = None

try:
    import numpy as np
except Exception:
    np = None

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None

BASE_DIR = Path(__file__).resolve().parent


# ----------------------------------------------------------------------------
# Palette (Apple system colors, dark mode) + typography helpers
# ----------------------------------------------------------------------------
class C:
    BG = "#1C1C1E"      # window base
    CARD = "#2C2C2E"    # surface / card
    ELEV = "#3A3A3C"    # elevated control / input
    SEP = "#48484A"     # separators / borders
    TXT = "#FFFFFF"
    TXT2 = "#AEAEB2"    # secondary text
    MUTED = "#8E8E93"
    BLUE = "#0A84FF"
    GREEN = "#30D158"
    ORANGE = "#FF9F0A"
    RED = "#FF453A"
    PURPLE = "#BF5AF2"
    TEAL = "#64D2FF"
    YELLOW = "#FFD60A"
    GRAY = "#636366"


UI_FAMILY = "Helvetica"
MONO_FAMILY = "Menlo"
_FONTS = {}


def get_font(size, weight="normal", mono=False):
    key = (size, weight, mono)
    f = _FONTS.get(key)
    if f is None:
        f = tkfont.Font(family=(MONO_FAMILY if mono else UI_FAMILY),
                        size=size, weight=weight)
        _FONTS[key] = f
    return f


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hx(rgb):
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(v))) for v in rgb)


def lighten(h, f=0.12):
    r, g, b = _rgb(h)
    return _hx((r + (255 - r) * f, g + (255 - g) * f, b + (255 - b) * f))


def darken(h, f=0.12):
    r, g, b = _rgb(h)
    return _hx((r * (1 - f), g * (1 - f), b * (1 - f)))


def mix(h1, h2, t):
    a, b = _rgb(h1), _rgb(h2)
    return _hx(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


# ----------------------------------------------------------------------------
# Rounded canvas button (tk.Button ignores bg color on macOS — this doesn't)
# ----------------------------------------------------------------------------
class RoundedButton(tk.Canvas):
    def __init__(self, parent, text="", command=None, color=C.BLUE, fg="#FFFFFF",
                 size=13, weight="bold", height=44, radius=None, padx=24,
                 width=None, variant="solid"):
        bg = parent["bg"]
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0)
        self.command = command
        self._text = text
        self._font = get_font(size, weight)
        if width is None:
            width = self._font.measure(text) + 2 * padx
        self._bw = int(width)
        self._bh = int(height)
        self._radius = radius if radius is not None else min(14, self._bh // 2)

        if variant == "solid":
            self._fill = color
            self._fill_h = lighten(color, 0.14)
            self._fill_p = darken(color, 0.14)
            self._fg = fg
        elif variant == "tinted":
            self._fill = mix(color, bg, 0.80)
            self._fill_h = mix(color, bg, 0.68)
            self._fill_p = mix(color, bg, 0.86)
            self._fg = lighten(color, 0.06)
        else:  # ghost
            self._fill = C.ELEV
            self._fill_h = lighten(C.ELEV, 0.12)
            self._fill_p = darken(C.ELEV, 0.10)
            self._fg = color

        self.config(width=self._bw, height=self._bh)
        self._render(self._fill)
        self.bind("<Enter>", lambda e: self._render(self._fill_h))
        self.bind("<Leave>", lambda e: self._render(self._fill))
        self.bind("<ButtonPress-1>", lambda e: self._render(self._fill_p))
        self.bind("<ButtonRelease-1>", self._on_release)
        self.configure(cursor="hand2")

    def _round_pts(self, x1, y1, x2, y2, r):
        return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
                x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]

    def _render(self, fill):
        self.delete("all")
        pts = self._round_pts(1, 1, self._bw - 1, self._bh - 1, self._radius)
        self.create_polygon(pts, smooth=True, splinesteps=28, fill=fill, outline=fill)
        self.create_text(self._bw // 2, self._bh // 2 + 1, text=self._text,
                         fill=self._fg, font=self._font)

    def _on_release(self, e):
        inside = 0 <= e.x <= self._bw and 0 <= e.y <= self._bh
        self._render(self._fill_h if inside else self._fill)
        if inside and self.command:
            self.command()

    def set_text(self, text):
        self._text = text
        self._render(self._fill)

    def set_color(self, color, fg=None):
        self._fill = color
        self._fill_h = lighten(color, 0.14)
        self._fill_p = darken(color, 0.14)
        if fg:
            self._fg = fg
        self._render(self._fill)

    def set_style(self, fill, fg):
        self._fill = fill
        self._fill_h = lighten(fill, 0.14)
        self._fill_p = darken(fill, 0.14)
        self._fg = fg
        self._render(self._fill)


# ----------------------------------------------------------------------------
# Metronome — pygame only (no winsound), drift-corrected, synthesized click
# ----------------------------------------------------------------------------
class Metronome:
    # all crisp/click-family, varied by pitch and snap (Click is the reference)
    SOUNDS = ["Click", "Bright", "Tick", "Snap", "Deep"]

    def __init__(self, wav_path=None, sound="Click"):
        self.bpm = 120
        self.volume = 0.5
        self.running = False
        self.sound_name = sound if sound in self.SOUNDS else "Click"
        self._thread = None
        self._sounds = {}
        self._fallback = None
        self._init_audio(wav_path)

    def _init_audio(self, wav_path):
        if pygame is None:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.pre_init(44100, -16, 2, 512)
                pygame.mixer.init()
        except Exception:
            return
        if np is not None:
            try:
                self._sounds = self._synth_all()
            except Exception:
                self._sounds = {}
        if not self._sounds and wav_path and os.path.exists(wav_path):
            try:
                self._fallback = pygame.mixer.Sound(str(wav_path))
            except Exception:
                self._fallback = None

    @staticmethod
    def _synth_all():
        sr = 44100

        def to_sound(mono):
            mono = mono / (np.max(np.abs(mono)) + 1e-9) * 0.5
            i16 = (mono * 32767).astype(np.int16)
            stereo = np.ascontiguousarray(np.column_stack([i16, i16]))
            return pygame.sndarray.make_sound(stereo)

        def perc(n, attack, tau):
            a = max(1, int(sr * attack))
            env = np.ones(n)
            env[:a] = 0.5 * (1 - np.cos(np.pi * np.arange(a) / a))
            env *= np.exp(-(np.arange(n) / sr) / tau)
            return env

        rng = np.random.default_rng(7)

        def click(freqs, dur, tau, attack=0.0004, noise=0.0):
            n = int(sr * dur)
            t = np.arange(n) / sr
            sig = np.zeros(n)
            for f, amp in freqs:
                sig += amp * np.sin(2 * np.pi * f * t)
            if noise:
                sig = sig + noise * rng.uniform(-1.0, 1.0, n)
            return sig * perc(n, attack, tau)

        out = {}
        # Click — the reference: bright, crisp, short (the one you liked best)
        out["Click"] = to_sound(click([(2000, 1.0), (4000, 0.5)], 0.030, 0.0060))
        # Bright — same character, higher and even crisper
        out["Bright"] = to_sound(click([(3000, 1.0), (6000, 0.5)], 0.026, 0.0050))
        # Tick — thin high clock tick with a tiny transient
        out["Tick"] = to_sound(click([(3200, 1.0), (5600, 0.35)], 0.018, 0.0032, noise=0.18))
        # Snap — snappier attack (bit of noise), like a rim click
        out["Snap"] = to_sound(click([(2500, 1.0), (5000, 0.45)], 0.022, 0.0038, noise=0.30))
        # Deep — lower-pitched but still a sharp click
        out["Deep"] = to_sound(click([(1300, 1.0), (2600, 0.5)], 0.034, 0.0075))
        return out

    @property
    def available(self):
        return bool(self._sounds) or self._fallback is not None

    def set_sound(self, name):
        if name in self.SOUNDS:
            self.sound_name = name

    def _current(self):
        return self._sounds.get(self.sound_name) or self._fallback

    def play_once(self):
        snd = self._current()
        if snd:
            snd.set_volume(self.volume)
            snd.play()

    def start(self):
        if self.running or not self.available:
            return self.available
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self.running = False

    def _loop(self):
        next_t = time.perf_counter()
        while self.running:
            snd = self._current()
            if snd is None:
                break
            try:
                snd.set_volume(self.volume)
                snd.play()
            except Exception:
                break
            next_t += 60.0 / max(1, self.bpm)
            delay = next_t - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                next_t = time.perf_counter()


# ----------------------------------------------------------------------------
# Main application
# ----------------------------------------------------------------------------
class GuitarTrainer:
    def __init__(self, root):
        global UI_FAMILY, MONO_FAMILY
        self.root = root

        fams = set(tkfont.families(root))
        for f in ("SF Pro Display", "SF Pro Text", "Helvetica Neue", "Helvetica", "Arial"):
            if f in fams:
                UI_FAMILY = f
                break
        if "Menlo" not in fams:
            MONO_FAMILY = UI_FAMILY

        # data files
        self.data_file = BASE_DIR / "Guitar Exercises.md"
        self.struct_file = BASE_DIR / "exercises.json"
        self.settings_file = BASE_DIR / "settings.json"
        self.wav_file = BASE_DIR / "untitled.wav"

        # state
        self.workout_data = []
        self.structure = {"folders": {}, "root": [], "info": {}}
        self.stale_days = 7
        self.metro_sound = "Click"
        self.current_exercise = None
        self.elapsed = 0
        self.timer_running = False
        self._timer_job = None
        self._metro_was_running = False

        self.load_data()
        self.load_structure()
        self.load_settings()

        self.metro = Metronome(self.wav_file, sound=self.metro_sound)

        self._setup_window()
        self._setup_style()
        self._build_chrome()
        self.show_main()

        self.root.protocol("WM_DELETE_WINDOW", self.on_quit)

    # ----- window / style / chrome -----------------------------------------
    def _setup_window(self):
        self.root.title("Guitar Trainer")
        self.root.configure(bg=C.BG)
        w, h = 920, 680
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = 44  # pin near the top so the window never slips under the Dock
        self.root.geometry(f"{w}x{h}+{max(0, x)}+{y}")
        self.root.minsize(840, 600)

    def _setup_style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("Dark.Treeview", background=C.CARD, fieldbackground=C.CARD,
                     foreground=C.TXT, borderwidth=0, font=get_font(13), rowheight=30)
        st.map("Dark.Treeview",
               background=[("selected", C.BLUE)],
               foreground=[("selected", "#FFFFFF")])
        st.layout("Dark.Treeview", [("Dark.Treeview.treearea", {"sticky": "nswe"})])
        st.configure("Dark.Vertical.TScrollbar", background=C.ELEV, troughcolor=C.BG,
                     bordercolor=C.BG, arrowcolor=C.TXT2, relief="flat")
        st.configure("Dark.TCombobox", fieldbackground=C.ELEV, background=C.ELEV,
                     foreground=C.TXT, arrowcolor=C.TXT, bordercolor=C.SEP)

    def _build_chrome(self):
        self.header = tk.Frame(self.root, bg=C.BG, height=72)
        self.header.pack(fill="x", side="top")
        self.header.pack_propagate(False)

        self.content = tk.Frame(self.root, bg=C.BG)
        self.content.pack(fill="both", expand=True, padx=28, pady=(0, 8))

        footer = tk.Frame(self.root, bg=C.BG, height=34)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        tk.Label(footer, text="Made by Leesty", fg=C.MUTED, bg=C.BG,
                 font=get_font(10)).pack(side="left", padx=28)
        self.total_time_label = tk.Label(footer, text="", fg=C.GREEN, bg=C.BG,
                                         font=get_font(10, "bold"))
        self.total_time_label.pack(side="right", padx=28)
        self.update_total_time()

    def set_header(self, title, back=True, back_cmd=None):
        for w in self.header.winfo_children():
            w.destroy()
        if back:
            RoundedButton(self.header, text="‹  Back", color=C.BLUE, variant="ghost",
                          height=38, size=13, padx=16,
                          command=back_cmd or self.show_main).pack(side="left", padx=(24, 0))
        tk.Label(self.header, text=title, fg=C.TXT, bg=C.BG,
                 font=get_font(20, "bold")).pack(side="left", padx=18)

    def clear_content(self):
        self.root.unbind_all("<MouseWheel>")  # drop any per-screen wheel binding
        for w in self.content.winfo_children():
            w.destroy()

    # ----- data layer (formats kept identical to the original) -------------
    def load_data(self):
        self.workout_data = []
        if not os.path.exists(self.data_file):
            return
        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"Error loading data: {e}")
            return
        current_date = None
        for line in content.split("\n"):
            if line.startswith("## "):
                current_date = line[3:].strip()
            elif line.startswith("| ") and ("BPM" in line or "Exercise Name" in line or "Название" in line):
                continue
            elif line.startswith("| ") and current_date and not line.startswith("| ---"):
                parts = line.split("|")
                if len(parts) >= 4:
                    exercise = parts[1].strip()
                    tm = parts[2].strip()
                    bpm = parts[3].strip()
                    if exercise and not exercise.startswith("-") and exercise != "Exercise Name":
                        try:
                            timestamp = datetime.strptime(current_date, "%d %B %Y").isoformat()
                        except Exception:
                            timestamp = datetime.now().isoformat()
                        self.workout_data.append({
                            "exercise": exercise, "time": tm, "bpm": bpm,
                            "timestamp": timestamp,
                        })

    def save_data(self):
        days = {}
        for d in self.workout_data:
            try:
                date = datetime.fromisoformat(d["timestamp"]).strftime("%d %B %Y")
            except Exception:
                continue
            days.setdefault(date, []).append(d)
        try:
            with open(self.data_file, "w", encoding="utf-8") as f:
                f.write("# Guitar Exercises\n\n")
                if not days:
                    f.write("Workout history is empty.\n")
                else:
                    for date in sorted(days.keys(), reverse=True,
                                       key=lambda s: self._date_key(s)):
                        f.write(f"## {date}\n\n")
                        f.write("| Exercise Name | Time  | BPM |\n")
                        f.write("| ------------------- | ------ | --- |\n")
                        for d in days[date]:
                            f.write(f"| {d['exercise']} | {d['time']} | {d['bpm']} |\n")
                        f.write("\n")
        except Exception as e:
            print(f"Error saving data: {e}")

    @staticmethod
    def _date_key(date_str):
        try:
            return datetime.strptime(date_str, "%d %B %Y")
        except Exception:
            return datetime.min

    def load_structure(self):
        if os.path.exists(self.struct_file):
            try:
                with open(self.struct_file, "r", encoding="utf-8") as f:
                    self.structure = json.load(f)
            except Exception:
                self.structure = {"folders": {}, "root": [], "info": {}}
        else:
            self.structure = {"folders": {}, "root": [], "info": {}}
        self.structure.setdefault("folders", {})
        self.structure.setdefault("root", [])
        self.structure.setdefault("info", {})

    def save_structure(self):
        try:
            with open(self.struct_file, "w", encoding="utf-8") as f:
                json.dump(self.structure, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving structure: {e}")

    def load_settings(self):
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.stale_days = int(data.get("stale_days", 7))
                self.metro_sound = data.get("metronome_sound", "Click")
                if self.metro_sound not in Metronome.SOUNDS:
                    self.metro_sound = "Click"
            else:
                self.save_settings()
        except Exception:
            self.stale_days = 7
            self.metro_sound = "Click"

    def save_settings(self):
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump({"stale_days": self.stale_days,
                           "metronome_sound": self.metro_sound},
                          f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def flatten(self):
        names = set(self.structure.get("root", []))
        for items in self.structure.get("folders", {}).values():
            names.update(items)
        return sorted(names)

    # ----- stats helpers ---------------------------------------------------
    def exercise_stats(self, name):
        data = [d for d in self.workout_data if d.get("exercise") == name]
        total_seconds = 0
        for d in data:
            try:
                m, s = d["time"].split(":")
                total_seconds += int(m) * 60 + int(s)
            except Exception:
                continue
        return {
            "sessions": len(data),
            "total_seconds": total_seconds,
            "total_formatted": self._fmt_seconds(total_seconds),
        }

    @staticmethod
    def _fmt_seconds(total):
        h, m, s = total // 3600, (total % 3600) // 60, total % 60
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    def best_bpm(self, name):
        best = 0
        for d in self.workout_data:
            if d.get("exercise") == name and str(d.get("bpm", "")).isdigit():
                best = max(best, int(d["bpm"]))
        return best

    def last_played(self, name):
        last = None
        for d in self.workout_data:
            if d.get("exercise") == name:
                try:
                    ts = datetime.fromisoformat(d["timestamp"])
                except Exception:
                    continue
                if last is None or ts > last:
                    last = ts
        return last.strftime("%d %B %Y") if last else None

    def is_stale(self, name):
        last = None
        for d in self.workout_data:
            if d.get("exercise") == name:
                try:
                    ts = datetime.fromisoformat(d["timestamp"])
                except Exception:
                    continue
                if last is None or ts > last:
                    last = ts
        if last is None:
            return self.stale_days > 0
        return (datetime.now() - last).days >= int(self.stale_days)

    def total_training_time(self):
        total = 0
        for d in self.workout_data:
            try:
                m, s = d["time"].split(":")
                total += int(m) * 60 + int(s)
            except Exception:
                continue
        return self._fmt_seconds(total)

    def update_total_time(self):
        if hasattr(self, "total_time_label"):
            self.total_time_label.config(text=f"⏱  Total Time: {self.total_training_time()}")

    # ----- small UI helpers ------------------------------------------------
    def lbl(self, parent, text, size=13, weight="normal", fg=C.TXT, mono=False, **kw):
        return tk.Label(parent, text=text, fg=fg, bg=parent["bg"],
                        font=get_font(size, weight, mono), **kw)

    def entry(self, parent, textvariable=None, width=24, size=13):
        e = tk.Entry(parent, textvariable=textvariable, width=width, font=get_font(size),
                     bg=C.ELEV, fg=C.TXT, insertbackground=C.TXT, relief="flat",
                     highlightthickness=1, highlightbackground=C.SEP,
                     highlightcolor=C.BLUE, disabledbackground=C.ELEV)
        return e

    def card(self, parent, **pack_kw):
        f = tk.Frame(parent, bg=C.CARD)
        if pack_kw:
            f.pack(**pack_kw)
        return f

    def dialog(self, title, w, h):
        top = tk.Toplevel(self.root)
        top.title(title)
        top.configure(bg=C.BG)
        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        top.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        top.transient(self.root)
        top.grab_set()
        return top

    # ----- main menu -------------------------------------------------------
    def show_main(self):
        for w in self.header.winfo_children():
            w.destroy()
        self.clear_content()
        self.update_total_time()

        hero = tk.Frame(self.content, bg=C.BG)
        hero.place(relx=0.5, rely=0.46, anchor="center")

        self.lbl(hero, "🎸  Guitar Trainer", size=34, weight="bold").pack()
        self.lbl(hero, "Track your practice, beat your best BPM",
                 size=14, fg=C.TXT2).pack(pady=(8, 34))

        menu = [
            ("🎯   New Workout", C.BLUE, self.new_workout),
            ("📊   Workout History", C.TEAL, self.show_history),
            ("📝   Manage Exercises", C.ORANGE, self.show_manage),
            ("⚙️   Settings", C.PURPLE, self.open_settings),
        ]
        for text, color, cmd in menu:
            RoundedButton(hero, text=text, color=color, command=cmd,
                          width=330, height=56, size=16, radius=16).pack(pady=7)
        RoundedButton(hero, text="Quit", color=C.RED, variant="ghost",
                      command=self.on_quit, width=330, height=44, size=13,
                      radius=14).pack(pady=(16, 0))

    # ----- new workout: exercise selection ---------------------------------
    def new_workout(self):
        if not self.flatten():
            messagebox.showwarning("Guitar Trainer",
                                   "Exercise list is empty. Add exercises in 'Manage Exercises'.")
            return
        self.show_select()

    def show_select(self):
        self.current_exercise = None
        self.set_header("Select Exercise", back_cmd=self.show_main)
        self.clear_content()

        body = tk.Frame(self.content, bg=C.BG)
        body.pack(fill="both", expand=True, pady=(4, 12))

        left = self.card(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 14))
        tk.Frame(left, bg=C.CARD, height=14).pack()

        tree_wrap = tk.Frame(left, bg=C.CARD)
        tree_wrap.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        tree = ttk.Treeview(tree_wrap, show="tree", style="Dark.Treeview", selectmode="browse")
        tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(tree_wrap, orient="vertical", command=tree.yview,
                           style="Dark.Vertical.TScrollbar")
        sb.pack(side="right", fill="y")
        tree.configure(yscrollcommand=sb.set)

        node_name = {}
        root_node = tree.insert("", "end", text="  All Exercises", open=True)
        node_name[root_node] = None
        for folder, items in sorted(self.structure.get("folders", {}).items()):
            fnode = tree.insert(root_node, "end", text=f"📁  {folder}", open=False)
            node_name[fnode] = None
            for name in sorted(items):
                disp = f"  {name}   🔴" if self.is_stale(name) else f"  {name}"
                node_name[tree.insert(fnode, "end", text=disp)] = name
        for name in sorted(self.structure.get("root", [])):
            disp = f"  {name}   🔴" if self.is_stale(name) else f"  {name}"
            node_name[tree.insert(root_node, "end", text=disp)] = name

        # right: stats panel
        right = self.card(body)
        right.pack(side="right", fill="y", ipadx=8)
        right.configure(width=260)
        right.pack_propagate(False)
        self.lbl(right, "Statistics", size=15, weight="bold").pack(pady=(20, 4), padx=20, anchor="w")
        tk.Frame(right, bg=C.SEP, height=1).pack(fill="x", padx=20, pady=(2, 14))
        stats_box = tk.Frame(right, bg=C.CARD)
        stats_box.pack(fill="x", padx=20)
        self._sel_stat_vars = {}
        for key, label, color in [("sessions", "Sessions", C.TXT),
                                   ("total", "Total Time", C.TXT),
                                   ("best", "Best BPM", C.YELLOW),
                                   ("last", "Last Played", C.TXT2)]:
            row = tk.Frame(stats_box, bg=C.CARD)
            row.pack(fill="x", pady=6)
            self.lbl(row, label, size=12, fg=C.MUTED).pack(anchor="w")
            v = self.lbl(row, "—", size=15, weight="bold", fg=color)
            v.pack(anchor="w")
            self._sel_stat_vars[key] = v

        self._sel_name = None

        def on_sel(_e):
            sel = tree.selection()
            name = node_name.get(sel[0]) if sel else None
            self._sel_name = name
            if not name:
                for v in self._sel_stat_vars.values():
                    v.config(text="—")
                return
            st = self.exercise_stats(name)
            self._sel_stat_vars["sessions"].config(text=str(st["sessions"]))
            self._sel_stat_vars["total"].config(text=st["total_formatted"])
            self._sel_stat_vars["best"].config(text=str(self.best_bpm(name)))
            self._sel_stat_vars["last"].config(text=self.last_played(name) or "—")

        tree.bind("<<TreeviewSelect>>", on_sel)
        tree.bind("<Double-1>", lambda e: self._start_from_select())

        # bottom action bar
        bar = tk.Frame(self.content, bg=C.BG)
        bar.pack(fill="x", pady=(0, 6))
        RoundedButton(bar, text="🎯  Start Exercise", color=C.GREEN,
                      command=self._start_from_select, width=240, height=48,
                      size=15).pack(side="left")
        RoundedButton(bar, text="Cancel", color=C.GRAY, variant="ghost",
                      command=self.show_main, width=140, height=48,
                      size=14).pack(side="right")

    def _start_from_select(self):
        if not self._sel_name:
            messagebox.showwarning("Guitar Trainer", "Select an exercise first.")
            return
        self.current_exercise = self._sel_name
        self.start_timer()

    # ----- timer screen ----------------------------------------------------
    def start_timer(self):
        self.elapsed = 0
        self.timer_running = True
        self.set_header(self.current_exercise, back_cmd=self.cancel_exercise)
        self.clear_content()

        wrap = tk.Frame(self.content, bg=C.BG)
        wrap.pack(fill="both", expand=True)

        top = tk.Frame(wrap, bg=C.BG)
        top.pack(pady=(10, 0))
        self.lbl(top, f"🎸  {self.current_exercise}", size=22, weight="bold").pack(side="left")
        RoundedButton(top, text="ℹ︎ Info", color=C.BLUE, variant="tinted",
                      command=self.show_info, height=34, size=12, padx=14).pack(side="left", padx=12)

        self.time_label = self.lbl(wrap, "00:00", size=78, weight="bold",
                                   fg=C.BLUE, mono=True)
        self.time_label.pack(pady=(6, 4))

        info = (f"🏆  Best BPM: {self.best_bpm(self.current_exercise)}      "
                f"🗓  Last: {self.last_played(self.current_exercise) or '—'}      "
                f"⏱  Total: {self.exercise_stats(self.current_exercise)['total_formatted']}")
        self.lbl(wrap, info, size=12, fg=C.TXT2).pack(pady=(0, 18))

        # metronome card
        mc = self.card(wrap)
        mc.pack(pady=6, ipadx=30, ipady=18)
        self.lbl(mc, "🎵  Metronome", size=15, weight="bold").pack(pady=(2, 10))
        self.bpm_label = self.lbl(mc, f"{self.metro.bpm}", size=40, weight="bold",
                                  fg=C.TXT, mono=True)
        self.bpm_label.pack()
        self.lbl(mc, "BPM", size=11, fg=C.MUTED).pack(pady=(0, 10))

        row = tk.Frame(mc, bg=C.CARD)
        row.pack(pady=(0, 6))
        RoundedButton(row, text="−5", color=C.GRAY, command=lambda: self.change_bpm(-5),
                      width=58, height=40, size=14).pack(side="left", padx=4)
        RoundedButton(row, text="−1", color=C.GRAY, command=lambda: self.change_bpm(-1),
                      width=58, height=40, size=14).pack(side="left", padx=4)
        self.metro_btn = RoundedButton(row, text="▶  Start", color=C.GREEN,
                                       command=self.toggle_metronome, width=120,
                                       height=40, size=14)
        self.metro_btn.pack(side="left", padx=8)
        RoundedButton(row, text="+1", color=C.GRAY, command=lambda: self.change_bpm(1),
                      width=58, height=40, size=14).pack(side="left", padx=4)
        RoundedButton(row, text="+5", color=C.GRAY, command=lambda: self.change_bpm(5),
                      width=58, height=40, size=14).pack(side="left", padx=4)

        vol = tk.Frame(mc, bg=C.CARD)
        vol.pack(pady=(10, 2))
        RoundedButton(vol, text="🔉", color=C.GRAY, variant="ghost",
                      command=lambda: self.change_volume(-0.1), width=46, height=34,
                      size=13).pack(side="left", padx=4)
        self.vol_label = self.lbl(vol, f"{int(self.metro.volume * 100)}%", size=13,
                                  weight="bold", fg=C.TXT2)
        self.vol_label.pack(side="left", padx=10)
        RoundedButton(vol, text="🔊", color=C.GRAY, variant="ghost",
                      command=lambda: self.change_volume(0.1), width=46, height=34,
                      size=13).pack(side="left", padx=4)

        # sound selector (tap to choose — plays a preview)
        snd_row = tk.Frame(mc, bg=C.CARD)
        snd_row.pack(pady=(12, 2))
        self.lbl(snd_row, "Sound", size=11, fg=C.MUTED).pack(side="left", padx=(0, 8))
        self._sound_chips = {}
        for name in Metronome.SOUNDS:
            chip = RoundedButton(snd_row, text=name, color=C.ELEV, variant="ghost",
                                 command=lambda n=name: self.pick_sound(n),
                                 height=30, size=11, padx=12)
            chip.pack(side="left", padx=3)
            self._sound_chips[name] = chip
        self._refresh_sound_chips()

        # controls
        ctrl = tk.Frame(wrap, bg=C.BG)
        ctrl.pack(pady=22)
        self.pause_btn = RoundedButton(ctrl, text="⏸  Pause", color=C.ORANGE,
                                       command=self.pause_timer, width=150, height=50,
                                       size=15)
        self.pause_btn.pack(side="left", padx=8)
        RoundedButton(ctrl, text="✅  Finish", color=C.GREEN, command=self.finish_exercise,
                      width=150, height=50, size=15).pack(side="left", padx=8)
        RoundedButton(ctrl, text="✕  Cancel", color=C.RED, variant="tinted",
                      command=self.cancel_exercise, width=150, height=50,
                      size=15).pack(side="left", padx=8)

        self._tick()

    def _tick(self):
        if self.timer_running:
            self.elapsed += 1
            self.time_label.config(text=f"{self.elapsed // 60:02d}:{self.elapsed % 60:02d}")
        self._timer_job = self.root.after(1000, self._tick)

    def change_bpm(self, delta):
        self.metro.bpm = max(20, min(400, self.metro.bpm + delta))
        if hasattr(self, "bpm_label"):
            self.bpm_label.config(text=f"{self.metro.bpm}")

    def change_volume(self, delta):
        self.metro.volume = max(0.0, min(1.0, round(self.metro.volume + delta, 2)))
        if hasattr(self, "vol_label"):
            self.vol_label.config(text=f"{int(self.metro.volume * 100)}%")

    def pick_sound(self, name):
        self.metro.set_sound(name)
        self.metro_sound = name
        self.save_settings()
        self._refresh_sound_chips()
        if not self.metro.running:
            self.metro.play_once()  # audition the choice

    def _refresh_sound_chips(self):
        for name, chip in self._sound_chips.items():
            if name == self.metro_sound:
                chip.set_style(C.BLUE, "#FFFFFF")
            else:
                chip.set_style(C.ELEV, C.TXT2)

    def toggle_metronome(self):
        if self.metro.running:
            self.metro.stop()
            self.metro_btn.set_text("▶  Start")
            self.metro_btn.set_color(C.GREEN)
        else:
            if not self.metro.start():
                messagebox.showinfo("Guitar Trainer", "Audio output is not available.")
                return
            self.metro_btn.set_text("⏸  Stop")
            self.metro_btn.set_color(C.RED)

    def pause_timer(self):
        if self.timer_running:
            self.timer_running = False
            self.pause_btn.set_text("▶  Resume")
            self._metro_was_running = self.metro.running
            if self.metro.running:
                self.metro.stop()
                self.metro_btn.set_text("▶  Start")
                self.metro_btn.set_color(C.GREEN)
        else:
            self.timer_running = True
            self.pause_btn.set_text("⏸  Pause")
            if self._metro_was_running:
                self.metro.start()
                self.metro_btn.set_text("⏸  Stop")
                self.metro_btn.set_color(C.RED)
                self._metro_was_running = False

    def _stop_clocks(self):
        self.timer_running = False
        self.metro.stop()
        if self._timer_job:
            try:
                self.root.after_cancel(self._timer_job)
            except Exception:
                pass
            self._timer_job = None

    def cancel_exercise(self):
        self._stop_clocks()
        self.show_main()

    def finish_exercise(self):
        self._stop_clocks()
        self.show_data_input()

    def show_data_input(self):
        self.set_header("Save Result", back_cmd=self.cancel_exercise)
        self.clear_content()
        wrap = tk.Frame(self.content, bg=C.BG)
        wrap.place(relx=0.5, rely=0.42, anchor="center")

        self.lbl(wrap, "📊  Exercise Result", size=24, weight="bold").pack(pady=(0, 6))
        self.lbl(wrap, self.current_exercise, size=15, fg=C.TXT2).pack()
        time_str = f"{self.elapsed // 60:02d}:{self.elapsed % 60:02d}"
        self.lbl(wrap, f"⏱  Time: {time_str}", size=16, fg=C.TXT).pack(pady=(16, 18))

        box = self.card(wrap)
        box.pack(ipadx=26, ipady=18)
        self.lbl(box, "Reached BPM", size=12, fg=C.MUTED).pack(pady=(2, 6))
        self.bpm_var = tk.StringVar(value=str(self.metro.bpm))
        e = self.entry(box, textvariable=self.bpm_var, width=10, size=22)
        e.pack(ipady=6, ipadx=8)
        e.focus_set()
        e.bind("<Return>", lambda ev: self.finish_workout())

        btns = tk.Frame(wrap, bg=C.BG)
        btns.pack(pady=24)
        RoundedButton(btns, text="🏁  Finish", color=C.GREEN, command=self.finish_workout,
                      width=170, height=50, size=15).pack(side="left", padx=8)
        RoundedButton(btns, text="🔄  Save & Next", color=C.BLUE,
                      command=self.save_and_continue, width=190, height=50,
                      size=15).pack(side="left", padx=8)

    def _record(self):
        bpm = self.bpm_var.get().strip()
        if not bpm.isdigit():
            messagebox.showerror("Guitar Trainer", "BPM must be a number.")
            return False
        time_str = f"{self.elapsed // 60:02d}:{self.elapsed % 60:02d}"
        self.workout_data.append({
            "exercise": self.current_exercise,
            "time": time_str,
            "bpm": bpm,
            "timestamp": datetime.now().isoformat(),
        })
        self.save_data()
        self.update_total_time()
        return True

    def finish_workout(self):
        if not self._record():
            return
        self.show_main()

    def save_and_continue(self):
        if not self._record():
            return
        self.elapsed = 0
        self.show_select()

    # ----- workout history -------------------------------------------------
    def show_history(self):
        self.set_header("Workout History", back_cmd=self.show_main)
        self.clear_content()

        if not self.workout_data:
            self.lbl(self.content, "Workout history is empty", size=15,
                     fg=C.MUTED).place(relx=0.5, rely=0.4, anchor="center")
            return

        days = {}
        for d in self.workout_data:
            try:
                date = datetime.fromisoformat(d["timestamp"]).strftime("%d %B %Y")
            except Exception:
                continue
            days.setdefault(date, []).append(d)

        outer = tk.Frame(self.content, bg=C.BG)
        outer.pack(fill="both", expand=True, pady=(4, 10))
        canvas = tk.Canvas(outer, bg=C.BG, highlightthickness=0)
        canvas.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview,
                           style="Dark.Vertical.TScrollbar")
        sb.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=sb.set)
        inner = tk.Frame(canvas, bg=C.BG)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))

        def _on_wheel(e):
            if not canvas.winfo_exists():
                return
            d = e.delta
            if not d:
                return
            # macOS reports small deltas (±1); Windows reports multiples of 120
            step = int(-d / 120) if abs(d) >= 120 else (-1 if d > 0 else 1)
            canvas.yview_scroll(step, "units")
        canvas.bind_all("<MouseWheel>", _on_wheel)

        for date in sorted(days.keys(), reverse=True, key=lambda s: self._date_key(s)):
            total = 0
            for d in days[date]:
                try:
                    m, s = d["time"].split(":")
                    total += int(m) * 60 + int(s)
                except Exception:
                    pass
            day = self.card(inner)
            day.pack(fill="x", pady=7, padx=2)
            head = tk.Frame(day, bg=C.CARD)
            head.pack(fill="x", padx=16, pady=(12, 6))
            self.lbl(head, f"📅  {date}", size=14, weight="bold", fg=C.TEAL).pack(side="left")
            self.lbl(head, f"⏱  {self._fmt_seconds(total)}", size=12, fg=C.TXT2).pack(side="left", padx=12)
            RoundedButton(head, text="🗑", color=C.RED, variant="ghost",
                          command=lambda d=date: self.delete_day(d), width=44,
                          height=30, size=12).pack(side="right")
            for d in days[date]:
                rowf = tk.Frame(day, bg=C.CARD)
                rowf.pack(fill="x", padx=24, pady=2)
                self.lbl(rowf, f"🎸  {d['exercise']}", size=12, fg=C.TXT).pack(side="left")
                self.lbl(rowf, f"{d['time']}  ·  {d['bpm']} BPM", size=12,
                         fg=C.MUTED).pack(side="right")
            tk.Frame(day, bg=C.CARD, height=10).pack()

    def delete_day(self, date):
        day_workouts = [d for d in self.workout_data
                        if self._safe_date(d) == date]
        if not day_workouts:
            return
        if messagebox.askyesno("Guitar Trainer",
                               f"Delete the whole day {date}?\n\n{len(day_workouts)} entries will be removed."):
            self.workout_data = [d for d in self.workout_data if self._safe_date(d) != date]
            self.save_data()
            self.update_total_time()
            self.show_history()

    @staticmethod
    def _safe_date(d):
        try:
            return datetime.fromisoformat(d["timestamp"]).strftime("%d %B %Y")
        except Exception:
            return None

    # ----- manage exercises ------------------------------------------------
    def show_manage(self):
        self.set_header("Manage Exercises", back_cmd=self.show_main)
        self.clear_content()

        toolbar = tk.Frame(self.content, bg=C.BG)
        toolbar.pack(fill="x", pady=(4, 8))
        RoundedButton(toolbar, text="🗂  Add Exercise", color=C.GREEN,
                      command=self.add_exercise_dialog, height=38, size=13,
                      padx=16).pack(side="left", padx=(0, 8))
        RoundedButton(toolbar, text="📁  New Folder", color=C.BLUE,
                      command=self.create_folder_dialog, height=38, size=13,
                      padx=16).pack(side="left", padx=8)
        RoundedButton(toolbar, text="🗑  Delete Folder", color=C.RED, variant="tinted",
                      command=self.delete_folder_dialog, height=38, size=13,
                      padx=16).pack(side="left", padx=8)

        body = tk.Frame(self.content, bg=C.BG)
        body.pack(fill="both", expand=True, pady=(0, 8))

        left = self.card(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 14))
        tk.Frame(left, bg=C.CARD, height=12).pack()
        hint = self.lbl(left, "Drag an exercise onto a folder to move it",
                        size=11, fg=C.MUTED)
        hint.pack(anchor="w", padx=16, pady=(0, 6))
        tree_wrap = tk.Frame(left, bg=C.CARD)
        tree_wrap.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.ex_tree = ttk.Treeview(tree_wrap, show="tree", style="Dark.Treeview",
                                    selectmode="browse")
        self.ex_tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.ex_tree.yview,
                           style="Dark.Vertical.TScrollbar")
        sb.pack(side="right", fill="y")
        self.ex_tree.configure(yscrollcommand=sb.set)
        self._build_manage_tree()

        # right side: info editor + actions
        right = self.card(body)
        right.pack(side="right", fill="y")
        right.configure(width=300)
        right.pack_propagate(False)
        self.lbl(right, "Exercise Info", size=15, weight="bold").pack(anchor="w", padx=18, pady=(18, 8))
        self.info_link_var = tk.StringVar()
        self.info_note_var = tk.StringVar()
        self.lbl(right, "YouTube / Link", size=11, fg=C.MUTED).pack(anchor="w", padx=18)
        self.entry(right, textvariable=self.info_link_var, width=26).pack(padx=18, pady=(2, 10), ipady=4, fill="x")
        self.lbl(right, "Note", size=11, fg=C.MUTED).pack(anchor="w", padx=18)
        self.entry(right, textvariable=self.info_note_var, width=26).pack(padx=18, pady=(2, 10), ipady=4, fill="x")
        irow = tk.Frame(right, bg=C.CARD)
        irow.pack(fill="x", padx=18, pady=(2, 4))
        RoundedButton(irow, text="📎 Image", color=C.PURPLE, variant="tinted",
                      command=self.attach_image, height=34, size=12, padx=12).pack(side="left")
        RoundedButton(irow, text="💾 Save", color=C.BLUE, command=self.save_info,
                      height=34, size=12, padx=14).pack(side="left", padx=8)

        tk.Frame(right, bg=C.SEP, height=1).pack(fill="x", padx=18, pady=14)
        self.lbl(right, "Actions", size=15, weight="bold").pack(anchor="w", padx=18, pady=(0, 8))
        for text, color, cmd in [
            ("➡️  Move to Folder…", C.ORANGE, self.move_to_folder_dialog),
            ("⬅️  Remove from Folder", C.GRAY, self.remove_from_folder),
            ("✏️  Rename", C.PURPLE, self.rename_exercise),
            ("📈  Progress Chart", C.TEAL, self.show_chart),
            ("🗑  Delete Exercise", C.RED, self.delete_exercise),
        ]:
            RoundedButton(right, text=text, color=color,
                          variant=("tinted" if color in (C.RED, C.GRAY) else "solid"),
                          command=cmd, width=262, height=40, size=13).pack(padx=18, pady=4)

        self.ex_tree.bind("<<TreeviewSelect>>", self._on_manage_select)
        self._setup_drag()

    def _build_manage_tree(self, open_folders=None):
        self.ex_tree.delete(*self.ex_tree.get_children())
        self._node_kind = {}
        self._node_name = {}
        open_folders = open_folders or set()
        root_node = self.ex_tree.insert("", "end", text="  All Exercises", open=True)
        self._node_kind[root_node] = "all"
        for folder, items in sorted(self.structure.get("folders", {}).items()):
            fnode = self.ex_tree.insert(root_node, "end", text=f"📁  {folder}",
                                        open=(folder in open_folders))
            self._node_kind[fnode] = "folder"
            self._node_name[fnode] = folder
            for name in sorted(items):
                n = self.ex_tree.insert(fnode, "end", text=f"  {name}")
                self._node_kind[n] = "ex"
                self._node_name[n] = name
        for name in sorted(self.structure.get("root", [])):
            n = self.ex_tree.insert(root_node, "end", text=f"  {name}")
            self._node_kind[n] = "ex"
            self._node_name[n] = name
        self._root_node = root_node

    def _selected(self):
        sel = self.ex_tree.selection()
        if not sel:
            return None, None
        iid = sel[0]
        return self._node_kind.get(iid), self._node_name.get(iid)

    def _on_manage_select(self, _e):
        kind, name = self._selected()
        if kind != "ex":
            self.info_link_var.set("")
            self.info_note_var.set("")
            return
        info = self.structure.get("info", {}).get(name, {})
        self.info_link_var.set(info.get("link", ""))
        self.info_note_var.set(info.get("note", ""))

    def _open_folder_set(self):
        return {self._node_name[i] for i in self._node_kind
                if self._node_kind[i] == "folder" and self.ex_tree.item(i, "open")}

    # structure mutations
    def _remove_everywhere(self, name):
        if name in self.structure["root"]:
            self.structure["root"].remove(name)
        for items in self.structure["folders"].values():
            if name in items:
                items.remove(name)

    def create_folder_dialog(self):
        top = self.dialog("New Folder", 380, 190)
        self.lbl(top, "Folder name", size=13, fg=C.TXT2).pack(pady=(24, 6))
        var = tk.StringVar()
        e = self.entry(top, textvariable=var, width=28)
        e.pack(ipady=5)
        e.focus_set()

        def create():
            name = var.get().strip()
            if name and name not in self.structure["folders"]:
                self.structure["folders"][name] = []
                self.save_structure()
                top.destroy()
                self.show_manage()
            else:
                top.destroy()
        e.bind("<Return>", lambda ev: create())
        bar = tk.Frame(top, bg=C.BG)
        bar.pack(pady=20)
        RoundedButton(bar, text="Create", color=C.GREEN, command=create,
                      width=120, height=42, size=14).pack(side="left", padx=6)
        RoundedButton(bar, text="Cancel", color=C.GRAY, variant="ghost",
                      command=top.destroy, width=110, height=42, size=14).pack(side="left", padx=6)

    def add_exercise_dialog(self):
        top = self.dialog("Add Exercise", 480, 380)
        cont = tk.Frame(top, bg=C.BG)
        cont.pack(fill="both", expand=True, padx=24, pady=20)
        self.lbl(cont, "Name", size=12, fg=C.MUTED).pack(anchor="w")
        name_var = tk.StringVar()
        ne = self.entry(cont, textvariable=name_var, width=36)
        ne.pack(fill="x", ipady=5, pady=(2, 12))
        ne.focus_set()

        self.lbl(cont, "Folder", size=12, fg=C.MUTED).pack(anchor="w")
        folders = ["Root"] + sorted(self.structure.get("folders", {}).keys())
        folder_var = tk.StringVar(value="Root")
        ttk.Combobox(cont, textvariable=folder_var, values=folders, state="readonly",
                     style="Dark.TCombobox").pack(fill="x", pady=(2, 12))

        self.lbl(cont, "YouTube / Link", size=12, fg=C.MUTED).pack(anchor="w")
        link_var = tk.StringVar()
        self.entry(cont, textvariable=link_var, width=36).pack(fill="x", ipady=5, pady=(2, 12))
        self.lbl(cont, "Note", size=12, fg=C.MUTED).pack(anchor="w")
        note_var = tk.StringVar()
        self.entry(cont, textvariable=note_var, width=36).pack(fill="x", ipady=5, pady=(2, 12))

        def add_now():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("Guitar Trainer", "Enter an exercise name.")
                return
            if name in self.flatten():
                messagebox.showwarning("Guitar Trainer", "Such exercise already exists.")
                return
            if folder_var.get() == "Root":
                self.structure["root"].append(name)
            else:
                self.structure["folders"].setdefault(folder_var.get(), []).append(name)
            self.structure["info"][name] = {
                "link": link_var.get().strip(),
                "note": note_var.get().strip(),
                "image": None,
            }
            self.save_structure()
            top.destroy()
            self.show_manage()

        bar = tk.Frame(cont, bg=C.BG)
        bar.pack(fill="x", pady=(6, 0))
        RoundedButton(bar, text="Add", color=C.GREEN, command=add_now,
                      width=120, height=44, size=14).pack(side="right", padx=(8, 0))
        RoundedButton(bar, text="Cancel", color=C.GRAY, variant="ghost",
                      command=top.destroy, width=110, height=44, size=14).pack(side="right")

    def delete_folder_dialog(self):
        folders = sorted(self.structure.get("folders", {}).keys())
        if not folders:
            messagebox.showinfo("Guitar Trainer", "There are no folders to delete.")
            return
        top = self.dialog("Delete Folder", 380, 110 + 34 * len(folders))
        self.lbl(top, "Folder to delete (exercises move to Root):", size=12,
                 fg=C.TXT2).pack(pady=(20, 10), padx=20, anchor="w")
        var = tk.StringVar(value=folders[0])
        for name in folders:
            tk.Radiobutton(top, text=name, variable=var, value=name, bg=C.BG, fg=C.TXT,
                           selectcolor=C.ELEV, activebackground=C.BG, activeforeground=C.TXT,
                           font=get_font(13), anchor="w").pack(fill="x", padx=24)

        def do_delete():
            folder = var.get()
            items = self.structure["folders"].pop(folder, [])
            for ex in items:
                if ex not in self.structure["root"]:
                    self.structure["root"].append(ex)
            self.save_structure()
            top.destroy()
            self.show_manage()
        bar = tk.Frame(top, bg=C.BG)
        bar.pack(pady=16)
        RoundedButton(bar, text="Delete", color=C.RED, command=do_delete,
                      width=120, height=42, size=14).pack(side="left", padx=6)
        RoundedButton(bar, text="Cancel", color=C.GRAY, variant="ghost",
                      command=top.destroy, width=110, height=42, size=14).pack(side="left", padx=6)

    def move_to_folder_dialog(self):
        kind, name = self._selected()
        if kind != "ex":
            return
        folders = sorted(self.structure.get("folders", {}).keys())
        if not folders:
            messagebox.showinfo("Guitar Trainer", "Create a folder first.")
            return
        top = self.dialog("Move to Folder", 360, 120 + 34 * len(folders))
        self.lbl(top, f"Move '{name}' to:", size=12, fg=C.TXT2).pack(pady=(20, 10), padx=20, anchor="w")
        var = tk.StringVar(value=folders[0])
        for f in folders:
            tk.Radiobutton(top, text=f, variable=var, value=f, bg=C.BG, fg=C.TXT,
                           selectcolor=C.ELEV, activebackground=C.BG, activeforeground=C.TXT,
                           font=get_font(13), anchor="w").pack(fill="x", padx=24)

        def confirm():
            self._remove_everywhere(name)
            self.structure["folders"].setdefault(var.get(), []).append(name)
            self.save_structure()
            top.destroy()
            self.show_manage()
        RoundedButton(top, text="Move", color=C.GREEN, command=confirm,
                      width=120, height=42, size=14).pack(pady=16)

    def remove_from_folder(self):
        kind, name = self._selected()
        if kind != "ex":
            return
        in_folder = any(name in items for items in self.structure["folders"].values())
        if not in_folder:
            return
        for items in self.structure["folders"].values():
            if name in items:
                items.remove(name)
        if name not in self.structure["root"]:
            self.structure["root"].append(name)
        self.save_structure()
        self.show_manage()

    def rename_exercise(self):
        kind, old = self._selected()
        if kind != "ex":
            return
        top = self.dialog("Rename Exercise", 420, 180)
        self.lbl(top, "New name", size=12, fg=C.MUTED).pack(pady=(24, 6))
        var = tk.StringVar(value=old)
        e = self.entry(top, textvariable=var, width=34)
        e.pack(ipady=5)
        e.focus_set()
        e.select_range(0, "end")

        def do_rename():
            new = var.get().strip()
            if not new or new == old:
                top.destroy()
                return
            for i, n in enumerate(self.structure["root"]):
                if n == old:
                    self.structure["root"][i] = new
            for items in self.structure["folders"].values():
                for i, n in enumerate(items):
                    if n == old:
                        items[i] = new
            if old in self.structure["info"]:
                self.structure["info"][new] = self.structure["info"].pop(old)
            for d in self.workout_data:
                if d.get("exercise") == old:
                    d["exercise"] = new
            self.save_structure()
            self.save_data()
            top.destroy()
            self.show_manage()
        e.bind("<Return>", lambda ev: do_rename())
        bar = tk.Frame(top, bg=C.BG)
        bar.pack(pady=18)
        RoundedButton(bar, text="Save", color=C.GREEN, command=do_rename,
                      width=120, height=42, size=14).pack(side="left", padx=6)
        RoundedButton(bar, text="Cancel", color=C.GRAY, variant="ghost",
                      command=top.destroy, width=110, height=42, size=14).pack(side="left", padx=6)

    def delete_exercise(self):
        kind, name = self._selected()
        if kind != "ex":
            return
        if not messagebox.askyesno("Guitar Trainer", f"Delete exercise '{name}'?"):
            return
        self._remove_everywhere(name)
        self.structure.get("info", {}).pop(name, None)
        self.save_structure()
        self.show_manage()

    def save_info(self):
        kind, name = self._selected()
        if kind != "ex":
            messagebox.showinfo("Guitar Trainer", "Select an exercise first.")
            return
        info = self.structure["info"].get(name, {})
        self.structure["info"][name] = {
            "link": self.info_link_var.get().strip(),
            "note": self.info_note_var.get().strip(),
            "image": info.get("image"),
        }
        self.save_structure()
        messagebox.showinfo("Guitar Trainer", "Info saved.")

    def attach_image(self):
        kind, name = self._selected()
        if kind != "ex":
            return
        path = filedialog.askopenfilename(
            title="Select Image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp")])
        if not path:
            return
        info = self.structure["info"].setdefault(name, {})
        info["image"] = path
        info.setdefault("link", "")
        info.setdefault("note", "")
        self.save_structure()
        messagebox.showinfo("Guitar Trainer", "Image attached.")

    # drag & drop in the manage tree
    def _setup_drag(self):
        self._drag = {"name": None, "iid": None, "start": None, "ghost": None, "active": False}
        self.ex_tree.bind("<ButtonPress-1>", self._drag_start, add="+")
        self.ex_tree.bind("<B1-Motion>", self._drag_motion, add="+")
        self.ex_tree.bind("<ButtonRelease-1>", self._drag_release, add="+")

    def _drag_start(self, e):
        iid = self.ex_tree.identify_row(e.y)
        if iid and self._node_kind.get(iid) == "ex":
            self._drag.update(name=self._node_name[iid], iid=iid,
                              start=(e.x_root, e.y_root), active=False)
        else:
            self._drag["name"] = None

    def _drag_motion(self, e):
        if not self._drag["name"]:
            return
        sx, sy = self._drag["start"]
        if not self._drag["active"]:
            if abs(e.x_root - sx) + abs(e.y_root - sy) < 6:
                return
            self._drag["active"] = True
            g = tk.Toplevel(self.root)
            g.overrideredirect(True)
            try:
                g.attributes("-alpha", 0.9)
                g.attributes("-topmost", True)
            except Exception:
                pass
            tk.Label(g, text=self._drag["name"], bg=C.BLUE, fg="#FFFFFF",
                     font=get_font(12, "bold"), padx=10, pady=4).pack()
            self._drag["ghost"] = g
            self.ex_tree.configure(cursor="hand2")
        if self._drag["ghost"]:
            self._drag["ghost"].geometry(f"+{e.x_root + 12}+{e.y_root + 12}")

    def _drag_release(self, e):
        d = self._drag
        if d["ghost"]:
            d["ghost"].destroy()
        self.ex_tree.configure(cursor="")
        if not d["name"] or not d["active"]:
            self._drag = {"name": None, "iid": None, "start": None, "ghost": None, "active": False}
            return
        name = d["name"]
        target = self.ex_tree.identify_row(e.y)
        kind = self._node_kind.get(target)
        if kind == "ex":
            target = self.ex_tree.parent(target)
            kind = self._node_kind.get(target)
        moved = False
        if kind == "folder":
            self._remove_everywhere(name)
            self.structure["folders"].setdefault(self._node_name[target], []).append(name)
            moved = True
        elif kind == "all":
            self._remove_everywhere(name)
            if name not in self.structure["root"]:
                self.structure["root"].append(name)
            moved = True
        self._drag = {"name": None, "iid": None, "start": None, "ghost": None, "active": False}
        if moved:
            open_folders = self._open_folder_set()
            self.save_structure()
            self._build_manage_tree(open_folders=open_folders)

    # ----- settings --------------------------------------------------------
    def open_settings(self):
        top = self.dialog("Settings", 440, 240)
        self.lbl(top, "⚙️  Settings", size=18, weight="bold").pack(pady=(22, 6))
        self.lbl(top, 'Mark an exercise as "not played recently"\nafter this many days:',
                 size=12, fg=C.TXT2, justify="center").pack(pady=(4, 14))
        val = tk.IntVar(value=int(self.stale_days))
        sp = tk.Spinbox(top, from_=1, to=60, textvariable=val, width=6,
                        font=get_font(18, "bold"), bg=C.ELEV, fg=C.TXT,
                        buttonbackground=C.ELEV, relief="flat", justify="center",
                        highlightthickness=1, highlightbackground=C.SEP)
        sp.pack(ipady=4)

        def save():
            try:
                self.stale_days = int(val.get())
            except Exception:
                self.stale_days = 7
            self.save_settings()
            top.destroy()
        bar = tk.Frame(top, bg=C.BG)
        bar.pack(pady=22)
        RoundedButton(bar, text="Save", color=C.GREEN, command=save,
                      width=120, height=42, size=14).pack(side="left", padx=6)
        RoundedButton(bar, text="Close", color=C.GRAY, variant="ghost",
                      command=top.destroy, width=110, height=42, size=14).pack(side="left", padx=6)

    # ----- info window -----------------------------------------------------
    def show_info(self):
        name = self.current_exercise
        info = self.structure.get("info", {}).get(name, {})
        link = info.get("link")
        note = info.get("note")
        image_path = info.get("image")

        top = self.dialog(f"Info — {name}", 640, 560)
        self.lbl(top, name, size=18, weight="bold").pack(pady=(20, 10))

        if link:
            link_lbl = self.lbl(top, "▶  Open video / link", size=13, fg=C.BLUE)
            link_lbl.configure(cursor="hand2")
            link_lbl.pack(pady=4)
            link_lbl.bind("<Button-1>", lambda ev: webbrowser.open(link))
        else:
            self.lbl(top, "No link", size=12, fg=C.MUTED).pack(pady=4)

        if note:
            self.lbl(top, note, size=13, fg=C.TXT2, wraplength=560,
                     justify="center").pack(pady=8, padx=20)

        holder = tk.Frame(top, bg=C.BG)
        holder.pack(fill="both", expand=True, padx=20, pady=12)
        if image_path and os.path.exists(image_path) and Image and ImageTk:
            try:
                img = Image.open(image_path)
                img.thumbnail((580, 360))
                tkimg = ImageTk.PhotoImage(img)
                lab = tk.Label(holder, image=tkimg, bg=C.BG)
                lab.image = tkimg
                lab.pack()
            except Exception:
                self.lbl(holder, "Could not load image", size=12, fg=C.RED).pack()
        elif not link and not note:
            self.lbl(holder, "No info added yet", size=13, fg=C.MUTED).pack(pady=30)

        RoundedButton(top, text="Close", color=C.GRAY, variant="ghost",
                      command=top.destroy, width=120, height=42, size=14).pack(pady=14)

    # ----- progress chart --------------------------------------------------
    def show_chart(self):
        kind, name = self._selected()
        if kind != "ex":
            messagebox.showinfo("Guitar Trainer", "Select an exercise first.")
            return
        data = [d for d in self.workout_data if d.get("exercise") == name]
        if not data:
            messagebox.showinfo("Guitar Trainer", f"No data for '{name}' yet.")
            return

        mpl = load_mpl()
        top = self.dialog(f"Progress — {name}", 900, 660)
        st = self.exercise_stats(name)
        self.lbl(top, f"📊  {name}", size=18, weight="bold").pack(pady=(18, 4))
        self.lbl(top, f"Sessions: {st['sessions']}      Total: {st['total_formatted']}"
                      f"      Best BPM: {self.best_bpm(name)}", size=13, fg=C.TXT2).pack(pady=(0, 8))

        dates, bpms = [], []
        for d in sorted(data, key=lambda x: x["timestamp"]):
            try:
                if str(d["bpm"]).isdigit():
                    dates.append(datetime.fromisoformat(d["timestamp"]))
                    bpms.append(int(d["bpm"]))
            except Exception:
                continue

        if mpl and len(dates) >= 2:
            plt, FigureCanvasTkAgg, mdates = mpl
            fig, ax = plt.subplots(figsize=(9, 4.6))
            fig.patch.set_facecolor(C.BG)
            ax.set_facecolor(C.CARD)
            ax.plot(dates, bpms, "o-", linewidth=2.4, markersize=8, color=C.BLUE)
            for dt, b in zip(dates, bpms):
                ax.annotate(str(b), (dt, b), textcoords="offset points",
                            xytext=(0, 10), ha="center", fontsize=8, color=C.TXT2)
            ax.set_ylabel("BPM", color=C.TXT2)
            ax.grid(True, alpha=0.18, color=C.SEP)
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
            for spine in ax.spines.values():
                spine.set_color(C.SEP)
            ax.tick_params(colors=C.TXT2)
            fig.autofmt_xdate(rotation=45)
            fig.tight_layout()
            canvas = FigureCanvasTkAgg(fig, top)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=True, padx=18, pady=10)
        else:
            self.lbl(top, "Need at least two logged sessions to draw a chart.",
                     size=13, fg=C.MUTED).pack(pady=40)

        RoundedButton(top, text="Close", color=C.GRAY, variant="ghost",
                      command=top.destroy, width=120, height=42, size=14).pack(pady=12)

    # ----- lifecycle -------------------------------------------------------
    def on_quit(self):
        self._stop_clocks()
        try:
            if pygame and pygame.mixer.get_init():
                pygame.mixer.quit()
        except Exception:
            pass
        self.root.destroy()


_MPL = None


def load_mpl():
    global _MPL
    if _MPL is None:
        try:
            import matplotlib
            matplotlib.use("TkAgg")
            import matplotlib.pyplot as plt
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            import matplotlib.dates as mdates
            _MPL = (plt, FigureCanvasTkAgg, mdates)
        except Exception:
            _MPL = False
    return _MPL


def main():
    root = tk.Tk()
    GuitarTrainer(root)
    root.mainloop()


if __name__ == "__main__":
    main()
