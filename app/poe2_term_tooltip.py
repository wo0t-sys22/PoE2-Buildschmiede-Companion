"""Guide glossary and passive-node tooltips, including in play mode.

In play mode the guide lets mouse input through to the game, so the guide gets no hover
events. Instead a light timer reads the pointer position while it is over a visible guide
and hit-tests the registered widgets. Glossary text comes from the website lexicon.
The passive map and its allocation list supply the selected node's own effects and notes.
"""

from __future__ import annotations

import logging
import tkinter as tk

from poe2_build_editorial import reference_parts
from poe2_build_art import build_icon, item_art_ref
from poe2_build_items import item_card
from poe2_build_loadout import SLOTS, slot_label
from poe2_build_terms import gem_color, gem_entry, gem_record, gem_spans
from poe2_language import CATALOG, display_label
from poe2_lexicon import NODE_KINDS, catalogue, display_stats, lexicon_prose, public_name
from poe2_lexicon_explain import currencies, currency_names, node_copy, term_summary
from poe2_overlay_lookup import make, published_terms
from poe2_r18_features import PALETTE, TERM_CATALOG, term_key, term_labels, term_matches
from poe2_website_content import LANGUAGES, localized_text

POLL_MS = 120
DELAY_MS = 400
LINK_GRACE_MS = 480  # a link tooltip stays while the pointer moves from the name onto it
MAX_WIDTH = 340


# Names that are ordinary words more often than game terms in the guide texts. Full names
# ("Trial of the Sekhemas", "Vaal Orb", "Waystone", "Zauberstab") keep their tooltip.
AMBIGUOUS_NAMES = {
    # Sekhemas or Chaos, the Vaal people, world or desert map, speedrun splits
    "*": {"trial", "vaal", "map", "split"},
    # German sentences (also in hybrid mode): wall, curve, a boss's staff, Asala's shield,
    # mirrored floors, a boss's attack chain
    "de": {"wand", "bogen", "stab", "schild", "gespiegelt", "kombo",
           "selten", "seltene", "seltenem", "seltenen", "seltener", "seltenes"},
}
# English names that are common verbs or phrases in lower case ("block your path", "as well").
CAPITALISED_ONLY = {"block", "hit", "fire", "focus", "rare", "well"}
# Proper names and phrases that contain a term but mean something else. Area names are added
# from the campaign catalogue; a longer match wins, so "Temple of Chaos" hides the Chaos tooltip.
BLOCKED_PHRASES = (
    "as well", "world map", "Desert Map", "Forward Command Tents", "Beast Pen", "Hollow Focus",
    "Supporting-Fire", "Ritual of Meditation", "Ritual of Dance", "Dryadic Ritual", "Dryadisches Ritual",
    "Dryadischen Ritual", "das Muster", "flügelähnliches Muster",
    # quest items, not the Poison ailment
    "Molten One's Gift", "Orok-Gift", "das Gift hast", "das Gift nach dem Fund",
    # Matiki's well and the short form of the Well of Souls are quest objects, not flask wells
    "Matiki am Brunnen", "Interagiere mit dem Brunnen", "Matiki by the well", "Interact with the well",
    "bis zum Brunnen", "Brunnen für entweihte", "am Brunnen enthüllen",
)
ARTICLES = ("the ", "der ", "die ", "das ")


def _area_names():
    for name, entry in CATALOG.get("areas", {}).items():
        yield name
        if isinstance(entry, dict) and entry.get("de"):
            yield entry["de"]


def _bare(name):
    key = term_key(name)
    for article in ARTICLES:
        key = key.removeprefix(article)
    return key


def _article(entry, language):
    titles = entry["title"]
    title = localized_text(titles, language) if language == "hybrid" else titles.get(language)
    if title and (lexicon_prose(entry.get("tooltipSummary"), language)
                  or lexicon_prose(entry.get("summary"), language)):
        return title, term_summary(entry, language)
    return None


