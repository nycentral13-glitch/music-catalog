import os
import sys
import json
import uuid
import time
import socket
import secrets
import subprocess
from datetime import datetime
from pathlib import Path
import requests
from flask import (
    Flask, render_template, request, jsonify, redirect, url_for,
    flash, session, send_file, Response
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from pathlib import Path

import database
import discogs

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'covers')
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def _clean_discogs_artist(release_data, fallback_artist=''):
    """Return (display_name, sort_name) from a Discogs release data dict.
    - Strips disambiguation suffix e.g. ' (2)'
    - Uses artists_sort when Discogs provides it (e.g. 'White, Barry')
    - Falls back to display name if sort name is absent
    """
    artists = release_data.get('artists', [])
    display = artists[0].get('name', '').strip() if artists else ''
    display = discogs.strip_discogs_suffix(display) or discogs.strip_discogs_suffix(fallback_artist) or fallback_artist

    sort = discogs.strip_discogs_suffix(release_data.get('artists_sort', '').strip())
    if not sort:
        sort = display
    return display, sort

def _normalize_artist_sort(name):
    """Move leading article (The, A, An) to end for sort purposes.
    e.g. 'The Rolling Stones' -> 'Rolling Stones, The'
         'A Tribe Called Quest' -> 'Tribe Called Quest, A'
    Only fires if the sort name does not already contain a comma
    (Discogs already returns 'Rolling Stones, The' so those pass through unchanged)."""
    if not name or ',' in name:
        return name
    for article in ('The ', 'the ', 'A ', 'a ', 'An ', 'an '):
        if name.startswith(article):
            rest = name[len(article):]
            return f"{rest}, {article.strip()}"
    return name

def _same_artist(result, expected_artist):
    """Check that a Discogs search result belongs to expected_artist.
    Discogs title field is 'Artist - Title'; we compare lowercased artist tokens."""
    if not expected_artist:
        return False
    title_str = result.get('title', '')
    if ' - ' not in title_str:
        return False
    result_artist = title_str.split(' - ')[0].strip().lower()
    if not result_artist:
        return False
    expected = expected_artist.lower()
    # Accept if one contains the other (handles 'Sleaford Mods' vs 'Sleaford Mods (2)')
    return expected in result_artist or result_artist in expected

# Initialize database on startup
with app.app_context():
    database.init_db()

# ============================================================================
# MAIN BROWSE PAGE
# ============================================================================

@app.route('/')
def index():
    """Browse collection with search and filter"""
    records = database.get_all_records()
    formats = database.get_all_formats()
    stats = database.get_collection_stats()

    # Build shelf position lookup: {record_id: {'shelf': 'Shelf 1', 'pos': 5, 'total': 86}}
    # Group non-duplicate records by shelf_section, sorted by sort_order, and assign position.
    shelf_groups = {}
    for r in records:
        shelf = r['shelf_section']
        if shelf and r['sort_order'] and not r['duplicate_flag']:
            shelf_groups.setdefault(shelf, []).append((r['sort_order'], r['id']))
    shelf_positions = {}
    for shelf, entries in shelf_groups.items():
        entries.sort()  # sort by sort_order
        total = len(entries)
        for pos, (sort_num, rec_id) in enumerate(entries, start=1):
            shelf_positions[rec_id] = {'shelf': shelf, 'pos': pos, 'total': total}

    return render_template(
        'index.html',
        records=records,
        formats=formats,
        stats=stats,
        shelf_positions=shelf_positions
    )

# ============================================================================
# ADD RECORD ROUTES
# ============================================================================

@app.route('/add')
def add():
    """Add record page with 3 entry modes"""
    formats = [
        'LP', 'Double LP', 'CD', '45', 'Box Set', 'EP', '12 Inch', '10 Inch', '7 Inch'
    ]
    return render_template('add.html', formats=formats)

@app.route('/add/barcode', methods=['POST'])
def add_barcode():
    """Process barcode scan"""
    upc = request.form.get('upc', '').strip()

    if not upc:
        return jsonify({'error': 'No barcode provided'}), 400

    # Check for existing UPC
    existing = database.check_duplicate_upc(upc)
    if existing:
        # Still fetch Discogs data so the frontend can offer "Add Anyway"
        dup_release_info = None
        try:
            dup_results = discogs.search_by_barcode_multi(upc, limit=1)
            if dup_results:
                dup_sr = dup_results[0]
                dup_rid = dup_sr.get('id')
                dup_rd = discogs.get_release_details(dup_rid) if dup_rid else None
                if dup_rd:
                    dup_artist_raw, dup_title = discogs.parse_search_title(dup_sr.get('title', ''))
                    dup_display, dup_sort = _clean_discogs_artist(dup_rd, dup_artist_raw)
                    dup_labels = dup_rd.get('labels', [{}])
                    dup_catno = dup_labels[0].get('catno', '') if dup_labels else ''
                    dup_cover = discogs.extract_cover_art_url(dup_rd)
                    dup_master_id = dup_rd.get('master_id')
                    if dup_master_id:
                        dup_master = discogs.get_master_details(dup_master_id)
                        dup_master_cover = discogs.extract_cover_art_url(dup_master) if dup_master else None
                        dup_cover = dup_master_cover or dup_cover
                    dup_release_info = {
                        'artist': dup_display,
                        'title': dup_title or dup_rd.get('title', ''),
                        'artist_sort': dup_sort,
                        'format': dup_sr.get('format', ''),
                        'year': dup_sr.get('year'),
                        'label': dup_sr.get('label', ''),
                        'upc': upc,
                        'catalog_number': dup_sr.get('catalog_number', '') or dup_catno,
                        'genre': (dup_sr.get('genre', []) or [''])[0],
                        'discogs_url': dup_sr.get('uri', ''),
                        'discogs_id': str(dup_rid),
                        'cover_image_url': dup_cover,
                        'cover_image_urls': [dup_cover] if dup_cover else [],
                        'tracklist': discogs.extract_tracklist(dup_rd)
                    }
        except Exception:
            pass
        return jsonify({
            'error': 'duplicate',
            'message': 'You already have this record — add another copy?',
            'existing_record': {
                'id': existing['id'],
                'artist': existing['artist'],
                'title': existing['title'],
                'year': existing['year']
            },
            'release_info': dup_release_info
        }), 409

    # Search Discogs — fetch top 2 results for cover picker
    search_results = discogs.search_by_barcode_multi(upc, limit=2)

    if not search_results:
        return jsonify({
            'error': 'not_found',
            'message': 'Record not found in Discogs. You can enter details manually.'
        }), 404

    search_result = search_results[0]

    # Get full release details for primary result
    release_id = search_result.get('id')
    release_data = discogs.get_release_details(release_id)

    if not release_data:
        return jsonify({
            'error': 'api_error',
            'message': 'Could not fetch record details from Discogs'
        }), 500

    # Extract data
    title_str = search_result.get('title', '')
    artist_raw, title = discogs.parse_search_title(title_str)

    tracklist = discogs.extract_tracklist(release_data)

    display_artist, sort_artist = _clean_discogs_artist(release_data, artist_raw)

    # Use master release cover as primary (canonical artwork), pressing cover as Option 2
    pressing_cover = discogs.extract_cover_art_url(release_data)
    master_id = release_data.get('master_id')
    master_cover = None
    if master_id:
        master_data = discogs.get_master_details(master_id)
        master_cover = discogs.extract_cover_art_url(master_data) if master_data else None

    # Primary = master cover if available, else pressing cover
    primary_cover = master_cover or pressing_cover
    cover_image_urls = [primary_cover] if primary_cover else []
    # Option 2 = pressing-specific cover if it differs from master
    if pressing_cover and pressing_cover != primary_cover:
        cover_image_urls.append(pressing_cover)

    release_info = {
        'artist': display_artist,
        'title': title or release_data.get('title', ''),
        'artist_sort': sort_artist,
        'format': search_result.get('format', ''),
        'year': search_result.get('year'),
        'label': search_result.get('label', ''),
        'upc': upc,
        'catalog_number': search_result.get('catalog_number', '') or (release_data.get('labels', [{}])[0].get('catno', '') if release_data.get('labels') else ''),
        'genre': (search_result.get('genre', []) or [''])[0],
        'discogs_url': search_result.get('uri', ''),
        'discogs_id': str(release_id),
        'cover_image_url': primary_cover,
        'cover_image_urls': cover_image_urls,
        'tracklist': tracklist
    }

    return jsonify({'success': True, 'release_info': release_info})

@app.route('/add/price-preview/<int:discogs_id>')
def price_preview(discogs_id):
    """Return marketplace low-ask price for display in the add confirmation modal."""
    try:
        prices = discogs.get_marketplace_prices(discogs_id)
        if prices and prices.get('lowest') is not None:
            return jsonify({'price': prices['lowest'], 'currency': prices.get('currency', 'USD'),
                            'num_for_sale': prices.get('num_for_sale', 0)})
        return jsonify({'price': None})
    except Exception as e:
        return jsonify({'price': None, 'error': str(e)})

@app.route('/add/discogs-link', methods=['POST'])
def add_discogs_link():
    """Look up a record directly from a pasted Discogs URL"""
    url = request.json.get('url', '').strip()
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    release_type, release_id = discogs.parse_discogs_url(url)
    if not release_id:
        return jsonify({'error': 'invalid_url', 'message': 'Could not recognise that Discogs URL. Paste a release or master link, e.g. https://www.discogs.com/release/12345'}), 400

    is_master = release_type == 'master'
    if is_master:
        release_data = discogs.get_master_details(release_id)
    else:
        release_data = discogs.get_release_details(release_id)

    if not release_data:
        return jsonify({'error': 'api_error', 'message': 'Could not fetch record details from Discogs'}), 500

    # Extract artist / title
    title = release_data.get('title', '')
    display_artist, sort_artist = _clean_discogs_artist(release_data)

    # Tracklist — fall back to first pressing for masters
    tracklist = discogs.extract_tracklist(release_data)
    if not tracklist and is_master:
        versions = discogs.get_master_versions(release_id, limit=1)
        if versions:
            version_data = discogs.get_release_details(versions[0]['id'])
            tracklist = discogs.extract_tracklist(version_data)

    # Cover art — master cover as primary, pressing cover as option 2
    pressing_cover = discogs.extract_cover_art_url(release_data)
    master_id = release_data.get('master_id') if not is_master else release_id
    master_cover = None
    if master_id and not is_master:
        master_data = discogs.get_master_details(master_id)
        master_cover = discogs.extract_cover_art_url(master_data) if master_data else None
    primary_cover = master_cover or pressing_cover
    cover_image_urls = [primary_cover] if primary_cover else []
    if pressing_cover and pressing_cover != primary_cover:
        cover_image_urls.append(pressing_cover)

    # Format
    formats = release_data.get('formats', [])
    fmt = _parse_discogs_format(formats)

    labels = release_data.get('labels', [])
    label = labels[0].get('name', '') if labels else ''
    catno = labels[0].get('catno', '') if labels else ''

    # Masters don't carry label/catalog info — fall back to first pressing
    if is_master and not label:
        versions = discogs.get_master_versions(release_id, limit=1)
        if versions:
            pressing = discogs.get_release_details(versions[0]['id'])
            if pressing:
                pressing_labels = pressing.get('labels', [])
                label = pressing_labels[0].get('name', '') if pressing_labels else ''
                catno = pressing_labels[0].get('catno', '') if pressing_labels else ''
                # Also fill format from pressing if missing
                if not fmt:
                    fmt = _parse_discogs_format(pressing.get('formats', []))

    release_info = {
        'artist': display_artist,
        'title': title,
        'artist_sort': sort_artist,
        'format': fmt,
        'year': release_data.get('year') or release_data.get('released', '')[:4] if release_data.get('released') else release_data.get('year'),
        'label': label,
        'catalog_number': catno,
        'upc': '',
        'genre': (release_data.get('genres', []) or [''])[0],
        'discogs_url': release_data.get('uri', ''),
        'discogs_id': str(release_id),
        'cover_image_url': primary_cover,
        'cover_image_urls': cover_image_urls,
        'tracklist': tracklist
    }

    return jsonify({'success': True, 'release_info': release_info})

