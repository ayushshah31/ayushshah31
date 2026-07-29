"""Turn a photograph into the ASCII portrait shown on the left of the profile card.

The card reserves a fixed 42x25 character grid, so the image is resized to that
grid (compensating for the fact that a character cell is much taller than it is
wide), normalised, and mapped onto a density ramp.

    python photo_to_ascii.py assets/profile.jpg

Run with --preview to print the result instead of writing ascii_art.txt.
"""

import argparse
import sys

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

# Dark end of the ramp first. A space is the background, '@' the brightest
# highlight. The glyphs in between are ordered by how much ink they put on the
# page in a monospace font, which is what makes the gradient read smoothly.
DEFAULT_RAMP = " .:-=+*ilrjkbdgmM%@"

# A character cell in the card is 8.8px wide and 20px tall, so pixels have to be
# sampled roughly 2.3x taller than they are wide or the portrait comes out squat.
DEFAULT_ASPECT = 2.27

GRID_COLS = 42
GRID_ROWS = 25


def load_image(path):
    try:
        image = Image.open(path)
    except FileNotFoundError:
        sys.exit(f"no such image: {path}")
    except OSError as exc:
        sys.exit(f"could not read {path}: {exc}")
    return ImageOps.exif_transpose(image).convert("RGB")


def crop_to_grid(image, cols, rows, aspect, focus):
    """Centre-crop the image to the aspect ratio of the character grid.

    Without this a portrait-orientation photo gets squashed horizontally. focus
    is the vertical anchor: 0.0 keeps the top of the frame, 0.5 the middle.
    """
    target = (cols / aspect) / rows
    width, height = image.size
    current = width / height

    if current > target:
        new_width = round(height * target)
        left = round((width - new_width) / 2)
        box = (left, 0, left + new_width, height)
    else:
        new_height = round(width / target)
        top = round((height - new_height) * focus)
        box = (0, top, width, top + new_height)
    return image.crop(box)


def prepare(image, cols, rows, contrast, sharpen):
    """Downsample to the grid and push the tonal range out to the full ramp."""
    grey = image.convert("L")
    if sharpen:
        # Facial features survive an aggressive downsample much better if the
        # edges are exaggerated first.
        grey = grey.filter(ImageFilter.UnsharpMask(radius=6, percent=180, threshold=2))
    grey = grey.resize((cols, rows), Image.LANCZOS)
    grey = ImageOps.autocontrast(grey, cutoff=contrast)
    if sharpen:
        grey = ImageEnhance.Contrast(grey).enhance(1.25)
    return grey


def to_ascii(grey, ramp, invert, gamma):
    steps = len(ramp) - 1
    lines = []
    for y in range(grey.height):
        row = []
        for x in range(grey.width):
            level = grey.getpixel((x, y)) / 255
            if invert:
                level = 1 - level
            if gamma != 1.0:
                level = level ** gamma
            row.append(ramp[round(level * steps)])
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
                        help="density ramp, darkest character first")
    parser.add_argument("--contrast", type=float, default=4.0,
                        help="percent to clip off each end of the histogram")
    parser.add_argument("--gamma", type=float, default=1.0,
                        help="<1 brightens midtones, >1 darkens them")
    parser.add_argument("--focus", type=float, default=0.35,
                        help="vertical crop anchor, 0 = top of frame")
    parser.add_argument("--invert", action="store_true",
                        help="map dark pixels to dense characters instead")
    parser.add_argument("--no-sharpen", dest="sharpen", action="store_false",
                        help="skip the edge-enhancement pass")
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
    grey = prepare(image, args.cols, args.rows, args.contrast, args.sharpen)
    lines = to_ascii(grey, args.ramp, args.invert, args.gamma)

    if args.preview:
        print("\n".join(lines))
        return 0

    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"wrote {args.output} ({args.cols}x{args.rows}) from {args.image}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
