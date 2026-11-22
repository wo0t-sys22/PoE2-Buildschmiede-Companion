"""Send user-authored Companion feedback to Buildschmiede."""

from contextlib import closing
from http.client import HTTPSConnection, HTTPException
import json
from queue import Empty, SimpleQueue
from threading import Thread
import tkinter as tk

from poe2_overlay_version import VERSION


CATEGORIES = (
    ("technical", "Technisches Problem", "Technical issue"),
    ("guide", "Guide-Korrektur", "Guide correction"),
    ("idea", "Idee", "Suggestion"),
)
MIN_MESSAGE = 10
MAX_MESSAGE = 2000


def send_feedback(category, message, language):
    body = json.dumps({"category": category, "message": message,
                       "language": language, "version": VERSION}, ensure_ascii=False).encode("utf-8")
    try:
        with closing(HTTPSConnection("buildschmiede.de", timeout=8)) as connection:
            connection.request("POST", "/wp-json/buildschmiede/v1/companion-feedback", body,
                               {"Content-Type": "application/json", "Accept": "application/json"})
            response = connection.getresponse()
            if response.status == 429:
                return "limited"
            if response.status == 201 and json.loads(response.read(4096)) == {"saved": True}:
                return "saved"
    except (OSError, HTTPException, ValueError):
        pass
    return "unavailable"


def open_feedback(parent, language, theme, family, native=None):
    english = language == "en"
    title = "Send feedback" if english else "Feedback geben"
    dialog = tk.Toplevel(parent)
    dialog.withdraw()
    dialog.title(title)
    dialog.transient(parent)
    dialog.attributes("-topmost", True)
    dialog.configure(bg=theme.panel)
    dialog.resizable(False, False)

    content = tk.Frame(dialog, bg=theme.panel, padx=18, pady=14)
    content.pack(fill="both", expand=True)
    label_style = {"bg": theme.panel, "fg": theme.text, "font": (family, 10)}
    button_style = {"bg": theme.control, "fg": theme.text, "activebackground": theme.active,
                    "activeforeground": theme.text, "disabledforeground": theme.text,
                    "highlightbackground": theme.edge, "highlightthickness": 1,
                    "relief": theme.treatment.button_relief, "font": (family, 10),
                    "padx": 10, "pady": 3}
    tk.Label(content, text="Kategorie" if not english else "Category", **label_style).pack(anchor="w")
    category = tk.StringVar(dialog, CATEGORIES[0][0])
    for key, german, translated in CATEGORIES:
        tk.Radiobutton(content, text=translated if english else german, variable=category, value=key,
                       selectcolor=theme.field_color, activebackground=theme.panel,
                       activeforeground=theme.accent, highlightbackground=theme.panel,
                       **label_style).pack(anchor="w")
    tk.Label(content, text="Nachricht" if not english else "Message",
             **label_style).pack(anchor="w", pady=(10, 3))
    editor = tk.Text(content, width=42, height=6, wrap="word", undo=True,
                     bg=theme.field_color, fg=theme.text, insertbackground=theme.text,
                     selectbackground=theme.selection_color, selectforeground=theme.selection_text,
                     highlightbackground=theme.edge, highlightcolor=theme.accent,
                     highlightthickness=1, bd=0, padx=7, pady=5, font=(family, 10))
    editor.pack(fill="x")
    disclosure = ("Your message, app version and language will be sent to Buildschmiede."
                  if english else "Nachricht, App-Version und Sprache gehen an Buildschmiede.")
    width = editor.winfo_reqwidth()
    tk.Label(content, text=disclosure, wraplength=width, justify="left",
             **label_style).pack(anchor="w", pady=(6, 0))
    status = tk.Label(content, height=2, anchor="w", wraplength=width, justify="left", **label_style)
    status.pack(anchor="w", pady=(4, 4))
    actions = tk.Frame(content, bg=theme.panel)
    actions.pack(fill="x")
    outcomes = SimpleQueue()
    pending = None
    messages = {
        "saved": ("Feedback gesendet. Danke!", "Feedback sent. Thank you!"),
        "limited": ("Zu viele Meldungen. Bitte versuche es später erneut.",
                    "Too many submissions. Please try again later."),
        "unavailable": ("Versand fehlgeschlagen. Bitte versuche es später erneut.",
                        "Could not send feedback. Please try again later."),
    }

    def close():
        if pending is None:
            dialog.destroy()

    def poll():
        nonlocal pending
        try:
            outcome = outcomes.get_nowait()
        except Empty:
            pending = dialog.after(100, poll)
            return
        pending = None
        status.configure(text=messages[outcome][english], fg=theme.accent if outcome == "saved" else theme.text)
        cancel.configure(state="normal")
        if outcome == "saved":
            cancel.configure(text="Close" if english else "Schließen")
            cancel.focus_set()
            return
        editor.configure(state="normal")
        send.configure(state="normal")

    def submit():
        nonlocal pending
        message = editor.get("1.0", "end-1c").strip()
        if not MIN_MESSAGE <= len(message) <= MAX_MESSAGE:
            status.configure(text=("Enter 10 to 2,000 characters." if english
                                   else "Gib 10 bis 2.000 Zeichen ein."))
            editor.focus_set()
            return
        selected = category.get()
        editor.configure(state="disabled")
        send.configure(state="disabled")
        cancel.configure(state="disabled")
        status.configure(text="Sending…" if english else "Wird gesendet…")
        Thread(target=lambda: outcomes.put(send_feedback(selected, message, language)), daemon=True).start()
        pending = dialog.after(100, poll)

    def stop_poll(event):
        if event.widget is dialog and pending is not None:
            dialog.after_cancel(pending)

    send = tk.Button(actions, text="Send" if english else "Senden", command=submit, **button_style)
    send.pack(side="right")
    cancel = tk.Button(actions, text="Cancel" if english else "Abbrechen", command=close, **button_style)
    cancel.pack(side="right", padx=(0, 8))
    dialog.protocol("WM_DELETE_WINDOW", close)
    dialog.bind("<Escape>", lambda _: close())
    dialog.bind("<Destroy>", stop_poll)
    dialog.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - dialog.winfo_reqwidth()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - dialog.winfo_reqheight()) // 2
    dialog.geometry(f"+{x}+{y}")
    dialog.deiconify()
    if native:
        dialog.update_idletasks()
        native.style_dialog(dialog, palette=(theme.edge, theme.panel, theme.text))
    dialog.grab_set()
    dialog.lift()
    editor.focus_force()
    return dialog
