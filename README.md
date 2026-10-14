# tCF-data

This repository stores UVA course listings for theCourseForum. It calls SIS. The website does not.

`fetch_page.py` requests every class-search page for one term and writes `data/<year>_<season>.csv`. The term is the SIS code: `1`, the two-digit year, then a season digit (`8` fall, `6` summer, `2` spring, `1` january). Fall 2026 is `1268`, and that file is `data/2026_fall.csv`.

```bash
python fetch_page.py
python fetch_page.py 1268
```

With no argument, the term is whichever semester has started by today's date. Fall, January, and spring starts through Spring 2030 come from the [registrar academic calendar](https://registrar.virginia.edu/calendar/academic). Summers after 2027, and every season after Spring 2030, use January 2, January 15, May 18, and August 25. Pass a term to fetch a different one.

The file uses the same columns as `load_semester` (mnemonic, number, instructors, meeting times, enrollment, description, disciplines, cost). Known attribute codes fill Disciplines and Cost. An unknown code is read from ClassDetails, one section at a time. The daily run does not fetch descriptions, and a blank description does not replace one already in the file. Pass `--descriptions` to update every course from SIS. A blank result is not written, so the stored description stays. Class-search pages are requested one at a time. The script writes the file only after every request succeeds. A blank description, discipline, or cost leaves the previous value in the file.

## GitHub Action

**Update course data** runs on the schedule in `.github/workflows/update-data.yml`, and when someone starts it from the Actions tab. The cron line runs once a day at 07:30 UTC. Edit that line to change the time. A scheduled run fetches the term for today's date and does not fetch descriptions. A manual run can pass a different term, and can turn on descriptions to refresh every catalog description. A blank result is left unchanged. The job commits `data/<year>_<season>.csv` only if the file changed.

## What the website does with this file

`fetch_data` in theCourseForum2 downloads `data/<year>_<season>.csv` from this repository. It does not call SIS. `load_semester` can import that CSV, including the description, discipline, and cost columns.
