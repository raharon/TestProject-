# TestProject-

## SOLAS FET Course Finder — dropdown scraper

`scrape_dropdowns.py` scrapes the dropdown option lists from the SOLAS FET
Course Finder advanced search filters (Award, Provider, Learning Fields,
Delivery Mode, Programme Category, Location) and exports them to
`dropdowns.csv` and `dropdowns.xlsx`.

The page (<https://www.fetchcourses.ie/hub/home/#/courses/view>) is an Angular
SPA, so the script uses Playwright (headless Chromium): it loads the page,
waits for network idle, clicks the "more search options" toggle to reveal the
advanced filters, then reads every `<select>` (and, best-effort, custom
widgets). If the live page is unreachable or the Award list comes back empty,
it falls back to the public SOLAS JSONP web service to recover the Award /
Awarding Body lists.

### Setup

```bash
pip install playwright openpyxl
playwright install chromium
```

### Run

```bash
python3 scrape_dropdowns.py
```

Outputs `dropdowns.csv` and `dropdowns.xlsx` in the project root and prints an
options-per-dropdown summary. The two output files are git-ignored because they
are runtime artifacts.

### Offline self-test

`selftest_export.py` verifies the JSONP-stripping and CSV/XLSX export pipeline
without needing network access:

```bash
python3 selftest_export.py
```

> **Note on Claude Code web sessions:** this environment's network allowlist
> blocks `fetchcourses.ie`, so the live scrape must be run somewhere with
> outbound access to that host (e.g. locally, or in an environment whose policy
> allowlists `fetchcourses.ie` and `service.fetchcourses.ie`).
