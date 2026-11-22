"""Shared controls and the clickable areas of a guide that lets other mouse input through."""

import logging
import tkinter as tk
from tkinter import ttk


class AutoHideScrollbar(ttk.Scrollbar):
    """A grid-managed scrollbar that only appears for overflowing content."""

    def set(self, first, last):
        super().set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            self.grid_remove()
        else:
            self.grid()


class ScrollArrows(tk.Frame):
    """Page controls for content that exceeds the available height."""

    def __init__(self, parent, view, background, accent, *, inset=4):
        super().__init__(parent, bg=background)
        self.view = view
        self.inset = inset
        self.buttons = []
        for direction, glyph in ((-1, "▲"), (1, "▼")):
            button = tk.Button(self, text=glyph, font=("Segoe UI Symbol", 16, "bold"),
                               relief="flat", bd=0, padx=5, pady=0,
                               command=lambda d=direction: view.yview_scroll(d, "pages"))
            button.pack(side="left")
            self.buttons.append(button)
        self.colors(background, accent)

    def colors(self, background, accent):
        self.configure(bg=background)
        for button in self.buttons:
            button.configure(bg=background, fg=accent, activebackground=background, activeforeground=accent,
                             disabledforeground="#706b61")

    def extent(self, first, last):
        above, below = float(first) > 0.00001, float(last) < 0.99999
        if above or below:
            if not self.winfo_manager():
                self.place(relx=1, rely=1, x=-self.inset, y=-3, anchor="se")
            self.lift()
            for button, enabled in zip(self.buttons, (above, below)):
                button.configure(state="normal" if enabled else "disabled")
        elif self.winfo_manager():
            self.place_forget()


class BrassSlider(tk.Canvas):
    """Integer slider with a bevelled thumb and keyboard control."""

    def __init__(self, parent, low, high, initial, command, px):
        super().__init__(parent, width=px(140), height=px(26), bg="#151515",
                         highlightthickness=1, highlightbackground="#151515",
                         highlightcolor="#a39069", bd=0, takefocus=True, cursor="hand2")
        self.low, self.high = low, high
        self.value = initial
        self.command = command
        self.colors = ("#64573f", "#24211e", "#a68f61", "#8a7752", "#dfcca0", "#e3d5b1")
        self.px = px
        self.thumb = "diamond"
        self.bind("<Configure>", self.draw)
        self.bind("<Button-1>", self.pick)
        self.bind("<B1-Motion>", self.pick)
        for key, delta in (("Left", -1), ("Right", 1), ("Down", -1), ("Up", 1)):
            self.bind("<" + key + ">", lambda event, d=delta: self.set(self.value + d))
        self.bind("<Home>", lambda event: self.set(self.low))
        self.bind("<End>", lambda event: self.set(self.high))

    def set(self, value, *, notify=True):
        value = max(self.low, min(self.high, round(value)))
        if self.value != value:
            self.value = value
            self.draw()
            if notify:
                self.command(value)
        return "break"

    def pick(self, event):
        self.focus_set()
        margin = self.px(9)
        width = max(1, self.winfo_width() - 2 * margin)
        self.set(self.low + (event.x - margin) * (self.high - self.low) / width)

    def apply_theme(self, theme):
        self.configure(bg=theme.panel, highlightbackground=theme.panel, highlightcolor=theme.accent)
        self.colors = (theme.edge, theme.control, theme.accent, theme.active, theme.accent, theme.text)
        self.thumb = theme.treatment.slider_thumb
        self.draw()

    def draw(self, event=None):
        self.delete("all")
        pad = self.px(9)
        right = max(pad + 1, self.winfo_width() - pad)
        y = self.winfo_height() // 2
        x = pad + (right-pad) * (self.value-self.low) / max(1, self.high-self.low)
        edge, track, fill, handle, outline, light = self.colors
        if self.thumb == "diamond":
            self.create_line(pad, y, right, y, width=self.px(7), fill=edge, capstyle="round")
            self.create_line(pad, y, right, y, width=self.px(5), fill=track, capstyle="round")
            self.create_line(pad, y, x, y, width=self.px(3), fill=fill, capstyle="round")
            w, h = self.px(5), self.px(8)
            self.create_polygon(x-w, y, x, y-h, x+w, y, x, y+h, fill=handle, outline=outline)
            self.create_polygon(x-w+1, y, x, y-h+1, x, y, fill=light, outline="")
            return

        self.create_line(pad, y, right, y, width=self.px(2), fill=edge)
        self.create_line(pad, y, x, y, width=self.px(2), fill=fill)
        w, h = self.px(5), self.px(7)
        if self.thumb == "dot":
            self.create_oval(x-w, y-w, x+w, y+w, fill=fill, outline="")
        elif self.thumb == "chamfer":
            notch = self.px(3)
            self.create_polygon(x-w, y-h+notch, x-w+notch, y-h, x+w, y-h, x+w, y+h-notch,
                                x+w-notch, y+h, x-w, y+h, fill=handle, outline=outline)
        elif self.thumb == "block":
            self.create_rectangle(x-w, y-h, x+w, y+h, fill=fill, outline="")
        elif self.thumb == "bar":
            self.create_line(x, y-h, x, y+h, fill=fill, width=self.px(3))
        elif self.thumb == "tally":
            self.create_rectangle(x-w, y-h, x+w, y+h, fill=handle, outline=outline)
            self.create_line(x, y-h+2, x, y+h-2, fill=outline)