@app.route('/add/photo', methods=['POST'])
def add_photo():
    """Process photo upload of album cover"""
    if 'photo' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['photo']

    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type'}), 400

    # Save temporarily
    temp_filename = f"temp_{uuid.uuid4()}.jpg"
    temp_path = os.path.join(UPLOAD_FOLDER, temp_filename)

    try:
        file.save(temp_path)
    except Exception as e:
        return jsonify({'error': f'File save failed: {str(e)}'}), 500

    # Vision identification not available
    identification = None

    unknown = {'', 'unknown', 'unknown artist', 'unknown album'}
    if (not identification
            or identification.get('artist', '').strip().lower() in unknown
            or identification.get('title', '').strip().lower() in unknown):
        os.remove(temp_path)
        return jsonify({
            'error': 'could_not_identify',
            'message': 'Could not identify the record. Try photographing the back cover or spine where the text is clearer.'
        }), 422

    # Check for duplicates
    existing = database.check_duplicate_fuzzy(
        identification['artist'],
        identification['title']
    )
    if existing:
        os.remove(temp_path)
        return jsonify({
            'error': 'duplicate',
            'message': 'A similar record already exists',
            'existing_record': {
                'id': existing['id'],
                'artist': existing['artist'],
                'title': existing['title'],
                'year': existing['year']
            }
        }), 409

    # Search Discogs — fetch top 2 results for cover picker
    search_results = discogs.search_by_artist_title_multi(
        identification['artist'],
        identification['title']
    )
    search_result = search_results[0] if search_results else None

    release_info = {
        'artist': identification['artist'],
        'title': identification['title'],
        'artist_sort': identification['artist'],
        'format': '',
        'year': None,
        'label': '',
        'upc': '',
        'catalog_number': '',
        'genre': '',
        'discogs_url': '',
        'discogs_id': '',
        'cover_image_url': None,
        'cover_image_urls': [],
        'cover_preview_url': None,
        'temp_photo_path': temp_filename
    }

    if search_result:
        release_id = search_result.get('id')
        is_master = search_result.get('type') == 'master'
        if is_master:
            release_data = discogs.get_master_details(release_id)
        else:
            release_data = discogs.get_release_details(release_id)

        if release_data:
            title_str = search_result.get('title', '')
            artist_raw, title = discogs.parse_search_title(title_str)

            # Extract tracklist; if master has none, fall back to first pressing
            tracklist = discogs.extract_tracklist(release_data)
            if not tracklist and is_master:
                versions = discogs.get_master_versions(release_id, limit=1)
                if versions:
                    version_data = discogs.get_release_details(versions[0]['id'])
                    tracklist = discogs.extract_tracklist(version_data)

            display_artist, sort_artist = _clean_discogs_artist(release_data, artist_raw or identification['artist'])

            # Build cover variants from up to 2 different pressings (same artist only)
            primary_cover = discogs.extract_cover_art_url(release_data)
            cover_image_urls = [primary_cover] if primary_cover else []
            if len(search_results) > 1 and _same_artist(search_results[1], display_artist):
                release_data2 = discogs.get_release_details(search_results[1].get('id'))
                if release_data2:
                    cover2 = discogs.extract_cover_art_url(release_data2)
                    if cover2 and cover2 != primary_cover:
                        cover_image_urls.append(cover2)

            release_info.update({
                'artist': display_artist,
                'title': title or identification['title'],
                'artist_sort': sort_artist,
                'format': search_result.get('format', ''),
                'year': search_result.get('year'),
                'label': search_result.get('label', ''),
                'catalog_number': search_result.get('catalog_number', ''),
                'genre': (search_result.get('genre', []) or [''])[0],
                'discogs_url': search_result.get('uri', ''),
                'discogs_id': str(release_id),
                'cover_image_url': primary_cover,
                'cover_image_urls': cover_image_urls,
                'cover_preview_url': search_result.get('cover_image'),
                'tracklist': tracklist
            })

    return jsonify({'success': True, 'release_info': release_info})

@app.route('/add/save', methods=['POST'])
def add_save():
    """Save a new record to the collection"""
    data = request.json

    # Validate required fields
    if not data.get('title') or not data.get('artist'):
        return jsonify({'error': 'Missing required fields'}), 400

    # Handle cover art
    cover_art_path = None
    cover_source = None

    if data.get('use_own_photo') and data.get('temp_photo_path'):
        # Use the temporary photo
        temp_filename = data.get('temp_photo_path')
        temp_path = os.path.join(UPLOAD_FOLDER, temp_filename)

        if os.path.exists(temp_path):
            # Generate final filename
            final_filename = f"{uuid.uuid4()}.jpg"
            final_path = os.path.join(UPLOAD_FOLDER, final_filename)

            try:
                # Process: auto-rotate, remove background, square crop
                with open(temp_path, 'rb') as f:
                    raw = f.read()
                processed = raw  # vision processing not available; use raw photo
                with open(final_path, 'wb') as f:
                    f.write(processed)
                os.remove(temp_path)
                cover_art_path = f'covers/{final_filename}'
                cover_source = 'own_photo'
            except Exception as e:
                print(f"Error processing temp photo: {e}")
                # Continue without cover art
    elif data.get('use_discogs_image') and data.get('cover_image_url'):
        # Download from Discogs
        image_url = data.get('cover_image_url')
        discogs_id = data.get('discogs_id', uuid.uuid4())
        filename = f"{discogs_id}.jpg"

        cover_art_path = discogs.download_cover_art(image_url, filename)
        if cover_art_path:
            cover_source = 'discogs'

    # Prepare record data
    record_data = {
        'title': data.get('title'),
        'artist': data.get('artist'),
        'artist_sort': _normalize_artist_sort(data.get('artist_sort') or data.get('artist')),
        'format': data.get('format'),
        'year': data.get('year'),
        'label': data.get('label'),
        'catalog_number': data.get('catalog_number'),
        'upc': data.get('upc'),
        'cover_art_path': cover_art_path,
        'genre': data.get('genre'),
        'discogs_url': data.get('discogs_url'),
        'discogs_id': data.get('discogs_id'),
        'shelf_section': data.get('shelf_section'),
        'entry_mode': data.get('entry_mode'),
        'notes': data.get('notes'),
        'needs_review': 1 if data.get('needs_review') else 0,
        'cover_source': cover_source
    }

    try:
        record_id = database.add_record(record_data)

        # Save tracklist if provided
        tracklist = data.get('tracklist')
        if tracklist and isinstance(tracklist, list):
            database.add_tracks(record_id, tracklist)

        # Fetch marketplace price from Discogs immediately on add
        discogs_id = data.get('discogs_id')
        if discogs_id:
            try:
                prices = discogs.get_marketplace_prices(int(discogs_id))
                conn = database.get_db()
                if prices:
                    conn.execute('''UPDATE collection
                        SET price_lowest=?, price_median=?, price_highest=?,
                            price_currency=?, price_updated=?
                        WHERE id=?''',
                        (prices['lowest'], prices['median'], prices['highest'],
                         prices['currency'], datetime.utcnow().isoformat()[:10], record_id))
                else:
                    # No listings — stamp zeros so it leaves the unpriced queue
                    conn.execute('''UPDATE collection
                        SET price_lowest=0, price_median=0, price_highest=0,
                            price_currency='', price_updated=?
                        WHERE id=?''',
                        (datetime.utcnow().isoformat()[:10], record_id))
                conn.commit()
                conn.close()
            except Exception as pe:
                print(f"Price fetch failed for new record {record_id}: {pe}")

        flash(f'Record added: {data.get("title")} by {data.get("artist")}', 'success')
        return jsonify({
            'success': True,
            'record_id': record_id,
            'redirect': url_for('view_record', record_id=record_id)
        })
    except Exception as e:
        # Clean up any temporary files
        if data.get('temp_photo_path'):
            try:
                temp_path = os.path.join(UPLOAD_FOLDER, data.get('temp_photo_path'))
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except:
                pass

        print(f"Error saving record: {e}")
        return jsonify({'error': str(e)}), 500

# ============================================================================
# RECORD DETAIL & EDIT ROUTES
# ============================================================================

@app.route('/api/record/<int:record_id>')
def api_record(record_id):
    """Return record details + tracks as JSON for the lightbox."""
    record = database.get_record(record_id)
    if not record:
        return jsonify({'error': 'Not found'}), 404
    tracks = database.get_tracks(record_id)
    return jsonify({
        'id':          record_id,
        'artist':      record['artist'] or '',
        'artist_sort': record['artist_sort'] or '',
        'title':       record['title'] or '',
        'year':        record['year'] or '',
        'format':      record['format'] or '',
        'label':       record['label'] or '',
        'genre':       record['genre'] or '',
        'shelf':       record['shelf_section'] or '',
        'sort_order':  record['sort_order'] or '',
        'price_low':   record['price_lowest'],
        'price_high':  record['price_highest'],
        'cover':       record['cover_art_path'] or '',
        'tracks':      [{'pos': t['position'], 'title': t['title'],
                         'duration': t['duration'], 'artist': t['artist']}
                        for t in tracks],
    })

@app.route('/record/<int:record_id>')
def view_record(record_id):
    """View a single record"""
    record = database.get_record(record_id)

    if not record:
        flash('Record not found', 'error')
        return redirect(url_for('index'))

    tracks = database.get_tracks(record_id)

    browse = request.args.get('browse', '')
    prev_id = database.get_adjacent_in_browse(record_id, browse, 'prev') if browse else None
    next_id = database.get_adjacent_in_browse(record_id, browse, 'next') if browse else None

    browse_label = ''
    if browse:
        if browse == 'dupes':
            browse_label = 'Dupes'
        elif browse.startswith('genre:'):
            browse_label = browse[6:].title()
        elif browse.startswith('format:'):
            browse_label = browse[7:]

    # Position within shelf (1-based count of records on same shelf with sort_order <= this one)
    shelf_position = None
    if record['shelf_section'] and record['sort_order']:
        conn = database.get_db()
        row = conn.execute("""
            SELECT COUNT(*) as pos FROM collection
            WHERE shelf_section = ?
              AND sort_order <= ?
              AND (notes != 'alpha-divider' OR notes IS NULL)
              AND duplicate_flag = 0
        """, (record['shelf_section'], record['sort_order'])).fetchone()
        conn.close()
        shelf_position = row['pos'] if row else None

    return render_template('record.html', record=record, tracks=tracks,
                           browse=browse, browse_label=browse_label,
                           prev_id=prev_id, next_id=next_id,
                           shelf_position=shelf_position)

