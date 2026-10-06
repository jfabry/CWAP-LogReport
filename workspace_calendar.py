#!/usr/bin/env python3
"""Render a yearly calendar of workspace occupancy from a badge-scanner log.

Usage:
    python3 workspace_calendar.py [path-to-log] [--cutoff YYYY-MM]

--cutoff ignores all log entries before the first day of the given month.

For each calendar year found in the log, writes a multi-page PDF
(<year>_workspace_occupancy.pdf) with 2 pages of 6 months each. Each day is
split into 4 time buckets (07-10, 10-13, 13-16, 16-19) colored by how many
distinct ajp/pex/*prof* badge holders were present during that bucket, assuming
each door-open keeps a person present for 45 minutes.
"""

import argparse
import calendar
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Rectangle

LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) - (\d{2}:\d{2}:\d{2}) - (.*) - (\S+)\s*$"
)

TAGS_OF_INTEREST = {"ajp", "pex"}
TAG_SUBSTRING_OF_INTEREST = "prof"


def is_tag_of_interest(tag):
    return tag in TAGS_OF_INTEREST or TAG_SUBSTRING_OF_INTEREST in tag

BUCKETS = [(7, 10), (10, 13), (13, 16), (16, 19)]
BUCKET_LABELS = ["07-10", "10-13", "13-16", "16-19"]

STAY_MINUTES = 45


def parse_log(path, cutoff=None):
    """Return list of (datetime, name, tag) for ajp/pex/*prof* door-opens on or
    after cutoff (a datetime, or None for no cutoff)."""
    events = []
    tag_counts = Counter()
    total_lines = 0
    skipped = 0
    before_cutoff = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            total_lines += 1
            m = LINE_RE.match(line)
            if not m:
                skipped += 1
                continue
            date_str, time_str, name, tag = m.groups()
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
            if cutoff is not None and dt < cutoff:
                before_cutoff += 1
                continue
            tag_counts[tag] += 1
            if is_tag_of_interest(tag.lower()):
                events.append((dt, name.strip(), tag.lower()))
    print(
        f"Parsed {total_lines} lines, {skipped} unparsed, "
        f"{before_cutoff} before cutoff ignored, "
        f"{len(events)} tracked events used.",
        file=sys.stderr,
    )
    print_tag_summary(tag_counts)
    return events


def print_tag_summary(tag_counts):
    kept = [(t, c) for t, c in tag_counts.most_common() if is_tag_of_interest(t.lower())]
    dropped = [(t, c) for t, c in tag_counts.most_common() if not is_tag_of_interest(t.lower())]
    total = sum(tag_counts.values())
    dropped_total = sum(c for _, c in dropped)
    width = max((len(t) for t in tag_counts), default=0)

    print("\nTags encountered (entries on/after cutoff):", file=sys.stderr)
    print("  Kept:", file=sys.stderr)
    for tag, count in kept:
        print(f"    {tag:<{width}}  {count:>6}", file=sys.stderr)
    print(f"  {'':-<{width + 10}}", file=sys.stderr)
    pct = 100 * dropped_total / total if total else 0
    print(
        f"  *** FILTERED OUT: {dropped_total} of {total} entries ({pct:.1f}%) "
        f"across {len(dropped)} tags ***",
        file=sys.stderr,
    )
    for tag, count in dropped:
        print(f"  ! {tag:<{width}}  {count:>6}", file=sys.stderr)
    print(file=sys.stderr)


def buckets_for_event(dt):
    """Return list of bucket indices (0-3) this door-open overlaps."""
    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    open_time = day_start.replace(hour=7)
    close_time = day_start.replace(hour=19)

    if dt < open_time:
        start = open_time
    elif dt >= close_time:
        return [len(BUCKETS) - 1]
    else:
        start = dt

    end = start + timedelta(minutes=STAY_MINUTES)

    overlapping = []
    for i, (h0, h1) in enumerate(BUCKETS):
        b_start = day_start.replace(hour=h0)
        b_end = day_start.replace(hour=h1)
        if start < b_end and end > b_start:
            overlapping.append(i)
    return overlapping


