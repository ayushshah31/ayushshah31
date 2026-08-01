"""Turn a photograph into the ASCII portrait shown on the left of the profile card.

The card gives the portrait a 42x25 character grid. Mapping brightness straight
onto a density ramp at that size produces mush: a face is mostly mid-tones, and
once each cell is a single average there is nothing left to recognise.

So this works structurally instead. For every cell it measures the structure
tensor of the image gradients, which gives two things a plain average does not:

  * how strongly the cell is oriented — whether it contains an edge at all
  * which way that edge runs

Cells holding a definite edge get a line glyph pointing the same way (| / - \),
so the jaw, hairline, nose and shoulders are drawn rather than shaded. Cells
with no clear edge fall back to a density ramp for tone. The result reads as a
line drawing, which also means it works on a light and a dark card equally well.

    python photo_to_ascii.py assets/profile.jpg --preview

Run without --preview to write ascii_art.txt.
"""

import argparse
import sys

import numpy as np
from PIL import Image, ImageFilter, ImageOps

# Tone ramp for cells with no dominant edge, lightest first. Deliberately avoids
# the line glyphs so shading never reads as structure.
DEFAULT_RAMP = " .',;coO8%@"

# Edge glyphs by direction, quarter turn apart, starting horizontal.
EDGE_GLYPHS = ("-", "/", "|", "\\")

# A character cell on the card is 8.8px wide and 20px tall, so the image has to
# be sampled roughly 2.3x taller than it is wide or the portrait comes out squat.
DEFAULT_ASPECT = 2.27

GRID_COLS = 42
GRID_ROWS = 25

# Supersampling factor: each character cell is measured over this many image
# pixels per side. Gradients need room to exist, so the image is resized to the
# grid times this rather than straight down to the grid.
CELL = 8


def load_image(path):
    try:
        image = Image.open(path)
    except FileNotFoundError:
        sys.exit(f"no such image: {path}")
    except OSError as exc:
        sys.exit(f"could not read {path}: {exc}")
    return ImageOps.exif_transpose(image).convert("RGB")


def crop_to_grid(image, cols, rows, aspect, focus):
    """Centre-crop to the aspect ratio of the character grid.

    Without this a portrait-orientation photo is squashed horizontally. focus is
    the vertical anchor: 0.0 keeps the top of the frame, 0.5 the middle.
    """
    target = (cols / aspect) / rows
    width, height = image.size

    if width / height > target:
        new_width = round(height * target)
        left = round((width - new_width) / 2)
        return image.crop((left, 0, left + new_width, height))
    new_height = round(width / target)
    top = round((height - new_height) * focus)
    return image.crop((0, top, width, top + new_height))


def local_contrast(tile, strength):
    """Even out lighting so a shadowed cheek still shows its edges.

    A portrait is usually lit from one side, and a single global stretch then
    spends most of the ramp on that gradient rather than on the face. This
    divides out the low-frequency illumination instead.
    """
    if strength <= 0:
        return tile
    # Through uint8 because Pillow will not blur a float image. Estimating the
    # illumination to the nearest level is plenty.
    blurred = Image.fromarray(tile.clip(0, 255).astype(np.uint8), mode="L").filter(
        ImageFilter.GaussianBlur(radius=max(tile.shape) / 12)
    )
    illumination = np.asarray(blurred, dtype=np.float32) + 1e-3
    flattened = tile / illumination * illumination.mean()
    return tile * (1 - strength) + flattened * strength


def sobel(tile):
    """Image gradients. Written out rather than pulled from scipy to keep the
    dependency list to numpy and Pillow."""
    padded = np.pad(tile, 1, mode="edge")
    kernel_x = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float32)
    kernel_y = kernel_x.T

    gx = np.zeros_like(tile)
    gy = np.zeros_like(tile)
    for dy in range(3):
        for dx in range(3):
            window = padded[dy:dy + tile.shape[0], dx:dx + tile.shape[1]]
            gx += kernel_x[dy, dx] * window
            gy += kernel_y[dy, dx] * window
    return gx, gy


def cell_view(array, rows, cols):
    """Reshape into (rows, cols, CELL, CELL) so each cell can be reduced at once."""
    return array.reshape(rows, CELL, cols, CELL).transpose(0, 2, 1, 3)


def analyse(tile, rows, cols):
    """Per cell: mean tone, edge direction, and how strongly oriented it is.

    The structure tensor is the reason this beats averaging the gradient
    directly. Averaging cancels out opposing gradients — the two sides of a
    nostril, say — and reports no edge where there is obviously one. The tensor
    averages gradient *products*, so orientation survives.
    """
    gx, gy = sobel(tile)

    cells = cell_view(tile, rows, cols)
    jxx = cell_view(gx * gx, rows, cols).mean(axis=(2, 3))
    jyy = cell_view(gy * gy, rows, cols).mean(axis=(2, 3))
    jxy = cell_view(gx * gy, rows, cols).mean(axis=(2, 3))

    trace = jxx + jyy
    # How much the cell prefers one direction, 0 (no preference) to 1 (a clean
    # edge). Corners and noise score low, which is what keeps them as tone.
    coherence = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (trace + 1e-6)

    # Orientation of the dominant gradient; the edge itself runs across it.
    # gy is negated because image rows increase downwards, and the glyphs are
    # chosen by how the line looks on screen.
    gradient_angle = 0.5 * np.arctan2(2 * jxy, jxx - jyy)
    edge_angle = (np.pi / 2 - gradient_angle) % np.pi

    return cells.mean(axis=(2, 3)), trace, coherence, edge_angle


