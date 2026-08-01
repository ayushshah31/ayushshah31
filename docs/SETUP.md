# How the profile card works

The README shows a single SVG. That SVG is generated: a GitHub Action runs
every morning, asks the GitHub API how much has changed, redraws the card, and
commits it back. Nothing is written by hand except `config.yml` and the photo.

```
assets/profile.jpg ──> photo_to_ascii.py ──> ascii_art.txt ─┐
                                                            ├─> card.py ──> dark_mode.svg
config.yml ─────────────────────────────────────────────────┤              light_mode.svg
GitHub GraphQL API ──> github_stats.py ──> cache/stats.json ─┘
```

| File | What it is for |
| --- | --- |
| `config.yml` | Every word on the right-hand side of the card |
| `photo_to_ascii.py` | Turns a photograph into the ASCII portrait |
| `github_stats.py` | Talks to the GitHub API, caches the expensive parts |
| `card.py` | Lays out the SVG |
| `today.py` | Entry point that runs the other three |
| `cache/` | Per-repository line counts, and the last set of numbers |

## Getting your own face on it

Save a photo as `assets/profile.jpg` — dragging it into the folder from the
GitHub web interface is enough. The next Action run converts it and the
placeholder portrait disappears.

The conversion works best on a photo **cropped to head and shoulders**. The card
gives the portrait 42 columns by 25 rows; a full-length shot loses the face
entirely at that size. Beyond that the converter adapts to the lighting itself.

To see the result before committing anything:

```bash
pip install -r requirements.txt
python photo_to_ascii.py assets/profile.jpg --preview
```

`--preview` prints to the terminal instead of writing `ascii_art.txt`.

### How it decides what to draw

Averaging brightness per cell and picking a character off a density ramp — the
usual approach — falls apart at this size. A face is mostly mid-tones, so once
each cell is one average there is nothing left to recognise. It produces mush.

