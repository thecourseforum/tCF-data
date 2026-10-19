"""Fetch one term into data/<year>_<season>.csv.

Class search supplies sections, one page at a time. Known attribute codes map
to Disciplines and Cost; ClassDetails is used only for an unknown code.
Pass --descriptions to fill catalog text. Without that flag, stored descriptions are kept.
With no argument, the term comes from today's date.
"""

import csv
import io
import os
import sys
import tempfile
from datetime import date

import certifi
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TIMEOUT = 30
MAX_RETRIES = 5
SIS_BASE = (
    "https://sisuva.admin.virginia.edu/psc/ihprd/UVSS/SA/s/"
    "WEBLIB_HCX_CM.H_CLASS_SEARCH.FieldFormula."
)
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
ATTRIBUTE_MAPPING = {  # Verified SIS labels. Unknown codes stay blank in this step.
    "ASUD-AIP": "Artistic, Interpretive, & Philosophical Inquiry",
    "ASUD-CMP": "Chemical, Mathematical, and Physical Universe",
    "ASUD-CSW": "Cultures & Societies of the World",
    "ASUD-HP": "Historical Perspectives",
    "ASUD-LS": "Living Systems",
    "ASUD-QCD": "Quantification, Computation & Data Analysis",
    "ASUD-SS": "Science & Society",
    "ASUD-SES": "Social & Economic Systems",
    "ASUD-WL": "World Languages",
    "ASUW-WL": "World Languages",
    "ASUQ-QCD": "Quantification, Computation & Data Analysis",
    "ASUR-R21C1": "First Writing",
    "ASUR-R21C2": "Second Writing",
    "NCLC-NOCOST": "No Cost Course Materials",
    "NCLC-LOWCOST": "Low Cost Course Materials",
}
IGNORED_ATTRIBUTES = {
    "CORE-CRITTHINK",
    "CORE-ORALCOMM",
    "CORE-WRITTEN",
    "CORE-RESEARCH",
    "CORE-SCIENTIFIC",
    "CORE-QUANTITAT",
    "CORE-ABROAD",
    "ASUM-POST1800",
    "ASUM-PRE1800",
    "LAW-1LCORE",
    "LAW-1LCORESEM",
    "LAW-303C",
    "LAW-PROFETHIC",
    "LAW-PROFSKILL",
    "LAW-ULWR",
}


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


def labels_from_codes(raw):
    """Mapped labels, or None when a code is not in the local list."""
    codes = [code.strip() for code in str(raw or "").split(",") if code.strip()]
    if any(code not in ATTRIBUTE_MAPPING and code not in IGNORED_ATTRIBUTES for code in codes):
        return None
    return [ATTRIBUTE_MAPPING[code] for code in codes if code not in IGNORED_ATTRIBUTES]


def discipline_and_cost(labels):
    labels = [label.strip() for label in labels if label and str(label).strip()]
    disciplines = "$".join(label for label in labels if "cost" not in label.lower())
    cost = next((label for label in reversed(labels) if "cost" in label.lower()), "")
    return disciplines, cost


def class_row(course):
    """One loader CSV row. Known attribute codes fill Disciplines and Cost."""
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
    row["Description"] = course.get("_description") or ""
    labels = course.get("_labels")
    if labels is None:
        labels = labels_from_codes(course.get("crse_attr_value")) or []
    row["Disciplines"], row["Cost"] = discipline_and_cost(labels)
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


# Description is not in class search. A blank discipline or cost must not wipe a stored value.
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
    import unittest

    suite = unittest.defaultTestLoader.loadTestsFromName("test_fetch_page")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def validate_first(payload):
    total = int(payload["pageCount"])
    classes = payload.get("classes") or []
    if total < 0 or bool(classes) != bool(total):
        raise SystemExit("SIS page count does not match its first page.")
    return total


def take_page(payload, page, total_pages, seen):
    """Section records from one page. Reject an empty or repeated page."""
    records = {str(course["class_nbr"]): course for course in payload["classes"]}
    if not records.keys() - seen:
        raise SystemExit(f"Empty or repeated SIS page {page}/{total_pages}.")
    seen.update(records)
    return list(records.values())


def ca_bundle():
    """Current certifi roots plus the emSign roots UVA SIS still chains through.

    certifi 2026.10.18 dropped those roots. Without them the runner reports
    a self-signed certificate in the SIS chain.
    """
    extra = os.path.join(os.path.dirname(__file__), "emsign-roots.pem")
    folder = os.path.join(tempfile.gettempdir(), "tcf-data")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "cas.pem")
    with open(certifi.where(), "rb") as base, open(extra, "rb") as more, open(path, "wb") as out:
        out.write(base.read())
        out.write(b"\n")
        out.write(more.read())
    return path


