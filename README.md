# tCF-data

This repository stores UVA course listings for theCourseForum. It calls SIS. The website does not.

`fetch_page.py` requests every class-search page for one term and writes `data/<year>_<season>.csv`. The term is the SIS code: `1`, the two-digit year, then a season digit (`8` fall, `6` summer, `2` spring, `1` january). Fall 2026 is `1268`, and that file is `data/2026_fall.csv`.

```bash
python fetch_page.py
python fetch_page.py 1268
```

With no argument, the term is whichever semester has started by today's date. Fall, January, and spring starts through Spring 2030 come from the [registrar academic calendar](https://registrar.virginia.edu/calendar/academic). Summers after 2027, and every season after Spring 2030, use January 2, January 15, May 18, and August 25. Pass a term to fetch a different one.

The file uses the same columns as `load_semester` (mnemonic, number, instructors, meeting times, enrollment). It is the class-search listing, not the separate per-class description page, so Description, Disciplines, and Cost are blank. The script writes the file only after every page succeeds.

## GitHub Action

**Update course data** runs on the schedule in `.github/workflows/update-data.yml`, and when someone starts it from the Actions tab. The cron line runs once a day at 07:30 UTC. Edit that line to change the time. A scheduled run fetches the term for today's date. A manual run can pass a different term. The job commits `data/<year>_<season>.csv` only if the file changed.

## What the website does with this file

`fetch_data` in theCourseForum2 downloads `data/<year>_<season>.csv` from this repository. It does not call SIS. `load_semester` can import that CSV. Catalog descriptions, discipline names, and course cost stay blank because this listing does not include them.
