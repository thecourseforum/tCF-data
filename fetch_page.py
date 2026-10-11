"""Fetch every class-search page for one term into data/<year>_<season>.csv.

This is the listing SIS returns for the term, not the per-class detail page.
With no argument, the term comes from today's date.
"""

import copy
import csv
import http.cookiejar
import io
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date

# Lower this if SIS starts timing out.
PAGE_WORKERS = 4

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


_SEASON_NAMES = {"1": "january", "2": "spring", "6": "summer", "8": "fall"}
COLUMNS = [
    "ClassNumber",
    "Mnemonic",
    "Number",
    "Section",
    "Type",
    "Units",
    "Instructor1",
    "Days1",
    "Room1",
    "MeetingDates1",
    "Instructor2",
    "Days2",
    "Room2",
    "MeetingDates2",
    "Instructor3",
    "Days3",
    "Room3",
    "MeetingDates3",
    "Instructor4",
    "Days4",
    "Room4",
    "MeetingDates4",
    "Title",
    "Topic",
    "Status",
    "Enrollment",
    "EnrollmentLimit",
    "Waitlist",
    "WaitlistLimit",
    "Description",
    "Disciplines",
    "Cost",
]


def semester_for_term(term):
    """``<year>_<season>`` for a SIS term. 1268 is 2026_fall."""
    digits = str(term)
    season = _SEASON_NAMES.get(digits[3:] if len(digits) == 4 else "")
    if season is None or not digits[1:3].isdigit():
        raise SystemExit(f"not a SIS term: {term}")
    return f"{2000 + int(digits[1:3])}_{season}"


def clock(raw):
    """SIS ``13.45.00.000000`` to ``1:45pm``. Empty when the time is missing."""
    parts = str(raw or "").split(".")
    if len(parts) < 2:
        return ""
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return ""
    suffix = "am" if hour < 12 else "pm"
    hour12 = hour % 12 or 12
    return f"{hour12}:{minute:02d}{suffix}"


def meeting_days(meeting):
    """``TuTh 12:30pm - 1:45pm``, the shape load_semester parses."""
    days = (meeting.get("days") or "").strip()
    if days in {"", "-"}:
        return ""
    start = clock(meeting.get("start_time"))
    end = clock(meeting.get("end_time"))
    if not start or not end:
        return days
    return f"{days} {start} - {end}"


def meeting_dates(meeting):
    start = (meeting.get("start_dt") or "").strip()
    end = (meeting.get("end_dt") or "").strip()
    if start and end:
        return f"{start} - {end}"
    return start or end


def class_row(course):
    """One loader CSV row. Description, Disciplines, and Cost are not in this listing."""
    row = {column: "" for column in COLUMNS}
    row["ClassNumber"] = course.get("class_nbr", "")
    row["Mnemonic"] = course.get("subject", "")
    row["Number"] = course.get("catalog_nbr", "")
    row["Section"] = course.get("class_section", "")
    row["Type"] = course.get("section_type", "")
    row["Units"] = course.get("units", "")
    row["Title"] = course.get("descr", "")
    row["Topic"] = course.get("topic", "")
    row["Status"] = course.get("enrl_stat_descr", "")
    row["Enrollment"] = course.get("enrollment_total", "")
    row["EnrollmentLimit"] = course.get("class_capacity", "")
    row["Waitlist"] = course.get("wait_tot", "")
    row["WaitlistLimit"] = course.get("wait_cap", "")
    instructors = course.get("instructors") or []
    meetings = course.get("meetings") or []
    for index in range(4):
        slot = index + 1
        if index < len(instructors):
            row[f"Instructor{slot}"] = instructors[index].get("name") or ""
        if index < len(meetings):
            row[f"Days{slot}"] = meeting_days(meetings[index])
            row[f"Room{slot}"] = meetings[index].get("room") or ""
            row[f"MeetingDates{slot}"] = meeting_dates(meetings[index])
    return row


# SIS class search does not return these. A later fill-in must survive the next fetch.
_KEEP_IF_BLANK = ("Description", "Disciplines", "Cost")


def _csv_line(row):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writerow({column: "" if row.get(column) is None else row[column] for column in COLUMNS})
    return buffer.getvalue()


def _record_spans(text):
    """Byte spans of each CSV record, including its newline. Quotes can hold commas."""
    spans = []
    start = 0
    in_quotes = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"':
            if in_quotes and index + 1 < len(text) and text[index + 1] == '"':
                index += 2
                continue
            in_quotes = not in_quotes
        elif char == "\n" and not in_quotes:
            spans.append((start, index + 1))
            start = index + 1
        index += 1
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _lines_by_class(text):
    """ClassNumber to the exact line already stored, so an unchanged row is not rewritten."""
    lines = {}
    for start, end in _record_spans(text):
        record = text[start:end]
        parsed = next(csv.reader(io.StringIO(record, newline="")))
        if not parsed or parsed[0] == "ClassNumber":
            continue
        lines[parsed[0]] = record if record.endswith("\n") else record + "\n"
    return lines


def render_snapshot(classes, previous_text):
    """CSV text for one term. Unchanged class lines are copied from previous_text."""
    previous_rows = {}
    previous_lines = {}
    if previous_text:
        previous_lines = _lines_by_class(previous_text)
        previous_rows = {
            row["ClassNumber"]: row
            for row in csv.DictReader(io.StringIO(previous_text, newline=""))
        }
    parts = [",".join(COLUMNS) + "\n"]
    ordered = sorted(classes, key=lambda course: course.get("class_nbr") or 0)
    for course in ordered:
        row = class_row(course)
        key = str(row["ClassNumber"])
        old = previous_rows.get(key)
        if old:
            for column in _KEEP_IF_BLANK:
                if row[column] in ("", None) and old.get(column):
                    row[column] = old[column]
        line = _csv_line(row)
        parts.append(previous_lines[key] if previous_lines.get(key) == line else line)
    return "".join(parts)