def create_session():
    """Pooled session. urllib3 retries status 429 and 5xx up to five times."""
    session = requests.Session()
    session.verify = ca_bundle()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
    )
    workers = min(32, (os.cpu_count() or 1) + 4)
    adapter = HTTPAdapter(pool_connections=workers, pool_maxsize=workers, max_retries=retry)
    session.mount("https://", adapter)
    return session


def request_sis_json(session, endpoint, **params):
    try:
        response = session.get(
            SIS_BASE + endpoint,
            params={"institution": "UVA01", **params},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as error:
        raise SystemExit(f"SIS request failed: {error}") from error
    except ValueError as error:
        raise SystemExit("SIS returned non-JSON data (possibly a login page).") from error
    if not isinstance(payload, dict):
        raise SystemExit("SIS returned non-JSON data (possibly a login page).")
    return payload


def labels_from_details(data):
    text = data["section_info"]["enrollment_information"]["class_attributes"] or ""
    return [line.strip() for line in str(text).splitlines() if line.strip()]


def fill_attributes(courses, session, term):
    """Unknown attribute codes, one ClassDetails call at a time on the search session."""
    pending = []
    for course in courses:
        labels = labels_from_codes(course.get("crse_attr_value"))
        if labels is None:
            pending.append(course)
        else:
            course["_labels"] = labels
    for course in pending:
        data = request_sis_json(
            session,
            "IScript_ClassDetails",
            term=term,
            class_nbr=course["class_nbr"],
        )
        course["_labels"] = labels_from_details(data)


def catalog_description(session, term, class_number):
    data = request_sis_json(
        session,
        "IScript_ClassDetails",
        term=term,
        class_nbr=class_number,
    )
    section_info = data.get("section_info") or {}
    catalog_descr = section_info.get("catalog_descr") or {}
    text = catalog_descr.get("crse_catalog_description")
    if not text or not str(text).strip():
        return ""
    return str(text).replace("\n", "").replace("\r", " ")


def assign_descriptions(classes, filled):
    """Copy non-empty description text onto each section. Blank text is ignored."""
    for course in classes:
        text = filled.get((course.get("subject") or "", str(course.get("catalog_nbr") or "")))
        if text:
            course["_description"] = text


def fill_descriptions(classes, session, term):
    """SIS catalog text for every course. A blank result does not replace stored text."""
    unique = {}
    for course in classes:
        key = (course.get("subject") or "", str(course.get("catalog_nbr") or ""))
        unique.setdefault(key, course)
    print(f"descriptions start ({len(unique)} SIS)", flush=True)
    filled = {}
    for key, course in unique.items():
        text = catalog_description(session, term, course["class_nbr"])
        if text:
            filled[key] = text
    assign_descriptions(classes, filled)
    print(f"descriptions done ({len(filled)} updated)", flush=True)


def _page_payload(session, term, page):
    payload = request_sis_json(session, "IScript_ClassSearch", term=term, page=page)
    if "pageCount" not in payload or "classes" not in payload:
        raise SystemExit(f"page {page} failed: SIS page is missing classes.")
    return payload


def fetch_pages(term):
    """Every class-search page for one term, one page at a time on one session."""
    session = create_session()
    first = _page_payload(session, term, 1)
    total_pages = validate_first(first)
    seen = set()
    classes = take_page(first, 1, total_pages, seen) if total_pages else []
    for page in range(2, total_pages + 1):
        classes.extend(take_page(_page_payload(session, term, page), page, total_pages, seen))
    return classes, total_pages, session


def main(argv):
    if argv[1:] == ["--check"]:
        _check()
        return
    descriptions = False
    term = None
    for arg in argv[1:]:
        if arg == "--descriptions":
            descriptions = True
        elif arg.isdigit() and term is None:
            term = arg
        else:
            raise SystemExit("usage: python fetch_page.py [--descriptions] [sis-term]")
    if term is None:
        term = term_for_date()
    classes, page_count, session = fetch_pages(term)
    if not classes:
        raise SystemExit("SIS returned no sections; existing file was kept.")
    fill_attributes(classes, session, term)
    if descriptions:
        fill_descriptions(classes, session, term)
    # Write only after every request succeeds, so a failed run cannot replace the file.
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