@app.route('/record/<int:record_id>/edit', methods=['GET', 'POST'])
def edit_record(record_id):
    """Edit a record"""
    record = database.get_record(record_id)

    if not record:
        flash('Record not found', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        data = request.form

        update_data = {
            'title': data.get('title'),
            'artist': data.get('artist'),
            'artist_sort': data.get('artist_sort'),
            'format': data.get('format'),
            'year': int(data.get('year')) if data.get('year') else None,
            'label': data.get('label'),
            'catalog_number': data.get('catalog_number'),
            'shelf_section': data.get('shelf_section'),
            'notes': data.get('notes'),
            'needs_review': 1 if data.get('needs_review') else 0
        }

        # Always save genre — text field is pre-filled so user controls it explicitly
        update_data['genre'] = data.get('genre', '').strip() or None

        # Handle cover art change
        if 'cover_art' in request.files:
            file = request.files['cover_art']
            if file and allowed_file(file.filename):
                filename = f"{uuid.uuid4()}.jpg"
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                file.save(filepath)
                update_data['cover_art_path'] = f'covers/{filename}'
                update_data['cover_source'] = 'own_photo'

        database.update_record(record_id, update_data)
        flash('Record updated', 'success')

        # If we came from the review queue, go to the next review item
        if request.form.get('from_review'):
            remaining = database.get_records_needing_review()
            # Skip the record we just saved (it may no longer need review)
            remaining = [r for r in remaining if r['id'] != record_id]
            if remaining:
                return redirect(url_for('edit_record', record_id=remaining[0]['id']) + '?from_review=1')
            else:
                flash('All reviews complete!', 'success')
                return redirect(url_for('review'))

        browse = request.form.get('browse', '')
        return redirect(url_for('view_record', record_id=record_id, browse=browse) if browse
                        else url_for('view_record', record_id=record_id))

    formats = [
        'LP', 'Double LP', 'CD', '45', 'Box Set', 'EP', '12 Inch', '10 Inch', '7 Inch'
    ]

    genres = [
        'Rock', 'Electronic', 'Pop', 'Jazz', 'Classical', 'Easy Listening',
        'Folk, World, & Country', 'Funk / Soul', 'Stage & Screen',
        'Hip Hop', 'Blues', 'Latin', 'Reggae',
        "Children's", 'Non-Music', 'Other'
    ]

    from_review = request.args.get('from_review', '')
    browse = request.args.get('browse', '')
    return render_template(
        'edit.html',
        record=record,
        formats=formats,
        genres=genres,
        from_review=from_review,
        browse=browse
    )

@app.route('/record/<int:record_id>/fetch-tracks', methods=['POST'])
def fetch_tracks(record_id):
    """Fetch and store tracklist from Discogs for an existing record"""
    record = database.get_record(record_id)
    if not record:
        flash('Record not found', 'error')
        return redirect(url_for('index'))

    tracklist = []

    # Prefer the stored discogs_id — avoids mismatches from re-searching by title
    stored_id = record['discogs_id']
    stored_url = record['discogs_url'] or ''

    if stored_id:
        is_master = '/master/' in stored_url
        if is_master:
            release_data = discogs.get_master_details(int(stored_id))
            tracklist = discogs.extract_tracklist(release_data) if release_data else []
            # Master with no tracklist — fall back to first pressing
            if not tracklist:
                versions = discogs.get_master_versions(int(stored_id), limit=1)
                if versions:
                    version_data = discogs.get_release_details(versions[0]['id'])
                    tracklist = discogs.extract_tracklist(version_data)
        else:
            release_data = discogs.get_release_details(int(stored_id))
            tracklist = discogs.extract_tracklist(release_data) if release_data else []
    else:
        # No stored ID — fall back to searching by artist/title
        # For vinyl formats, request a vinyl pressing so we get A/B side positions
        vinyl_formats = {'LP', 'Double LP', 'EP', '12 Inch', '10 Inch', '7 Inch'}
        format_hint = 'Vinyl' if record['format'] in vinyl_formats else None

        search_result = discogs.search_by_artist_title(record['artist'], record['title'], format_hint=format_hint)
        if not search_result:
            flash('No Discogs match found for this record', 'error')
            return redirect(url_for('view_record', record_id=record_id))

        release_id = search_result.get('id')
        is_master = search_result.get('type') == 'master'

        if is_master:
            release_data = discogs.get_master_details(release_id)
        else:
            release_data = discogs.get_release_details(release_id)

        tracklist = discogs.extract_tracklist(release_data) if release_data else []

        if not tracklist and is_master:
            versions = discogs.get_master_versions(release_id, limit=1)
            if versions:
                version_data = discogs.get_release_details(versions[0]['id'])
                tracklist = discogs.extract_tracklist(version_data)

    if tracklist:
        database.add_tracks(record_id, tracklist)
        flash(f'Fetched {len(tracklist)} tracks from Discogs', 'success')
    else:
        flash('No tracklist found on Discogs for this release', 'error')

    return redirect(url_for('view_record', record_id=record_id))

def _safe_delete_cover(cover_art_path, exclude_record_id):
    """Delete a cover file only if no other record still references it."""
    if not cover_art_path:
        return
    conn = database.get_db()
    others = conn.execute(
        'SELECT COUNT(*) FROM collection WHERE cover_art_path=? AND id!=?',
        (cover_art_path, exclude_record_id)
    ).fetchone()[0]
    conn.close()
    if others == 0:
        filepath = os.path.join(os.path.dirname(__file__), cover_art_path)
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except:
            pass

@app.route('/record/<int:record_id>/delete', methods=['POST'])
def delete_record_route(record_id):
    """Delete a record"""
    record = database.get_record(record_id)

    if not record:
        flash('Record not found', 'error')
        return redirect(url_for('index'))

    _safe_delete_cover(record['cover_art_path'], record_id)
    database.delete_record(record_id)
    flash('Record deleted', 'success')
    return redirect(url_for('index'))

# ============================================================================
# REVIEW & DUPLICATE MANAGEMENT
# ============================================================================

@app.route('/review')
def review():
    """Review records flagged for review"""
    records = database.get_records_needing_review()
    return render_template('review.html', records=records)

@app.route('/duplicates')
def duplicates():
    """Manage duplicate records"""
    records = database.get_duplicate_records()
    return render_template('duplicates.html', records=records)

@app.route('/duplicates/<int:record_id>/resolve', methods=['POST'])
def resolve_duplicate(record_id):
    """Resolve duplicate: keep, delete, or mark as distinct"""
    action = request.form.get('action')
    record = database.get_record(record_id)

    if not record:
        flash('Record not found', 'error')
        return redirect(url_for('duplicates'))

    if action == 'keep':
        # Mark as no longer duplicate
        database.update_record(record_id, {
            'duplicate_flag': 0,
            'duplicate_of': None
        })
        flash('Marked as distinct pressing', 'success')

    elif action == 'delete':
        _safe_delete_cover(record['cover_art_path'], record_id)
        database.delete_record(record_id)
        flash('Duplicate deleted', 'success')

    return redirect(url_for('duplicates'))

# ============================================================================
# SORT ORDER GENERATION
# ============================================================================

@app.route('/sort-order')
def sort_order():
    """Sort order generator page"""
    return render_template('sort_order.html')

@app.route('/sort-order/generate', methods=['POST'])
def generate_sort_order():
    """Generate sort order for vinyl records.
    If a shelf plan has been saved, respects those shelf boundaries.
    Otherwise distributes proportionally across 13 shelves.
    """
    records = database.get_records_for_sort_order()

    if not records:
        return jsonify({'error': 'No vinyl records found'}), 404

    # weight comes from SQL: COALESCE(shelf_units, format-default)
    total_units = sum(r['weight'] for r in records)

    saved_plan = database.get_shelf_plan()

    if saved_plan:
        # Re-sort within plan boundaries: re-derive shelf_section from plan endpoints
        # (same logic as apply_shelf_plan) so newly-added records land on the right shelf.
        # MUST use a globally sequential counter — not per-shelf — so the divider-placement
        # query (ORDER BY sort_order ASC) can find the true first record of each letter.
        endpoint_ids = {int(end_id) for end_id in saved_plan.values()}
        current_shelf = 1
        updates = []
        for global_pos, record in enumerate(records, start=1):
            updates.append((record['id'], global_pos * 100, f'Shelf {current_shelf}'))
            if record['id'] in endpoint_ids:
                current_shelf += 1
    elif len(records) < 200:
        # Small collection — keep everything on one shelf until 200 records
        updates = []
        for index, record in enumerate(records):
            updates.append((record['id'], (index + 1) * 100, 'Shelf 1'))
    else:
        # Distribute proportionally using user's saved shelf config,
        # snapping shelf breaks to letter boundaries within 10 records.
        config_json = database.get_setting('shelf_config')
        if config_json:
            config      = json.loads(config_json)
            shelf_widths = config['shelf_widths']
            num_shelves  = config['shelf_count']
        else:
            shelf_widths = [100.0]
            num_shelves  = 1

        total_inches = sum(shelf_widths)
        cumulative_caps = []
        running = 0
        for w in shelf_widths:
            running += (w / total_inches) * total_units
            cumulative_caps.append(running)

        SNAP_LIMIT = 10

        # Build cumulative unit array and letter-boundary index list
        cum_units = []
        cu = 0
        for r in records:
            cu += r['weight']
            cum_units.append(cu)

        letter_boundaries = []
        for i in range(len(records) - 1):
            curr = (records[i]['artist_sort'] or '')[0:1].upper()
            nxt  = (records[i + 1]['artist_sort'] or '')[0:1].upper()
            if curr != nxt:
                letter_boundaries.append(i)   # records[i] is the last of its letter

        # For each of num_shelves-1 breaks, find proportional target then snap
        break_indices = []   # index of LAST record on each shelf
        used_boundaries = set()

        for shelf in range(1, num_shelves):
            cap = cumulative_caps[shelf - 1]
            # Natural break: last index whose running total <= cap
            nat_idx = 0
            for i, cu in enumerate(cum_units):
                if cu <= cap:
                    nat_idx = i
                else:
                    break
            min_idx = (break_indices[-1] + 1) if break_indices else 0

            # Nearest letter boundary within SNAP_LIMIT, not already used
            best, best_dist = None, SNAP_LIMIT + 1
            for b in letter_boundaries:
                if b < min_idx or b in used_boundaries:
                    continue
                dist = abs(b - nat_idx)
                if dist <= SNAP_LIMIT and dist < best_dist:
                    best_dist = dist
                    best = b

            chosen = best if best is not None else max(nat_idx, min_idx)
            break_indices.append(chosen)
            if best is not None:
                used_boundaries.add(best)

        # Assign shelves
        updates = []
        current_shelf = 1
        next_break_ptr = 0

        for index, record in enumerate(records):
            updates.append((record['id'], (index + 1) * 100, f'Shelf {current_shelf}'))
            if next_break_ptr < len(break_indices) and index == break_indices[next_break_ptr]:
                current_shelf += 1
                next_break_ptr += 1

    # Apply sort order updates (shelf_section only changed when no plan exists)
    database.update_sort_order_batch(updates)

    # --- Overflow shelves 14 (Children's), 15 (Classical), 16 (Jazz) ---
    overflow_data = database.get_records_for_overflow_shelves()
    overflow_updates = []
    overflow_rows = []
    for genre_key in ('children', 'jazz', 'classical', 'ten_inch', 'easy_listening', 'other'):
        group = overflow_data[genre_key]
        shelf_label = f"Shelf {group['shelf']}"
        for pos, record in enumerate(group['records'], start=1):
            sort_num = pos * 100
            overflow_updates.append((record['id'], sort_num, shelf_label))
            overflow_rows.append({
                'sort_num': sort_num,
                'shelf': shelf_label,
                'artist_sort': record['artist_sort'] or record['artist'],
                'title': record['title'],
                'format': record['format'],
                'current_shelf': record['shelf_section'] or 'Not set'
            })
    database.update_sort_order_batch(overflow_updates)

    # --- Position alpha dividers just before the first real record of each letter ---
    # Build a lookup: for each letter, find the first real record whose artist_sort
    # starts with that letter (case-insensitive) and place the divider 50 sort units before it.
    conn = database.get_db()
    cur = conn.cursor()
    cur.execute("SELECT artist, artist_sort FROM collection WHERE notes = 'alpha-divider'")
    dividers = cur.fetchall()
    conn.close()

    divider_updates = []
    for div in dividers:
        letter = div['artist'].strip().upper()
        # Find the first real record starting with this letter (after sort order assigned)
        conn2 = database.get_db()
        cur2 = conn2.cursor()
        cur2.execute("""
            SELECT id, sort_order, shelf_section FROM collection
            WHERE (notes != 'alpha-divider' OR notes IS NULL)
              AND duplicate_flag = 0
              AND sort_order IS NOT NULL
              AND UPPER(SUBSTR(COALESCE(NULLIF(artist_sort,''), artist), 1, 1)) = ?
              AND (genre IS NULL
                   OR (LOWER(genre) NOT LIKE '%children%'
                   AND LOWER(genre) NOT LIKE '%classical%'
                   AND LOWER(genre) NOT LIKE '%jazz%'
                   AND LOWER(genre) NOT LIKE '%easy listening%'
                   AND LOWER(genre) != 'other'))
              AND (format IS NULL OR format != '10 Inch')
            ORDER BY sort_order ASC
            LIMIT 1
        """, (letter,))
        first = cur2.fetchone()
        conn2.close()

        if first:
            divider_sort = max(1, first['sort_order'] - 50)
            shelf_section = first['shelf_section']

            # Check: how many real records remain on this shelf AFTER the divider position?
            # If fewer than 5, push divider AND those trailing records to the next shelf.
            conn_chk = database.get_db()
            cur_chk = conn_chk.cursor()
            trailing_row = cur_chk.execute("""
                SELECT COUNT(*) as cnt, MIN(sort_order) as min_sort FROM collection
                WHERE shelf_section = ?
                  AND sort_order > ?
                  AND (notes != 'alpha-divider' OR notes IS NULL)
                  AND duplicate_flag = 0
            """, (shelf_section, divider_sort)).fetchone()
            trailing = trailing_row['cnt']
            min_trailing_sort = trailing_row['min_sort']

            if trailing < 5 and letter != 'Z':
                shelf_num = int(shelf_section.replace('Shelf ', '')) if shelf_section else 1
                next_shelf = f'Shelf {shelf_num + 1}'
                next_first = cur_chk.execute("""
                    SELECT sort_order FROM collection
                    WHERE shelf_section = ?
                      AND (notes != 'alpha-divider' OR notes IS NULL)
                      AND duplicate_flag = 0
                    ORDER BY sort_order ASC LIMIT 1
                """, (next_shelf,)).fetchone()
                if next_first:
                    # Move trailing records on this shelf to the next shelf too
                    cur_chk.execute("""
                        UPDATE collection
                        SET shelf_section = ?
                        WHERE shelf_section = ?
                          AND sort_order > ?
                          AND (notes != 'alpha-divider' OR notes IS NULL)
                          AND duplicate_flag = 0
                    """, (next_shelf, shelf_section, divider_sort))
                    conn_chk.commit()
                    # Place divider just before the first trailing record (not before next shelf's first)
                    divider_sort = max(1, min_trailing_sort - 10)
                    shelf_section = next_shelf
            conn_chk.close()

            divider_updates.append((first['id'], divider_sort, shelf_section, div['artist']))

    # Apply divider updates
    if divider_updates:
        conn3 = database.get_db()
        cur3 = conn3.cursor()
        for (_, divider_sort, shelf_section, artist) in divider_updates:
            cur3.execute("""
                UPDATE collection
                SET sort_order = ?, shelf_section = ?
                WHERE notes = 'alpha-divider' AND artist = ?
            """, (divider_sort, shelf_section, artist))
        conn3.commit()
        conn3.close()

    # Build response rows (main + overflow combined)
    table_rows = []
    for sort_num, shelf_section, record in zip(
        [u[1] for u in updates],
        [u[2] for u in updates],
        records
    ):
        table_rows.append({
            'sort_num': sort_num,
            'shelf': shelf_section,
            'artist_sort': record['artist_sort'] or record['artist'],
            'title': record['title'],
            'format': record['format'],
            'current_shelf': record['shelf_section'] or 'Not set'
        })
    table_rows.extend(overflow_rows)

    # Count records per shelf for summary
    shelf_counts = {}
    for u in updates + overflow_updates:
        shelf_counts[u[2]] = shelf_counts.get(u[2], 0) + 1

    total_all = len(records) + len(overflow_updates)

    return jsonify({
        'success': True,
        'total': total_all,
        'total_units': total_units,
        'shelves': 16,
        'shelf_counts': shelf_counts,
        'data': table_rows
    })

@app.route('/sort-order/generate-unpriced', methods=['POST'])
def generate_sort_order_unpriced():
    """Return LP/12 Inch records that still need pricing, in alphabetical sort order."""
    records = database.get_records_needing_price_for_sort()

    if not records:
        return jsonify({'success': True, 'total': 0, 'shelves': 0, 'data': []})

    table_rows = []
    for record in records:
        table_rows.append({
            'sort_num': '—',
            'shelf': record['shelf_section'] or 'Not set',
            'artist_sort': record['artist_sort'] or record['artist'],
            'title': record['title'],
            'format': record['format'] or '',
            'current_shelf': record['shelf_section'] or 'Not set',
            'id': record['id']
        })

    return jsonify({
        'success': True,
        'total': len(records),
        'shelves': '—',
        'data': table_rows
    })

# ============================================================================
# SHELF PLANNER
# ============================================================================

@app.route('/shelf-planner')
def shelf_planner():
    """Shelf compaction planner page."""
    reconfigure = request.args.get('reconfigure') == '1'
    config_json = database.get_setting('shelf_config')
    if config_json and not reconfigure:
        config = json.loads(config_json)
        return render_template('shelf_planner.html',
                               shelf_configured=True,
                               shelf_count=config['shelf_count'],
                               shelf_widths=config['shelf_widths'])
    return render_template('shelf_planner.html',
                           shelf_configured=False,
                           shelf_count=0,
                           shelf_widths=[])


@app.route('/shelf-planner/configure', methods=['POST'])
def shelf_planner_configure():
    """Save user's shelf count and per-shelf widths."""
    data = request.json or {}
    try:
        shelf_count = int(data.get('shelf_count', 0))
        shelf_widths = [float(w) for w in data.get('shelf_widths', [])]
    except (ValueError, TypeError) as e:
        return jsonify({'ok': False, 'error': str(e)})
    if shelf_count < 1 or len(shelf_widths) != shelf_count:
        return jsonify({'ok': False, 'error': 'Shelf count and widths must match'})
    database.save_setting('shelf_config', json.dumps({
        'shelf_count': shelf_count,
        'shelf_widths': shelf_widths
    }))
    return jsonify({'ok': True})

@app.route('/shelf-planner/records')
def shelf_planner_records():
    """Return all main vinyl records in sort order plus saved plan."""
    rows = database.get_shelf_planner_records()
    records = []
    for r in rows:
        records.append({
            'id':          r['id'],
            'artist':      r['artist'] or '',
            'artist_sort': r['artist_sort'] or r['artist'] or '',
            'title':       r['title'] or '',
            'format':      r['format'] or '',
            'shelf':       r['shelf_section'] or '',
            'sort_order':  r['sort_order'],
            'is_divider':  r['notes'] == 'alpha-divider',
            'weight':      r['weight'],
        })
    saved_plan = database.get_shelf_plan()
    return jsonify({'records': records, 'saved_plan': {str(k): v for k, v in saved_plan.items()}})

@app.route('/shelf-planner/save', methods=['POST'])
def shelf_planner_save():
    """Save shelf plan endpoints. Body: {plan: {shelf_num: end_record_id}}."""
    data = request.get_json()
    plan = {int(k): int(v) for k, v in data.get('plan', {}).items()}
    database.save_shelf_plan(plan)
    return jsonify({'success': True, 'saved': len(plan)})

@app.route('/shelf-planner/apply', methods=['POST'])
def shelf_planner_apply():
    """Apply saved plan to shelf_section column for all records in shelves 1-13."""
    saved_plan = database.get_shelf_plan()
    if not saved_plan:
        return jsonify({'error': 'No plan saved yet'}), 400
    count = database.apply_shelf_plan(saved_plan)
    return jsonify({'success': True, 'updated': count})

# ============================================================================
# COVER ART SERVING
# ============================================================================

@app.route('/covers/<filename>')
def serve_cover(filename):
    """Serve cover art images"""
    safe_filename = secure_filename(filename)
    filepath = os.path.join(UPLOAD_FOLDER, safe_filename)

    if os.path.exists(filepath):
        return send_file(filepath)

    # Return placeholder
    return '', 404

# ============================================================================
# STATISTICS
# ============================================================================

@app.route('/library-app')
def serve_library_app():
    """Serve the offline library app HTML file."""
    from flask import send_from_directory
    app_dir = os.path.abspath(os.path.dirname(__file__))
    return send_from_directory(app_dir, 'library-app.html')

@app.route('/service-worker.js')
def service_worker():
    """Service worker that caches the library app for offline use."""
    sw_js = """
const CACHE = 'music-catalog-offline';

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE).then(cache => cache.add('/library-app'))
    );
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', event => {
    if (event.request.url.includes('/library-app')) {
        event.respondWith(
            caches.match('/library-app').then(cached => cached || fetch(event.request))
        );
    }
});
"""
    from flask import Response
    return Response(sw_js, mimetype='application/javascript',
                    headers={'Cache-Control': 'no-cache, no-store'})

@app.route('/apple-touch-icon.png')
@app.route('/apple-touch-icon-precomposed.png')
def serve_touch_icon():
    """Serve the iOS home screen icon from disk."""
    from flask import send_from_directory
    app_dir = os.path.abspath(os.path.dirname(__file__))
    icon_path = os.path.join(app_dir, 'apple-touch-icon.png')
    if not os.path.exists(icon_path):
        # Generate and save it if missing
        b64 = _build_app_icon_b64()
        if b64:
            import base64
            with open(icon_path, 'wb') as f:
                f.write(base64.b64decode(b64))
        else:
            return '', 404
    return send_from_directory(app_dir, 'apple-touch-icon.png')

@app.route('/stats')
def stats():
    """Collection statistics"""
    stats_data = database.get_collection_stats()
    return render_template('stats.html', stats=stats_data)

# ============================================================================
# ============================================================================
# ADMIN / MAINTENANCE
# ============================================================================

@app.route('/admin/fix-all', methods=['POST'])
def fix_all():
    """Combined batch: fix artist_sort + fetch marketplace prices in one pass.
    Processes 50 records per call; client auto-continues until done.

    Per record (max 4 Discogs calls):
      1. get_release_details  — used for both sort fix and as a cross-check
      2. get_artist_details   — only when release-level artists_sort didn't help
      3. marketplace/stats    — for price low + num_for_sale
      4. marketplace/search   — only when num_for_sale > 1
    """
    import re
    records = database.get_records_needing_fix(limit=10)

    sort_fixed = 0
    sort_band = 0       # confirmed band — sort left as display name (correct)
    price_fetched = 0
    price_none = 0
    errors = 0

    conn = database.get_db()

    for rec in records:
        rid         = rec['id']
        artist      = rec['artist'] or ''
        artist_sort = rec['artist_sort'] or ''
        discogs_id  = rec['discogs_id']

        needs_sort  = (not artist_sort or artist_sort == artist)
        # Re-read price status from live DB in case a previous batch already set it
        row = conn.execute('SELECT price_lowest FROM collection WHERE id=?', (rid,)).fetchone()
        needs_price = (row is None or row['price_lowest'] is None)

        if not (needs_sort or needs_price):
            continue

        # ── Step 1: fetch release details (shared for sort + sanity) ──────────
        try:
            time.sleep(1.2)
            rel = discogs.get_release_details(int(discogs_id))
        except Exception as e:
            print(f"Error fetching release {discogs_id} for record {rid}: {e}")
            rel = None

        if not rel:
            # Dead release ID — stamp price_lowest=0 so it leaves the queue
            conn.execute('''UPDATE collection SET price_lowest=0, price_median=0,
                price_highest=0, price_currency='', price_updated=? WHERE id=?''',
                (datetime.utcnow().isoformat()[:10], rid))
            errors += 1
            continue

        # ── Step 2: sort fix ───────────────────────────────────────────────────
        if needs_sort:
            # Strip disambiguation suffix first
            clean_artist = re.sub(r'\s*\(\d+\)\s*$', '', artist.strip()).strip()
            _, new_sort = _clean_discogs_artist(rel, clean_artist)

            if new_sort and new_sort != clean_artist:
                # Discogs release-level artists_sort gave us a proper sort name
                new_sort = _normalize_artist_sort(new_sort)
                conn.execute('UPDATE collection SET artist=?, artist_sort=? WHERE id=?',
                             (clean_artist, new_sort, rid))
                sort_fixed += 1
            else:
                # Try the artist profile — realname present means real person
                release_artists = rel.get('artists', [])
                artist_discogs_id = release_artists[0].get('id') if release_artists else None
                fixed = False
                if artist_discogs_id:
                    try:
                        time.sleep(1.2)
                        artist_data = discogs.get_artist_details(artist_discogs_id)
                        if artist_data and artist_data.get('realname', '').strip():
                            inverted = discogs.invert_person_name(clean_artist)
                            inverted = _normalize_artist_sort(inverted)
                            conn.execute('UPDATE collection SET artist=?, artist_sort=? WHERE id=?',
                                         (clean_artist, inverted, rid))
                            sort_fixed += 1
                            fixed = True
                        else:
                            # Confirmed band — sort name is display name, which is correct
                            if clean_artist != artist:
                                conn.execute('UPDATE collection SET artist=? WHERE id=?',
                                             (clean_artist, rid))
                            sort_band += 1
                            fixed = True
                    except Exception as e:
                        print(f"Error fetching artist profile for record {rid}: {e}")

                if not fixed:
                    errors += 1

        # ── Step 3: price fetch ────────────────────────────────────────────────
        if needs_price:
            try:
                prices = discogs.get_marketplace_prices(int(discogs_id))
                if prices:
                    conn.execute('''
                        UPDATE collection
                        SET price_lowest=?, price_median=?, price_highest=?,
                            price_currency=?, price_updated=?
                        WHERE id=?
                    ''', (prices['lowest'], prices['median'], prices['highest'],
                          prices['currency'], datetime.utcnow().isoformat()[:10], rid))
                    price_fetched += 1
                else:
                    # No listings — store 0 so we skip on future runs
                    conn.execute('''
                        UPDATE collection
                        SET price_lowest=0, price_median=0, price_highest=0,
                            price_currency='', price_updated=?
                        WHERE id=?
                    ''', (datetime.utcnow().isoformat()[:10], rid))
                    price_none += 1
            except Exception as e:
                print(f"Error fetching prices for record {rid}: {e}")
                # Store 0 so this record is not retried endlessly
                conn.execute('''
                    UPDATE collection
                    SET price_lowest=0, price_median=0, price_highest=0,
                        price_currency='', price_updated=?
                    WHERE id=?
                ''', (datetime.utcnow().isoformat()[:10], rid))
                errors += 1

    conn.commit()
    conn.close()

    remaining = database.count_records_needing_fix()

    return jsonify({
        'success': True,
        'batch_size': len(records),
        'sort_fixed': sort_fixed,
        'sort_band': sort_band,
        'price_fetched': price_fetched,
        'price_none': price_none,
        'errors': errors,
        'remaining': remaining,
        'done': remaining == 0
    })

# ============================================================================

@app.route('/admin/fetch-prices', methods=['POST'])
def fetch_prices():
    """Batch-fetch marketplace prices from Discogs.
    Processes up to 100 records per call; client should keep calling until remaining == 0."""
    records = database.get_records_without_prices(limit=100)
    remaining_before = database.count_records_without_prices()

    fetched = 0
    no_listing = 0
    errors = 0

    for rec in records:
        release_id = rec['discogs_id']
        try:
            prices = discogs.get_marketplace_prices(int(release_id))
            if prices:
                database.update_record_prices(
                    rec['id'],
                    prices['lowest'],
                    prices['median'],
                    prices['highest'],
                    prices['currency']
                )
                fetched += 1
            else:
                # No listings — store zeros so we don't re-try every run
                database.update_record_prices(rec['id'], 0, 0, 0, '')
                no_listing += 1
        except Exception as e:
            print(f"Error fetching prices for record {rec['id']}: {e}")
            database.update_record_prices(rec['id'], 0, 0, 0, '')
            errors += 1
        time.sleep(1.2)

    remaining_after = database.count_records_without_prices()

    return jsonify({
        'success': True,
        'batch_size': len(records),
        'fetched': fetched,
        'no_listing': no_listing,
        'errors': errors,
        'remaining': remaining_after,
        'done': remaining_after == 0
    })

# ============================================================================

@app.route('/admin/fix-shelf-sections', methods=['POST'])
def fix_shelf_sections():
    """Fix records whose shelf_section doesn't match their sort_order position."""
    shelf_bounds = [
        ('Shelf 1',   100,    9700),
        ('Shelf 2',   9800,   19600),
        ('Shelf 3',   19700,  29400),
        ('Shelf 4',   29500,  39200),
        ('Shelf 5',   39300,  48000),
        ('Shelf 6',   48100,  57500),
        ('Shelf 7',   57600,  69500),
        ('Shelf 8',   69600,  78100),
        ('Shelf 9',   78200,  87200),
        ('Shelf 10',  87300,  93400),
        ('Shelf 11',  93500,  105200),
        ('Shelf 12',  105300, 999999),
    ]
    conn = database.get_db()
    rows = conn.execute("""
        SELECT id, sort_order, shelf_section FROM collection
        WHERE notes != 'alpha-divider' AND duplicate_flag = 0
          AND shelf_section LIKE 'Shelf %'
          AND sort_order IS NOT NULL
          AND CAST(REPLACE(shelf_section,'Shelf ','') AS INTEGER) <= 12
    """).fetchall()
    fixes = []
    for r in rows:
        for shelf, lo, hi in shelf_bounds:
            if lo <= r['sort_order'] <= hi:
                if r['shelf_section'] != shelf:
                    fixes.append((shelf, r['id']))
                break
    if fixes:
        conn.executemany('UPDATE collection SET shelf_section=? WHERE id=?', fixes)
        conn.commit()
    conn.close()
    return jsonify({'success': True, 'fixed': len(fixes)})

@app.route('/admin/retag-genres', methods=['POST'])
def retag_genres():
    """Comprehensive genre migration: Easy Listening, Classical, and Latin corrections."""
    easy_listening = [
        # Orchestral mood / lounge / cocktail
        159,   # Living Strings - Play Henry Mancini
        209,   # Art Van Damme Quintet - Martini Time
        212,   # Hugo Winterhalter Orchestra
        339,   # Various - Aloha Hawaii
        442,   # Banda De La Plaza De Toros - Music Of The Bullring
        454,   # Living Marimbas - Love Is Blue
        470,   # Various - Winter Warnerland
        492,   # Nick Arnold Orchestra - Valentino Tangos
        494,   # Various - This Is Stereorama
        517,   # Imre Magyari - Hungarian Gypsy Music
        522,   # Various - 12 Greatest Hits San Remo 1961
        540,   # Roger Williams - By Special Request
        544,   # Rudi Bohn Und Sein Orchester - Percussive Oompah
        546,   # Russ Case - Gypsy Moods
        547,   # Various - Tavana's Polynesia
        548,   # Howard Keel - With Love
        594,   # Max Greger - Tanz '74
        647,   # Shirley Bassey - Shirley Bassey
        678,   # Various - Music To Read James Bond By
        806,   # Jackie Gleason - Music, Martinis, And Memories
        852,   # Arthur Fiedler - Pops Varieties
        853,   # Various - Mood Music For Listening And Relaxation
        854,   # Various - Hear Them Again!
        855,   # Bing Crosby - Bing Sings 96 Greatest Hits
        856,   # Los Norte Americanos
        860,   # placeholder removed
        861,   # Various - Magnificent Sounds Of Guitar/Mandolin/Accordion
        862,   # Various - Designed For Dancing
        866,   # Peggy Lee - Olé Ala Lee!
        887,   # Edmundo Ros - Bongos From The South
        889,   # Frank Sinatra - That Old Feeling
        890,   # The Somerset Strings - Look For The Silver Lining
        902,   # Various - Music Box
        947,   # Arthur Lyman - Taboo
        949,   # Henry Mancini - The Pink Panther
        950,   # Henry Mancini - Breakfast At Tiffany's
        951,   # Freddy Martin - Dancing Party
        952,   # Johnny Mathis - Open Fire, Two Guitars
        959,   # Ray Conniff - Hollywood In Rhythm
        960,   # Bing Crosby - Merry Christmas
        968,   # Ernie Heckscher - Dance Atop Nob Hill
        974,   # Manos Hadjidakis - Never On Sunday
        975,   # Ray Noble - We Danced All Night
        977,   # André Previn And His Orchestra - Like Love
        988,   # Julie London - The Best Of Julie
        994,   # Chorus And Percussion Of Keith Textor - Sounds Sensational
        995,   # Don Catelli - Passionate Percussion
        996,   # Karl Reiner - Percussion Classics
        1004,  # Juan Garcia Esquivel - Space-Age Bachelor Pad Music
        1027,  # Maxwell Davis - Persistent Percussion
        1028,  # Four Roses Society - Sing With The Four Roses Society
        1029,  # Vibrant Percussion
        1053,  # Jackie Gleason - Music For Lovers Only
        1055,  # Various - Music To Live By
        1088,  # Various - 60 Years Of Music America Loves Best
        1089,  # Arthur Murray Favorites - Rhumbas
        1139,  # Various - Around The World In 36 Melodies
        204,   # Mikis Theodorakis - Zorba The Greek
        417,   # Carmen Cavallaro - Cavallaro With That Latin Beat
    ]

    classical = [
        208,   # Levant Plays Gershwin
        416,   # Carmen Jones (opera adaptation)
        506,   # Oklahoma (Rodgers & Hammerstein)
        891,   # The Sound Of Music
        892,   # South Pacific (Fred Waring)
        893,   # Big Hits From Broadway (Cyril Stapleton)
        948,   # Jeanette MacDonald (opera singer)
        961,   # Doctor Zhivago (symphonic score)
        973,   # My Fair Lady
        1030,  # Milk and Honey (Broadway cast)
    ]

    # Latin/flamenco records that fit on the Easy Listening shelf
    easy_listening += [
        696,   # Trio Los Panchos
        1072,  # Carlos Montoya - Flamenco
    ]

    conn = database.get_db()
    real_el = [i for i in easy_listening if i != 860]  # drop placeholder
    conn.executemany('UPDATE collection SET genre = ? WHERE id = ?',
                     [('Easy Listening', i) for i in real_el])
    conn.executemany('UPDATE collection SET genre = ? WHERE id = ?',
                     [('Classical', i) for i in classical])
    conn.commit()
    updated = conn.total_changes
    conn.close()
    return jsonify({'success': True, 'updated': updated,
                    'easy_listening': len(real_el), 'classical': len(classical)})
    return jsonify({'success': True, 'updated': updated})

@app.route('/admin/fix-artist-data', methods=['POST'])
def fix_artist_data():
    """One-time fix for existing records:
    1. Strip Discogs disambiguation suffix (2), (3) from artist and artist_sort.
    2. For records where artist_sort == artist (no sort transform was applied)
       and a discogs_id exists, re-fetch artists_sort from Discogs.
    Returns a summary of changes made."""
    import re
    conn = database.get_db()
    records = conn.execute('SELECT id, artist, artist_sort, discogs_id FROM collection').fetchall()

    strip_updates = []
    resync_updates = []

    for r in records:
        rid = r['id']
        artist = r['artist'] or ''
        artist_sort = r['artist_sort'] or ''
        discogs_id = r['discogs_id']

        # 1. Strip disambiguation suffix
        clean_artist = re.sub(r'\s*\(\d+\)\s*$', '', artist.strip()).strip()
        clean_sort = re.sub(r'\s*\(\d+\)\s*$', '', artist_sort.strip()).strip()

        changed = clean_artist != artist or clean_sort != artist_sort
        if changed:
            strip_updates.append((clean_artist, clean_sort, rid))

        # 2. Re-fetch artists_sort from Discogs when sort == display name and discogs_id exists
        effective_sort = clean_sort if changed else artist_sort
        effective_artist = clean_artist if changed else artist
        if discogs_id and effective_sort == effective_artist and ',' not in effective_sort:
            resync_updates.append((rid, discogs_id, effective_artist))

    # Apply suffix-strip updates immediately
    for new_artist, new_sort, rid in strip_updates:
        conn.execute('UPDATE collection SET artist=?, artist_sort=? WHERE id=?',
                     (new_artist, new_sort, rid))

    # Re-fetch artists_sort from Discogs for records that need it
    # 1.2s between calls stays well under Discogs 60 req/min limit
    resynced = 0
    failed_resync = 0
    for rid, discogs_id, fallback_artist in resync_updates:
        time.sleep(1.2)
        try:
            rel = discogs.get_release_details(int(discogs_id))
            if not rel:
                conn.execute('UPDATE collection SET needs_review=1 WHERE id=?', (rid,))
                failed_resync += 1
                continue

            _, new_sort = _clean_discogs_artist(rel, fallback_artist)

            if new_sort and new_sort != fallback_artist:
                # Discogs release-level artists_sort gave us something useful
                conn.execute('UPDATE collection SET artist_sort=? WHERE id=?', (new_sort, rid))
                resynced += 1
            else:
                # Release-level sort didn't help — check the artist profile directly.
                # If the artist has a realname set they are a real person; invert the
                # display name (e.g. "Al Green" -> "Green, Al").
                # If no realname they are a band/group and the name stays as-is.
                artists = rel.get('artists', [])
                artist_id = artists[0].get('id') if artists else None
                inverted = False
                if artist_id:
                    time.sleep(1.2)
                    artist_data = discogs.get_artist_details(artist_id)
                    if artist_data and artist_data.get('realname', '').strip():
                        # Confirmed person — invert display name for sort
                        inverted_sort = discogs.invert_person_name(fallback_artist)
                        inverted_sort = _normalize_artist_sort(inverted_sort)
                        conn.execute('UPDATE collection SET artist_sort=? WHERE id=?',
                                     (inverted_sort, rid))
                        resynced += 1
                        inverted = True

                if not inverted:
                    # Band name or couldn't confirm — leave sort as display name,
                    # no review flag needed (it's probably correct for a band)
                    pass

        except Exception as e:
            print(f"Error resyncing record {rid}: {e}")
            conn.execute('UPDATE collection SET needs_review=1 WHERE id=?', (rid,))
            failed_resync += 1

    conn.commit()

    return jsonify({
        'success': True,
        'suffix_stripped': len(strip_updates),
        'artist_sort_resynced': resynced,
        'artist_sort_needs_manual_review': failed_resync,
        'message': f'Fixed {len(strip_updates)} disambiguation suffixes. '
                   f'Re-synced sort name for {resynced} records (release data + artist profile check). '
                   f'{failed_resync} records could not be auto-fixed and need manual review.'
    })

# LIBRARY APP GENERATOR
# ============================================================================

def _build_app_icon_b64():
    """Generate a purple icon with a white quarter note (head + stem), centred."""
    try:
        from PIL import Image, ImageDraw
        import base64, io
        W = 512
        img = Image.new('RGB', (W, W), color=(109, 40, 217))
        draw = ImageDraw.Draw(img)
        WHITE = (255, 255, 255)

        # Quarter note: head centred horizontally, lower third of icon
        head_cx, head_cy = 235, 340
        head_rx, head_ry = 80, 56
        draw.ellipse([head_cx - head_rx, head_cy - head_ry,
                      head_cx + head_rx, head_cy + head_ry], fill=WHITE)

        # Stem: rises from right side of head
        stem_x = head_cx + head_rx - 22
        stem_top = 110
        stem_bot = head_cy - 10
        stem_w = 28
        draw.rectangle([stem_x, stem_top, stem_x + stem_w, stem_bot], fill=WHITE)

        buf = io.BytesIO()
        img.save(buf, 'PNG')
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ''

@app.route('/generate-library-app', methods=['POST'])
def generate_library_app():
    """Generate a self-contained offline HTML library app for phone use."""
    try:
        conn = database.get_db()
        records = conn.execute('''
            SELECT id, artist, artist_sort, title, year, format, genre,
                   shelf_section, sort_order, price_lowest, price_highest,
                   cover_art_path, notes, label, discogs_url, catalog_number
            FROM collection
            WHERE duplicate_flag = 0
              AND (notes != 'alpha-divider' OR notes IS NULL)
            ORDER BY
                CASE WHEN shelf_section IS NULL OR shelf_section = '' THEN 9999
                     ELSE CAST(REPLACE(shelf_section, 'Shelf ', '') AS INTEGER)
                END ASC,
                COALESCE(sort_order, 999999) ASC
        ''').fetchall()
        conn.close()

        from PIL import Image as PILImage
        import base64, io

        app_dir = os.path.abspath(os.path.dirname(__file__))
        THUMB_SIZE = 108

        def make_image_b64(cover_path, size, quality):
            if not cover_path:
                return None
            full_path = os.path.join(app_dir, cover_path)
            if not os.path.exists(full_path):
                return None
            try:
                with PILImage.open(full_path) as img:
                    img = img.convert('RGB')
                    img.thumbnail((size, size), PILImage.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, 'JPEG', quality=quality, optimize=True)
                    return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
            except Exception:
                return None

        catalog = []
        for r in records:
            shelf_num = None
            if r['shelf_section']:
                try:
                    shelf_num = int(r['shelf_section'].replace('Shelf ', ''))
                except:
                    pass
            raw_tracks = database.get_tracks(r['id'])
            tracks = [{'pos': t['position'], 'title': t['title'], 'duration': t['duration']}
                      for t in raw_tracks if t['title']]
            catalog.append({
                'artist':    r['artist'] or '',
                'title':     r['title'] or '',
                'year':      r['year'] or '',
                'format':    r['format'] or '',
                'genre':     r['genre'] or '',
                'label':       r['label'] or '',
                'artistSort':  r['artist_sort'] or '',
                'catalogNum':  r['catalog_number'] or '',
                'discogsUrl':  r['discogs_url'] or '',
                'shelf':       r['shelf_section'] or '',
                'shelfNum':  shelf_num or 999,
                'sortOrder': r['sort_order'] or 999999,
                'priceLow':  round(r['price_lowest'], 0) if r['price_lowest'] else None,
                'priceHigh': round(r['price_highest'], 0) if r['price_highest'] else None,
                'cover':     make_image_b64(r['cover_art_path'], THUMB_SIZE, 50),
                'tracks':    tracks,
            })

        catalog_json = json.dumps(catalog, ensure_ascii=False)
        generated_date = datetime.now().strftime('%B %d, %Y')
        total = len(catalog)

        # Save icon to disk so iOS can fetch it reliably as a static file
        icon_b64 = _build_app_icon_b64()
        if icon_b64:
            import base64 as _b64
            icon_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'apple-touch-icon.png')
            with open(icon_path, 'wb') as f:
                f.write(_b64.b64decode(icon_b64))
        html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Vinyl Collection">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<title>Vinyl Collection</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ height: 100%; overflow-x: hidden; }}