def tooltip_terms(lexicon, language, *, include_ids=False):
    """Tooltip index plus the spellings a name must match exactly.

    index: {term_key(name): (title, summary)} for every name of a website entry with a summary,
    and {term_key(phrase): None} for proper names that must not show a tooltip for a part.
    exact: {term_key(name): {spelling, ...}} for abbreviations (ES, AS) and capitalised-only names.
    """
    index = {}
    titles, catalogue_aliases, published_aliases = [], [], []
    exact = {}
    ignored = AMBIGUOUS_NAMES["*"] | (set() if language == "en" else AMBIGUOUS_NAMES["de"])
    for ident, entry in (lexicon or {}).items():
        article = _article(entry, language)
        if not article:
            continue
        shown = entry["title"]
        if language == "en" and shown.get("en"):
            # English texts never use German names, so "Gift" or "Leben" stay plain English words.
            shown = {"en": shown["en"]}
        if include_ids:
            article = (*article, ident)
        titles.extend((name, article) for name in shown.values())
        published_aliases.extend((name, article) for name in entry.get("aliases", ()) if public_name(name, ident))
        term = TERM_CATALOG.get(ident)
        if term:
            languages = ("en",) if language == "en" else LANGUAGES
            names = [label for lang in languages for label in term_labels(term, lang)]
            names += [*term.get("aliases", ()), *term.get("routeAliases", ())]
            catalogue_aliases.extend((name, article) for name in names if public_name(name, ident))
    for name, article in (*titles, *catalogue_aliases, *published_aliases):
        key = term_key(name)
        if key in ignored:
            continue
        index.setdefault(key, article)
        if (len(name) > 1 and name.isupper()) or key in CAPITALISED_ONLY:
            exact.setdefault(key, set()).add(name if name.isupper() else name[:1].upper() + name[1:])
    terms = dict(index)
    phrases = (*map(term_key, BLOCKED_PHRASES), *map(_bare, _area_names())) if terms else ()
    for key in phrases:
        if key not in terms and any(term_matches(key, terms)):
            index[key] = None
    return index, exact


def tooltip_index(lexicon, language):
    return tooltip_terms(lexicon, language)[0]


def tooltip_art_ref(record, *, node_id=None):
    """Resolve exact local art for a catalogue record or editorial title."""
    if node_id:
        icon = catalogue()["plannerTree"]["nodes"].get(node_id, {}).get("icon", -1)
        return f"tree/{icon}" if icon >= 0 else ""
    if record.get("currencyId") and "title" in record:
        related = currencies().get(record["currencyId"],{})
        if related.get("imageLocal"):
            return related["imageLocal"]
    name = record.get("name") or record.get("title", {}).get("en", "")
    return (record.get("imageLocal") or record.get("icon")
            or currency_names().get(name.casefold(), {}).get("imageLocal")
            or item_art_ref(name))


def tooltip_spans(text, index, exact):
    """(start, end) of every term in text that gets a tooltip."""
    spans = []
    for start, end, article in term_matches(text, index):
        allowed = exact.get(term_key(text[start:end]))
        if article is not None and (allowed is None or text[start:end] in allowed):
            spans.append((start, end))
    return spans


def term_at(boxes, x, y):
    """Phrase of the term box under canvas coordinates (x, y), or None."""
    for left, top, right, bottom, phrase in boxes:
        if left <= x < right and top <= y < bottom:
            return phrase
    return None


