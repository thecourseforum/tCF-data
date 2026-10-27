"""Offline checks for the course listing fetcher. No SIS calls."""

import csv
import io
import unittest
from datetime import date
from unittest.mock import patch

import fetch_page


def course(**overrides):
    row = {
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
    row.update(overrides)
    return row


class TermTests(unittest.TestCase):
    def test_registrar_dates_include_january(self):
        self.assertEqual(fetch_page.term_for_date(date(2026, 1, 2)), "1261")
        self.assertEqual(fetch_page.term_for_date(date(2026, 1, 12)), "1262")
        self.assertEqual(fetch_page.term_for_date(date(2026, 5, 18)), "1266")
        self.assertEqual(fetch_page.term_for_date(date(2026, 8, 25)), "1268")
        self.assertEqual(fetch_page.term_for_date(date(2026, 10, 3)), "1268")
        self.assertEqual(fetch_page.term_for_date(date(2028, 1, 10)), "1281")
        self.assertEqual(fetch_page.term_for_date(date(2028, 6, 1)), "1286")
        self.assertEqual(fetch_page.semester_for_term("1268"), "2026_fall")

    def test_bad_term_is_rejected(self):
        with self.assertRaises(SystemExit):
            fetch_page.semester_for_term("nope")


class ListingTests(unittest.TestCase):
    def test_meeting_time_keeps_day_case(self):
        row = fetch_page.class_row(course())
        self.assertEqual(row["Days1"], "TuTh 12:30pm - 1:45pm")
        self.assertEqual(row["MeetingDates1"], "08/25/2026 - 12/08/2026")
        self.assertEqual(row["Instructor1"], "Kevin Gaines")

    def test_known_codes_fill_discipline_and_cost(self):
        row = fetch_page.class_row(course(crse_attr_value="ASUD-HP,NCLC-NOCOST"))
        self.assertEqual(row["Disciplines"], "Historical Perspectives")
        self.assertEqual(row["Cost"], "No Cost Course Materials")

    def test_unknown_code_leaves_discipline_blank(self):
        row = fetch_page.class_row(course(crse_attr_value="ASUD-NOT-A-CODE"))
        self.assertEqual(row["Disciplines"], "")
        self.assertEqual(row["Cost"], "")

    def test_daily_listing_keeps_a_stored_description(self):
        original = course(_description="Kept description", _labels=["Kept discipline"])
        other = course(class_nbr=10468, class_section="101", enrollment_total=10)
        stored = fetch_page.render_snapshot([original, other], "")
        self.assertEqual(fetch_page.render_snapshot([original, other], stored), stored)
        bumped = course(enrollment_total=158)
        kept = fetch_page.render_snapshot([bumped, other], stored)
        lines = fetch_page._lines_by_class(kept)
        self.assertIn("Kept description", lines["10467"])
        self.assertEqual(lines["10468"], fetch_page._lines_by_class(stored)["10468"])
        self.assertEqual(fetch_page.changed_class_count(stored, kept), 1)

    def test_description_with_a_comma_round_trips(self):
        original = course(_description='Hello, "world"')
        stored = fetch_page.render_snapshot([original], "")
        fresh = course(enrollment_total=1)
        kept = fetch_page.render_snapshot([fresh], stored)
        rows = list(csv.DictReader(io.StringIO(kept)))
        self.assertEqual(rows[0]["Description"], 'Hello, "world"')


class DescriptionTests(unittest.TestCase):
    def test_blank_update_is_not_applied(self):
        section = course()
        fetch_page.assign_descriptions([section], {("AAS", "1010"): ""})
        self.assertFalse(section.get("_description"))
        stored = fetch_page.render_snapshot([course(_description="Kept description")], "")
        kept = fetch_page.render_snapshot([section], stored)
        self.assertIn("Kept description", kept)

    def test_nonblank_update_is_applied_to_every_section(self):
        first = course(class_nbr=1)
        second = course(class_nbr=2, class_section="101")
        calls = []

        def fake_catalog(_session, _term, class_number):
            calls.append(class_number)
            return "A catalog description" if class_number == 1 else ""

        with patch("fetch_page.catalog_description", fake_catalog):
            fetch_page.fill_descriptions([first, second], None, "1268")
        self.assertEqual(calls, [1])
        self.assertEqual(first["_description"], "A catalog description")
        self.assertEqual(second["_description"], "A catalog description")

    def test_blank_sis_result_leaves_the_section_unset(self):
        section = course()
        with patch("fetch_page.catalog_description", return_value=""):
            fetch_page.fill_descriptions([section], None, "1268")
        self.assertFalse(section.get("_description"))


class TrustTests(unittest.TestCase):
    def test_bundle_includes_the_emsign_root_uva_uses(self):
        with open(fetch_page.ca_bundle(), encoding="utf-8") as bundle:
            text = bundle.read()
        self.assertIn("emSign Root CA - G1", text)


class PageTests(unittest.TestCase):
    def test_first_page_count_must_match_its_classes(self):
        self.assertEqual(fetch_page.validate_first({"pageCount": 2, "classes": [{"class_nbr": 1}]}), 2)
        with self.assertRaises(SystemExit):
            fetch_page.validate_first({"pageCount": 2, "classes": []})

    def test_repeated_page_stops_the_run(self):
        seen = set()
        first = {"pageCount": 2, "classes": [{"class_nbr": 1}]}
        self.assertEqual(fetch_page.take_page(first, 1, 2, seen)[0]["class_nbr"], 1)
        with self.assertRaises(SystemExit) as caught:
            fetch_page.take_page({"pageCount": 2, "classes": [{"class_nbr": 1}]}, 2, 2, seen)
        self.assertIn("repeated", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
