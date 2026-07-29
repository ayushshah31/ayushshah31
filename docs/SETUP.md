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

The conversion works best on a photo that is:

- **cropped to head and shoulders.** The card gives the portrait 42 columns by
  25 rows. A full-length shot loses the face entirely at that size.
- **brightly lit, with the subject clearly lighter than the background.** The
  converter maps bright pixels to dense characters, so contrast is what draws
  the outline.

To see the result before committing anything:

```bash
pip install -r requirements.txt
python photo_to_ascii.py assets/profile.jpg --preview
```

`--preview` prints to the terminal instead of writing `ascii_art.txt`. If the
portrait comes out too dark or too washed out, the flags worth reaching for are
`--contrast` (how much of the histogram to clip, try 2–10), `--gamma` (below 1
brightens the midtones), and `--focus` (where to crop vertically, 0 is the top
of the frame). `--help` lists the rest.

You can also skip the photo and hand-edit `ascii_art.txt` directly. Anything up
to 42 columns and 25 rows works; the card grows to fit if you go over.

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
