"""Fetch every class-search page for one term into data/<term>.json.

This is the listing SIS returns for the term, not the per-class detail page.
"""

import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request

if len(sys.argv) != 2 or not sys.argv[1].isdigit():
    raise SystemExit("usage: python fetch_page.py <sis-term>")
TERM = sys.argv[1]
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