So each cell is measured with the **structure tensor** of the image gradients,
which reports two things an average cannot: how strongly the cell is oriented,
and which way. Cells holding a definite edge are drawn with a line glyph running
the same way (`|` `/` `-` `\`), so the jaw, hairline, nose and shoulders are
*drawn* rather than shaded. Everything else falls back to the tone ramp.

The tensor matters rather than just averaging the gradient: averaging cancels
opposing gradients — the two sides of a nostril — and reports no edge where
there plainly is one. Averaging gradient *products* keeps the orientation.

Two things happen automatically:

- **Inversion.** If the border of the frame is brighter than the middle — a
  subject against a pale wall — the tones are flipped so the subject is drawn in
  ink on empty paper. Without this the wall fills in solid and the face comes
  out pale, which is backwards. Override with `--invert` / `--no-invert`.
- **Background blanking.** Cells that are both flat and pale are left empty
  rather than given the lightest ramp character, so the wall does not become a
  field of stipple competing with the face.

### Tuning

If the result is not right, in rough order of usefulness:

| Flag | Try | Does |
| --- | --- | --- |
| `--focus` | `0`–`1` | where to crop vertically, 0 is the top of the frame |
| `--black-point` | `8`–`25` | higher empties more background |
| `--edge-percentile` | `70`–`88` | lower draws more line work, higher more shading |
| `--coherence` | `0.3`–`0.6` | how definite an edge must be to earn a line glyph |
| `--floor` | `0.3`–`0.55` | how pale a flat cell must be before it is left blank |
| `--flatten` | `0`–`1` | how much uneven lighting to divide out |

`--no-edges` falls back to shading only, and `--help` lists the rest.

You can also skip the photo and hand-edit `ascii_art.txt` directly. Anything up
to 42 columns and 25 rows works; the card grows to fit if you go over.

### Prior art

The same idea, if you want to compare output: [p2ascii](https://github.com/Hugana/p2ascii)
also uses Sobel gradients for orientation, [Asciimatic](https://github.com/dijkstracula/Asciimatic)
builds on Canny edges, and [deep_ascii_converter](https://github.com/saiccoumar/deep_ascii_converter)
takes a learned approach to the same problem.

## The typing animation

The card prints itself line by line with a cursor blinking at the end. Turn it
off in `config.yml`:

```yaml
card:
  animate: false
  animation_seconds: 2.5   # how long the whole card takes to print
```

It is built with SMIL (`<animate>` driving a clip rectangle) rather than CSS
animation, and that choice is load-bearing. Each clip rectangle carries a static
width of *fully open*, and the animation only overrides it once it begins — so
anything that reads the file without running the clock draws the finished card.
The natural CSS version needs `animation-fill-mode: backwards` to hold a line
hidden until its turn, and a renderer that instantiates animations without
advancing them then paints a **completely blank card**. That is not
hypothetical; it is what happens under headless Chromium.

If you change any of this, verify by sampling the timeline rather than trusting
a screenshot delay:

```html
<script>
  const s = document.querySelector("svg");
  s.pauseAnimations();
  s.setCurrentTime(1.2);   // seconds into the animation
</script>
```

Readers who set `prefers-reduced-motion: reduce` get the finished card with no
reveal and no cursor.

## The language bar and the sparkline

Two rows at the bottom are drawn rather than written:

- **Languages by bytes** — a stacked bar of what you actually write, weighted by
  source bytes across every repository you have touched, coloured with GitHub's
  own language colours. Bytes rather than repository count, so one small
  hand-written project does not outweigh a large one. Cells are apportioned by
  largest remainder so the bar is always exactly full.
- **Last 30 days** — daily contributions as a sparkline, with the year total on
  the right. A zero day draws the shortest block rather than a space, so the
  baseline stays continuous.

Both cost nothing extra: the language data rides along with the repository query
that was already being made, and contributions are a single additional call.

Both are skipped entirely when the data is missing, so a `cache/stats.json`
written before they existed still renders.

One caveat in light mode: a few language colours — GitHub's yellow for
JavaScript especially — are low contrast on white. They are GitHub's own values,
used as-is.

## Editing the text

Everything on the right comes from `config.yml`. A row looks like this:

```yaml
- key: Languages.Programming
  value: [Python, JavaScript, Java]
```

The dotted key is cosmetic — `Languages.Programming` renders with each half
highlighted. A list value is joined with commas. `blank: true` leaves a gap, and
a section with a `title` gets its own `- Title -———` heading rule.

Rows are padded with dots out to a fixed width, so a long value has nowhere to
go. `today.py` warns you by name when one is too long:

```
warning: 'Stack.Frontend' is 4 characters too wide and will run past the column
```

After editing, rebuild without touching the API:

```bash
python today.py --offline
```

That reuses the numbers in `cache/stats.json`, so it is instant and needs no
token. Commit the two SVGs along with your config change.

## Running it against the live API

```bash
export USER_NAME=ayushshah31
export ACCESS_TOKEN=github_pat_...
python today.py
```

The first run is slow. Lines of code are counted by walking the commit history
of every repository you have touched, which is a few hundred API calls. Every
run after that reads `cache/<hash>.txt` and only re-walks repositories whose
commit count actually changed, so a normal day is a handful of calls.

## The token

The Action falls back to the `GITHUB_TOKEN` that Actions provides, so it works
with no setup at all — it just only counts public activity.

To include private and organisation repositories, create a **fine-grained
personal access token** and save it as a repository secret named
`ACCESS_TOKEN` (Settings → Secrets and variables → Actions). It needs:

- Account permissions: `Followers: read`, `Starring: read`
- Repository permissions (all repositories): `Contents: read`, `Metadata: read`

Note that the card then publishes aggregate counts that include private work —
total commits and lines of code go up. No repository names are ever written to
the card, but the numbers are visible to anyone.

## When something breaks

**The numbers are all zero.** The first Action run has not finished, or it
failed. Check the Actions tab.

**The columns look ragged.** The card assumes a monospace font. It ships a
`size-adjust` rule that lines Consolas up with the more common metrics, and the
portrait and text are emitted as one padded run per line so they cannot drift
apart — but a proportional fallback font will still look wrong.

**Lines of code jumped or collapsed.** Delete `cache/<hash>.txt` and let it
rebuild from scratch. The cache is keyed on commit counts, so a force-push or a
rewritten history can leave it holding numbers for commits that no longer exist.

**The Action cannot push.** It needs `contents: write`, and the repository
needs Settings → Actions → General → Workflow permissions set to read *and*
write.