body {{ background: #0f172a; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; display: flex; flex-direction: column; height: 100%; padding-top: env(safe-area-inset-top); }}
#sticky-header {{ background: #1e293b; border-bottom: 1px solid #334155; flex-shrink: 0; }}
.inner {{ max-width: 480px; margin: 0 auto; width: 100%; }}
.search-wrap {{ padding: 8px 12px 6px; position: relative; }}
input[type=text] {{ width: 100%; padding: 7px 36px 7px 12px; background: #334155; color: #fff; border: none; border-radius: 8px; font-size: 0.9rem; outline: none; }}
input[type=text]::placeholder {{ color: #64748b; }}
#search-clear {{ display: none; position: absolute; right: 20px; top: 50%; transform: translateY(-50%); background: none; border: none; color: #94a3b8; font-size: 1rem; cursor: pointer; padding: 0; line-height: 1; }}
.filters {{ display: flex; gap: 5px; flex-wrap: wrap; padding: 4px 12px 6px; }}
.filter-btn {{ padding: 3px 9px; border-radius: 6px; border: none; background: #334155; color: #94a3b8; font-size: 0.68rem; cursor: pointer; white-space: nowrap; }}
.filter-btn.active {{ background: #7c3aed; color: #fff; }}
.count-bar {{ padding: 4px 12px; font-size: 0.68rem; color: #64748b; }}
#scroll-area {{ flex: 1; overflow-y: auto; -webkit-overflow-scrolling: touch; padding-bottom: env(safe-area-inset-bottom); }}
.grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 2px; padding: 2px; }}
.card {{ background: #1e293b; border-radius: 5px; overflow: hidden; cursor: default; }}
.card-cover {{ width: 100%; aspect-ratio: 1; background: #334155; display: flex; align-items: center; justify-content: center; overflow: hidden; }}
.card-cover img {{ width: 100%; height: 100%; object-fit: cover; }}
.card-cover-placeholder {{ font-size: 1.2rem; color: #475569; }}
.card-body {{ padding: 4px; }}
.card-artist {{ font-size: 0.62rem; font-weight: 600; color: #e2e8f0; margin-bottom: 1px; line-height: 1.2; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }}
.card-title {{ font-size: 0.58rem; color: #94a3b8; margin-bottom: 2px; line-height: 1.2; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }}
.card-meta {{ display: flex; flex-wrap: wrap; gap: 2px; }}
.badge {{ font-size: 0.52rem; padding: 1px 3px; border-radius: 3px; background: #334155; color: #94a3b8; }}
.badge.shelf {{ background: #312e81; color: #a5b4fc; }}
.badge.price {{ background: #14532d; color: #86efac; }}
.no-results {{ padding: 40px 16px; text-align: center; color: #475569; font-size: 0.9rem; }}
@media (orientation: landscape) {{ .grid {{ grid-template-columns: repeat(5, 1fr); }} }}
/* Lightbox */
#lightbox {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.92); z-index: 9999; align-items: flex-start; justify-content: center; overflow-y: auto; padding: 16px; }}
#lightbox.open {{ display: flex; }}
#lightbox-inner {{ background: #1e293b; border-radius: 12px; max-width: 420px; width: 100%; overflow: hidden; box-shadow: 0 20px 60px rgba(0,0,0,0.8); }}
#lightbox img {{ width: 100%; aspect-ratio: 1; object-fit: cover; display: block; }}
#lightbox-body {{ padding: 14px; }}
#lightbox-artist {{ font-size: 1rem; font-weight: 700; color: #e2e8f0; }}
#lightbox-title  {{ font-size: 0.85rem; color: #94a3b8; margin-top: 3px; }}
#lightbox-badges {{ display: flex; flex-wrap: wrap; gap: 5px; margin-top: 10px; }}
.lb-badge {{ font-size: 0.68rem; padding: 2px 7px; border-radius: 4px; background: #334155; color: #94a3b8; }}
.lb-badge.shelf {{ background: #312e81; color: #a5b4fc; }}
.lb-badge.price {{ background: #14532d; color: #86efac; font-family: monospace; }}
.lb-badge.label {{ background: #1e3a5f; color: #93c5fd; }}
#lightbox-tracks {{ margin-top: 12px; }}
#lightbox-tracks h4 {{ font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.08em; color: #475569; margin-bottom: 6px; }}
.lb-track {{ display: flex; gap: 8px; padding: 4px 0; border-top: 1px solid #334155; font-size: 0.75rem; color: #94a3b8; }}
.lb-track .pos {{ color: #475569; min-width: 22px; flex-shrink: 0; }}
.lb-track .dur {{ color: #475569; margin-left: auto; flex-shrink: 0; }}
#lightbox {{ cursor: pointer; }}
#lightbox-inner {{ cursor: default; }}
.card-cover img {{ cursor: pointer; }}
</style>
</head>
<body>
<div id="sticky-header">
  <div class="inner">
    <div class="search-wrap">
      <input type="text" id="search" placeholder="Search artist or title..." autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" oninput="applyFilters();document.getElementById('search-clear').style.display=this.value?'block':'none';">
      <button id="search-clear" onclick="document.getElementById('search').value='';applyFilters();this.style.display='none';">✕</button>
    </div>
    <div class="filters" id="filters"></div>
    <div class="count-bar">Showing <span id="count">{total}</span> of {total} records &nbsp;·&nbsp; {generated_date}</div>
  </div>
</div>
<div id="scroll-area">
  <div class="inner">
    <div class="grid" id="grid"></div>
  </div>
</div>

<div id="lightbox" onclick="closeLightbox()" ontouchend="closeLightbox()">
  <div id="lightbox-inner" onclick="event.stopPropagation()" ontouchend="event.stopPropagation()">
    <img id="lightbox-img" src="" alt="" onclick="closeLightbox()" ontouchend="closeLightbox()" style="cursor:pointer">
    <div id="lightbox-body">
      <div id="lightbox-artist"></div>
      <div id="lightbox-title"></div>
      <div id="lightbox-badges"></div>
      <div id="lightbox-tracks"></div>
    </div>
  </div>
</div>

<script>
const CATALOG = {catalog_json};

const SHELF_LABELS = {{
  14: 'Kids', 15: 'Jazz', 16: 'Classical', 17: '10 Inch', 18: 'Easy Listening', 19: 'Other'
}};

// Pre-compute per-shelf counts
const shelfCounts = {{}};
for (const r of CATALOG) {{
  if (r.shelfNum && r.shelfNum !== 999) {{
    shelfCounts[r.shelfNum] = (shelfCounts[r.shelfNum] || 0) + 1;
  }}
}}

let activeFormat = 'all';
let filteredCatalog = [];
let renderedCount = 0;
const PAGE_SIZE = 60;

// Build format filter buttons
const formats = ['all', 'Double LP', 'CD', '45', '10 Inch', 'Box Set'];
const filterEl = document.getElementById('filters');
formats.forEach(f => {{
  const b = document.createElement('button');
  b.className = 'filter-btn' + (f === 'all' ? ' active' : '');
  b.textContent = f === 'all' ? 'All' : f;
  b.onclick = () => {{
    activeFormat = f;
    document.querySelectorAll('.filter-btn').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    applyFilters();
  }};
  filterEl.appendChild(b);
}});

function shelfLabel(r) {{
  if (!r.shelf) return '';
  const n = r.shelfNum;
  const total = shelfCounts[n] || '';
  const extra = SHELF_LABELS[n] ? ` · ${{SHELF_LABELS[n]}}` : '';
  return `${{r.shelf}} / ${{total}}${{extra}}`;
}}

function openLightbox(idx) {{
  const r = CATALOG[idx];
  document.getElementById('lightbox-img').src = r.cover || '';
  document.getElementById('lightbox-artist').textContent = r.artist;
  const sortLine = (r.artistSort && r.artistSort !== r.artist) ? `Sort: ${{r.artistSort}}` : '';
  document.getElementById('lightbox-title').innerHTML =
    `<div style="margin-top:3px;color:#94a3b8;font-size:0.85rem">${{r.title}}${{r.year ? ' (' + r.year + ')' : ''}}</div>` +
    (sortLine ? `<div style="margin-top:2px;color:#475569;font-size:0.72rem">${{sortLine}}</div>` : '');

  const shelf = shelfLabel(r);
  const badges = [];
  if (shelf)        badges.push(`<span class="lb-badge shelf">${{shelf}}</span>`);
  if (r.label)      badges.push(`<span class="lb-badge label">${{r.label}}</span>`);
  if (r.catalogNum) badges.push(`<span class="lb-badge">${{r.catalogNum}}</span>`);
  if (r.format)     badges.push(`<span class="lb-badge">${{r.format}}</span>`);
  if (r.genre)      badges.push(`<span class="lb-badge">${{r.genre}}</span>`);
  if (r.priceLow)   badges.push(`<span class="lb-badge price">$${{r.priceLow}}${{r.priceHigh ? ' – $${{r.priceHigh}}' : ''}} low ask</span>`);
  if (r.discogsUrl) badges.push(`<a href="${{r.discogsUrl}}" target="_blank" style="text-decoration:none"><span class="lb-badge" style="background:#1a1a2e;color:#818cf8">Discogs ↗</span></a>`);
  document.getElementById('lightbox-badges').innerHTML = badges.join('');

  const tracksEl = document.getElementById('lightbox-tracks');
  if (r.tracks && r.tracks.length) {{
    let html = '<h4>Track Listing</h4>';
    r.tracks.forEach(t => {{
      html += `<div class="lb-track"><span class="pos">${{t.pos || ''}}</span><span>${{t.title}}</span>${{t.duration ? '<span class="dur">' + t.duration + '</span>' : ''}}</div>`;
    }});
    tracksEl.innerHTML = html;
  }} else {{
    tracksEl.innerHTML = '';
  }}
  document.getElementById('lightbox').classList.add('open');
}}

function closeLightbox() {{
  document.getElementById('lightbox').classList.remove('open');
  document.getElementById('lightbox-img').src = '';
}}

function renderCard(r, catalogIdx) {{
  const shelf = shelfLabel(r);
  const price = r.priceLow ? `$${{r.priceLow}}` + (r.priceHigh ? `–$${{r.priceHigh}}` : '') : '';
  const coverHtml = r.cover
    ? `<img src="${{r.cover}}" alt="" onclick="event.stopPropagation();openLightbox(${{catalogIdx}})">`
    : `<div class="card-cover-placeholder">🎵</div>`;
  return `<div class="card">
    <div class="card-cover">${{coverHtml}}</div>
    <div class="card-body">
      <div class="card-artist">${{r.artist}}</div>
      <div class="card-title">${{r.title}}${{r.year ? ' (' + r.year + ')' : ''}}</div>
      <div class="card-meta">
        ${{r.format ? `<span class="badge">${{r.format}}</span>` : ''}}
        ${{shelf ? `<span class="badge shelf">${{shelf}}</span>` : ''}}
        ${{price ? `<span class="badge price">${{price}}</span>` : ''}}
      </div>
    </div>
  </div>`;
}}

function applyFilters() {{
  const q = document.getElementById('search').value.toLowerCase().trim();
  filteredCatalog = [];
  for (let i = 0; i < CATALOG.length; i++) {{
    const r = CATALOG[i];
    if (activeFormat !== 'all' && r.format !== activeFormat) continue;
    if (q && !r.artist.toLowerCase().includes(q) && !r.title.toLowerCase().includes(q)) continue;
    filteredCatalog.push(i);
  }}
  renderedCount = 0;
  const grid = document.getElementById('grid');
  grid.innerHTML = '';
  document.getElementById('scroll-area').scrollTop = 0;
  renderNextBatch();
  document.getElementById('count').textContent = filteredCatalog.length;
}}

function renderNextBatch() {{
  const grid = document.getElementById('grid');
  if (renderedCount >= filteredCatalog.length) {{
    if (filteredCatalog.length === 0) {{
      grid.innerHTML = '<div class="no-results">No records found</div>';
    }}
    return;
  }}
  const end = Math.min(renderedCount + PAGE_SIZE, filteredCatalog.length);
  let html = '';
  for (let i = renderedCount; i < end; i++) {{
    const catalogIdx = filteredCatalog[i];
    html += renderCard(CATALOG[catalogIdx], catalogIdx);
  }}
  grid.insertAdjacentHTML('beforeend', html);
  renderedCount = end;
}}

// Load more cards when user scrolls near the bottom
document.getElementById('scroll-area').addEventListener('scroll', function() {{
  const el = this;
  if (el.scrollHeight - el.scrollTop - el.clientHeight < 300) {{
    renderNextBatch();
  }}
}});

applyFilters();
</script>
<script>
if ('serviceWorker' in navigator) {{
    navigator.serviceWorker.register('/service-worker.js')
        .catch(function(e) {{ console.log('SW error', e); }});
}}
</script>
</body>
</html>'''

        output_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'library-app.html')
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)

        return jsonify({'success': True, 'path': output_path, 'total': total})

    except Exception as e:
        import traceback
        return jsonify({'success': False, 'error': str(e), 'trace': traceback.format_exc()}), 500

# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(error):
    return render_template('500.html'), 500

# ============================================================================
# SETTINGS
# ============================================================================

LAUNCHAGENT_LABEL = 'com.vinyl-catalog.server'
LAUNCHAGENT_PATH  = Path.home() / 'Library' / 'LaunchAgents' / f'{LAUNCHAGENT_LABEL}.plist'


def _is_autostart_enabled():
    return LAUNCHAGENT_PATH.exists()


def _write_launchagent_plist():
    """Generate and write the LaunchAgent plist using this app's actual runtime paths."""
    app_path = os.path.abspath(__file__)
    work_dir = os.path.dirname(app_path)
    log_path = os.path.join(work_dir, 'flask.log')
    py_path  = sys.executable
    LAUNCHAGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHAGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{py_path}</string>
        <string>{app_path}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{work_dir}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>"""
    LAUNCHAGENT_PATH.write_text(plist)


@app.route('/settings')
def settings():
    return render_template('settings.html', autostart=_is_autostart_enabled())


@app.route('/settings/autostart/enable', methods=['POST'])
def settings_autostart_enable():
    try:
        _write_launchagent_plist()
        result = subprocess.run(
            ['launchctl', 'load', str(LAUNCHAGENT_PATH)],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 or 'already loaded' in (result.stderr or ''):
            return jsonify({'ok': True})
        return jsonify({'ok': False, 'error': result.stderr.strip() or 'launchctl load failed'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@app.route('/settings/autostart/disable', methods=['POST'])
def settings_autostart_disable():
    try:
        if LAUNCHAGENT_PATH.exists():
            subprocess.run(
                ['launchctl', 'unload', str(LAUNCHAGENT_PATH)],
                capture_output=True, text=True, timeout=10
            )
            LAUNCHAGENT_PATH.unlink(missing_ok=True)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@app.route('/settings/save-token', methods=['POST'])
def settings_save_token():
    token = (request.json or {}).get('token', '').strip()
    if not token:
        return jsonify({'ok': False, 'error': 'No token provided'})
    _save_env_value('DISCOGS_TOKEN', token)
    _save_env_value('SETUP_COMPLETE', '1')
    return jsonify({'ok': True})


@app.route('/settings/save-username', methods=['POST'])
def settings_save_username():
    username = (request.json or {}).get('username', '').strip()
    if not username:
        return jsonify({'ok': False, 'error': 'No username provided'})
    _save_env_value('DISCOGS_USERNAME', username)
    return jsonify({'ok': True})


_sync_state = {'running': False, 'added': 0, 'skipped': 0, 'errors': 0, 'done': 0, 'total': 0, 'finished': False, 'error': None, 'last_status': None, 'last_msg': '', 'status_counts': {}, 'failed_records': []}

def _run_discogs_sync(token, username, records, mark_synced=True):
    import time, re, threading
    global _sync_state
    _sync_state.update({'running': True, 'added': 0, 'skipped': 0, 'errors': 0, 'done': 0,
                        'total': len(records), 'finished': False, 'error': None,
                        'last_status': None, 'last_msg': '', 'status_counts': {}, 'failed_records': []})
    headers = {
        'Authorization': f'Discogs token={token}',
        'User-Agent': 'VinylCatalog/1.0',
        'Content-Type': 'application/json',
    }
    for r in records:
        url_str = r['discogs_url'] or ''
        # Handle both /release/NNN and /master/NNN URLs
        m = re.search(r'/release/(\d+)', url_str)
        if not m:
            # Try master: fetch main_release_id from Discogs
            mm = re.search(r'/master/(\d+)', url_str)
            if mm:
                try:
                    mresp = requests.get(
                        f'https://api.discogs.com/masters/{mm.group(1)}',
                        headers=headers, timeout=10
                    )
                    if mresp.status_code == 200:
                        main_id = mresp.json().get('main_release')
                        if main_id:
                            m = type('M', (), {'group': lambda self, x: str(main_id)})()
                    time.sleep(0.26)
                except Exception:
                    pass
        if not m:
            _sync_state['skipped'] += 1
            _sync_state['done'] += 1
            continue
        release_id = m.group(1)
        api_url = f'https://api.discogs.com/users/{username}/collection/folders/1/releases/{release_id}'
        for attempt in range(4):   # up to 3 retries on 429
            try:
                resp = requests.post(api_url, headers=headers, timeout=10)
                if resp.status_code in (200, 201):
                    _sync_state['added'] += 1
                    if mark_synced:
                        try:
                            c = database.get_db()
                            c.execute("UPDATE collection SET discogs_synced_at = ? WHERE id = ?",
                                      (datetime.utcnow().isoformat()[:19], r['id']))
                            c.commit()
                            c.close()
                        except Exception:
                            pass
                    break
                elif resp.status_code == 429:
                    wait = 65 if attempt < 3 else 0
                    _sync_state['last_status'] = 429
                    _sync_state['last_msg'] = f'Rate limited — waiting {wait}s (attempt {attempt+1})'
                    if wait:
                        time.sleep(wait)
                    else:
                        _sync_state['errors'] += 1
                        _sync_state['status_counts']['429'] = _sync_state['status_counts'].get('429', 0) + 1
                        break
                else:
                    _sync_state['errors'] += 1
                    sc = str(resp.status_code)
                    _sync_state['status_counts'][sc] = _sync_state['status_counts'].get(sc, 0) + 1
                    _sync_state['failed_records'].append({'artist': r['artist'], 'title': r['title'], 'status': resp.status_code})
                    break
            except Exception as e:
                _sync_state['errors'] += 1
                _sync_state['status_counts']['network'] = _sync_state['status_counts'].get('network', 0) + 1
                _sync_state['failed_records'].append({'artist': r['artist'], 'title': r['title'], 'status': 'network'})
                break
        _sync_state['done'] += 1
        time.sleep(1.0)
    _sync_state['running'] = False
    _sync_state['finished'] = True


@app.route('/settings/sync-discogs', methods=['POST'])
def settings_sync_discogs():
    """Start a background sync of local records to Discogs collection.
    Pass {"full": true} to re-sync all records regardless of prior sync status."""
    import threading
    global _sync_state
    if _sync_state.get('running'):
        return jsonify({'ok': False, 'error': 'Sync already in progress.'})
    token    = os.getenv('DISCOGS_TOKEN', '')
    username = os.getenv('DISCOGS_USERNAME', '')
    if not token:
        return jsonify({'ok': False, 'error': 'No Discogs token saved.'})
    if not username:
        return jsonify({'ok': False, 'error': 'No Discogs username saved — add it in Settings first.'})
    full_sync = (request.json or {}).get('full', False)
    conn = database.get_db()
    if full_sync:
        where = "discogs_url IS NOT NULL AND discogs_url != '' AND (notes != 'alpha-divider' OR notes IS NULL)"
    else:
        where = "discogs_url IS NOT NULL AND discogs_url != '' AND discogs_synced_at IS NULL AND (notes != 'alpha-divider' OR notes IS NULL)"
    records = conn.execute(
        f"SELECT id, artist, title, discogs_url FROM collection WHERE {where}"
    ).fetchall()
    conn.close()
    t = threading.Thread(target=_run_discogs_sync, args=(token, username, records), daemon=True)
    t.start()
    return jsonify({'ok': True, 'started': True, 'total': len(records), 'full': full_sync})


@app.route('/settings/sync-status')
def settings_sync_status():
    return jsonify(_sync_state)


@app.route('/settings/sync-errors-csv')
def settings_sync_errors_csv():
    """Download failed sync records as Excel (.xlsx)."""
    import io, openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Sync Errors'
    ws.append(['Artist', 'Title', 'HTTP Status'])
    header_fill = PatternFill(start_color='1E293B', end_color='1E293B', fill_type='solid')
    header_font = Font(bold=True, color='E2E8F0')
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
    for r in _sync_state.get('failed_records', []):
        ws.append([r['artist'], r['title'], r['status']])
    ws.column_dimensions['A'].width = 40
    ws.column_dimensions['B'].width = 45
    ws.column_dimensions['C'].width = 14
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(buf.getvalue(),
                    mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': 'attachment; filename=sync-errors.xlsx'})


@app.route('/export-csv')
def export_csv():
    """Download the full collection as a CSV file."""
    import csv, io
    conn = database.get_db()
    records = conn.execute(
        "SELECT artist, title, format, year, label, catalog_number, shelf_section, discogs_url "
        "FROM collection "
        "WHERE (notes != 'alpha-divider' OR notes IS NULL) "
        "ORDER BY artist_sort ASC, year ASC, title ASC"
    ).fetchall()
    conn.close()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Artist', 'Title', 'Format', 'Year', 'Label', 'Catalog #', 'Shelf', 'Discogs URL'])
    for r in records:
        writer.writerow([r['artist'], r['title'], r['format'], r['year'],
                         r['label'], r['catalog_number'], r['shelf_section'], r['discogs_url']])
    return Response(buf.getvalue().encode('utf-8'), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=my-collection.csv'})


@app.route('/export-xlsx')
def export_xlsx():
    """Download the full collection as an Excel (.xlsx) file."""
    import io
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    conn = database.get_db()
    records = conn.execute(
        "SELECT artist, title, format, year, label, catalog_number, shelf_section, discogs_url "
        "FROM collection "
        "WHERE (notes != 'alpha-divider' OR notes IS NULL) "
        "ORDER BY artist_sort ASC, year ASC, title ASC"
    ).fetchall()
    conn.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Collection'

    headers = ['Artist', 'Title', 'Format', 'Year', 'Label', 'Catalog #', 'Shelf', 'Discogs URL']
    ws.append(headers)

    # Style the header row
    header_fill = PatternFill(start_color='1E293B', end_color='1E293B', fill_type='solid')
    header_font = Font(bold=True, color='E2E8F0')
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='left')

    for r in records:
        ws.append([r['artist'], r['title'], r['format'], r['year'],
                   r['label'], r['catalog_number'], r['shelf_section'], r['discogs_url']])

    # Auto-fit column widths (approximate)
    col_widths = [40, 45, 12, 6, 30, 16, 10, 50]
    for i, width in enumerate(col_widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = width

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(
        buf.getvalue(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': 'attachment; filename=my-collection.xlsx'}
    )


@app.route('/generate-phone-pdf-covers', methods=['POST'])
def generate_phone_pdf_covers():
    """Generate a PDF library list with 80x80 cover art thumbnails."""
    try:
        conn = database.get_db()
        records = conn.execute(
            "SELECT artist, title, format, cover_art_path, discogs_url FROM collection "
            "WHERE (notes != 'alpha-divider' OR notes IS NULL) "
            "ORDER BY artist_sort ASC, year ASC, title ASC"
        ).fetchall()
        conn.close()

        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Image as RLImage, Flowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from PIL import Image as PILImage
        import io

        from reportlab.lib.utils import ImageReader

        class LinkedImage(Flowable):
            """Image that opens a URL when clicked in a PDF reader."""
            def __init__(self, img_buf, width, height, url=None):
                Flowable.__init__(self)
                self.img_buf = img_buf
                self.width = width
                self.height = height
                self.url = url
            def draw(self):
                self.img_buf.seek(0)
                self.canv.drawImage(ImageReader(self.img_buf), 0, 0, self.width, self.height)
                if self.url:
                    self.canv.linkURL(self.url, (0, 0, self.width, self.height), relative=1)

        BASE_DIR = os.path.abspath(os.path.dirname(__file__))
        THUMB_PX = 80

        out_path = os.path.join(BASE_DIR, 'phone-list-covers.pdf')
        doc = SimpleDocTemplate(out_path, pagesize=letter,
                                leftMargin=0.5*inch, rightMargin=0.5*inch,
                                topMargin=0.5*inch, bottomMargin=0.5*inch)

        styles = getSampleStyleSheet()
        cell_style = ParagraphStyle('c', parent=styles['Normal'], fontSize=20, leading=24)

        VINYL_COLOR  = colors.HexColor('#4f46e5')
        CD_COLOR     = colors.HexColor('#0891b2')
        INCH45_COLOR = colors.HexColor('#db2777')

        THUMB_INCH = THUMB_PX / 96.0

        data = []
        row_colors = []

        for i, r in enumerate(records):
            fmt_lower = (r['format'] or '').lower()
            if 'cd' in fmt_lower:
                color = CD_COLOR
            elif '7 inch' in fmt_lower or fmt_lower == '45' or '7"' in fmt_lower:
                color = INCH45_COLOR
            else:
                color = VINYL_COLOR

            thumb_cell = ''
            cover_path = r['cover_art_path']
            discogs_url = r['discogs_url'] or None
            if cover_path:
                full_path = os.path.join(BASE_DIR, cover_path)
                if os.path.exists(full_path):
                    try:
                        img = PILImage.open(full_path).convert('RGB')
                        img.thumbnail((THUMB_PX, THUMB_PX), PILImage.LANCZOS)
                        buf = io.BytesIO()
                        img.save(buf, format='JPEG', quality=60, optimize=True)
                        buf.seek(0)
                        thumb_cell = LinkedImage(buf, THUMB_INCH*inch, THUMB_INCH*inch, url=discogs_url)
                    except Exception:
                        thumb_cell = ''

            row_colors.append((i, color))
            data.append([
                thumb_cell,
                Paragraph(r['artist'] or '', cell_style),
                Paragraph(r['title']  or '', cell_style),
            ])

        col_widths = [THUMB_INCH*inch + 4, 2.8*inch, 3.7*inch]
        row_h = max(THUMB_INCH*inch + 4, 0.35*inch)

        table = Table(data, colWidths=col_widths,
                      rowHeights=[row_h] * len(records))

        ts = [
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, colors.HexColor('#f8fafc')]),
            ('TOPPADDING',     (0,0), (-1,-1), 2),
            ('BOTTOMPADDING',  (0,0), (-1,-1), 2),
            ('LEFTPADDING',    (0,0), (0,-1),  2),
            ('RIGHTPADDING',   (0,0), (0,-1),  2),
            ('GRID',           (0,0), (-1,-1), 0.25, colors.HexColor('#e2e8f0')),
            ('VALIGN',         (0,0), (-1,-1), 'MIDDLE'),
        ]
        for row_idx, color in row_colors:
            ts.append(('TEXTCOLOR', (1, row_idx), (2, row_idx), color))
            ts.append(('FONTNAME',  (1, row_idx), (2, row_idx), 'Helvetica-Bold'))

        table.setStyle(TableStyle(ts))
        doc.build([table])

        return send_file(out_path, as_attachment=True, download_name='phone-list-covers.pdf',
                         mimetype='application/pdf')
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# FIRST-RUN SETUP WIZARD
# ============================================================================

def _is_setup_complete():
    """True once a valid Discogs token has been saved, or setup was explicitly skipped."""
    if os.getenv('SETUP_COMPLETE') == '1':
        return True
    token = os.getenv('DISCOGS_TOKEN', '')
    return bool(token and token not in ('your_discogs_token_here', ''))


def _get_local_ip():
    """Best-effort LAN IP (not loopback)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def _parse_discogs_format(formats):
    """Derive a clean format string from a Discogs formats list.
    Checks descriptions before name so 7\"/10\"/12\" singles are detected correctly."""
    if not formats:
        return ''
    desc = formats[0].get('descriptions', [])
    name = formats[0].get('name', '')
    # Check size descriptions first (singles stored as Vinyl with a size description)
    if '7"' in desc:
        return '7 Inch'
    if '10"' in desc:
        return '10 Inch'
    if '12"' in desc:
        # 12" could be a single/maxi or an EP — use EP if 'EP' also in desc, else 12 Inch
        return 'EP' if 'EP' in desc else '12 Inch'
    if 'LP' in desc or 'LP' in name:
        return 'Double LP' if 'Double' in desc else 'LP'
    if 'EP' in desc:
        return 'EP'
    if 'CD' in name:
        return 'CD'
    return name


def _save_env_value(key, value):
    """Write/update a single KEY=value line in .env and apply it to os.environ."""
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    lines = []
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            lines = f.readlines()
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f'{key}='):
            lines[i] = f'{key}={value}\n'
            updated = True
            break
    if not updated:
        lines.append(f'{key}={value}\n')
    with open(env_path, 'w') as f:
        f.writelines(lines)
    os.environ[key] = value


@app.before_request
def require_setup():
    """Redirect to the setup wizard on first run."""
    if request.path.startswith('/setup') or request.path.startswith('/static'):
        return None
    if not _is_setup_complete():
        return redirect(url_for('setup_wizard'))


@app.route('/setup')
def setup_wizard():
    return render_template('setup.html', local_ip=_get_local_ip())


@app.route('/setup/test-token', methods=['POST'])
def setup_test_token():
    token = (request.json or {}).get('token', '').strip()
    if not token:
        return jsonify({'ok': False, 'error': 'No token provided'})
    try:
        import requests as req
        r = req.get(
            'https://api.discogs.com/oauth/identity',
            headers={
                'Authorization': f'Discogs token={token}',
                'User-Agent': 'VinylCatalogApp/1.0',
            },
            timeout=8,
        )
        if r.status_code == 200:
            username = r.json().get('username', '')
            return jsonify({'ok': True, 'username': username})
        return jsonify({'ok': False, 'error': f'Discogs returned HTTP {r.status_code}'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@app.route('/setup/save', methods=['POST'])
def setup_save():
    data = request.json or {}
    token = data.get('discogs_token', '').strip()
    skip  = data.get('skip', False)

    if not token and not skip:
        return jsonify({'ok': False, 'error': 'Token required unless skipping'})

    if token:
        _save_env_value('DISCOGS_TOKEN', token)

    # Harden the secret key if it's still the placeholder
    existing_key = os.getenv('SECRET_KEY', '')
    if not existing_key or existing_key == 'change_this_to_a_random_string':
        _save_env_value('SECRET_KEY', secrets.token_hex(24))

    _save_env_value('FLASK_ENV', 'development')
    _save_env_value('SETUP_COMPLETE', '1')

    return jsonify({'ok': True})


# ============================================================================
# CLI & MAIN
# ============================================================================

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5001,
        debug=os.getenv('FLASK_ENV') == 'development'
    )
