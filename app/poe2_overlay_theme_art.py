"""Small, DPI-aware ornaments for the native Companion themes."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeTreatment:
    motif: str = "classic"
    body_fonts: tuple[str, ...] = ()
    heading_fonts: tuple[str, ...] = ()
    card_inset: int = 8
    card_padding: int = 5
    card_border: int = 1
    tab_padding: int = 5
    button_relief: str = "flat"
    slider_thumb: str = "diamond"


CLASSIC = ThemeTreatment()


def mix_color(base, accent, amount):
    return "#" + "".join(f"{round(int(base[i:i+2], 16) * (1 - amount) + int(accent[i:i+2], 16) * amount):02x}"
                         for i in (1, 3, 5))


def paint_header(canvas, theme, width, height, px):
    if width < px(20) or height < px(10):
        return
    motif = theme.treatment.motif
    left, top, right, bottom = 1, 1, width - 2, height - 2
    if motif == "precision":
        cut = px(8)
        canvas.create_polygon(left, top, right-cut, top, right, top+cut, right, bottom,
                              left+cut, bottom, left, bottom-cut, fill=theme.control, outline=theme.edge)
        canvas.create_line(left+px(3), top+px(5), left+px(3), bottom-px(8), fill=theme.accent, width=px(2))
        for offset in (5, 9, 13):
            x = right - px(offset)
            canvas.create_line(x, bottom-px(3), x-px(3), bottom-px(7), fill=theme.edge)
    elif motif == "temple":
        step = px(5)
        canvas.create_polygon(left, top+step, left+step, top+step, left+step, top,
                              right-step, top, right-step, top+step, right, top+step,
                              right, bottom-step, right-step, bottom-step, right-step, bottom,
                              left+step, bottom, left+step, bottom-step, left, bottom-step,
                              fill=theme.control, outline=theme.edge)
        for x, direction in ((left, 1), (right, -1)):
            a, b = x + direction * px(4), x + direction * px(12)
            canvas.create_line(b, px(4), a, px(4), a, px(11), fill=theme.accent)
            canvas.create_line(b, height-px(5), a, height-px(5), a, height-px(12), fill=theme.accent)
        canvas.create_line(left+px(15), bottom-px(2), right-px(15), bottom-px(2), fill=theme.active)
    elif motif == "terminal":
        canvas.create_rectangle(left, top, right, bottom, fill=theme.control, outline=theme.edge)
        canvas.create_line(left+1, bottom, right-1, bottom, fill=theme.accent)
        canvas.create_rectangle(right-px(11), height//2+px(3), right-px(5), height//2+px(5),
                                fill=theme.accent, outline="")
    elif motif == "ledger":
        canvas.create_rectangle(left, top, right, bottom, fill=theme.control, outline="")
        canvas.create_line(left, top, right, top, fill=theme.edge)
        canvas.create_line(left, bottom-px(2), right, bottom-px(2), fill=theme.edge)
        canvas.create_line(left, bottom, right, bottom, fill=theme.accent)
        canvas.create_line(left+px(11), top, left+px(11), bottom, fill=theme.edge)
    elif motif == "oled":
        canvas.create_rectangle(left, top, right, bottom, fill=theme.control, outline="")
        canvas.create_line(left, bottom, right, bottom, fill=theme.edge)
        canvas.create_line(width*.43, bottom, width*.57, bottom, fill=theme.accent)
    elif motif == "minimal":
        canvas.create_line(left+px(5), bottom, right-px(5), bottom, fill=theme.edge)
    else:
        canvas.create_rectangle(left, top, right, bottom, fill=theme.control, outline=theme.edge)


def paint_rule(canvas, theme, width, height, px):
    """Draw the section divider and the compact trim below the Options title."""
    if width < px(24):
        return
    motif = theme.treatment.motif
    y = height // 2
    edge, accent = theme.edge, theme.accent
    x0, x1 = px(4), width - px(4)
    if motif == "temple":
        step = px(5)
        canvas.create_line(x0, y+px(2), x0+step, y+px(2), x0+step, y,
                           x1-step, y, x1-step, y+px(2), x1, y+px(2), fill=edge)
        center = width // 2
        canvas.create_polygon(center-step, y, center, y-px(3), center+step, y, center, y+px(3), fill=accent)
    elif motif == "precision":
        canvas.create_line(x0, y, x1, y, fill=edge)
        canvas.create_line(x0, y, x0+px(20), y, fill=accent, width=px(2))
        for x in (x1-px(12), x1-px(7)):
            canvas.create_line(x, y+px(2), x+px(3), y-px(2), fill=accent)
    elif motif == "terminal":
        canvas.create_line(x0, y, x1, y, fill=edge, dash=(px(5), px(3)))
        canvas.create_line(x0, y, x0+px(10), y, fill=accent)
    elif motif == "ledger":
        canvas.create_line(x0+px(11), y-1, x1, y-1, fill=edge)
        canvas.create_line(x0+px(11), y+2, x1, y+2, fill=edge)
        canvas.create_line(x0+px(6), 0, x0+px(6), height, fill=accent)
    else:
        first = x0 if motif == "oled" else x0+px(4)
        last = x1 if motif == "oled" else min(x1, first+px(44))
        canvas.create_line(first, y, last, y, fill=edge if motif == "oled" else accent)
