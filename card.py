"""Render the profile card SVGs from a config file, the ASCII art and live stats.

The card imitates a neofetch dump: an ASCII portrait on the left, a right-hand
column of dotted key/value rows. Both SVGs are written from scratch on every
run, so the layout is decided here rather than patched into an existing file.
"""

from xml.sax.saxutils import escape

# Consolas advances 0.55em, most other monospace faces about 0.60em, and the
# size-adjust in the stylesheet scales Consolas up to match. Everything
# therefore lands on a ~9.63px grid at 16px — but this is only ever used to
# size the canvas. The portrait and the info column are emitted as one padded
# monospace run per line, so they stay aligned whatever font actually loads.
CHAR_WIDTH = 9.63
LINE_HEIGHT = 20
FONT_SIZE = 16
MARGIN = 15

# Blank columns between the portrait and the start of the info column.
GUTTER = 3

# Right-hand column: rows are padded with dots so every value ends here.
INFO_COLUMNS = 60

THEMES = {
    "dark": {
        "background": "#161b22",
        "text": "#c9d1d9",
        "key": "#ffa657",
        "value": "#a5d6ff",
        "dots": "#616e7f",
        "added": "#3fb950",
        "deleted": "#f85149",
    },
    "light": {
        "background": "#ffffff",
        "text": "#24292f",
        "key": "#953800",
        "value": "#0550ae",
        "dots": "#6e7781",
        "added": "#1a7f37",
        "deleted": "#cf222e",
    },
}


class Span:
    """A run of text on one line, optionally coloured and addressable by id."""

    __slots__ = ("text", "cls", "id")

    def __init__(self, text, cls=None, id=None):
        self.text = str(text)
        self.cls = cls
        self.id = id

    def render(self):
        if self.cls is None and self.id is None:
            return escape(self.text)
        attributes = ""
        if self.cls:
            attributes += f' class="{self.cls}"'
        if self.id:
            attributes += f' id="{self.id}"'
        return f"<tspan{attributes}>{escape(self.text)}</tspan>"

    def __len__(self):
        return len(self.text)


def thousands(value):
    return f"{value:,}" if isinstance(value, int) else str(value)


def filler(gap):
    """The run of dots that pushes a value out to the right-hand edge.

    Always at least one space: an over-long value would otherwise end up welded
    to its own colon.
    """
    gap = max(1, gap)
    return f" {'.' * (gap - 2)} " if gap >= 3 else " " * gap


def rule(label, columns=INFO_COLUMNS):
    """A section heading padded out with em dashes, e.g. '- Contact -————-—-'."""
    dashes = max(0, columns - len(label) - 5)
    return [Span(label), Span(f" -{'—' * dashes}-—-")]


def row(key, value, value_id=None, columns=INFO_COLUMNS):
    """One '. Key: ......... value' line, right-aligned to the column width.

    A dotted key like 'Languages.Programming' is split so each segment is
    coloured but the separating dots are not.
    """
    spans = [Span(". ", "cc")]
    prefix = 2
    for index, segment in enumerate(str(key).split(".")):
        if index:
            spans.append(Span("."))
            prefix += 1
        spans.append(Span(segment, "key"))
        prefix += len(segment)
    spans.append(Span(":"))
    prefix += 1

    value = thousands(value)
    dots_id = f"{value_id}_dots" if value_id else None
    spans.append(Span(filler(columns - prefix - len(value)), "cc", dots_id))
    spans.append(Span(value, "value", value_id))
    return spans


def stat_row(pairs, columns=INFO_COLUMNS):
    """A line carrying two stats separated by a pipe, e.g. 'Repos: 12 | Stars: 3'.

    The dots go in the first gap so the second pair always sits flush right.
    """
    spans = [Span(". ", "cc")]
    tail = []
    tail_length = 0
    for key, value, value_id in pairs[1:]:
        tail.extend([Span(" | "), Span(key, "key"), Span(": "),
                     Span(thousands(value), "value", value_id)])
        tail_length += 3 + len(key) + 2 + len(thousands(value))

    key, value, value_id = pairs[0]
    value = thousands(value)
    prefix = 2 + len(key) + 1
    spans.extend([Span(key, "key"), Span(":")])

    spans.append(Span(filler(columns - prefix - len(value) - tail_length),
                      "cc", f"{value_id}_dots" if value_id else None))
    spans.append(Span(value, "value", value_id))
    spans.extend(tail)
    return spans


def loc_row(added, deleted, total, columns=INFO_COLUMNS):
    """The lines-of-code line, with red and green diff counts in brackets."""
    label = "Lines of Code on GitHub"
    added, deleted, total = thousands(added), thousands(deleted), thousands(total)
    suffix_length = len(f" ( {added}++, {deleted}-- )")

    prefix = 2 + len(label) + 1
    gap = columns - prefix - len(total) - suffix_length

    return [
        Span(". ", "cc"), Span(label, "key"), Span(":"),
        Span(filler(gap), "cc", "loc_data_dots"), Span(total, "value", "loc_data"),
        Span(" ( "), Span(added, "addColor", "loc_add"), Span("++", "addColor"),
        Span(", "), Span(deleted, "delColor", "loc_del"), Span("--", "delColor"),
        Span(" )"),
    ]


