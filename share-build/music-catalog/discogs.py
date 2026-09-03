import requests
import os
import time
from urllib.parse import urlencode

DISCOGS_BASE_URL = 'https://api.discogs.com'

def _get_token():
    """Read token at call time so runtime updates to os.environ are picked up."""
    return os.getenv('DISCOGS_TOKEN', '')

# Rate limiting
LAST_REQUEST_TIME = 0
MIN_REQUEST_INTERVAL = 0.5  # seconds

def _rate_limit():
    """Enforce rate limiting between requests"""
    global LAST_REQUEST_TIME
    elapsed = time.time() - LAST_REQUEST_TIME
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    LAST_REQUEST_TIME = time.time()

def _get_headers():
    """Get headers for Discogs API requests"""
    return {
        'User-Agent': 'MusicCatalogApp/1.0',
        'Authorization': f'Discogs token={_get_token()}'
    }

def parse_discogs_url(url):
    """Parse a Discogs release or master URL and return (release_type, release_id).
    release_type is 'release' or 'master'.
    Returns (None, None) if the URL is not recognisable."""
    import re
    url = url.strip()
    # Match e.g. https://www.discogs.com/release/12345-...
    #        or  https://www.discogs.com/master/12345-...
    #        or  https://www.discogs.com/Artist/release/12345-...
    m = re.search(r'/(release|master)/(\d+)', url)
    if m:
        return m.group(1), int(m.group(2))
    # Also handle plain numeric IDs pasted directly
    if url.isdigit():
        return 'release', int(url)
    return None, None

def search_by_barcode(upc):
    """Search Discogs by barcode/UPC — returns first result"""
    results = search_by_barcode_multi(upc, limit=1)
    return results[0] if results else None

def search_by_barcode_multi(upc, limit=2):
    """Search Discogs by barcode/UPC — returns up to `limit` results"""
    if not _get_token() or not upc:
        return []

    _rate_limit()

    try:
        params = {
            'barcode': upc,
            'token': _get_token()
        }
        url = f'{DISCOGS_BASE_URL}/database/search'
        response = requests.get(url, params=params, headers=_get_headers(), timeout=10)
        response.raise_for_status()

        data = response.json()
        return data.get('results', [])[:limit]
    except Exception as e:
        print(f"Error searching Discogs by barcode: {e}")
        return []

def search_by_artist_title(artist, title, format_hint=None):
    """Search Discogs by artist and title.
    format_hint: optional Discogs format string e.g. 'Vinyl' to restrict to that format type."""
    if not _get_token() or not artist or not title:
        return None

    _rate_limit()

    try:
        params = {
            'artist': artist,
            'release_title': title,
            'token': _get_token(),
            'per_page': 10
        }
        if format_hint:
            params['format'] = format_hint
        url = f'{DISCOGS_BASE_URL}/database/search'
        response = requests.get(url, params=params, headers=_get_headers(), timeout=10)
        response.raise_for_status()

        data = response.json()
        results = data.get('results', [])
        if not results:
            return None
        for r in results:
            if r.get('type') == 'master':
                return r
        for r in results:
            if r.get('cover_image', '') and 'spacer' not in r.get('cover_image', ''):
                return r
        return results[0]
    except Exception as e:
        print(f"Error searching Discogs by artist/title: {e}")
        return None

def search_by_artist_title_multi(artist, title, format_hint=None, limit=2):
    """Search Discogs by artist/title — returns up to `limit` distinct results for cover picking"""
    if not _get_token() or not artist or not title:
        return []

    _rate_limit()

    try:
        params = {
            'artist': artist,
            'release_title': title,
            'token': _get_token(),
            'per_page': 10
        }
        if format_hint:
            params['format'] = format_hint
        url = f'{DISCOGS_BASE_URL}/database/search'
        response = requests.get(url, params=params, headers=_get_headers(), timeout=10)
        response.raise_for_status()

        results = response.json().get('results', [])
        if not results:
            return []

        # Pick best primary result first (master preferred)
        primary = None
        for r in results:
            if r.get('type') == 'master':
                primary = r
                break
        if not primary:
            primary = results[0]

        # Pick a second result that is a different release with a cover image
        second = None
        for r in results:
            if r.get('id') == primary.get('id'):
                continue
            if r.get('cover_image', '') and 'spacer' not in r.get('cover_image', ''):
                second = r
                break

        out = [primary]
        if second:
            out.append(second)
        return out[:limit]
    except Exception as e:
        print(f"Error searching Discogs by artist/title (multi): {e}")
        return []

