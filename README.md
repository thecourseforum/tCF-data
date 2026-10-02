# tCF-data

This repository stores UVA course listings for theCourseForum. It calls SIS. The website does not.

`fetch_page.py` requests every class-search page for one term and writes `data/<term>.json`. The term is the SIS code: `1`, the two-digit year, then a season digit (`8` fall, `6` summer, `2` spring, `1` january). Fall 2026 is `1268`.

```bash
python fetch_page.py 1268
```

The file is the class-search listing (subject, number, title, instructors, meetings, enrollment). It is not the separate per-class description page. The script writes the file only after every page succeeds.

## GitHub Action

**Update course data** runs on the schedule in `.github/workflows/update-data.yml`, and when someone starts it from the Actions tab. The cron line runs once a day at 07:30 UTC. Edit that line to change the time. A scheduled run uses term `1268` until that default is edited. The job commits `data/<term>.json` only if the file changed.

## What the website does with this file

A developer runs `python manage.py fetch_data <year>_<season>` in theCourseForum2. That command downloads `data/<term>.json` from this repository. It does not call SIS, and it does not load the JSON into the website database.
