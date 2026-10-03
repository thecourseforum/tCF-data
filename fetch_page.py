"""Fetch every class-search page for one term into data/<term>.json.

This is the listing SIS returns for the term, not the per-class detail page.
With no argument, the term comes from today's date.
"""

import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date

# First day of courses, from https://registrar.virginia.edu/calendar/academic
# through Spring 2030. Keep this tuple identical to current_semester in
# theCourseForum2 tcf_website/utils.py. Summer 2026 and 2027 are the first
# Summer Session class day; those registrar pages do not list one.
_SEMESTER_STARTS = (
    (date(2025, 8, 26), "2025_fall"),
    (date(2026, 1, 2), "2026_january"),
    (date(2026, 1, 12), "2026_spring"),
    (date(2026, 5, 18), "2026_summer"),
    (date(2026, 8, 25), "2026_fall"),
    (date(2027, 1, 4), "2027_january"),
    (date(2027, 1, 20), "2027_spring"),
    (date(2027, 5, 17), "2027_summer"),
    (date(2027, 8, 24), "2027_fall"),
    (date(2028, 1, 3), "2028_january"),
    (date(2028, 1, 19), "2028_spring"),
    (date(2028, 8, 22), "2028_fall"),
    (date(2029, 1, 2), "2029_january"),
    (date(2029, 1, 15), "2029_spring"),
    (date(2029, 8, 21), "2029_fall"),
    (date(2030, 1, 2), "2030_january"),
    (date(2030, 1, 14), "2030_spring"),
)
_PUBLISHED_SEMESTERS = {name for _, name in _SEMESTER_STARTS}
_SEASON_ORDER = {"january": 1, "spring": 2, "summer": 3, "fall": 4}
_SEASON_DIGITS = {"january": "1", "spring": "2", "summer": "6", "fall": "8"}


def _semester_key(name):
    year, _, season = name.partition("_")
    return int(year), _SEASON_ORDER[season]


def _general_semester(today):
    """Seasons with no published start. January 2, January 15, May 18, August 25."""
    if today.month == 1 and today.day == 1:
        return f"{today.year - 1}_fall"
    if today.month == 1 and today.day < 15:
        return f"{today.year}_january"
    if today.month < 5 or (today.month == 5 and today.day < 18):
        return f"{today.year}_spring"
    if today.month < 8 or (today.month == 8 and today.day < 25):
        return f"{today.year}_summer"
    return f"{today.year}_fall"


def semester_for_date(today=None):
    """``<year>_<season>`` for a calendar date."""
    today = date.today() if today is None else today
    chosen = None
    for start, name in _SEMESTER_STARTS:
        if today < start:
            break
        chosen = name
    general = _general_semester(today)
    if chosen is None or (
        general not in _PUBLISHED_SEMESTERS and _semester_key(general) > _semester_key(chosen)
    ):
        return general
    return chosen


def term_for_date(today=None):
    """SIS term for a calendar date."""
    year, _, season = semester_for_date(today).partition("_")
    return f"1{int(year) % 100:02d}{_SEASON_DIGITS[season]}"


def _check():
    assert term_for_date(date(2026, 1, 2)) == "1261"
    assert term_for_date(date(2026, 1, 12)) == "1262"
    assert term_for_date(date(2026, 5, 18)) == "1266"
    assert term_for_date(date(2026, 8, 25)) == "1268"
    assert term_for_date(date(2026, 10, 3)) == "1268"
    assert term_for_date(date(2028, 1, 10)) == "1281"
    assert term_for_date(date(2028, 6, 1)) == "1286"
    print("ok")


if len(sys.argv) == 2 and sys.argv[1] == "--check":
    _check()
    raise SystemExit(0)
if len(sys.argv) == 1:
    TERM = term_for_date()
elif len(sys.argv) == 2 and sys.argv[1].isdigit():
    TERM = sys.argv[1]
else:
    raise SystemExit("usage: python fetch_page.py [sis-term]")
SEARCH = (
    "https://sisuva.admin.virginia.edu/psc/ihprd/UVSS/SA/s/"
    "WEBLIB_HCX_CM.H_CLASS_SEARCH.FieldFormula.IScript_ClassSearch"
    f"?institution=UVA01&term={TERM}&page="
)

# SIS sets a session cookie on a redirect. Without it the next hop is a 403.
cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))


def fetch_page(page):
    last_error = None
    for _ in range(3):
        try:
            with opener.open(SEARCH + str(page), timeout=60) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            time.sleep(2)
    raise SystemExit(f"page {page} failed: {last_error}")


first = fetch_page(1)
page_count = int(first["pageCount"])
classes = list(first.get("classes") or [])
for page in range(2, page_count + 1):
    payload = fetch_page(page)
    classes.extend(payload.get("classes") or [])

# Write only after every page succeeds, so a failed run cannot replace the file.
out = {"term": TERM, "pageCount": page_count, "classes": classes}
path = f"data/{TERM}.json"
os.makedirs("data", exist_ok=True)
with open(path, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(out, handle, indent=2, sort_keys=True)
    handle.write("\n")
print(f"wrote {path} ({len(classes)} classes, {page_count} pages)")
output = os.environ.get("GITHUB_OUTPUT")
if output:
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(f"term={TERM}\n")