def compute_occupancy(events):
    """Return {date: [set(names), set(names), set(names), set(names)]}."""
    occupancy = defaultdict(lambda: [set() for _ in BUCKETS])
    for dt, name, _tag in events:
        date = dt.date()
        for b in buckets_for_event(dt):
            occupancy[date][b].add(name)
    return occupancy


def counts_grid(occupancy):
    """Return {date: [int, int, int, int]} and the global max count."""
    counts = {}
    global_max = 0
    for date, buckets in occupancy.items():
        c = [len(s) for s in buckets]
        counts[date] = c
        global_max = max(global_max, max(c))
    return counts, global_max


def draw_swatch_legend(ax, colors, labels, caption, fontsize=8):
    """Draw a row of equal-width discrete color swatches with a label
    centered under each one (avoids matplotlib colorbar tick placement,
    which anchors BoundaryNorm ticks to bin edges rather than centers)."""
    n = len(colors)
    ax.set_xlim(0, n)
    ax.set_ylim(0, 1)
    for i, color in enumerate(colors):
        ax.add_patch(Rectangle((i, 0), 1, 1, facecolor=color, edgecolor="black", linewidth=0.8))
        ax.text(i + 0.5, -0.55, str(labels[i]), ha="center", va="top", fontsize=fontsize)
    ax.text(n / 2, -1.7, caption, ha="center", va="top", fontsize=fontsize, color="#444444")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def quadrant_origins(x0, y0, half):
    """Sub-cell origins in bucket order: [07-10, 10-13, 13-16, 16-19]
    i.e. top-left, top-right, bottom-left, bottom-right."""
    return [
        (x0, y0),
        (x0 + half, y0),
        (x0, y0 + half),
        (x0 + half, y0 + half),
    ]


def draw_month(ax, year, month, counts, cmap, norm):
    ax.set_title(calendar.month_name[month], fontsize=13, fontweight="bold")
    ax.set_xlim(0, 7)
    weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for i, lbl in enumerate(weekday_labels):
        ax.text(i + 0.5, -0.4, lbl, ha="center", va="center", fontsize=7, color="#555555")

    weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    n_weeks = len(weeks)
    ax.set_ylim(n_weeks, -0.8)

    for w, week in enumerate(weeks):
        for d, day in enumerate(week):
            x0, y0 = d, w
            if day == 0:
                ax.add_patch(
                    Rectangle((x0, y0), 1, 1, facecolor="#f2f2f2", edgecolor="white")
                )
                continue

            date = calendar.datetime.date(year, month, day)
            day_counts = counts.get(date, [0, 0, 0, 0])

            half = 0.5
            for q, (qx, qy) in enumerate(quadrant_origins(x0, y0, half)):
                color = cmap(norm(day_counts[q]))
                ax.add_patch(
                    Rectangle(
                        (qx, qy), half, half, facecolor=color, edgecolor="white", linewidth=0.4
                    )
                )

            ax.add_patch(
                Rectangle((x0, y0), 1, 1, facecolor="none", edgecolor="#bbbbbb", linewidth=0.5)
            )
            ax.text(
                x0 + 0.06,
                y0 + 0.16,
                str(day),
                ha="left",
                va="center",
                fontsize=6,
                color="black",
                fontweight="bold",
            )

    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def person_bucket_counts(occupancy, year):
    """Return {name: total number of (date, bucket) slots occupied in year}."""
    counts = Counter()
    for date, buckets in occupancy.items():
        if date.year != year:
            continue
        for bucket_set in buckets:
            for name in bucket_set:
                counts[name] += 1
    return counts


def person_weekday_bucket_counts(occupancy, year, name):
    """Return counts[weekday(0=Mon)][bucket] = number of days (that weekday)
    name occupied that bucket during the year."""
    matrix = [[0] * len(BUCKETS) for _ in range(7)]
    for date, buckets in occupancy.items():
        if date.year != year:
            continue
        wd = date.weekday()
        for b, bucket_set in enumerate(buckets):
            if name in bucket_set:
                matrix[wd][b] += 1
    return matrix