class SearchCategories(tk.Frame):
    """Keep category positions aligned and reserve room for the actual search results."""

    def __init__(self, parent, guide, labels, current, select, caption):
        super().__init__(parent, bg=guide.hud_bg)
        self.gap = guide._icon_pixels(3)
        self.columns = None
        theme = guide.theme
        self.buttons = []
        for index, label in enumerate(labels):
            button = guide.small_button(self, label, lambda i=index: select(i))
            button.configure(padx=guide._icon_pixels(5), pady=guide._icon_pixels(3))
            if index == current:
                button.configure(bg=theme.selection_color, fg=theme.selection_text,
                                 activebackground=theme.selection_color, activeforeground=theme.selection_text,
                                 highlightbackground=theme.accent)
            self.buttons.append(button)

        self.compact = tk.Frame(self, bg=theme.panel)
        self.compact.columnconfigure(1, weight=1)
        self.caption = tk.Label(self.compact, text=caption, bg=theme.panel, fg=theme.accent,
                                font=guide.ui_font(9, "bold"), padx=2 * self.gap)
        self.caption.grid(row=0, column=0)
        self.picker = ttk.Combobox(self.compact, values=labels, state="readonly", width=1,
                                   font=guide.ui_font(9, "bold"), style="Atlas.TCombobox")
        if current is not None:
            self.picker.current(current)
        self.picker.bind("<<ComboboxSelected>>", lambda event: select(self.picker.current()))
        self.picker.grid(row=0, column=1, sticky="ew")
        self.picker_fonts = []
        for points in range(9, 4, -1):
            font = guide.ui_font(points, "bold")
            self.picker_fonts.append((font, max(font.measure(label) for label in labels)))
        self.picker_inset = self.picker.winfo_reqwidth() - guide.ui_font(9, "bold").measure("0") + self.gap

    def fit(self, width, body_height):
        widths = [b.winfo_reqwidth() for b in self.buttons]
        row_height = max(b.winfo_reqheight() for b in self.buttons)
        count = len(widths)
        columns = 0
        for candidate in (8, 4, 2):
            if candidate > count:
                continue
            # The longest label sets its column's minimum across all rows.
            needed = sum(max(widths[i::candidate]) for i in range(candidate)) + (candidate - 1) * self.gap
            rows = (count + candidate - 1) // candidate
            # Allow for the search action and at least three lines below the filters.
            if needed <= width and (rows + 4) * row_height + rows * self.gap <= body_height:
                columns = candidate
                break
        if not columns:
            room = width - self.picker_inset
            if self.caption.winfo_reqwidth() + self.picker_fonts[0][1] <= room:
                if not self.caption.winfo_manager():
                    self.caption.grid()
                room -= self.caption.winfo_reqwidth()
            elif self.caption.winfo_manager():
                self.caption.grid_remove()
            font = next((font for font, needed in self.picker_fonts if needed <= room), self.picker_fonts[-1][0])
            if str(self.picker.cget("font")) != str(font):
                self.picker.configure(font=font)
        if columns == self.columns:
            return
        for col in range(self.columns or 0):
            self.columnconfigure(col, weight=0)
        self.columns = columns
        if not columns:
            for button in self.buttons:
                button.grid_remove()
            self.compact.grid(row=0, column=0, sticky="ew")
            self.columnconfigure(0, weight=1)
            return
        self.compact.grid_remove()
        for col in range(columns):
            self.columnconfigure(col, weight=1)
        for index, button in enumerate(self.buttons):
            row, col = divmod(index, columns)
            button.grid(row=row, column=col, sticky="nsew",
                        padx=(0, self.gap if col + 1 < columns else 0), pady=(self.gap if row else 0, 0))