def build_lines(config, stats, uptime, columns=INFO_COLUMNS):
    """Turn the config plus live stats into the right-hand column, line by line."""
    lines = [rule(config["card"]["title"], columns)]

    for section in config.get("sections", []):
        if section.get("title"):
            lines.append([])
            lines.append(rule(f"- {section['title']}", columns))
        for entry in section.get("rows", []):
            if not entry or entry.get("blank"):
                lines.append([])
                continue
            # Uptime is filled in here rather than from the config, which would
            # otherwise hold a value that is stale the moment it is written.
            if entry.get("id") == "age_data":
                value = uptime
            else:
                value = entry.get("value", "")
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            lines.append(row(entry["key"], value, entry.get("id"), columns))

    lines.append([])
    lines.append(rule("- GitHub Stats", columns))
    lines.append(stat_row([
        ("Repos", stats["repos"], "repo_data"),
        ("Contributed", stats["contributed"], "contrib_data"),
        ("Stars", stats["stars"], "star_data"),
    ], columns))
    lines.append(stat_row([
        ("Commits", stats["commits"], "commit_data"),
        ("Followers", stats["followers"], "follower_data"),
    ], columns))
    lines.append(loc_row(stats["loc_added"], stats["loc_deleted"],
                         stats["loc_total"], columns))
    return lines


def fitted_lines(config, stats, uptime):
    """Build the column, widening it if any row refuses to fit.

    INFO_COLUMNS is a minimum, not a cap. Seven-figure line counts overflow it
    on their own, and a row that overflows loses its dots and leaves the right
    edge ragged, so measure the longest row and justify everything to that.
    """
    lines = build_lines(config, stats, uptime)
    widest = max((sum(len(span) for span in line) for line in lines), default=0)
    if widest > INFO_COLUMNS:
        lines = build_lines(config, stats, uptime, widest)
    return lines


def compose(ascii_art, info_lines):
    """Merge the portrait and the info column into one span list per line.

    Each portrait line is padded to a fixed column count and the info spans are
    appended to it, so both halves ride the same character grid. Positioning the
    two as separate blocks would mean trusting a hard-coded pixel advance, and
    the columns collide the moment a reader's fallback font is a little wider.
    """
    gutter = max((len(line) for line in ascii_art), default=0) + GUTTER
    lines = []
    for index in range(max(len(ascii_art), len(info_lines))):
        art = ascii_art[index] if index < len(ascii_art) else ""
        spans = [Span(art.ljust(gutter))]
        spans.extend(info_lines[index] if index < len(info_lines) else [])
        lines.append(spans)
    return lines


def render(config, stats, ascii_art, uptime, theme):
    palette = THEMES[theme]
    lines = compose(ascii_art, fitted_lines(config, stats, uptime))

    longest = max((sum(len(span) for span in line) for line in lines), default=0)
    width = config["card"].get("width", round(longest * CHAR_WIDTH) + MARGIN * 2)
    height = LINE_HEIGHT * len(lines) + MARGIN * 2

    out = [
        "<?xml version='1.0' encoding='UTF-8'?>",
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}px" '
        f'height="{height}px" font-size="{FONT_SIZE}px" '
        'font-family="ConsolasFallback,Consolas,Menlo,monospace">',
        "<style>",
        "@font-face {",
        "src: local('Consolas'), local('Consolas Bold');",
        "font-family: 'ConsolasFallback';",
        "font-display: swap;",
        # Consolas is narrower than most fallbacks; nudge substitutes to match
        # so the dotted columns stay aligned for readers without it installed.
        "-webkit-size-adjust: 109%;",
        "size-adjust: 109%;",
        "}",
        f".key {{fill: {palette['key']};}}",
        f".value {{fill: {palette['value']};}}",
        f".cc {{fill: {palette['dots']};}}",
        f".addColor {{fill: {palette['added']};}}",
        f".delColor {{fill: {palette['deleted']};}}",
        "text, tspan {white-space: pre;}",
        "</style>",
        f'<rect width="{width}px" height="{height}px" '
        f'fill="{palette["background"]}" rx="15"/>',
    ]

    out.append(f'<text x="{MARGIN}" y="{LINE_HEIGHT + 10}" '
               f'fill="{palette["text"]}">')
    for index, line in enumerate(lines):
        body = "".join(span.render() for span in line)
        out.append(f'<tspan x="{MARGIN}" y="{LINE_HEIGHT * (index + 1) + 10}">'
                   f'{body}</tspan>')
    out.append("</text>")
    out.append("</svg>")
    return "\n".join(out) + "\n"