QUARTILE_COLORS = ["white", "#eff3ff", "#bdd7e7", "#6baed6", "#2171b5"]
PERSON_CMAP = ListedColormap(QUARTILE_COLORS)


def quartile_index(value, n):
    """Classify value into 0 (=0, white) or a quartile (1-4) of the
    person's nonzero range (0, n]."""
    if value <= 0 or n <= 0:
        return 0
    if value <= n / 4:
        return 1
    if value <= n / 2:
        return 2
    if value <= 3 * n / 4:
        return 3
    return 4


def quartile_labels(n):
    if n <= 0:
        return ["0"] * 5
    q1 = max(1, round(n / 4))
    q2 = max(q1 + 1, round(n / 2))
    q3 = max(q2 + 1, round(3 * n / 4))
    q4 = max(q3 + 1, n)
    return ["0", f"1-{q1}", f"{q1 + 1}-{q2}", f"{q2 + 1}-{q3}", f"{q3 + 1}-{q4}"]


def draw_top10(ax, top10):
    ranked = list(reversed(top10))
    names = [name for name, _ in ranked]
    values = [count for _, count in ranked]
    y = range(len(names))

    ax.barh(y, values, color="#d9534f", height=0.6, zorder=3)
    ax.set_yticks(list(y))
    ax.set_yticklabels(names, fontsize=9)
    ax.set_xlabel("Buckets occupied")
    ax.set_title("Top 10 by bucket-presence", fontsize=13, fontweight="bold")
    ax.grid(axis="x", color="#eeeeee", zorder=0)
    for i, v in enumerate(values):
        ax.text(v + max(values) * 0.02, i, str(v), va="center", fontsize=8)
    ax.set_xlim(0, max(values) * 1.15)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def draw_person_week(fig, pos, name, count, matrix):
    inner = pos.subgridspec(2, 1, height_ratios=[6, 1], hspace=0.25)
    ax = fig.add_subplot(inner[0])
    cax = fig.add_subplot(inner[1])

    n = max(max(row) for row in matrix)

    weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    ax.set_title(f"{name}\n{count} buckets", fontsize=10, fontweight="bold")
    pitch = 1.125
    ax.set_xlim(-0.6, 6 * pitch + 1)
    ax.set_ylim(1.2, -0.35)
    ax.set_aspect("equal")

    for label, y in (("AM", 0.25), ("PM", 0.75)):
        ax.text(-0.1, y, label, ha="right", va="center", fontsize=8, fontweight="bold", color="#444444")

    for wd in range(7):
        x0, y0 = wd * pitch, 0
        for value, (qx, qy) in zip(matrix[wd], quadrant_origins(x0, y0, 0.5)):
            color = QUARTILE_COLORS[quartile_index(value, n)]
            ax.add_patch(
                Rectangle(
                    (qx, qy), 0.5, 0.5,
                    facecolor=color,
                    edgecolor="#bbbbbb", linewidth=0.5,
                )
            )
        ax.add_patch(
            Rectangle((x0, y0), 1, 1, facecolor="none", edgecolor="#888888", linewidth=0.8)
        )
        ax.text(x0 + 0.5, 1.05, weekday_labels[wd], ha="center", va="top", fontsize=8, color="#444444")

    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    draw_swatch_legend(
        cax, QUARTILE_COLORS, quartile_labels(n),
        "days present (this weekday/bucket)", fontsize=5.5,
    )


def cutoff_suffix(cutoff):
    return f" - from {cutoff:%Y-%m}" if cutoff else ""


