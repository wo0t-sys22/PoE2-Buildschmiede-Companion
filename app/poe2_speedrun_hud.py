"""Compact, independently positioned speedrun timer for the in-game HUD."""

import logging
import time
import tkinter as tk
from tkinter import messagebox

from poe2_overlay_controls import ClickTargets, InputRegion


SEGMENT_LABELS = {
    "act1": ("Akt 1", "Act 1"),
    "act2": ("Akt 2", "Act 2"),
    "act3": ("Akt 3", "Act 3"),
    "act4": ("Akt 4", "Act 4"),
    "act5": ("Akt 5", "Act 5"),
    "act6": ("Akt 6", "Act 6"),
}
STATUS_LABELS = {
    "ready": ("Bereit", "Ready"),
    "running": ("Läuft", "Running"),
    "paused": ("Pausiert", "Paused"),
    "finished": ("Beendet", "Finished"),
}


def duration(seconds, *, tenths=False):
    if seconds is None:
        return "–"
    ticks = int(max(0, seconds) * 10)
    hours, rest = divmod(ticks // 10, 3600)
    minutes, seconds = divmod(rest, 60)
    text = f"{minutes:02d}:{seconds:02d}"
    if hours:
        text = f"{hours}:{text}"
    return f"{text}.{ticks % 10}" if tenths else text


class TimerPosition:
    """Mouse gestures and persisted coordinates independent of the campaign HUD."""

    def __init__(self, hud):
        self.hud = hud
        self.drag = None
        self.location = None

    def restore(self):
        window = self.hud.window
        saved = self.hud.app.prefs.get("speedrun_position")
        if isinstance(saved, list) and len(saved) == 2 and all(type(value) is int for value in saved):
            self.place(*saved)
            return
        guide = self.hud.app.current.layout
        width = window.winfo_reqwidth()
        left, _, right, _ = guide._work_area(guide.x, guide.y, guide.width, guide.height)
        x = guide.x + guide.width + 12
        if x + width > right and guide.x - width - 12 >= left:
            x = guide.x - width - 12
        self.place(x, guide.y)

    def place(self, x, y):
        window = self.hud.window
        native = self.hud.app.native
        width, height = window.winfo_reqwidth(), window.winfo_reqheight()
        rect = (x, y, x + width, y + height)
        work = native.work_area(rect=rect) if native else None
        left, top, right, bottom = work or (0, 0, window.winfo_screenwidth(), window.winfo_screenheight())
        x = max(left, min(x, right - width))
        y = max(top, min(y, bottom - height))
        self.location = (x, y)
        if native and window.winfo_ismapped():
            native.place(native.hwnd(window), x, y, width, height)
        else:
            window.geometry(f"+{x}+{y}")
        if self.hud.click_targets:
            self.hud.click_targets.schedule()

    def begin(self, event):
        self.drag = (event.x_root - self.hud.window.winfo_rootx(), event.y_root - self.hud.window.winfo_rooty())

    def move(self, event):
        if self.drag:
            self.place(event.x_root - self.drag[0], event.y_root - self.drag[1])

    def finish(self):
        if self.drag and self.location is not None:
            try:
                self.hud.app.save_preferences(speedrun_position=list(self.location))
            except OSError:
                logging.exception("Position des Speedrun-Timers konnte nicht gespeichert werden.")
        self.drag = None


class SpeedrunHUD:
    """A top-level that shares the guide's opacity and input routing."""

    def __init__(self, app):
        self.app = app
        self.hud_bg = app.current.hud_bg
        self.window = tk.Toplevel(app.root, bg=self.hud_bg)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.protocol("WM_DELETE_WINDOW", lambda: app.set_speedrun_details(False))
        self.window.bind("<Escape>", lambda _: app.set_speedrun_details(False))
        self.shell = tk.Frame(self.window, padx=9, pady=6, highlightthickness=1)
        self.shell.pack(fill="both", expand=True)
        self.header = tk.Frame(self.shell)
        self.header.pack(fill="x")
        self.title = tk.Label(self.header, text="Speedrun Timer", anchor="w")
        self.title.pack(side="left", fill="x", expand=True)
        self.close_button = tk.Button(self.header, text="×", width=2, command=lambda: app.set_speedrun_details(False))
        self.close_button.pack(side="right")
        self.help_button = tk.Button(self.header, text="?", width=2, command=self._show_help)
        self.help_button.pack(side="right", padx=(0, 3))
        self.time = tk.Label(self.shell, anchor="w", width=12)
        self.time.pack(fill="x")
        self.status = tk.Label(self.shell, anchor="w")
        self.status.pack(fill="x", pady=(0, 4))
        self.table = tk.Frame(self.shell, padx=5, pady=3)
        self.table.pack(fill="x")
        header_names = (("Abschnitt", "Segment"), ("Zeit", "Time"), ("Δ PB", "Δ PB"), ("Best", "Best"))
        self.columns = tuple((self._cell(0, column), names) for column, names in enumerate(header_names))
        self.rows = {
            ident: tuple(self._cell(row, column) for column in range(len(header_names)))
            for row, ident in enumerate(SEGMENT_LABELS, 1)
        }
        self.summary = tk.Label(self.shell, anchor="w")
        self.summary.pack(fill="x", pady=(4, 2))
        self.actions = tk.Frame(self.shell)
        self.actions.pack(fill="x")
        self.toggle_button = self._button("toggle", 0)
        self.finish_button = self._button("finish", 1)
        self.reset_button = self._button("reset", 2)
        self.layout = TimerPosition(self)
        self.sample = None
        self.sampled_at = None
        self.tick_job = None
        self.visible = False
        self.control_state = None
        self.theme_state = None
        self.click_targets = (ClickTargets(self) if app.color_key else InputRegion(self)) if app.native else None
        self.window.bind("<Map>", self._mapped, add="+")
        self.window.bind("<Configure>", self._configured, add="+")
        for widget in (self.header, self.title):
            widget.bind("<ButtonPress-1>", lambda event: self._begin_gesture("move", event))
            widget.bind("<B1-Motion>", self._move_gesture)
            widget.bind("<ButtonRelease-1>", lambda _: self.layout.finish())

    def _cell(self, row, column):
        width = (14, 7, 7, 7)[column]
        label = tk.Label(self.table, anchor="w" if column == 0 else "e", width=width, padx=3)
        label.grid(row=row, column=column, sticky="ew")
        return label

    def _button(self, action, column):
        button = tk.Button(self.actions, command=lambda: self.app.control_timer(action))
        button.grid(row=0, column=column, sticky="ew", padx=2)
        self.actions.columnconfigure(column, weight=1, uniform="timer")
        return button

    def _show_help(self):
        english = self.app.language == "en"
        explanation = (
            "Automatic splits use the area events identified in Client.txt. Acts 5 and 6 are ready "
            "for the campaign change. Their 1.0 area mappings still need verification with live logs "
            "once the patch is available. Without a game log, you can use the timer as a stopwatch."
            if english else
            "Die automatischen Splits verwenden die erkannten Gebietswechsel aus Client.txt. Akt 5 und 6 "
            "sind für den Kampagnenwechsel vorgesehen. Ihre Gebietszuordnung muss mit echten Logs "
            "geprüft werden, sobald 1.0 verfügbar ist. Ohne Spiel-Log kannst du die Stoppuhr verwenden."
        )
        messagebox.showinfo("Speedrun Timer" if english else "Speedrun-Timer", explanation, parent=self.window)

    @property
    def lookup_dialog(self):
        return self.app.current.lookup_dialog

    def scroll_guide(self, _event):
        return None  # The timer has no scrollable content.

    def _begin_gesture(self, _operation, event):
        if not self.app.click_through:
            self.layout.begin(event)

    def _move_gesture(self, event):
        self.layout.move(event)

    def _mapped(self, event):
        if not self.visible:
            return
        if event.widget is self.window:
            self._sync_click_mode()
        elif self.click_targets:
            # Child widgets can map after the transparent native input window.
            self.click_targets.schedule()

    def _configured(self, _event):
        if self.click_targets:
            self.click_targets.schedule()

    def _sync_click_mode(self):
        if not self.window.winfo_viewable():
            return
        cursor = "arrow" if self.app.click_through else "fleur"
        for widget in (self.header, self.title):
            widget.configure(cursor=cursor)
        if not self.click_targets:
            return
        try:
            if self.app.color_key:
                # On Windows the picture is click-through; the masked input window
                # handles only interactive controls while the HUD is locked.
                self.app.native.set_click_mode(self.window, True, alpha=self.app.overlay_alpha())
            self.click_targets.show()
        except (OSError, tk.TclError):
            logging.exception("Klickflächen des Speedrun-Timers konnten nicht aktiviert werden.")

    def apply_opacity(self):
        """Update the picture; the separate Windows click layer keeps its own fixed alpha."""
        alpha = self.app.overlay_alpha()
        if self.app.native:
            if not self.app.color_key or self.window.winfo_viewable():
                self.app.native.set_opacity(self.window, alpha)
        else:
            self.window.attributes("-alpha", alpha / 255)

    def show(self):
        if not self.visible:
            self.visible = True
            if not self.app.color_key:
                self.apply_opacity()
            self.window.update_idletasks()
            self.layout.restore()
            self.window.deiconify()
            self._sync_click_mode()
        self._schedule_tick()

    def hide(self):
        if not self.visible:
            return
        self.visible = False
        self.layout.finish()
        if self.tick_job is not None:
            self.window.after_cancel(self.tick_job)
            self.tick_job = None
        if self.click_targets:
            self.click_targets.hide()
        self.window.withdraw()

    def close(self):
        self.hide()
        self.window.destroy()

    def _style(self):
        theme = self.app.theme
        family = self.app.theme_font(fallback=self.app.ui_family)
        state = (theme, family)
        if state == self.theme_state:
            return
        self.theme_state = state
        background = theme.panel
        self.shell.configure(bg=background, highlightbackground=theme.edge, highlightcolor=theme.edge)
        for frame in (self.header, self.actions):
            frame.configure(bg=background)
        self.table.configure(bg=theme.control)
        self.title.configure(bg=background, fg=theme.accent, font=(family, 10, "bold"))
        self.time.configure(bg=background, fg=theme.text, font=("Consolas", 23, "bold"))
        for label in (self.status, self.summary):
            label.configure(bg=background, fg=theme.text, font=(family, 8))
        for label, _ in self.columns:
            label.configure(bg=theme.control, fg=theme.accent, font=(family, 8, "bold"))
        for segment in self.rows.values():
            for label in segment:
                label.configure(bg=theme.control, fg=theme.text, font=(family, 8))
        for button in (self.close_button, self.help_button, self.toggle_button, self.finish_button, self.reset_button):
            button.configure(bg=theme.control, fg=theme.text, disabledforeground=theme.edge,
                             activebackground=theme.active, activeforeground=theme.text,
                             bd=0, pady=1, cursor="hand2", font=(family, 9))

    def refresh(self, sample):
        self.sample = sample
        self.sampled_at = time.monotonic()
        self._style()
        english = self.app.language == "en"
        self.title.configure(text="Speedrun Timer" if english else "Speedrun-Timer")
        status = sample["status"]
        active = next((row for row in sample["rows"] if row["status"] == "active"), None)
        label = STATUS_LABELS[status][english]
        if active:
            label += "  ·  " + SEGMENT_LABELS[active["id"]][english]
        if status != "ready" and not sample["eligible"]:
            label += "  ·  " + ("Practice" if english else "Übung")
        elif status == "ready" and not sample["autoSplits"]:
            label += "  ·  " + ("No client log" if english else "Kein Spiel-Log")
        self.status.configure(text=label)
        for header, names in self.columns:
            header.configure(text=names[english])
        theme = self.app.theme
        for row in sample["rows"]:
            segment, elapsed, delta, best = self.rows[row["id"]]
            is_active = row["status"] == "active"
            color = theme.accent if is_active else theme.text
            background = theme.active if is_active else theme.control
            segment.configure(text=SEGMENT_LABELS[row["id"]][english], fg=color, bg=background)
            elapsed.configure(text=duration(row["seconds"]), fg=color, bg=background)
            diff = row["delta"]
            sign = "−" if diff is not None and diff < 0 else "+"
            diff_text = sign + duration(abs(diff)) if diff is not None else "–"
            diff_color = ("#a0ee7d" if diff < 0 else "#ffbdb0") if diff else color
            delta.configure(text=diff_text, fg=diff_color, bg=background)
            best.configure(text=duration(row["best"]), fg=color, bg=background)
        totals = "Best segments" if english else "Beste Abschnitte"
        self.summary.configure(text=f"PB {duration(sample['personalBest'])}   ·   {totals} {duration(sample['sumOfBest'])}")
        control_state = english, status, sample["canFinish"]
        if control_state != self.control_state:
            self.control_state = control_state
            self.toggle_button.configure(text={
                "ready": ("Start", "Start"), "running": ("Pause", "Pause"),
                "paused": ("Weiter", "Resume"), "finished": ("Neuer Lauf", "New run"),
            }[status][english])
            self.finish_button.configure(text="Finish" if english else "Beenden",
                                         state="normal" if sample["canFinish"] else "disabled")
            self.reset_button.configure(text="Reset",
                                        state="disabled" if status == "ready" else "normal")
            if self.click_targets:
                self.click_targets.schedule()
        self._render_time()
        self._schedule_tick()

    def _render_time(self):
        elapsed = self.sample["elapsed"]
        if self.sample["status"] == "running":
            advance = time.monotonic() - self.sampled_at
            elapsed += advance
            active = next((row for row in self.sample["rows"] if row["status"] == "active"), None)
            if active and active["seconds"] is not None:
                self.rows[active["id"]][1].configure(text=duration(active["seconds"] + advance))
        self.time.configure(text=duration(elapsed, tenths=True))

    def _schedule_tick(self):
        if self.visible and self.sample["status"] == "running" and self.tick_job is None:
            self.tick_job = self.window.after(100, self._tick)

    def _tick(self):
        self.tick_job = None
        self._render_time()
        self._schedule_tick()
