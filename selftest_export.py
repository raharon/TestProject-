#!/usr/bin/env python3
"""
Offline self-test for scrape_dropdowns.py.

Because this container's network allowlist blocks fetchcourses.ie, we cannot do
the live Playwright hop here. This test exercises everything that does NOT need
the live site: JSONP stripping, the export pipeline, and the summary -- proving
the CSV/XLSX writers produce non-empty, well-formed files that read back.
"""
import csv
import json
import os

from openpyxl import load_workbook

import scrape_dropdowns as s

FAILS = []


def check(cond, msg):
    print(("PASS" if cond else "FAIL"), "-", msg)
    if not cond:
        FAILS.append(msg)


# 1. JSONP stripping ---------------------------------------------------------
check(s.strip_jsonp('cb([{"Id":1}]);') == '[{"Id":1}]', "strip simple JSONP wrapper")
check(s.strip_jsonp('jsonpCallback({"d": []})') == '{"d": []}', "strip wrapper, no semicolon")
check(s.strip_jsonp('[{"a":1}]') == '[{"a":1}]', "leave plain JSON untouched")
check(
    json.loads(s.strip_jsonp('angular.callbacks._0([{"Id":7,"Name":"QQI"}]);'))
    == [{"Id": 7, "Name": "QQI"}],
    "stripped JSONP parses as JSON",
)

# 2. Service-shaped data -> Option rows (simulate parser logic) --------------
sample_rows = [
    s.Option("Award", "QQI – Level 5 Certificate", "501"),
    s.Option("Award", "QQI – Level 6 Advanced Cert", "601"),
    s.Option("Awarding Body", "QQI", "7"),
    s.Option("Delivery Mode", "Classroom", "1"),
    s.Option("Delivery Mode", "Online", "2"),
    s.Option("Programme Category", "Apprenticeship", "10"),
    s.Option("Learning Fields", "Engineering", "20"),
    s.Option("(custom widget)", "Dublin", ""),
]

# 3. CSV export --------------------------------------------------------------
csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dropdowns.csv")
xlsx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dropdowns.xlsx")
s.write_csv(sample_rows, csv_path)
check(os.path.getsize(csv_path) > 0, "CSV file is non-empty")
with open(csv_path, newline="", encoding="utf-8") as f:
    read = list(csv.reader(f))
check(read[0] == ["dropdown", "option_text", "option_value"], "CSV header correct")
check(len(read) == len(sample_rows) + 1, "CSV row count matches input")
check(read[1] == ["Award", "QQI – Level 5 Certificate", "501"], "CSV first data row correct")

# 4. XLSX export -------------------------------------------------------------
s.write_xlsx(sample_rows, xlsx_path)
check(os.path.getsize(xlsx_path) > 0, "XLSX file is non-empty")
wb = load_workbook(xlsx_path)
ws = wb.active
check(ws.title == "dropdowns", "XLSX sheet named 'dropdowns'")
check([c.value for c in ws[1]] == ["dropdown", "option_text", "option_value"], "XLSX header correct")
check(ws.freeze_panes == "A2", "XLSX header row frozen (freeze_panes=A2)")
check(ws[1][0].font.bold is True, "XLSX header row bold")
check(ws.max_row == len(sample_rows) + 1, "XLSX row count matches input")

# 5. Summary doesn't crash on empty or populated -----------------------------
s.print_summary([])
s.print_summary(sample_rows)

print()
if FAILS:
    print(f"{len(FAILS)} CHECK(S) FAILED")
    raise SystemExit(1)
print("ALL CHECKS PASSED")
