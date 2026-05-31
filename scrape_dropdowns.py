#!/usr/bin/env python3
"""
Scrape the dropdown option lists from the SOLAS FET Course Finder and export
them to dropdowns.csv and dropdowns.xlsx.

Target page (Angular SPA):
    https://www.fetchcourses.ie/hub/home/#/courses/view

The advanced filters (Provider, Award, Learning Fields, Delivery Mode,
Programme Category) are hidden behind a "more search options" toggle that must
be clicked before the <select> elements are present in the DOM.

"Award", "Delivery Mode", "Programme Category" and "Learning Fields" are native
<select> elements. "Location" and "Provider" may be custom widgets, so those are
read on a best-effort basis and never crash the run.

Optional fallback: if Playwright cannot reach the site (or the Award dropdown
comes back empty), the SOLAS JSONP web service is used to recover the Award list:
    http://service.fetchcourses.ie/service/fetchcourse.svc/json/GetAwardingBodyList
    http://service.fetchcourses.ie/service/fetchcourse.svc/json/GetAwardList?AwardingBodyId=<id>

Usage:
    python3 scrape_dropdowns.py
"""

from __future__ import annotations

import csv
import glob
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass

TARGET_URL = "https://www.fetchcourses.ie/hub/home/#/courses/view"
SERVICE_BASE = "http://service.fetchcourses.ie/service/fetchcourse.svc/json"

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dropdowns.csv")
XLSX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dropdowns.xlsx")

# Text that identifies the "show more filters" toggle (case-insensitive).
TOGGLE_PATTERNS = [
    "more search options",
    "show search options",
    "advanced search",
    "advanced filters",
    "more options",
    "show more",
]


@dataclass
class Option:
    dropdown: str
    option_text: str
    option_value: str


# --------------------------------------------------------------------------- #
# Playwright extraction
# --------------------------------------------------------------------------- #
def _discover_chromium_executable() -> str | None:
    """
    Return an explicit chromium executable path if the default Playwright build
    isn't installed but another build exists under PLAYWRIGHT_BROWSERS_PATH.

    On a normal machine `playwright install chromium` puts the matching build in
    place and this returns None (use Playwright's own resolution). In a
    pre-provisioned container the build number may differ, so fall back to any
    chromium build that is present.
    """
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not base or not os.path.isdir(base):
        return None
    candidates = sorted(glob.glob(os.path.join(base, "chromium-*", "chrome-linux", "chrome")))
    return candidates[-1] if candidates else None


def _derive_label(select_handle) -> str:
    """Best-effort human label for a <select> element."""
    label = select_handle.evaluate(
        """
        (el) => {
            // 1. <label for="id">
            if (el.id) {
                const byFor = document.querySelector(`label[for="${el.id}"]`);
                if (byFor && byFor.textContent.trim()) return byFor.textContent.trim();
            }
            // 2. wrapping <label>
            const wrap = el.closest('label');
            if (wrap && wrap.textContent.trim()) return wrap.textContent.trim();
            // 3. aria-label / aria-labelledby
            if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
            const lb = el.getAttribute('aria-labelledby');
            if (lb) {
                const t = document.getElementById(lb);
                if (t && t.textContent.trim()) return t.textContent.trim();
            }
            // 4. label-ish sibling within the form-group
            const group = el.closest('.form-group, .form-row, .field, div');
            if (group) {
                const lab = group.querySelector('label');
                if (lab && lab.textContent.trim()) return lab.textContent.trim();
            }
            // 5. fall back to name / id
            return el.getAttribute('name') || el.id || '';
        }
        """
    )
    label = re.sub(r"\s+", " ", (label or "")).strip()
    return label or "(unlabelled select)"


def _expand_advanced_options(page) -> bool:
    """Click the 'more search options' toggle. Returns True if a toggle was clicked."""
    for pat in TOGGLE_PATTERNS:
        # Case-insensitive text match across clickable elements.
        locator = page.locator(
            f"a:has-text('{pat}'), button:has-text('{pat}'), "
            f"span:has-text('{pat}'), label:has-text('{pat}')"
        )
        try:
            count = locator.count()
        except Exception:
            count = 0
        for i in range(count):
            el = locator.nth(i)
            try:
                if el.is_visible():
                    el.click(timeout=5000)
                    page.wait_for_timeout(800)
                    return True
            except Exception:
                continue
    return False


def extract_with_playwright() -> list[Option]:
    from playwright.sync_api import sync_playwright

    rows: list[Option] = []
    exe = _discover_chromium_executable()
    launch_kwargs = {
        "headless": True,
        "args": ["--no-sandbox", "--ignore-certificate-errors"],
    }
    if exe:
        launch_kwargs["executable_path"] = exe

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        # ignore_https_errors covers TLS-intercepting proxies; harmless otherwise.
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=90_000)
        # SPA: wait for XHR/filters to settle.
        try:
            page.wait_for_load_state("networkidle", timeout=60_000)
        except Exception:
            pass

        clicked = _expand_advanced_options(page)
        print(f"[playwright] advanced-options toggle clicked: {clicked}", file=sys.stderr)

        # Give Angular a moment to render the now-visible selects.
        try:
            page.wait_for_selector("select", timeout=15_000)
        except Exception:
            pass
        page.wait_for_timeout(1000)

        # ---- native <select> elements ----
        selects = page.locator("select")
        n = selects.count()
        print(f"[playwright] found {n} <select> element(s)", file=sys.stderr)
        for i in range(n):
            sel = selects.nth(i)
            try:
                label = _derive_label(sel)
                opts = sel.evaluate(
                    """(el) => Array.from(el.options).map(o => ({
                            text: (o.textContent || '').trim(),
                            value: o.value
                       }))"""
                )
            except Exception as e:  # never crash on one bad widget
                print(f"[playwright] skipped select #{i}: {e}", file=sys.stderr)
                continue
            for o in opts:
                rows.append(Option(label, o["text"], o["value"]))

        # ---- best-effort custom widgets (Location / Provider) ----
        rows.extend(_extract_custom_widgets(page))

        context.close()
        browser.close()

    return rows


