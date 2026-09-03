#!/usr/bin/env python3
"""Debug script — fetches raw tracklist data for a Discogs release and prints every item."""

import requests
import sys
import os
from dotenv import load_dotenv

load_dotenv()
DISCOGS_TOKEN = os.getenv('DISCOGS_TOKEN', '')
if not DISCOGS_TOKEN:
    print("Set DISCOGS_TOKEN in your .env file or environment before running this script.")
    sys.exit(1)
HEADERS = {
    'User-Agent': 'MusicCatalogApp/1.0',
    'Authorization': f'Discogs token={DISCOGS_TOKEN}'
}

release_id = sys.argv[1] if len(sys.argv) > 1 else '10249581'
url = f'https://api.discogs.com/releases/{release_id}'

print(f"Fetching: {url}\n")
r = requests.get(url, params={'token': DISCOGS_TOKEN}, headers=HEADERS, timeout=10)
r.raise_for_status()
data = r.json()

print(f"Title   : {data.get('title')}")
print(f"Artist  : {data.get('artists_sort')}")
print(f"Year    : {data.get('year')}")
print(f"Labels  : {[l.get('name') for l in data.get('labels', [])]}")
print()

raw = data.get('tracklist', [])
print(f"Raw tracklist items: {len(raw)}")
print()
for i, item in enumerate(raw):
    print(f"  [{i}] type_={item.get('type_')!r:12}  pos={item.get('position')!r:6}  title={item.get('title')!r}")
    for j, sub in enumerate(item.get('sub_tracks', [])):
        print(f"       sub[{j}] type_={sub.get('type_')!r:12}  pos={sub.get('position')!r:6}  title={sub.get('title')!r}")
