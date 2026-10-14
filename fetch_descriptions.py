"""Fill Description in data/<year>_<season>.csv. Does not download the class listing.

Reuses a description already stored for that mnemonic and number. SIS ClassDetails
runs only for a course that is still blank, one course at a time. Pass --all to
refetch every course. With no term, the term comes from today's date.
"""

import csv
import io
import os
import sys

from fetch_page import (
    COLUMNS,
    _SEASON_ORDER,
    _csv_line,
    _lines_by_class,
    create_session,
    request_sis_json,
    semester_for_term,
    term_for_date,
)


def _semester_rank(semester):
    year, _, season = semester.partition("_")
    if not year.isdigit() or season not in _SEASON_ORDER:
        return None
    return int(year), _SEASON_ORDER[season]


def description_plan(rows, older_maps, refresh_all):
    """Stored text to apply, and one row per course that still needs SIS."""
    current = {}
    older = {}
    if not refresh_all:
        for row in rows:
            text = (row.get("Description") or "").strip()
            if text:
                current.setdefault((row["Mnemonic"], row["Number"]), text)
        for mapping in older_maps:
            for key, text in mapping.items():
                older.setdefault(key, text)
    filled = {}
    pending = {}
    seen = set()
    for row in rows:
        key = (row["Mnemonic"], row["Number"])
        if key in seen:
            continue
        seen.add(key)
        if key in current:
            filled[key] = current[key]
        elif key in older:
            filled[key] = older[key]
        else:
            pending[key] = row
    return filled, pending


def older_description_maps(semester, data_dir="data"):
    """Non-empty descriptions from earlier semester files, newest first."""
    current = _semester_rank(semester)
    ranked = []
    if current is None or not os.path.isdir(data_dir):
        return []
    for name in os.listdir(data_dir):
        if not name.endswith(".csv"):
            continue
        other = name[:-4]
        rank = _semester_rank(other)
        if rank is None or other == semester or rank >= current:
            continue
        ranked.append((rank, os.path.join(data_dir, name)))
    ranked.sort(reverse=True)
    maps = []
    for _, path in ranked:
        with open(path, encoding="utf-8", newline="") as handle:
            mapping = {}
            for row in csv.DictReader(handle):
                text = (row.get("Description") or "").strip()
                if text:
                    mapping.setdefault((row["Mnemonic"], row["Number"]), text)
            maps.append(mapping)
    return maps


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


def render_descriptions(previous_text, filled):
    """CSV text with Description updated. Unchanged class lines are copied."""
    rows = list(csv.DictReader(io.StringIO(previous_text, newline="")))
    lines = _lines_by_class(previous_text)
    parts = [",".join(COLUMNS) + "\n"]
    for row in rows:
        key = (row["Mnemonic"], row["Number"])
        # A missing or empty fetch must not wipe a description already in the file.
        if filled.get(key):
            row["Description"] = filled[key]
        line = _csv_line(row)
        class_number = str(row["ClassNumber"])
        parts.append(lines[class_number] if lines.get(class_number) == line else line)
    return "".join(parts)


def _check():
    rows = [
        {"Mnemonic": "AAS", "Number": "1010", "ClassNumber": "1", "Description": "Kept"},
        {"Mnemonic": "AAS", "Number": "1010", "ClassNumber": "2", "Description": "Kept"},
        {"Mnemonic": "CS", "Number": "2100", "ClassNumber": "3", "Description": ""},
        {"Mnemonic": "CS", "Number": "1110", "ClassNumber": "9", "Description": ""},
    ]
    older = [{("CS", "2100"): "From spring", ("AAS", "1010"): "Older text"}]
    filled, pending = description_plan(rows, older, False)
    assert ("AAS", "1010") not in pending
    assert filled[("AAS", "1010")] == "Kept"
    assert ("CS", "2100") not in pending
    assert filled[("CS", "2100")] == "From spring"
    assert list(pending) == [("CS", "1110")]
    filled, pending = description_plan(rows, older, True)
    assert ("AAS", "1010") not in filled
    assert set(pending) == {("AAS", "1010"), ("CS", "2100"), ("CS", "1110")}
    blank = {column: "" for column in COLUMNS}
    blank.update({"ClassNumber": "1", "Mnemonic": "AAS", "Number": "1010", "Enrollment": "10"})
    previous = ",".join(COLUMNS) + "\n" + _csv_line(blank)
    same = render_descriptions(previous, {("AAS", "1010"): ""})
    assert same == previous
    kept = dict(blank, Description="Kept")
    stored = ",".join(COLUMNS) + "\n" + _csv_line(kept)
    assert render_descriptions(stored, {("AAS", "1010"): ""}) == stored
    assert "Kept" in render_descriptions(stored, {})
    updated = render_descriptions(previous, {("AAS", "1010"): "A catalog description"})
    assert "A catalog description" in updated
    assert "10" in updated
    print("ok")


def main(argv):
    args = argv[1:]
    if args == ["--check"]:
        _check()
        return
    refresh_all = False
    if "--all" in args:
        refresh_all = True
        args.remove("--all")
    if len(args) == 0:
        term = term_for_date()
    elif len(args) == 1 and args[0].isdigit():
        term = args[0]
    else:
        raise SystemExit("usage: python fetch_descriptions.py [--all] [sis-term]")
    semester = semester_for_term(term)
    path = f"data/{semester}.csv"
    if not os.path.isfile(path):
        raise SystemExit(f"{path} is missing; run fetch_page.py first.")
    with open(path, encoding="utf-8", newline="") as handle:
        previous = handle.read()
    rows = list(csv.DictReader(io.StringIO(previous, newline="")))
    older = [] if refresh_all else older_description_maps(semester)
    filled, pending = description_plan(rows, older, refresh_all)
    print(f"descriptions start ({len(pending)} SIS)", flush=True)
    if pending:
        session = create_session()
        for row in pending.values():
            text = catalog_description(session, term, row["ClassNumber"])
            if text:
                filled[(row["Mnemonic"], row["Number"])] = text
    text = render_descriptions(previous, filled)
    if text != previous:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
    print(f"descriptions done ({len(pending)} SIS)", flush=True)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"term={term}\nsemester={semester}\n")


if __name__ == "__main__":
    main(sys.argv)