def changed_class_count(previous_text, text):
    old = _lines_by_class(previous_text) if previous_text else {}
    new = _lines_by_class(text)
    keys = set(old) | set(new)
    return sum(1 for key in keys if old.get(key) != new.get(key))


def write_csv(term, classes):
    """Update data/<year>_<season>.csv. Skip the write when every class line matches."""
    semester = semester_for_term(term)
    os.makedirs("data", exist_ok=True)
    path = f"data/{semester}.csv"
    previous = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8", newline="") as handle:
            previous = handle.read()
    text = render_snapshot(classes, previous)
    changed = changed_class_count(previous, text)
    if text != previous:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
    return path, semester, changed


def _check():
    assert term_for_date(date(2026, 1, 2)) == "1261"
    assert term_for_date(date(2026, 1, 12)) == "1262"
    assert term_for_date(date(2026, 5, 18)) == "1266"
    assert term_for_date(date(2026, 8, 25)) == "1268"
    assert term_for_date(date(2026, 10, 3)) == "1268"
    assert term_for_date(date(2028, 1, 10)) == "1281"
    assert term_for_date(date(2028, 6, 1)) == "1286"
    assert semester_for_term("1268") == "2026_fall"
    course = {
        "class_nbr": 10467,
        "subject": "AAS",
        "catalog_nbr": "1010",
        "class_section": "100",
        "section_type": "Lecture",
        "units": "4",
        "descr": "Introduction to African-American and African Studies I",
        "topic": "",
        "enrl_stat_descr": "Open",
        "enrollment_total": 157,
        "class_capacity": 180,
        "wait_tot": 1,
        "wait_cap": 199,
        "instructors": [{"name": "Kevin Gaines"}],
        "meetings": [
            {
                "days": "TuTh",
                "start_time": "12.30.00.000000",
                "end_time": "13.45.00.000000",
                "room": "***",
                "start_dt": "08/25/2026",
                "end_dt": "12/08/2026",
            }
        ],
    }
    row = class_row(course)
    assert row["Days1"] == "TuTh 12:30pm - 1:45pm"
    assert row["MeetingDates1"] == "08/25/2026 - 12/08/2026"
    assert row["Description"] == ""
    assert row["Disciplines"] == ""
    assert row["Cost"] == ""
    other = dict(course, class_nbr=10468, class_section="101", enrollment_total=10)
    stored = render_snapshot([course, other], "")
    assert render_snapshot([course, other], stored) == stored
    enriched = stored.replace(",,,\n", ",Kept description,Kept discipline,\n", 1)
    bumped = dict(course, enrollment_total=158)
    kept = render_snapshot([bumped, other], enriched)
    assert "Kept description" in _lines_by_class(kept)["10467"]
    assert _lines_by_class(kept)["10468"] == _lines_by_class(stored)["10468"]
    assert changed_class_count(stored, kept) == 1
    assert PAGE_WORKERS > 1
    gathered = gather_pages(lambda page: {"classes": [{"class_nbr": page}]}, 5, PAGE_WORKERS)
    assert [row["class_nbr"] for row in gathered] == [2, 3, 4, 5]
    print("ok")


def gather_pages(fetch_one, page_count, workers):
    """Classes from pages 2 through page_count, in page order."""
    if page_count < 2:
        return []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        payloads = pool.map(fetch_one, range(2, page_count + 1))
        classes = []
        for payload in payloads:
            classes.extend(payload.get("classes") or [])
    return classes


def _opener_with_cookies(cookie_jar):
    copied = http.cookiejar.CookieJar()
    for cookie in cookie_jar:
        copied.set_cookie(copy.copy(cookie))
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(copied))


def fetch_pages(term):
    """Every class-search page for one term. SIS sets a session cookie on a redirect."""
    search = (
        "https://sisuva.admin.virginia.edu/psc/ihprd/UVSS/SA/s/"
        "WEBLIB_HCX_CM.H_CLASS_SEARCH.FieldFormula.IScript_ClassSearch"
        f"?institution=UVA01&term={term}&page="
    )
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

    def fetch_with(page_opener, page):
        last_error = None
        for _ in range(3):
            try:
                with page_opener.open(search + str(page), timeout=60) as response:
                    return json.load(response)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                last_error = error
                time.sleep(2)
        raise SystemExit(f"page {page} failed: {last_error}")

    first = fetch_with(opener, 1)
    page_count = int(first["pageCount"])
    classes = list(first.get("classes") or [])
    local = threading.local()

    def fetch_later(page):
        page_opener = getattr(local, "opener", None)
        if page_opener is None:
            page_opener = _opener_with_cookies(cookie_jar)
            local.opener = page_opener
        return fetch_with(page_opener, page)

    classes.extend(gather_pages(fetch_later, page_count, PAGE_WORKERS))
    return classes, page_count


def main(argv):
    if len(argv) == 2 and argv[1] == "--check":
        _check()
        return
    if len(argv) == 1:
        term = term_for_date()
    elif len(argv) == 2 and argv[1].isdigit():
        term = argv[1]
    else:
        raise SystemExit("usage: python fetch_page.py [sis-term]")
    classes, page_count = fetch_pages(term)
    # Write only after every page succeeds, so a failed run cannot replace the file.
    path, semester, changed = write_csv(term, classes)
    if changed:
        print(f"updated {changed} classes in {path} ({len(classes)} classes, {page_count} pages)")
    else:
        print(f"{path} already matches ({len(classes)} classes, {page_count} pages)")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"term={term}\nsemester={semester}\n")


if __name__ == "__main__":
    main(sys.argv)