def background_is_light(tone):
    """True when the frame's border is brighter than its middle.

    Studio portraits are usually a subject against a lighter wall. Shading them
    by brightness fills the wall solid and leaves the face pale — backwards.
    Inverting draws the subject in ink on empty paper instead, which is also why
    the result works on both the light and the dark card.
    """
    border = np.concatenate([
        tone[0, :], tone[-1, :], tone[:, 0], tone[:, -1],
    ])
    inset = tone[tone.shape[0] // 4: -tone.shape[0] // 4,
                 tone.shape[1] // 4: -tone.shape[1] // 4]
    return border.mean() > inset.mean()


def to_ascii(tone, energy, coherence, angle, ramp, args):
    """Choose a glyph per cell: a line where there is one, otherwise shading."""
    invert = background_is_light(tone) if args.invert is None else args.invert
    if invert:
        tone = -tone

    # Percentile rather than min/max: one specular highlight or one black pupil
    # should not compress everything else into the middle of the ramp.
    low, high = np.percentile(tone, [args.black_point, args.white_point])
    tone = np.clip((tone - low) / ((high - low) or 1), 0, 1)
    if args.gamma != 1.0:
        tone = tone ** args.gamma

    # Both thresholds are percentiles of this image, because edge energy varies
    # by orders of magnitude between a crisp photo and a soft one.
    cutoff = np.percentile(energy, args.edge_percentile)
    quiet = np.percentile(energy, args.quiet_percentile)

    steps = len(ramp) - 1
    lines = []
    for y in range(tone.shape[0]):
        row = []
        for x in range(tone.shape[1]):
            if (args.edges and energy[y, x] >= cutoff
                    and coherence[y, x] >= args.coherence):
                bucket = int(round(angle[y, x] / (np.pi / 4))) % 4
                row.append(EDGE_GLYPHS[bucket])
            elif energy[y, x] <= quiet and tone[y, x] <= args.floor:
                # Flat and pale: empty background, not the lightest shade. Left
                # as a ramp character it turns the wall behind the subject into
                # a field of stipple that competes with the face.
                row.append(" ")
            else:
                row.append(ramp[int(round(tone[y, x] * steps))])
        lines.append("".join(row).rstrip())
    return lines


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", nargs="?", default="assets/profile.jpg",
                        help="source photograph (default: assets/profile.jpg)")
    parser.add_argument("-o", "--output", default="ascii_art.txt",
                        help="where to write the art (default: ascii_art.txt)")
    parser.add_argument("--cols", type=int, default=GRID_COLS)
    parser.add_argument("--rows", type=int, default=GRID_ROWS)
    parser.add_argument("--aspect", type=float, default=DEFAULT_ASPECT,
                        help="height:width ratio of one character cell")
    parser.add_argument("--ramp", default=DEFAULT_RAMP,
                        help="tone ramp for flat cells, lightest character first")
    parser.add_argument("--edge-percentile", type=float, default=80.0,
                        help="cells above this share of edge energy are drawn as "
                             "lines; lower means more line work")
    parser.add_argument("--coherence", type=float, default=0.45,
                        help="how one-directional a cell must be to earn a line "
                             "glyph, 0 to 1")
    parser.add_argument("--quiet-percentile", type=float, default=45.0,
                        help="cells below this share of edge energy may be left "
                             "blank if they are also pale")
    parser.add_argument("--floor", type=float, default=0.42,
                        help="tone below which a featureless cell is left blank")
    parser.add_argument("--black-point", type=float, default=16.0,
                        help="percentile mapped to blank")
    parser.add_argument("--white-point", type=float, default=97.0,
                        help="percentile mapped to the densest character")
    parser.add_argument("--flatten", type=float, default=0.35,
                        help="how much uneven lighting to divide out, 0 to 1")
    parser.add_argument("--gamma", type=float, default=1.0,
                        help="<1 brightens midtones, >1 darkens them")
    parser.add_argument("--focus", type=float, default=0.35,
                        help="vertical crop anchor, 0 = top of frame")
    parser.add_argument("--invert", action=argparse.BooleanOptionalAction,
                        default=None,
                        help="draw dark pixels dense. Left unset, chosen by "
                             "whether the background is lighter than the subject")
    parser.add_argument("--no-edges", dest="edges", action="store_false",
                        help="shade only, no line glyphs")
    parser.add_argument("--no-crop", dest="crop", action="store_false",
                        help="stretch to the grid instead of centre-cropping")
    parser.add_argument("--preview", action="store_true",
                        help="print the art instead of writing it to disk")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    image = load_image(args.image)
    if args.crop:
        image = crop_to_grid(image, args.cols, args.rows, args.aspect, args.focus)

    tile = np.asarray(
        image.convert("L").resize((args.cols * CELL, args.rows * CELL),
                                  Image.LANCZOS),
        dtype=np.float32,
    )
    tile = local_contrast(tile, args.flatten)

    tone, energy, coherence, angle = analyse(tile, args.rows, args.cols)
    lines = to_ascii(tone, energy, coherence, angle, args.ramp, args)

    if args.preview:
        print("\n".join(lines))
        return 0

    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"wrote {args.output} ({args.cols}x{args.rows}) from {args.image}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
