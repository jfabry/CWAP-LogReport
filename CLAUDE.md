# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-script tool, `workspace_calendar.py`, that turns a door badge-scanner log (`acceso-BPN317.txt`) into occupancy report PDFs. There is no build, lint or test setup; the only dependency is `matplotlib` (stdlib otherwise).

## Running

```bash
python3 workspace_calendar.py [path-to-log] [--cutoff YYYY-MM]
```

- Log path defaults to `acceso-BPN317.txt` in the current directory.
- `--cutoff` drops all entries before the first day of that month; the cutoff is appended to every page title.
- Writes one `<year>_workspace_occupancy.pdf` per calendar year present in the (filtered) data, into the current directory. Each PDF has 3 pages: Jan-Jun, Jul-Dec, per-person analysis.
- Parse stats (unparsed lines, entries before cutoff, entries used) and a per-tag count table (kept tags, then filtered-out tags highlighted) are printed to stderr. A non-zero "unparsed" count usually means the log format changed again.
- Matplotlib uses the `Agg` backend; there is no way to preview other than opening the PDFs or saving a figure to PNG yourself.

## Log format and filtering

Each line is `YYYY-MM-DD - HH:MM:SS - Name - tag` (`LINE_RE`). The tag is the last space-free token. The format has changed before (older logs had `: Abriendo puerta BPN317:` between time and name); only the current format is supported.

Only entries whose lowercased tag is `ajp` or `pex`, or contains `prof` (`is_tag_of_interest`), are tracked; everything else (`adm`, `sis`, ...) is ignored. People are identified solely by the name string, so the same person logged under two tags is one person, and a name spelled differently is a different person.

## Occupancy model (the non-obvious part)

- Each door-open means the person stays present for `STAY_MINUTES` (45).
- A day has 4 fixed buckets, 07-10, 10-13, 13-16, 16-19 (`BUCKETS`). `buckets_for_event` returns every bucket the person's `[open, open+stay)` window overlaps, so one entry can land in two adjacent buckets. Opens before 07:00 are clamped to start at 07:00; opens at/after 19:00 go straight to the last bucket.
- `compute_occupancy` produces `{date: [set(names) x 4]}`; sets dedupe repeat badge-ins. This structure is the single source for everything else: `counts_grid` takes set sizes for the calendar pages, while the per-person page keeps the names (`person_bucket_counts`, `person_weekday_bucket_counts`).
- The calendar colour scale is global across all years (0 = white, then `YlOrRd` per integer count up to the global max). The per-person page uses a different blue scale: 0 = white, then quartiles of that person's own busiest weekday/bucket cell, so each person's legend has different ranges.

## Rendering conventions

- Every day / weekday cell is split into a 2x2 quadrant layout in bucket order (top-left 07-10, top-right 10-13, bottom-left 13-16, bottom-right 16-19, i.e. top row AM, bottom row PM). `quadrant_origins` is the shared helper; keep calendar and per-person charts consistent with it.
- Legends are hand-drawn with `draw_swatch_legend`, not `fig.colorbar`: matplotlib colorbars with `BoundaryNorm` place tick labels on bin edges rather than centred under each colour.
- The per-person page shows a top-10 bar chart plus weekly grids for the top 6. Rankings are per year, not across the whole log.
- Titles, captions and legend text mention "ajp/pex/prof"; update them if the tracked tags change.
