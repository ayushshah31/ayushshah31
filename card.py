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
    """A run of text on one line, optionally coloured and addressable by id.

    Colour comes either from a stylesheet class or, for language swatches whose
    colour is whatever GitHub reports, from an explicit fill.
    """

    __slots__ = ("text", "cls", "id", "fill")

    def __init__(self, text, cls=None, id=None, fill=None):
        self.text = str(text)
        self.cls = cls
        self.id = id
        self.fill = fill

    def render(self):
        if self.cls is None and self.id is None and self.fill is None:
            return escape(self.text)
        attributes = ""
        if self.cls:
            attributes += f' class="{self.cls}"'
        if self.id:
            attributes += f' id="{self.id}"'
        if self.fill:
            attributes += f' fill="{escape(self.fill, {chr(34): "&quot;"})}"'
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


def language_lines(languages, columns=INFO_COLUMNS):
    """A stacked bar of language share, followed by a colour-keyed legend.

    Neofetch ends with a row of palette swatches; this is the same idea, except
    the colours mean something. Returns an empty list when there is no language
    data, which is the case for a cache written before this existed.
    """
    if not languages:
        return []

    label = ". Languages by bytes:"
    span_width = columns - len(label) - 1

    # Shares are of *all* languages, but only the leading few are listed, so
    # they do not sum to 1. Name the difference rather than stretching the
    # listed languages to cover it, which would overstate every one of them.
    listed = sum(language["share"] for language in languages)
    if listed < 0.995:
        languages = languages + [
            {"name": "Other", "share": 1 - listed, "color": "#8b949e"}
        ]

    # Largest-remainder apportionment: floor every share, then hand the leftover
    # cells to whoever was rounded down hardest. Rounding each independently
    # leaves the bar a cell short or a cell long.
    exact = [language["share"] * span_width for language in languages]
    cells = [int(value) for value in exact]
    for index in sorted(range(len(languages)),
                        key=lambda i: exact[i] - cells[i], reverse=True):
        if sum(cells) >= span_width:
            break
        cells[index] += 1

    bar = [Span(". ", "cc"), Span("Languages by bytes", "key"), Span(":"), Span(" ")]
    for language, count in zip(languages, cells):
        if count:
            bar.append(Span("█" * count, fill=language["color"]))

    lines = [bar]
    entries = [(f"{language['name']} {language['share'] * 100:.1f}%",
                language["color"]) for language in languages]

    # Pack the legend across as many lines as it needs.
    row_spans, used = [Span("  ")], 2
    for text, colour in entries:
        piece = len(text) + 3  # the swatch, its space, and the trailing gap
        if used + piece > columns and len(row_spans) > 1:
            lines.append(row_spans)
            row_spans, used = [Span("  ")], 2
        row_spans.extend([Span("● ", fill=colour), Span(text, "value"), Span("  ")])
        used += piece
    if len(row_spans) > 1:
        lines.append(row_spans)
    return lines


def sparkline_row(daily, year_total, columns=INFO_COLUMNS):
    """Recent daily contributions as a terminal sparkline."""
    if not daily:
        return []

    # A zero day is the shortest block rather than a space, so the sparkline
    # keeps a continuous baseline instead of breaking up into islands. Any
    # non-zero count is lifted clear of that baseline.
    blocks = "▁▂▃▄▅▆▇█"
    peak = max(daily)
    spark = "".join(
        blocks[0] if count == 0
        else blocks[max(1, round(count / peak * (len(blocks) - 1)))]
        for count in daily
    )

    label, suffix = f"Last {len(daily)} days", f"{year_total:,} this year"
    prefix = 2 + len(label) + 1
    gap = columns - prefix - len(spark) - len(suffix) - 1
    return [[
        Span(". ", "cc"), Span(label, "key"), Span(":"),
        Span(filler(gap), "cc"), Span(spark, "addColor"),
        Span(" "), Span(suffix, "value"),
    ]]


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
    # Both are skipped when absent, so a cache written before they existed
    # still renders.
    lines.extend(sparkline_row(stats.get("contributions_recent", []),
                               stats.get("contributions_year", 0), columns))
    lines.extend(language_lines(stats.get("language_bytes", []), columns))
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

    animate = config["card"].get("animate", True)
    duration = float(config["card"].get("animation_seconds", 2.5))
    step = duration / max(1, len(lines))

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
    ]

    if animate:
        out.extend([
            # CSS wins over the clip-path presentation attribute, so this drops
            # the reveal entirely for readers who ask for less motion.
            "@media (prefers-reduced-motion: reduce) {",
            "text {clip-path: none !important;} .cursor {display: none;} }",
        ])

    out += [
        "</style>",
        f'<rect width="{width}px" height="{height}px" '
        f'fill="{palette["background"]}" rx="15"/>',
    ]

    if animate:
        # Each line is wiped in left to right so the card prints itself like a
        # terminal. SMIL rather than CSS, because a clip rectangle carries a
        # static width of "fully open" and the animation only overrides it once
        # it begins. Anything that parses the file without running the clock —
        # a rasteriser, a screenshot tool, a stricter image sandbox — is still
        # before begin, so it draws the finished card instead of a blank one.
        # The equivalent in CSS needs fill-mode backwards to hold a line hidden
        # until its turn, and that renders blank in exactly those cases.
        wipe = min(step * 1.6, duration)
        out.append("<defs>")
        for index in range(len(lines)):
            start = index * step
            out.append(
                f'<clipPath id="w{index}">'
                f'<rect x="0" y="0" width="{width}" height="{height}">'
                f'<animate attributeName="width" begin="0.01s" '
                f'dur="{duration}s" fill="freeze" calcMode="linear" '
                f'values="0;0;{width};{width}" '
                f'keyTimes="0;{start / duration:.4f};'
                f'{min(start + wipe, duration) / duration:.4f};1"/>'
                f"</rect></clipPath>"
            )
        out.append("</defs>")

        for index, line in enumerate(lines):
            body = "".join(span.render() for span in line)
            out.append(
                f'<text clip-path="url(#w{index})" x="{MARGIN}" '
                f'y="{LINE_HEIGHT * (index + 1) + 10}" '
                f'fill="{palette["text"]}">{body}</text>'
            )

        # The cursor rests one column past the last character printed, which is
        # where a terminal would leave it. Parking it at column 0 of a fresh
        # line instead strands it under the portrait, reading as a stray block
        # rather than a cursor.
        tail = "".join(span.text for span in lines[-1]).rstrip()
        baseline = LINE_HEIGHT * len(lines) + 10
        out.append(
            f'<rect class="cursor" '
            f'x="{MARGIN + round((len(tail) + 1) * CHAR_WIDTH)}" '
            f'y="{baseline - FONT_SIZE + 3}" '
            f'width="{round(CHAR_WIDTH)}" height="{FONT_SIZE}" '
            # opacity="0" keeps the cursor off a card that never animates.
            f'fill="{palette["text"]}" opacity="0">'
            f'<animate attributeName="opacity" begin="{duration}s" dur="1.06s" '
            f'repeatCount="indefinite" calcMode="discrete" '
            f'values="1;0" keyTimes="0;0.55"/></rect>'
        )
    else:
        out.append(f'<text x="{MARGIN}" y="{LINE_HEIGHT + 10}" '
                   f'fill="{palette["text"]}">')
        for index, line in enumerate(lines):
            body = "".join(span.render() for span in line)
            out.append(f'<tspan x="{MARGIN}" y="{LINE_HEIGHT * (index + 1) + 10}">'
                       f'{body}</tspan>')
        out.append("</text>")

    out.append("</svg>")
    return "\n".join(out) + "\n"