def _extract_custom_widgets(page) -> list[Option]:
    """
    Read custom (non-<select>) dropdowns gracefully. These vary a lot between
    component libraries, so anything that can't be read is skipped silently.
    """
    rows: list[Option] = []
    selectors = [
        "[role='listbox'] [role='option']",
        ".dropdown-menu li, .dropdown-menu a[role='option']",
        "ng-select .ng-option",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            cnt = loc.count()
        except Exception:
            continue
        for i in range(cnt):
            try:
                el = loc.nth(i)
                text = (el.inner_text() or "").strip()
                value = el.get_attribute("data-value") or el.get_attribute("value") or ""
                if text:
                    rows.append(Option("(custom widget)", text, value))
            except Exception:
                continue
    return rows


# --------------------------------------------------------------------------- #
# Fallback: SOLAS JSONP web service (Award list)
# --------------------------------------------------------------------------- #
def strip_jsonp(payload: str) -> str:
    """
    Strip a JSONP wrapper such as `callback({...});` and return the inner JSON.
    If there is no wrapper, the payload is returned unchanged.
    """
    s = payload.strip()
    # Remove a leading `identifier(` ... and a trailing `);`
    m = re.match(r"^[\w.$]+\s*\((.*)\)\s*;?\s*$", s, re.DOTALL)
    if m:
        return m.group(1).strip()
    return s


def _http_get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (dropdown-scraper)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def extract_award_from_service() -> list[Option]:
    """Recover Award + Awarding Body lists from the public SOLAS web service."""
    rows: list[Option] = []

    bodies_raw = _http_get(f"{SERVICE_BASE}/GetAwardingBodyList")
    bodies = json.loads(strip_jsonp(bodies_raw))
    if isinstance(bodies, dict):  # some methods wrap in {"d": [...]}
        bodies = bodies.get("d", bodies)

    for body in bodies:
        bid = body.get("Id") or body.get("AwardingBodyId") or body.get("ID")
        bname = body.get("Name") or body.get("Description") or str(bid)
        rows.append(Option("Awarding Body", str(bname), str(bid)))
        if bid is None:
            continue
        try:
            awards_raw = _http_get(f"{SERVICE_BASE}/GetAwardList?AwardingBodyId={bid}")
            awards = json.loads(strip_jsonp(awards_raw))
            if isinstance(awards, dict):
                awards = awards.get("d", awards)
            for aw in awards:
                aid = aw.get("Id") or aw.get("AwardId") or aw.get("ID")
                aname = aw.get("Name") or aw.get("Description") or str(aid)
                rows.append(Option("Award", f"{bname} – {aname}", str(aid)))
        except Exception as e:
            print(f"[service] award list failed for body {bid}: {e}", file=sys.stderr)

    return rows


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
def write_csv(rows: list[Option], path: str = CSV_PATH) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["dropdown", "option_text", "option_value"])
        for r in rows:
            w.writerow([r.dropdown, r.option_text, r.option_value])


def write_xlsx(rows: list[Option], path: str = XLSX_PATH) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "dropdowns"
    headers = ["dropdown", "option_text", "option_value"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
    ws.freeze_panes = "A2"  # frozen header row
    for r in rows:
        ws.append([r.dropdown, r.option_text, r.option_value])
    # Reasonable column widths.
    widths = {"A": 28, "B": 60, "C": 16}
    for col, width in widths.items():
        ws.column_dimensions[col].width = width
    wb.save(path)


def print_summary(rows: list[Option]) -> None:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.dropdown] = counts.get(r.dropdown, 0) + 1
    print("\n=== Options per dropdown ===")
    if not counts:
        print("  (none)")
    for name in sorted(counts):
        print(f"  {name:<32} {counts[name]:>4}")
    print(f"  {'TOTAL':<32} {len(rows):>4}")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    rows: list[Option] = []
    try:
        rows = extract_with_playwright()
    except Exception as e:
        print(f"[main] Playwright extraction failed: {e}", file=sys.stderr)

    have_award = any(r.dropdown.lower() == "award" for r in rows)
    if not rows or not have_award:
        print("[main] Award data missing/empty - trying SOLAS web service fallback...",
              file=sys.stderr)
        try:
            rows.extend(extract_award_from_service())
        except Exception as e:
            print(f"[main] Service fallback failed: {e}", file=sys.stderr)

    write_csv(rows)
    write_xlsx(rows)
    print_summary(rows)
    print(f"\nWrote {CSV_PATH}")
    print(f"Wrote {XLSX_PATH}")

    if not rows:
        print("\nWARNING: no options captured. The page/service may be unreachable "
              "(network allowlist?) or the page layout changed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
