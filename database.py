import sqlite3
import os
from datetime import datetime

# Ensure database directory exists
DB_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(DB_DIR, exist_ok=True)
DATABASE_PATH = os.path.join(DB_DIR, 'collection.db')

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database schema"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS collection (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            artist TEXT NOT NULL,
            artist_sort TEXT,
            format TEXT,
            year INTEGER,
            label TEXT,
            catalog_number TEXT,
            upc TEXT,
            cover_art_path TEXT,
            genre TEXT,
            discogs_url TEXT,
            discogs_id TEXT,
            shelf_section TEXT,
            needs_review INTEGER DEFAULT 0,
            entry_mode TEXT,
            notes TEXT,
            date_added TEXT,
            sort_order INTEGER,
            duplicate_flag INTEGER DEFAULT 0,
            duplicate_of INTEGER,
            cover_source TEXT,
            UNIQUE(upc) ON CONFLICT IGNORE,
            FOREIGN KEY (duplicate_of) REFERENCES collection(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            position TEXT,
            title TEXT NOT NULL,
            duration TEXT,
            FOREIGN KEY (record_id) REFERENCES collection(id) ON DELETE CASCADE
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tracks_record ON tracks(record_id)')

    # Migration: add artist column to tracks if it doesn't exist yet
    try:
        cursor.execute('ALTER TABLE tracks ADD COLUMN artist TEXT')
    except Exception:
        pass  # Column already exists

    # Migration: add marketplace price columns if they don't exist yet
    for col in (
        'ALTER TABLE collection ADD COLUMN price_lowest REAL',
        'ALTER TABLE collection ADD COLUMN price_median REAL',
        'ALTER TABLE collection ADD COLUMN price_highest REAL',
        'ALTER TABLE collection ADD COLUMN price_currency TEXT',
        'ALTER TABLE collection ADD COLUMN price_updated TEXT',
    ):
        try:
            cursor.execute(col)
        except Exception:
            pass  # Column already exists

    # Migration: per-record shelf unit override (NULL = use format default)
    try:
        cursor.execute('ALTER TABLE collection ADD COLUMN shelf_units INTEGER')
    except Exception:
        pass  # Column already exists

    # Migration: track when a record was last synced to Discogs collection
    try:
        cursor.execute('ALTER TABLE collection ADD COLUMN discogs_synced_at TEXT')
    except Exception:
        pass  # Column already exists

    # Seed: Stooges Fun House box set is physically 3.5" wide (~25 units)
    cursor.execute(
        'UPDATE collection SET shelf_units = 25 WHERE id = 850 AND (shelf_units IS NULL OR shelf_units != 25)'
    )

    # Shelf plan: stores user-confirmed endpoint record ID for each shelf
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shelf_plan (
            shelf_num   INTEGER PRIMARY KEY,
            end_record_id INTEGER,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # App settings: generic key-value store for user configuration
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS app_settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # Create indexes for common queries
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_artist ON collection(artist)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_title ON collection(title)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_artist_sort ON collection(artist_sort)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_format ON collection(format)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_upc ON collection(upc)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_discogs_id ON collection(discogs_id)')

    conn.commit()
    conn.close()

def add_record(data):
    """Add a new record to the collection"""
    conn = get_db()
    cursor = conn.cursor()

    now = datetime.utcnow().isoformat()

    cursor.execute('''
        INSERT INTO collection (
            title, artist, artist_sort, format, year, label,
            catalog_number, upc, cover_art_path, genre, discogs_url,
            discogs_id, shelf_section, needs_review, entry_mode,
            notes, date_added, sort_order, duplicate_flag,
            duplicate_of, cover_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        data.get('title'),
        data.get('artist'),
        data.get('artist_sort'),
        data.get('format'),
        data.get('year'),
        data.get('label'),
        data.get('catalog_number'),
        data.get("upc") or None,
        data.get('cover_art_path'),
        data.get('genre'),
        data.get('discogs_url'),
        data.get('discogs_id'),
        data.get('shelf_section'),
        data.get('needs_review', 0),
        data.get('entry_mode'),
        data.get('notes'),
        now,
        data.get('sort_order'),
        data.get('duplicate_flag', 0),
        data.get('duplicate_of'),
        data.get('cover_source')
    ))

    record_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return record_id

def get_record(record_id):
    """Get a single record by ID"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM collection WHERE id = ?', (record_id,))
    record = cursor.fetchone()
    conn.close()
    return record

def get_all_records(limit=None, offset=0):
    """Get all records, optionally with pagination"""
    conn = get_db()
    cursor = conn.cursor()

    query = 'SELECT * FROM collection WHERE duplicate_flag = 0 ORDER BY artist_sort ASC, year ASC, title ASC'

    if limit:
        query += f' LIMIT {limit} OFFSET {offset}'

    cursor.execute(query)
    records = cursor.fetchall()
    conn.close()
    return records

def search_records(query_text):
    """Search records by artist, title, or label (fuzzy match)"""
    conn = get_db()
    cursor = conn.cursor()

    search_pattern = f'%{query_text}%'

    cursor.execute('''
        SELECT * FROM collection
        WHERE duplicate_flag = 0 AND (
            artist LIKE ? OR
            title LIKE ? OR
            label LIKE ? OR
            artist_sort LIKE ?
        )
        ORDER BY artist_sort ASC, year ASC, title ASC
    ''', (search_pattern, search_pattern, search_pattern, search_pattern))

    records = cursor.fetchall()
    conn.close()
    return records

def filter_by_format(format_type):
    """Get all records of a specific format"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT * FROM collection
        WHERE duplicate_flag = 0 AND format = ?
        ORDER BY artist_sort ASC, year ASC, title ASC
    ''', (format_type,))

    records = cursor.fetchall()
    conn.close()
    return records

def get_all_formats():
    """Get list of all formats in collection"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT DISTINCT format FROM collection WHERE format IS NOT NULL ORDER BY format')
    formats = [row[0] for row in cursor.fetchall()]
    conn.close()
    return formats

def check_duplicate_upc(upc):
    """Check if UPC already exists in collection"""
    if not upc:
        return None

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM collection WHERE upc = ?', (upc,))
    record = cursor.fetchone()
    conn.close()
    return record

def check_duplicate_fuzzy(artist, title):
    """Check for fuzzy match on artist+title"""
    conn = get_db()
    cursor = conn.cursor()

    artist_pattern = f'%{artist}%'
    title_pattern = f'%{title}%'

    cursor.execute('''
        SELECT * FROM collection
        WHERE artist LIKE ? AND title LIKE ? AND duplicate_flag = 0
        LIMIT 1
    ''', (artist_pattern, title_pattern))

    record = cursor.fetchone()
    conn.close()
    return record

def update_record(record_id, data):
    """Update an existing record"""
    conn = get_db()
    cursor = conn.cursor()

    # Build dynamic update query
    fields = []
    values = []

    for key, value in data.items():
        if key != 'id':
            fields.append(f'{key} = ?')
            values.append(value)

    values.append(record_id)

    query = f'UPDATE collection SET {", ".join(fields)} WHERE id = ?'
    cursor.execute(query, values)

    conn.commit()
    conn.close()

def delete_record(record_id):
    """Delete a record"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM collection WHERE id = ?', (record_id,))
    conn.commit()
    conn.close()

def get_records_needing_review():
    """Get all records flagged for review"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM collection
        WHERE needs_review = 1
        ORDER BY date_added DESC
    ''')
    records = cursor.fetchall()
    conn.close()
    return records

def get_duplicate_records():
    """Get all records marked as duplicates"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM collection
        WHERE duplicate_flag = 1
        ORDER BY duplicate_of ASC, date_added DESC
    ''')
    records = cursor.fetchall()
    conn.close()
    return records

def _browse_where(browse):
    """Return (where_clause, params) for a browse filter string like 'genre:rock' or 'format:vinyl'."""
    vinyl = ('LP', 'Double LP', 'EP', '12 Inch', '10 Inch')
    if not browse or browse == 'all':
        return 'duplicate_flag = 0', []
    if browse == 'dupes':
        return "duplicate_flag = 0 AND LOWER(notes) LIKE '%copies%'", []
    kind, _, val = browse.partition(':')
    if kind == 'genre':
        return "duplicate_flag = 0 AND LOWER(genre) LIKE ?", [f'%{val}%']
    if kind == 'format':
        if val == 'vinyl':
            placeholders = ','.join('?' * len(vinyl))
            return f"duplicate_flag = 0 AND format IN ({placeholders})", list(vinyl)
        return "duplicate_flag = 0 AND format = ?", [val]
    return 'duplicate_flag = 0', []

def get_adjacent_in_browse(record_id, browse, direction='next'):
    """Return the id of the previous or next record within a browse filter,
    ordered by artist_sort then title."""
    conn = get_db()
    cur = conn.cursor()

    # Get current record's sort key
    row = cur.execute(
        'SELECT artist_sort, title FROM collection WHERE id = ?', (record_id,)
    ).fetchone()
    if not row:
        conn.close()
        return None
    cur_sort  = (row['artist_sort'] or '').lower()
    cur_title = (row['title'] or '').lower()

    where, params = _browse_where(browse)

    if direction == 'next':
        sql = f'''
            SELECT id FROM collection
            WHERE {where}
              AND (LOWER(COALESCE(artist_sort,'')) > ?
                   OR (LOWER(COALESCE(artist_sort,'')) = ? AND LOWER(title) > ?))
            ORDER BY LOWER(COALESCE(artist_sort,'')), LOWER(title)
            LIMIT 1
        '''
    else:
        sql = f'''
            SELECT id FROM collection
            WHERE {where}
              AND (LOWER(COALESCE(artist_sort,'')) < ?
                   OR (LOWER(COALESCE(artist_sort,'')) = ? AND LOWER(title) < ?))
            ORDER BY LOWER(COALESCE(artist_sort,'')) DESC, LOWER(title) DESC
            LIMIT 1
        '''

    result = cur.execute(sql, params + [cur_sort, cur_sort, cur_title]).fetchone()
    conn.close()
    return result['id'] if result else None

def get_records_for_sort_order():
    """Get vinyl records for sort order generation.
    Excludes Children's, Classical, and Jazz (those go on dedicated overflow shelves 14/15/16)."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT *,
               COALESCE(shelf_units, CASE format WHEN 'Double LP' THEN 2 WHEN 'Box Set' THEN 3 ELSE 1 END) as weight
        FROM collection
        WHERE format IN ('LP', 'Double LP', '12 Inch', 'EP', 'Box Set', '45')
          AND duplicate_flag = 0
          AND (notes != 'alpha-divider' OR notes IS NULL)
          AND (genre IS NULL
               OR (LOWER(genre) NOT LIKE '%children%'
               AND LOWER(genre) NOT LIKE '%classical%'
               AND LOWER(genre) NOT LIKE '%jazz%'
               AND LOWER(genre) NOT LIKE '%easy listening%'
               AND LOWER(genre) != 'other'))
        ORDER BY artist_sort ASC, year ASC, title ASC
    ''')
    records = cursor.fetchall()
    conn.close()
    return records

def get_records_for_overflow_shelves():
    """Get Children's, Classical, and Jazz records for overflow shelf assignment (14/15/16).
    Returns a dict: {'children': [...], 'jazz': [...], 'classical': [...], 'ten_inch': [...]}
    Children sorted by title (ignoring leading 'The'); others sorted by artist_sort."""
    conn = get_db()
    cursor = conn.cursor()
    result = {}

    # Children's: sort by title, ignoring a leading "The "
    cursor.execute('''
        SELECT * FROM collection
        WHERE duplicate_flag = 0
          AND LOWER(genre) LIKE '%children%'
        ORDER BY CASE WHEN LOWER(title) LIKE 'the %' THEN LOWER(SUBSTR(title, 5))
                      ELSE LOWER(title) END ASC
    ''')
    result['children'] = {'records': cursor.fetchall(), 'shelf': 14}

    # Jazz and Classical: sort by artist as usual
    for genre_key, like_pattern, shelf_num in [
        ('jazz',      '%jazz%',      15),
        ('classical', '%classical%', 16),
    ]:
        cursor.execute('''
            SELECT * FROM collection
            WHERE duplicate_flag = 0
              AND LOWER(genre) LIKE ?
            ORDER BY artist_sort ASC, year ASC, title ASC
        ''', (like_pattern,))
        result[genre_key] = {'records': cursor.fetchall(), 'shelf': shelf_num}

    # Shelf 17: all 10 Inch records
    cursor.execute('''
        SELECT * FROM collection
        WHERE duplicate_flag = 0
          AND format = '10 Inch'
        ORDER BY artist_sort ASC, year ASC, title ASC
    ''')
    result['ten_inch'] = {'records': cursor.fetchall(), 'shelf': 17}

    # Shelf 18: Easy Listening
    cursor.execute('''
        SELECT * FROM collection
        WHERE duplicate_flag = 0
          AND LOWER(genre) LIKE '%easy listening%'
        ORDER BY artist_sort ASC, year ASC, title ASC
    ''')
    result['easy_listening'] = {'records': cursor.fetchall(), 'shelf': 18}

    # Shelf 19: Other (oddball / miscellaneous records tagged genre = 'Other')
    cursor.execute('''
        SELECT * FROM collection
        WHERE duplicate_flag = 0
          AND LOWER(genre) = 'other'
        ORDER BY artist_sort ASC, year ASC, title ASC
    ''')
    result['other'] = {'records': cursor.fetchall(), 'shelf': 19}

    conn.close()
    return result

def update_sort_order_batch(updates):
    """Update sort_order and shelf_section for multiple records"""
    conn = get_db()
    cursor = conn.cursor()

    for record_id, sort_order, shelf_section in updates:
        cursor.execute('''
            UPDATE collection
            SET sort_order = ?, shelf_section = ?
            WHERE id = ?
        ''', (sort_order, shelf_section, record_id))

    conn.commit()
    conn.close()

def add_tracks(record_id, tracks):
    """Save track listing for a record"""
    if not tracks:
        return
    conn = get_db()
    cursor = conn.cursor()
    # Clear any existing tracks first (safe for re-saves)
    cursor.execute('DELETE FROM tracks WHERE record_id = ?', (record_id,))
    cursor.executemany(
        'INSERT INTO tracks (record_id, position, title, duration, artist) VALUES (?, ?, ?, ?, ?)',
        [(record_id, t.get('position', ''), t.get('title', ''), t.get('duration', ''), t.get('artist', '')) for t in tracks]
    )
    conn.commit()
    conn.close()

def get_tracks(record_id):
    """Get track listing for a record"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tracks WHERE record_id = ? ORDER BY id', (record_id,))
    tracks = cursor.fetchall()
    conn.close()
    return tracks

def update_record_prices(record_id, lowest, median, highest, currency):
    """Store marketplace price data for a record"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE collection
        SET price_lowest = ?, price_median = ?, price_highest = ?,
            price_currency = ?, price_updated = ?
        WHERE id = ?
    ''', (lowest, median, highest, currency, datetime.utcnow().isoformat()[:10], record_id))
    conn.commit()
    conn.close()

def get_records_needing_fix(limit=50):
    """Return records where price_lowest has not been fetched yet.
    Sort fix runs as part of this same pass, so once a record has prices
    (real value or 0 for no listings) it is considered fully processed."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, artist, artist_sort, discogs_id
        FROM collection
        WHERE discogs_id IS NOT NULL AND discogs_id != ''
          AND price_lowest IS NULL
        ORDER BY id
        LIMIT ?
    ''', (limit,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def count_records_needing_fix():
    """Count records that still need processing (price not yet fetched)."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM collection
        WHERE discogs_id IS NOT NULL AND discogs_id != ''
          AND price_lowest IS NULL
    ''')
    count = cursor.fetchone()[0]
    conn.close()
    return count

def update_record_artist_sort(record_id, artist_sort):
    """Update just the artist_sort field for a record."""
    conn = get_db()
    conn.execute('UPDATE collection SET artist_sort=? WHERE id=?', (artist_sort, record_id))
    conn.commit()
    conn.close()

def get_records_needing_price_for_sort():
    """Get LP and 12 Inch records that have no price data yet, ordered for sort-order display."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, artist, artist_sort, title, format, shelf_section
        FROM collection
        WHERE format IN ('LP', '12 Inch') AND duplicate_flag = 0
          AND price_lowest IS NULL
        ORDER BY artist_sort ASC, year ASC, title ASC
    ''')
    records = cursor.fetchall()
    conn.close()
    return records

def count_records_needing_price():
    """Count LP/12 Inch records with no price data."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM collection
        WHERE format IN ('LP', '12 Inch') AND duplicate_flag = 0
          AND price_lowest IS NULL
    ''')
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_records_without_prices(limit=100):
    """Return records that have a discogs_id but no price data yet"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, discogs_id, artist, title
        FROM collection
        WHERE discogs_id IS NOT NULL AND discogs_id != ''
          AND price_lowest IS NULL
        ORDER BY id
        LIMIT ?
    ''', (limit,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def count_records_without_prices():
    """Count how many records still need price fetching"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM collection
        WHERE discogs_id IS NOT NULL AND discogs_id != ''
          AND price_lowest IS NULL
    ''')
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_collection_stats():
    """Get collection statistics"""
    conn = get_db()
    cursor = conn.cursor()

    EXCLUDE_DIVIDERS = "AND (notes != 'alpha-divider' OR notes IS NULL)"

    # Total records
    cursor.execute(f'SELECT COUNT(*) as count FROM collection WHERE duplicate_flag = 0 {EXCLUDE_DIVIDERS}')
    total = cursor.fetchone()['count']

    # By format
    cursor.execute(f'''
        SELECT format, COUNT(*) as count FROM collection
        WHERE duplicate_flag = 0 {EXCLUDE_DIVIDERS}
        GROUP BY format
        ORDER BY count DESC
    ''')
    by_format = {row['format'] or 'Unknown': row['count'] for row in cursor.fetchall()}

    # By year
    cursor.execute(f'''
        SELECT year, COUNT(*) as count FROM collection
        WHERE duplicate_flag = 0 AND year IS NOT NULL {EXCLUDE_DIVIDERS}
        GROUP BY year
        ORDER BY year DESC
        LIMIT 20
    ''')
    by_year = {str(row['year']): row['count'] for row in cursor.fetchall()}

    # With covers
    cursor.execute(f'''
        SELECT COUNT(*) as count FROM collection
        WHERE duplicate_flag = 0 AND cover_art_path IS NOT NULL {EXCLUDE_DIVIDERS}
    ''')
    with_covers = cursor.fetchone()['count']

    # Needs review
    cursor.execute(f'SELECT COUNT(*) as count FROM collection WHERE needs_review = 1 {EXCLUDE_DIVIDERS}')
    needs_review = cursor.fetchone()['count']

    # Duplicates
    cursor.execute(f'SELECT COUNT(*) as count FROM collection WHERE duplicate_flag = 1 {EXCLUDE_DIVIDERS}')
    duplicates = cursor.fetchone()['count']

    # Marketplace price totals (only records with real listings, price_lowest > 0)
    cursor.execute(f'''
        SELECT
            SUM(price_lowest)  as total_low,
            COUNT(*)           as priced_count
        FROM collection
        WHERE duplicate_flag = 0
          AND price_lowest IS NOT NULL
          AND price_lowest > 0
          {EXCLUDE_DIVIDERS}
    ''')
    price_row = cursor.fetchone()
    total_low      = price_row['total_low'] or 0
    priced_count   = price_row['priced_count'] or 0

    conn.close()

    return {
        'total': total,
        'by_format': by_format,
        'by_year': by_year,
        'with_covers': with_covers,
        'cover_percentage': round(100 * with_covers / total, 1) if total > 0 else 0,
        'needs_review': needs_review,
        'duplicates': duplicates,
        'total_low': total_low,
        'priced_count': priced_count,
    }


# ── Shelf Planner ─────────────────────────────────────────────────────────────

def get_shelf_planner_records():
    """Return all main vinyl records in stable alphabetical order for the shelf planner.
    Uses artist_sort ordering — never depends on sort_order so corrupted values cannot break it."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, artist, artist_sort, title, format, shelf_section, sort_order, notes,
               COALESCE(shelf_units, CASE format WHEN 'Double LP' THEN 2 WHEN 'Box Set' THEN 3 ELSE 1 END) as weight
        FROM collection
        WHERE duplicate_flag = 0
          AND format IN ('LP','Double LP','12 Inch','EP','Box Set','45')
          AND (notes != 'alpha-divider' OR notes IS NULL)
          AND (genre IS NULL
               OR (LOWER(genre) NOT LIKE '%children%'
               AND LOWER(genre) NOT LIKE '%classical%'
               AND LOWER(genre) NOT LIKE '%jazz%'
               AND LOWER(genre) NOT LIKE '%easy listening%'
               AND LOWER(genre) != 'other'))
        ORDER BY artist_sort ASC, year ASC, title ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_shelf_plan():
    """Return saved shelf plan as {shelf_num: end_record_id}."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT shelf_num, end_record_id FROM shelf_plan ORDER BY shelf_num")
    plan = {row['shelf_num']: row['end_record_id'] for row in cursor.fetchall()}
    conn.close()
    return plan

def save_shelf_plan(plan):
    """Save shelf plan. plan = {shelf_num: end_record_id}."""
    conn = get_db()
    cursor = conn.cursor()
    from datetime import datetime
    now = datetime.utcnow().isoformat()
    for shelf_num, end_record_id in plan.items():
        cursor.execute("""
            INSERT INTO shelf_plan (shelf_num, end_record_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(shelf_num) DO UPDATE SET end_record_id=excluded.end_record_id, updated_at=excluded.updated_at
        """, (shelf_num, end_record_id, now))
    conn.commit()
    conn.close()

def apply_shelf_plan(plan):
    """Apply saved plan: reassign shelf_section AND sort_order for all records in shelves 1-13.
    plan = {shelf_num: end_record_id} where keys are 1..11 (shelf 12 catches the rest).
    Returns count of updated records.
    """
    rows = get_shelf_planner_records()
    if not rows:
        return 0

    # Build endpoint lookup: record_id -> True (just marks where shelves end)
    endpoint_ids = {int(end_id) for end_id in plan.values()}

    # Pass 1: assign shelf_section
    shelf_updates = []
    current_shelf = 1
    for row in rows:
        shelf_updates.append((f'Shelf {current_shelf}', row['id']))
        if row['id'] in endpoint_ids:
            current_shelf += 1

    # Pass 2: assign sort_order as a GLOBAL sequence across all shelves.
    # Must be globally unique so the divider-placement query (ORDER BY sort_order ASC)
    # can correctly find the first record of each letter across the whole collection.
    sort_updates = []
    for global_pos, (shelf_section, rec_id) in enumerate(shelf_updates, start=1):
        sort_updates.append((global_pos * 100, rec_id))

    conn = get_db()
    cursor = conn.cursor()
    cursor.executemany("UPDATE collection SET shelf_section=? WHERE id=?", shelf_updates)
    cursor.executemany("UPDATE collection SET sort_order=? WHERE id=?", sort_updates)
    conn.commit()
    conn.close()
    return len(shelf_updates)


def get_setting(key):
    """Return a value from app_settings, or None if not set."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM app_settings WHERE key = ?', (key,))
    row = cursor.fetchone()
    conn.close()
    return row['value'] if row else None

def save_setting(key, value):
    """Insert or update a value in app_settings."""
    conn = get_db()
    conn.execute(
        'INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
        (key, value)
    )
    conn.commit()
    conn.close()