def get_release_details(release_id):
    """Fetch full release details including cover art"""
    if not _get_token() or not release_id:
        return None

    _rate_limit()

    try:
        url = f'{DISCOGS_BASE_URL}/releases/{release_id}'
        params = {'token': _get_token()}
        response = requests.get(url, params=params, headers=_get_headers(), timeout=10)
        response.raise_for_status()

        data = response.json()
        return data
    except Exception as e:
        print(f"Error fetching Discogs release details: {e}")
        return None


def get_master_details(master_id):
    """Fetch master release details for canonical high-res cover art"""
    if not _get_token() or not master_id:
        return None
    _rate_limit()
    try:
        url = f'{DISCOGS_BASE_URL}/masters/{master_id}'
        response = requests.get(url, params={'token': _get_token()}, headers=_get_headers(), timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching master details: {e}")
        return None

def extract_cover_art_url(release_data):
    """Extract primary cover art URL from release data"""
    urls = extract_cover_art_urls(release_data, limit=1)
    return urls[0] if urls else None

def extract_cover_art_urls(release_data, limit=2):
    """Extract up to `limit` front cover URLs (primary type only) from release data"""
    if not release_data:
        return []

    images = release_data.get('images', [])
    if not images:
        return []

    # Only primary (front cover) images — avoids back covers / inner sleeves
    primary = [img.get('uri') for img in images if img.get('type') == 'primary' and img.get('uri')]

    # If nothing is tagged primary, fall back to the very first image only
    if not primary:
        first = images[0].get('uri')
        return [first] if first else []

    return primary[:limit]

def download_cover_art(image_url, filename):
    """Download and save cover art image"""
    if not image_url:
        return None

    _rate_limit()

    try:
        covers_dir = os.path.join(os.path.dirname(__file__), 'covers')
        os.makedirs(covers_dir, exist_ok=True)

        filepath = os.path.join(covers_dir, filename)

        response = requests.get(image_url, headers=_get_headers(), timeout=10)
        response.raise_for_status()

        with open(filepath, 'wb') as f:
            f.write(response.content)

        # Return relative path
        return f'covers/{filename}'
    except Exception as e:
        print(f"Error downloading cover art: {e}")
        return None

def extract_tracklist(release_data):
    """Extract clean tracklist from release or master data.
    Handles classical releases where movements are type 'sub_track'
    listed under a 'heading' work title, or nested inside an 'index'
    container (a parent item with a sub_tracks list)."""
    if not release_data:
        return []
    tracks = []

    def _process_item(item):
        type_ = item.get('type_')
        title = item.get('title', '').strip()

        # 'index' = container with nested sub_tracks (e.g. Discogs classical layout)
        # Emit the index title as a heading, then recurse into sub_tracks
        if type_ == 'index':
            if title:
                tracks.append({'position': '', 'title': title, 'duration': '', 'is_heading': True})
            for sub in item.get('sub_tracks', []):
                _process_item(sub)
            return

        # 'heading' = section label with no sub_tracks
        if type_ == 'heading':
            if title:
                tracks.append({'position': '', 'title': title, 'duration': '', 'is_heading': True})
            return

        # Allow regular tracks and classical sub-tracks (movements)
        if type_ not in ('track', 'sub_track', '', None):
            return

        if not title:
            return

        # Per-track artist (compilations) — join multiple artists respecting the 'join' field
        track_artists = item.get('artists', [])
        if track_artists:
            parts = []
            for a in track_artists:
                name = strip_discogs_suffix(a.get('name', '').strip())
                if name:
                    parts.append(name)
                join = a.get('join', '').strip()
                if join and join != ',':
                    parts.append(join)
            track_artist = ' '.join(parts).strip(' ,')
        else:
            track_artist = ''

        tracks.append({
            'position': item.get('position', '').strip(),
            'title': title,
            'duration': item.get('duration', '').strip(),
            'artist': track_artist,
            'is_heading': False
        })

    for item in release_data.get('tracklist', []):
        _process_item(item)

    return tracks

def get_master_versions(master_id, limit=1):
    """Fetch versions of a master release — used to get tracklist when master lacks one"""
    if not _get_token() or not master_id:
        return []
    _rate_limit()
    try:
        url = f'{DISCOGS_BASE_URL}/masters/{master_id}/versions'
        params = {'token': _get_token(), 'per_page': limit}
        response = requests.get(url, params=params, headers=_get_headers(), timeout=10)
        response.raise_for_status()
        return response.json().get('versions', [])
    except Exception as e:
        print(f"Error fetching master versions: {e}")
        return []

def strip_discogs_suffix(name):
    """Remove Discogs disambiguation suffix e.g. ' (2)', ' (3)' from artist names."""
    import re
    if not name:
        return name
    return re.sub(r'\s*\(\d+\)\s*$', '', name.strip()).strip()

def parse_search_title(title_str):
    """Parse Discogs search result title (format: Artist - Title)"""
    if not title_str:
        return '', ''

    if ' - ' in title_str:
        parts = title_str.split(' - ', 1)
        return strip_discogs_suffix(parts[0].strip()), parts[1].strip()

    return '', title_str.strip()

def get_marketplace_prices(release_id):
    """Fetch lowest, median and highest marketplace prices for a release.
    Returns dict with keys: lowest, median, highest, currency, num_for_sale
    or None if no listings exist or the call fails."""
    if not _get_token() or not release_id:
        return None

    # Step 1: stats endpoint — fast, gives lowest price + num_for_sale
    _rate_limit()
    try:
        url = f'{DISCOGS_BASE_URL}/marketplace/stats/{release_id}'
        r = requests.get(url, params={'token': _get_token(), 'curr_abbr': 'USD'},
                         headers=_get_headers(), timeout=10)
        r.raise_for_status()
        stats = r.json()
    except Exception as e:
        print(f"Error fetching marketplace stats for {release_id}: {e}")
        return None

    num_for_sale = stats.get('num_for_sale', 0)
    if not num_for_sale:
        return None

    lowest_data = stats.get('lowest_price') or {}
    lowest = lowest_data.get('value')
    currency = lowest_data.get('currency', 'USD')

    # Stats only gives lowest — return that with median/highest as None.
    # The record detail page handles None gracefully.
    return {'lowest': lowest, 'median': None, 'highest': None,
            'currency': currency, 'num_for_sale': num_for_sale}

def get_artist_details(artist_id):
    """Fetch Discogs artist profile by numeric artist ID.
    Returns the raw response dict, or None on failure."""
    if not _get_token() or not artist_id:
        return None
    _rate_limit()
    try:
        url = f'{DISCOGS_BASE_URL}/artists/{artist_id}'
        r = requests.get(url, params={'token': _get_token()},
                         headers=_get_headers(), timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Error fetching artist details for {artist_id}: {e}")
        return None

def invert_person_name(display_name):
    """'Al Green' -> 'Green, Al'  |  'John Lee Hooker' -> 'Hooker, John Lee'
    Only call this when you have confirmed the artist is a real person."""
    parts = display_name.strip().split()
    if len(parts) < 2:
        return display_name
    return f"{parts[-1]}, {' '.join(parts[:-1])}"

def get_artist_sort_name(artist_str):
    """Convert artist name to sort format (Last, First)"""
    if not artist_str:
        return ''
    return artist_str.strip()