def render_person_analysis_page(pdf, year, occupancy, cutoff=None):
    counts = person_bucket_counts(occupancy, year)
    if not counts:
        return
    top10 = counts.most_common(10)
    top6 = top10[:6]

    fig = plt.figure(figsize=(16, 10))
    fig.suptitle(
        f"BPN317 Workspace Occupancy - {year} - Per-Person Analysis{cutoff_suffix(cutoff)}",
        fontsize=16, fontweight="bold",
    )
    gs = fig.add_gridspec(
        3, 3, width_ratios=[1.5, 1, 1],
        left=0.20, right=0.97, top=0.88, bottom=0.12, hspace=0.65, wspace=0.3,
    )

    ax_left = fig.add_subplot(gs[:, 0])
    draw_top10(ax_left, top10)

    positions = [gs[0, 1], gs[1, 1], gs[2, 1], gs[0, 2], gs[1, 2], gs[2, 2]]
    for pos, (name, count) in zip(positions, top6):
        matrix = person_weekday_bucket_counts(occupancy, year, name)
        draw_person_week(fig, pos, name, count, matrix)

    fig.text(
        0.5, 0.02,
        "Weekly charts (top 6): quadrant color = quartile of how often that person occupied that weekday/bucket "
        "during the year, relative to their own busiest cell (N). Each chart has its own legend since N differs per person. "
        "Layout matches the monthly calendar: 07-10 top-left, 10-13 top-right, 13-16 bottom-left, 16-19 bottom-right.",
        ha="center", fontsize=8, color="#444444",
    )

    pdf.savefig(fig)
    plt.close(fig)


def render_year(year, counts, occupancy, cmap, norm, global_max, out_path, cutoff=None):
    with PdfPages(out_path) as pdf:
        for half, months in enumerate([range(1, 7), range(7, 13)]):
            fig, axes = plt.subplots(2, 3, figsize=(16, 10))
            fig.suptitle(
                f"BPN317 Workspace Occupancy - {year} "
                f"({'Jan-Jun' if half == 0 else 'Jul-Dec'}){cutoff_suffix(cutoff)}",
                fontsize=16,
                fontweight="bold",
            )
            for ax, month in zip(axes.flat, months):
                draw_month(ax, year, month, counts, cmap, norm)

            fig.subplots_adjust(left=0.03, right=0.97, top=0.88, bottom=0.14, wspace=0.15, hspace=0.35)

            legend_ax = fig.add_axes([0.32, 0.045, 0.36, 0.03])
            draw_swatch_legend(
                legend_ax, cmap.colors, list(range(global_max + 1)),
                f"People present in bucket (ajp/pex/prof, {STAY_MINUTES}min dwell)",
            )

            fig.text(
                0.03, 0.05,
                "Each day cell = 4 buckets:\n"
                "07-10 | 10-13\n13-16 | 16-19",
                fontsize=8, va="center", ha="left", color="#444444",
            )

            pdf.savefig(fig)
            plt.close(fig)

        render_person_analysis_page(pdf, year, occupancy, cutoff)
    print(f"Wrote {out_path}", file=sys.stderr)


def parse_cutoff(value):
    try:
        return datetime.strptime(value, "%Y-%m")
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid cutoff {value!r}, expected YYYY-MM")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("log", nargs="?", default="acceso-BPN317.txt", help="path to the badge log")
    parser.add_argument(
        "--cutoff", type=parse_cutoff, metavar="YYYY-MM",
        help="ignore entries before the first day of this month",
    )
    args = parser.parse_args()

    events = parse_log(args.log, args.cutoff)
    if not events:
        print("No tracked events found; nothing to render.", file=sys.stderr)
        return

    occupancy = compute_occupancy(events)
    counts, global_max = counts_grid(occupancy)

    base = matplotlib.colormaps.get_cmap("YlOrRd").resampled(max(global_max, 1))
    colors = ["white"] + [base(i) for i in range(base.N)]
    cmap = ListedColormap(colors)
    norm = BoundaryNorm(list(range(global_max + 2)), cmap.N)

    years = sorted({date.year for date in counts})
    for year in years:
        out_path = f"{year}_workspace_occupancy.pdf"
        render_year(year, counts, occupancy, cmap, norm, global_max, out_path, args.cutoff)


if __name__ == "__main__":
    main()