class TermTooltips:
    def __init__(self, app):
        self.app = app
        self.canvases = []
        self.window = None
        self.job = None
        self.pending = None
        self.shown = None
        self.lexicon = None
        self.language = None
        self.index = {}
        self.exact = {}
        self.grace = 0

    # Registration from pack_message -----------------------------------------------------

    def register(self, canvas):
        if canvas not in self.canvases:
            self.canvases.append(canvas)

    # Data ----------------------------------------------------------------------------------

    def _entries(self):
        lexicon = self.app.website_lexicon()
        language = self.app.language
        if lexicon is not self.lexicon or language != self.language:
            self.lexicon, self.language = lexicon, language
            self.index, self.exact = tooltip_terms(lexicon, language, include_ids=True)
        return self.index

    def lookup(self, phrase):
        article = self._entries().get(term_key(phrase))
        return article[:2] if article else None

    def spans(self, text, term_refs=None):
        index = self._entries()
        if not term_refs:
            return tooltip_spans(text, index, self.exact)
        authored = {key: article for key, ident in term_refs.items() if (article := self._article_by_id(ident))}
        inferred = tooltip_spans(text, index, self.exact)
        bound = [(start, end) for start, end, _ in term_matches(text, authored)]
        return sorted([*bound, *(span for span in inferred
                                 if all(span[1] <= start or span[0] >= end for start, end in bound))])

    def _article_by_id(self, ident):
        if entry := (self.lexicon or {}).get(ident):
            if article := _article(entry, self.app.language):
                return (*article, ident)
        return None

    def build_markup(self, value, preferred=(), context=()):
        """Render author references and fill unlinked prose from the local catalogues."""
        language = self.app.language
        pieces, explicit, offset = [], [], 0
        for part, ref, _ in reference_parts(value):
            kind, _, ident = ref.partition(":")
            if kind == "gem" and gem_record(ident):
                explicit.append((offset, offset + len(part), ("gem", ident), gem_color(ident)))
            elif kind == "node" and ident in catalogue()["nodes"]:
                explicit.append((offset, offset + len(part), ("node", ident), PALETTE["mod"]))
            elif kind == "item" and context and ident in SLOTS:
                explicit.append((offset, offset + len(part), ("item", (*context, ident)), PALETTE["normal"]))
            pieces.append(part)
            offset += len(part)
        value = "".join(pieces)
        candidates = []
        for start, end in self.spans(value):
            _, _, ident = self.index[term_key(value[start:end])]
            role = TERM_CATALOG.get(ident, {}).get("role")
            candidates.append((start, end, ("term", ident), PALETTE.get(role)))
        for start, end, ident in gem_spans(value, language, preferred):
            candidates.append((start, end, ("gem", ident), gem_color(ident)))

        # Full names beat contained words. At equal length preserve a glossary mechanic,
        # but prefer the catalogue's actual gem over an editorial entry about that gem.
        def priority(span):
            start, end, (kind, ident), _ = span
            mechanic = kind == "term" and TERM_CATALOG.get(ident, {}).get("role") not in ("gem", "support")
            return (end - start, mechanic, kind == "gem")

        spans = list(explicit)
        for candidate in sorted(candidates, key=priority, reverse=True):
            start, end = candidate[:2]
            if all(end <= left or start >= right for left, right, *_ in spans):
                spans.append(candidate)
        return value, sorted(spans)

    def build_lexicon_entry(self, target):
        kind, ident = target
        language = self.app.language
        if kind == "term":
            row = (self.app.website_lexicon() or {}).get(ident)
            return next(published_terms(language, {ident: row}), None) if row else None
        if kind == "gem" and (row := gem_record(ident)):
            facet = "support" if ident in catalogue()["supports"] else "skill"
        elif kind == "node" and (row := catalogue()["nodes"].get(ident)):
            facet = row["type"]
        else:
            return None
        title = (row.get("de") if language == "de" else None) or row["name"]
        return make("lexicon", title, {"group": "nodes", "facet": facet, "ident": ident, "row": row, "positions": None},
                    details=(display_label(NODE_KINDS[facet], language),))

    @property
    def enabled(self):
        return self.app.tooltips_enabled

    # Polling -------------------------------------------------------------------------------

    def start(self):
        if self.job is None:
            self.job = self.app.root.after(POLL_MS, self.poll)

    def stop(self):
        if self.job is not None:
            self.app.root.after_cancel(self.job)
            self.job = None
        self.hide()

    def pointer(self):
        native = self.app.native
        return (native.pointer() if native else None) or self.app.root.winfo_pointerxy()

    def poll(self):
        self.job = None
        try:
            self._poll()
        except tk.TclError:
            self.hide()
        except Exception:
            logging.exception("Tooltip-Abfrage fehlgeschlagen.")
            self.hide()
            return  # stop polling after an unexpected error instead of logging it every 120 ms
        if not self.app.closed:
            self.job = self.app.root.after(POLL_MS, self.poll)

    def _hit(self, x, y):
        guide = self.app.current
        if not self.enabled or guide is None:
            return None
        if not (self.app.visible and guide.window.winfo_viewable()):
            return None
        left, top = guide.window.winfo_rootx(), guide.window.winfo_rooty()
        if not (left <= x < left + guide.window.winfo_width() and top <= y < top + guide.window.winfo_height()):
            return None
        for dialog in (guide.lookup_dialog, self.app.welcome, self.app.settings):
            if dialog is not None and dialog.winfo_exists() and dialog.winfo_viewable():
                dx, dy = dialog.winfo_rootx(), dialog.winfo_rooty()
                if dx <= x < dx + dialog.winfo_width() and dy <= y < dy + dialog.winfo_height():
                    return None
        self.canvases = [canvas for canvas in self.canvases if canvas.winfo_exists()]
        for canvas in self.canvases:
            boxes = getattr(canvas, "term_boxes", ())
            links = getattr(canvas, "link_boxes", ())
            resolver = getattr(canvas, "term_at_point", None)
            details = getattr(canvas, "detail_at_point", None)
            if ((not boxes and not links and not resolver and not details) or not canvas.winfo_viewable()
                    or canvas.winfo_toplevel() is not guide.window):
                continue
            cx, cy = x - canvas.winfo_rootx(), y - canvas.winfo_rooty()
            if 0 <= cx < canvas.winfo_width() and 0 <= cy < canvas.winfo_height():
                viewport = guide.route_canvas
                if details or str(canvas).startswith(str(viewport) + "."):
                    vx, vy = x - viewport.winfo_rootx(), y - viewport.winfo_rooty()
                    if not (0 <= vx < viewport.winfo_width() and 0 <= vy < viewport.winfo_height()):
                        continue  # a scrolled row can extend behind the header or buttons
                if details:
                    detail = details(cx, cy)
                    if detail:
                        identity, entry = detail
                        return canvas, identity, entry, None
                    continue
                for box_left, box_top, box_right, box_bottom, target in links:
                    if box_left <= cx < box_right and box_top <= cy < box_bottom:
                        anchor = (canvas.winfo_rootx() + box_left, canvas.winfo_rooty() + box_bottom)
                        if not hasattr(canvas, "link_previews"):
                            canvas.link_previews = {}
                        if target not in canvas.link_previews:
                            canvas.link_previews[target] = self.link_entry(guide, target, with_art=True)
                        return canvas, target, canvas.link_previews[target], anchor
                phrase = resolver(cx, cy) if resolver else term_at(boxes, cx, cy)
                article = None
                if phrase:
                    key = term_key(phrase)
                    index = self._entries()
                    ident = getattr(canvas, "term_refs", {}).get(key)
                    article = self._article_by_id(ident) or index.get(key)
                if article:
                    title, summary, ident = article
                    record = (self.lexicon or {}).get(ident, {})
                    return canvas, phrase, (title, summary, None, tooltip_art_ref(record)), None
        return None

    def link_entry(self, guide, target, *, with_art=False):
        """Article preview or the destination of a campaign navigation link."""
        english = self.app.language == "en"
        language = self.app.language
        if target[0] == "item":
            key, phase, slot = target[1]
            stage = next((s for build in guide.companion.data.get("builds", ()) if build["id"] == key
                          for s in build["stages"] if s["id"] == phase), {})
            label = slot_label(slot, language)
            gear = stage.get("plannerGear", {}).get(slot)
            if gear:
                card = item_card(gear, language, show_targets=True)
                lines = [card.base, *(line for _, entries in card.sections for line in entries)]
                preview = (card.title or label, "\n".join(filter(None, [label, *lines[:4]])), target)
                return (*preview, card.icon) if with_art else preview
            return label, ("Equipment slot in this phase" if english else "Ausrüstungsplatz dieser Phase"), target
        if target[0] == "node":
            row = catalogue()["nodes"][target[1]]
            title = (row.get("de") if language == "de" else None) or row["name"]
            stats = display_stats(row.get("stats", ()), language, german=row.get("statsDe", ()),
                                  hybrid=row.get("statsHybrid", ()))
            summary, _ = node_copy(row, row["type"], target[1], language)
            return title, "\n".join(stats) if stats else summary, target
        if target[0] in ("gem", "term"):
            if target[0] == "gem":
                title, summary = gem_entry(target[1], self.app.language)
            else:
                row = self.app.website_lexicon()[target[1]]
                title = localized_text(row["title"], self.app.language)
                summary = term_summary(row, self.app.language)
            return title, summary, target
        if target[0] == "boss":
            action = "Click to open the boss guide" if english else "Klicken öffnet den Boss-Guide"
        else:
            action = "Click to open the area" if english else "Klicken öffnet das Gebiet"
        return guide.link_title(target), action, target

    def over_window(self, x, y):
        window = self.window
        if window is None or not window.winfo_exists() or not window.winfo_viewable():
            return False
        margin = self.app.current.layout.px(6) if self.app.current else 6
        left, top = window.winfo_rootx() - margin, window.winfo_rooty() - margin
        return (left <= x < left + window.winfo_width() + 2 * margin
                and top <= y < top + window.winfo_height() + 2 * margin)

    def _poll(self):
        x, y = self.pointer()
        link_shown = self.shown is not None and isinstance(self.shown[1], tuple)
        if link_shown and self.over_window(x, y):
            self.grace = LINK_GRACE_MS  # over the clickable link tooltip
            return
        hit = self._hit(x, y)
        target = (hit[0], hit[1]) if hit else None
        if target is None:
            if link_shown and self.grace > 0:
                self.grace -= POLL_MS  # on the way from the name to the tooltip
                return
            self.pending = None
            self.hide()
            return
        if self.shown == target:
            self.grace = LINK_GRACE_MS
            return
        if self.pending and self.pending[0] == target:
            if self.pending[1] >= DELAY_MS:
                self.show(hit[2], x, y, anchor=hit[3])
                self.shown = target
                self.grace = LINK_GRACE_MS
                self.pending = None
            else:
                self.pending = (target, self.pending[1] + POLL_MS)
        else:
            self.hide()
            self.pending = (target, POLL_MS)

    # Window --------------------------------------------------------------------------------

    def _build(self):
        app = self.app
        window = tk.Toplevel(app.root)
        window.withdraw()
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        frame = tk.Frame(window, padx=app.current.layout.px(10), pady=app.current.layout.px(7))
        frame.pack(fill="both", expand=True)
        window.title_label = tk.Label(frame, anchor="w", justify="left", compound="left")
        window.title_label.pack(anchor="w")
        window.body_label = tk.Label(frame, anchor="w", justify="left")
        window.body_label.pack(anchor="w", pady=(app.current.layout.px(3), 0))
        window.action_label = tk.Label(frame, anchor="w")
        window.frame = frame
        window.link_target = None
        for widget in (window, frame, window.title_label, window.body_label, window.action_label):
            widget.bind("<ButtonRelease-1>", lambda event: self.open_link())
        return window

    def open_link(self):
        target = getattr(self.window, "link_target", None)
        guide = self.app.current
        if target and guide is not None:
            self.hide()
            guide.open_link(target)

    def show(self, entry, x, y, anchor=None):
        title, summary = entry[:2]
        target = entry[2] if len(entry) > 2 else None
        link = (target,) if target else ()
        icon_ref = entry[3] if len(entry) > 3 else ""
        app = self.app
        layout = app.current.layout
        if self.window is None or not self.window.winfo_exists():
            self.window = self._build()
        window = self.window
        theme = app.theme
        family = app.theme_font()
        window.configure(bg=theme.edge, padx=1, pady=1)
        window.frame.configure(bg=theme.control)
        if target and not icon_ref:
            kind, ident = target
            if kind == "gem":
                icon_ref = tooltip_art_ref(gem_record(ident) or {})
            elif kind == "node":
                icon_ref = tooltip_art_ref({}, node_id=ident)
            elif kind == "term":
                icon_ref = tooltip_art_ref((app.website_lexicon() or {}).get(ident, {}))
        window.icon = build_icon(window, icon_ref, layout.px(26)) if icon_ref else None
        window.title_label.configure(text=title, bg=theme.control, fg=theme.accent,
                                     image=window.icon or "", padx=layout.px(3) if window.icon else 0,
                                     wraplength=layout.px(MAX_WIDTH - (30 if window.icon else 0)),
                                     font=(app.theme_font(heading=True), 10, "bold"))
        article = bool(link and link[0][0] in ("gem", "term", "node", "item"))
        navigation = bool(link and not article)
        window.body_label.configure(text=summary, bg=theme.control, fg=theme.accent if navigation else theme.text,
                                    font=(family, 10, "underline") if navigation else (family, 10),
                                    wraplength=layout.px(MAX_WIDTH))
        if article:
            action = "Open glossary entry" if app.language == "en" else "Im Lexikon öffnen"
            if link[0][0] == "item":
                action = ("Show gear in build guide" if app.language == "en"
                          else "Ausrüstung im Buildguide anzeigen")
            window.action_label.configure(text=action, bg=theme.control, fg=theme.accent, cursor="hand2",
                                          font=(family, 9, "underline"))
            window.action_label.pack(anchor="w", pady=(layout.px(4), 0))
        else:
            window.action_label.pack_forget()
        window.link_target = link[0] if link else None
        for widget in (window, window.frame, window.title_label, window.body_label):
            widget.configure(cursor="hand2" if link else "")
        window.update_idletasks()
        width, height = window.winfo_reqwidth(), window.winfo_reqheight()
        native = app.native
        work = native.work_area(point=(x, y)) if native else None
        left, top, right, bottom = work or (0, 0, window.winfo_screenwidth(), window.winfo_screenheight())
        if anchor:
            # Directly under the name, so the pointer reaches the clickable tooltip without a gap.
            tx, ty = anchor
            if tx + width > right:
                tx = max(left, right - width)
            if ty + height > bottom:
                ty = max(top, anchor[1] - layout.px(22) - height)
        else:
            tx = x + layout.px(16)
            ty = y + layout.px(20)
            if tx + width > right:
                tx = max(left, x - layout.px(16) - width)
            if ty + height > bottom:
                ty = max(top, y - layout.px(12) - height)
        window.geometry(f"+{tx}+{ty}")
        window.deiconify()
        window.lift()
        if native:
            try:
                window.update_idletasks()
                # Only a link tooltip takes clicks, without taking the focus from the game.
                native.set_click_mode(window, not link, no_activate=True)
            except OSError:
                logging.debug("Tooltip ohne Klickdurchlässigkeit.", exc_info=True)

    def hide(self):
        self.shown = None
        if self.window is not None and self.window.winfo_exists():
            self.window.withdraw()