class FlowRow(tk.Frame):
    """Wrap controls within the width already assigned by the surrounding pane."""

    def __init__(self, parent, *, bg, gap=4, distribute=False):
        super().__init__(parent, bg=bg, height=1)
        self.distribute = distribute
        self.gap = gap
        self.pending = None
        self.bind("<Configure>", self.reflow)

    def reflow(self, event=None):
        if self.pending is None:
            self.pending = self.after_idle(self._layout)

    def _layout(self):
        self.pending = None
        available = self.winfo_width()
        if available <= 1:
            return
        children = self.winfo_children()
        if self.distribute and children:
            minimum = max(child.winfo_reqwidth() for child in children)
            columns = max(1, min(len(children), (available + self.gap) // (minimum + self.gap)))
            height = max(child.winfo_reqheight() for child in children)
            for start in range(0, len(children), columns):
                row = children[start:start+columns]
                usable = available - self.gap * (len(row)-1)
                for i, child in enumerate(row):
                    left = i * usable // len(row)
                    right = (i+1) * usable // len(row)
                    child.place(x=left+i*self.gap, y=(start//columns)*(height+self.gap),
                                width=right-left, height=height)
            total = ((len(children)-1)//columns+1)*(height+self.gap)-self.gap
            if int(self.cget("height")) != total:
                self.configure(height=total)
            return
        x = y = row_height = 0
        for child in self.winfo_children():
            width = min(available, child.winfo_reqwidth())
            height = child.winfo_reqheight()
            if x and x + width > available:
                x = 0
                y += row_height + self.gap
                row_height = 0
            child.place(x=x, y=y, width=width, height=height)
            x += width + self.gap
            row_height = max(row_height, height)
        height = max(1, y + row_height)
        if int(self.cget("height")) != height:
            self.configure(height=height)

    def destroy(self):
        self.unbind("<Configure>")
        if self.pending is not None:
            self.after_cancel(self.pending)
            self.pending = None
        super().destroy()


class ClickTargets:
    def __init__(self, guide):
        self.guide = guide
        self.native = guide.app.native
        self.window = tk.Toplevel(guide.window, bg=guide.hud_bg)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.canvas = tk.Canvas(self.window, bg=guide.hud_bg, bd=0, highlightthickness=0, cursor="hand2")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<MouseWheel>", guide.scroll_guide)
        self.pressed = None
        self.dragging_header = False
        self.targets = {}
        self.signature = None
        self.pending = None
        self.enabled = False

    def show(self):
        self.enabled = True
        self.sync()

    def hide(self):
        self.enabled = False
        if self.pending:
            self.window.after_cancel(self.pending)
            self.pending = None
        self.pressed = None
        self.dragging_header = False
        self.signature = None
        self.window.withdraw()

    def schedule(self):
        if self.enabled and not self.pending:
            self.pending = self.window.after_idle(self.sync)

    @staticmethod
    def _size(widget):
        x, y = widget.winfo_rootx(), widget.winfo_rooty()
        return x, y, x + widget.winfo_width(), y + widget.winfo_height()

    def _widgets(self, widget, clip):
        if not widget.winfo_ismapped():
            return
        a, b, c, d = self._size(widget)
        rect = max(a, clip[0]), max(b, clip[1]), min(c, clip[2]), min(d, clip[3])
        if rect[0] >= rect[2] or rect[1] >= rect[3]:
            return
        interactive = (isinstance(widget, (tk.Button, ttk.Button, ttk.Combobox))
                       or callable(getattr(widget, "invoke", None))
                       or callable(getattr(widget, "overlay_pointer", None)))
        if interactive and str(widget.cget("state")) != "disabled":
            yield widget, rect
        elif getattr(widget, "build_links", False):
            for left, top, right, bottom, _ in getattr(widget, "link_boxes", ()):
                area = (max(rect[0], a + int(left)), max(rect[1], b + int(top)),
                        min(rect[2], a + int(right)), min(rect[3], b + int(bottom)))
                if area[0] < area[2] and area[1] < area[3]:
                    yield widget, area
        else:
            for child in widget.winfo_children():
                yield from self._widgets(child, rect)

    def sync(self):
        self.pending = None
        if not self.enabled or not self.guide.window.winfo_ismapped():
            return
        x, y, right, bottom = self._size(self.guide.window)
        rectangles = tuple(self._widgets(self.guide.shell, (x, y, right, bottom)))
        if not self.guide.app.click_through:
            rectangles = ((self.guide.header, self._size(self.guide.header)), *rectangles)
        dialog = self.guide.lookup_dialog or self.guide.app.welcome or self.guide.app.settings
        mask = self._size(dialog) if dialog and dialog.winfo_ismapped() else None
        signature = x, y, right, bottom, rectangles, mask
        if signature == self.signature:
            return
        if self.signature is None:
            # The pixels outside buttons are the color key. A tiny nonzero alpha at
            # the buttons leaves their original appearance visible underneath.
            try:
                self.native.set_click_mode(self.window, False, no_activate=True, alpha=1)
            except OSError:
                # Tk can create the top-level wrapper only when it first maps.
                pass
            self.window.deiconify()
            self.native.set_click_mode(self.window, False, no_activate=True, alpha=1)
        if self.signature is None or signature[:4] != self.signature[:4]:
            self.native.place(self.native.hwnd(self.window), x, y, right - x, bottom - y)
        self.canvas.delete("all")
        self.targets.clear()
        for widget, (a, b, c, d) in rectangles:
            item = self.canvas.create_rectangle(a-x, b-y, c-x, d-y, fill="white", outline="")
            self.targets[item] = widget
        if mask:
            a, b, c, d = mask
            self.canvas.create_rectangle(a-x, b-y, c-x, d-y, fill=self.guide.hud_bg, outline="")
        self.signature = signature

    def _at(self, event):
        for item in reversed(self.canvas.find_overlapping(event.x, event.y, event.x + 1, event.y + 1)):
            if item in self.targets:
                return self.targets[item]
        return None

    def _press(self, event):
        self.pressed = self._at(event)
        self.dragging_header = self.pressed is self.guide.header
        if self.dragging_header:
            self.guide._begin_gesture("move", event)
        elif self.pressed is not None and hasattr(self.pressed, "overlay_pointer"):
            self.pressed.overlay_pointer("press", event)

    def _drag(self, event):
        if self.dragging_header:
            self.guide._move_gesture(event)
        elif self.pressed is not None and self.pressed.winfo_exists() and hasattr(self.pressed, "overlay_pointer"):
            self.pressed.overlay_pointer("motion", event)

    def _release(self, event):
        widget, self.pressed = self.pressed, None
        if self.dragging_header:
            self.dragging_header = False
            self.guide.layout.finish()
            return
        if widget is not None and widget.winfo_exists() and hasattr(widget, "overlay_pointer"):
            widget.overlay_pointer("release", event)
        elif widget is not None and widget == self._at(event) and widget.winfo_exists():
            if getattr(widget, "build_links", False):
                widget.event_generate("<ButtonRelease-1>", x=event.x_root - widget.winfo_rootx(),
                                      y=event.y_root - widget.winfo_rooty())
            elif isinstance(widget, ttk.Combobox):
                widget.tk.call("ttk::combobox::Post", str(widget))
            else:
                widget.invoke()


class BackgroundMirror:
    """Linux: shows the guide with a see-through background through the backend's ARGB mirror.

    The backend copies the guide's picture into an ARGB window after layout changes and every
    300 ms (timers, tooltips, redraws); it only uploads pixels that changed. On any error the
    mirror is removed and the guide shows itself again with its normal, opaque background.
    """

    INTERVAL = 300

    def __init__(self, guide):
        self.guide = guide
        self.native = guide.app.native
        self.window = guide.window
        self.pending = None
        self.heartbeat = None
        self.stopped = False

    def schedule(self):
        if self.pending is None and not self.stopped:
            self.pending = self.window.after(40, self.sync)

    def sync(self):
        self.pending = None
        if self.heartbeat is not None:
            self.window.after_cancel(self.heartbeat)
            self.heartbeat = None
        if self.stopped:
            return
        try:
            if self.window.winfo_viewable():
                app = self.guide.app
                self.native.mirror_update(self.window, app.overlay_alpha(), app.translucent_colors())
            else:
                self.native.mirror_hide(self.window)
        except Exception:
            logging.exception("Durchsichtiger Hintergrund abgeschaltet, HUD wird deckend angezeigt.")
            self.close()
            return
        self.heartbeat = self.window.after(self.INTERVAL, self.schedule)

    def hide(self):
        try:
            self.native.mirror_hide(self.window)
        except Exception:
            logging.exception("Spiegelfenster konnte nicht ausgeblendet werden.")

    def close(self):
        self.stopped = True
        for job in (self.pending, self.heartbeat):
            if job is not None:
                self.window.after_cancel(job)
        self.pending = self.heartbeat = None
        try:
            self.native.mirror_close(self.window, self.guide.app.overlay_alpha())
        except Exception:
            logging.exception("Spiegelfenster konnte nicht entfernt werden.")


class InputRegion(ClickTargets):
    """Click-through without a colour key (X11): the guide itself only takes input on its buttons.

    Shares the button search with ClickTargets but needs no extra window. The backend's
    ``set_input_region`` receives rectangles relative to the guide window, or ``None`` when
    the whole guide should take mouse input (edit mode).
    """

    def __init__(self, guide):
        self.guide = guide
        self.native = guide.app.native
        self.window = guide.window
        self.signature = None
        self.pending = None
        self.enabled = False

    def show(self):
        # set_click_mode may just have reset the region, so apply it again.
        self.signature = "stale"
        super().show()

    def schedule(self):
        app = self.guide.app
        if not self.enabled and app.visible and app.current is self.guide and self.window.winfo_viewable():
            # The guide maps after enter() set the click mode: activate the region now.
            self.guide._sync_click_mode()
            return
        super().schedule()

    def hide(self):
        self.enabled = False
        if self.pending:
            self.window.after_cancel(self.pending)
            self.pending = None
        if self.signature is not None and self.window.winfo_exists():
            self.native.set_input_region(self.window, None)
        self.signature = None

    @staticmethod
    def relative(rectangles, origin):
        x, y = origin
        return tuple((a - x, b - y, c - x, d - y) for a, b, c, d in rectangles)

    def sync(self):
        self.pending = None
        if not self.enabled or not self.window.winfo_ismapped():
            return
        if self.guide.app.click_through:
            x, y, right, bottom = self._size(self.window)
            buttons = (rect for _, rect in self._widgets(self.guide.shell, (x, y, right, bottom)))
            region = self.relative(buttons, (x, y))
        else:
            region = None
        # Tk may create the outer window only when it first maps: apply again if it changes.
        signature = self.window.wm_frame(), region
        if signature != self.signature:
            self.native.set_input_region(self.window, region)
            self.signature = signature
