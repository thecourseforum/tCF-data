# tCF-data

This repository stores UVA course listings for theCourseForum. It calls SIS. The website does not.

`fetch_page.py` requests every class-search page for one term and writes `data/<year>_<season>.csv`. The term is the SIS code: `1`, the two-digit year, then a season digit (`8` fall, `6` summer, `2` spring, `1` january). Fall 2026 is `1268`, and that file is `data/2026_fall.csv`.

```bash
python fetch_page.py
python fetch_page.py 1268
```

With no argument, the term is whichever semester has started by today's date. Fall, January, and spring starts through Spring 2030 come from the [registrar academic calendar](https://registrar.virginia.edu/calendar/academic). Summers after 2027, and every season after Spring 2030, use January 2, January 15, May 18, and August 25. Pass a term to fetch a different one.

The file uses the same columns as `load_semester` (mnemonic, number, instructors, meeting times, enrollment, description, disciplines, cost). The script writes the file only after every request succeeds.

## Thomas's fetcher

The extra fields come from the faster course fetcher in [theCourseForum2#1306](https://github.com/thecourseforum/theCourseForum2/pull/1306). `fetch_page.py` uses that retrieval and still writes `data/<year>_<season>.csv`.

Class search supplies every section. Known attribute codes map to Disciplines and Cost here. ClassDetails runs only for an unknown code. Descriptions are fetched once per course: HoosList for the current or a future term, SIS catalog text for older terms, and SIS again if HoosList fails or returns non-text. An empty SIS description stays blank. Requests use a pooled session and retry up to five times. An empty, repeated, or inconsistent page stops the run.

The registrar term dates stay as they were, including January. Meeting times stay `TuTh 12:30pm - 1:45pm`, which `load_semester` parses. Later class-search pages are still fetched in parallel. A blank description, discipline, or cost leaves the previous value in the file.

## GitHub Action

**Update course data** runs on the schedule in `.github/workflows/update-data.yml`, and when someone starts it from the Actions tab. The cron line runs once a day at 07:30 UTC. Edit that line to change the time. A scheduled run fetches the term for today's date. A manual run can pass a different term. The job commits `data/<year>_<season>.csv` only if the file changed.

The job runs on GitHub's `ubuntu-latest` machine. That machine exists only for the run: it checks out this repository, installs `requests` (the machine starts without it), runs `fetch_page.py`, and pushes the CSV when the file changed. The next day's run is a new machine, so the install happens again.

Any computer that can run `python fetch_page.py` on a schedule and push `data/` can take that job. An AWS schedule, such as EventBridge starting a Lambda or a small ECS task, would do the same work. The website still only downloads the CSV.

## What the website does with this file

`fetch_data` in theCourseForum2 downloads `data/<year>_<season>.csv` from this repository. It does not call SIS. `load_semester` can import that CSV, including the description, discipline, and cost columns.
