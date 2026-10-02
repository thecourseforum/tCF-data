# tCF-data

This repository stores UVA course listings for theCourseForum. It calls SIS. The website does not.

`fetch_page.py` requests every class-search page for one term and writes `data/<term>.json`. The term is the SIS code: `1`, the two-digit year, then a season digit (`8` fall, `6` summer, `2` spring, `1` january). Fall 2026 is `1268`.

```bash
python fetch_page.py 1268
```

The file is the class-search listing (subject, number, title, instructors, meetings, enrollment). It is not the separate per-class description page. The script writes the file only after every page succeeds.

## GitHub Action

**Update course data** runs when someone starts it from the Actions tab and enters a SIS term. The job runs `fetch_page.py` and commits `data/<term>.json` only if the file changed.

The every-two-hours schedule in `.github/workflows/update-data.yml` stays commented out.

## What the website does with this file

A developer runs `python manage.py fetch_data <year>_<season>` in theCourseForum2. That command downloads `data/<term>.json` from this repository. It does not call SIS, and it does not load the JSON into the website database.
