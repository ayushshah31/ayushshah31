"""Regenerate dark_mode.svg and light_mode.svg.

Run by .github/workflows/profile-card.yml once a day, and safe to run by hand:

    USER_NAME=ayushshah31 ACCESS_TOKEN=ghp_... python today.py

Pass --offline to rebuild the SVGs from the cached numbers without touching the
GitHub API, which is what you want when you are only editing config.yml.
"""

import argparse
import datetime
import json
import os
import sys
import time

import yaml
from dateutil import relativedelta

import card
import github_stats

CONFIG_PATH = "config.yml"
ASCII_PATH = "ascii_art.txt"
STATS_PATH = "cache/stats.json"
OUTPUTS = {"dark": "dark_mode.svg", "light": "light_mode.svg"}


def plural(count):
    return "" if count == 1 else "s"


def uptime_since(birthday):
    """'23 years, 4 months, 12 days', with a cake on the day itself."""
    delta = relativedelta.relativedelta(datetime.datetime.today(), birthday)
    text = (f"{delta.years} year{plural(delta.years)}, "
            f"{delta.months} month{plural(delta.months)}, "
            f"{delta.days} day{plural(delta.days)}")
    return text + " 🎂" if delta.months == 0 and delta.days == 0 else text


def load_config(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except FileNotFoundError:
        sys.exit(f"missing {path} — see docs/SETUP.md")


def load_ascii(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return [line.rstrip("\n") for line in handle]
    except FileNotFoundError:
        sys.exit(f"missing {path} — run photo_to_ascii.py to generate it")


def load_cached_stats():
    try:
        with open(STATS_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, ValueError):
        sys.exit(f"no cached stats at {STATS_PATH} — run once without --offline")


def save_cached_stats(stats):
    os.makedirs(os.path.dirname(STATS_PATH), exist_ok=True)
    with open(STATS_PATH, "w", encoding="utf-8") as handle:
        json.dump(stats, handle, indent=2, sort_keys=True)
        handle.write("\n")


def birthday_from(config, stats):
    """The date the Uptime row counts from.

    config.card.birthday wins. Without it, fall back to the age of the GitHub
    account, which is at least true. Before the first successful API run there
    is no account date either, so say so rather than invent one.
    """
    value = config["card"].get("birthday")
    if value:
        if isinstance(value, datetime.date):
            return datetime.datetime.combine(value, datetime.time())
        return datetime.datetime.strptime(str(value), "%Y-%m-%d")
    created = stats.get("created_at")
    if created:
        return datetime.datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ")
    return None


def warn_about_wide_rows(config):
    """Flag config rows longer than the column, which widen the whole card."""
    for section in config.get("sections", []):
        for entry in section.get("rows", []):
            if not entry or entry.get("blank") or entry.get("id") == "age_data":
                continue
            value = entry.get("value", "")
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            spans = card.row(entry["key"], value)
            excess = sum(len(span) for span in spans) - card.INFO_COLUMNS
            if excess > 0:
                print(f"warning: '{entry['key']}' is {excess} characters wider "
                      f"than the column; the whole card grows to fit it",
                      file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true",
                        help="rebuild from cache/stats.json, no API calls")
    parser.add_argument("--config", default=CONFIG_PATH)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    ascii_art = load_ascii(ASCII_PATH)
    warn_about_wide_rows(config)

    if args.offline:
        stats = load_cached_stats()
        print("using cached stats")
    else:
        started = time.perf_counter()
        client = github_stats.from_environment()
        stats = client.collect()
        save_cached_stats(stats)
        print(f"fetched stats in {time.perf_counter() - started:.1f}s "
              f"({stats['api_calls']} API calls, "
              f"{stats['repos_refreshed']} repo histories refreshed)")

    birthday = birthday_from(config, stats)
    uptime = uptime_since(birthday) if birthday else "TODO: set card.birthday"

    for theme, filename in OUTPUTS.items():
        with open(filename, "w", encoding="utf-8") as handle:
            handle.write(card.render(config, stats, ascii_art, uptime, theme))
        print(f"wrote {filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
