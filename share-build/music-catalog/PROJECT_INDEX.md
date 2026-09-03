# Music Catalog - Project Index

## Overview
Complete Flask web application for cataloging vinyl records and CDs (~3,000 capacity) with barcode scanning, AI album recognition, and metadata management.

## Core Application Files

### Backend
- **app.py** (18KB)
  - Flask application and all routes
  - Entry points: barcode, photo, manual
  - Record CRUD operations
  - Review and duplicate management
  - Sort order generation
  - Statistics dashboard

- **database.py** (9.6KB)
  - SQLite schema definition
  - Database initialization
  - Query functions (search, filter, browse)
  - Statistics aggregation
  - Batch operations

- **discogs.py** (4.6KB)
  - Discogs API client
  - Barcode and text search
  - Release detail fetching
  - Cover art extraction
  - Rate limiting (0.5s between requests)

- **vision.py** (2.8KB)
  - Claude Vision API integration
  - Album cover image recognition
  - Artist/title extraction
  - JSON response parsing

### Frontend Templates (11 pages)

**Layout & Navigation**
- **templates/base.html**
  - Main layout with navigation
  - Flash message handling
  - Mobile menu toggle
  - CSS framework setup

**Content Pages**
- **templates/index.html**
  - Collection browse with album art grid
  - Real-time search & filter
  - Format selection (LP, CD, 45, etc.)
  - Sort options (artist, title, year, date)
  - Results counter

- **templates/add.html**
  - Three-tab entry interface
  - Barcode scanner input (auto-focus)
  - Photo upload with file input
  - Manual entry form
  - Confirmation modal with cover preview
  - Duplicate warnings

- **templates/record.html**
  - Full record details
  - Cover art display
  - Metadata grid
  - Edit/Delete actions
  - Status badges (review, duplicate)

- **templates/edit.html**
  - Form for updating all fields
  - Cover art replacement
  - Review flag toggle
  - Cancel/Save buttons

- **templates/review.html**
  - Queue of records flagged for review
  - Quick view details
  - Edit/view action links
  - Record count

- **templates/duplicates.html**
  - Duplicate record management
  - Keep/Delete/Review options
  - Original record link
  - Bulk resolution interface

- **templates/sort_order.html**
  - Sort order generator UI
  - Results table with position info
  - Print-friendly formatting
  - Shelf assignment algorithm

- **templates/stats.html**
  - Collection statistics
  - Format breakdown chart
  - Year distribution
  - Cover art percentage
  - Quick stats cards

**Error Pages**
- **templates/404.html** - Not found
- **templates/500.html** - Server error

### Static Assets

- **static/app.js** (3.5KB)
  - Utility functions
  - API call helpers
  - Form utilities
  - Storage management
  - Keyboard shortcuts (/ for search, Esc for modal)

- **static/style.css** (2.2KB)
  - Global styles
  - Custom animations
  - Mobile optimizations
  - Scrollbar styling
  - Print media queries

### Configuration & Setup

- **requirements.txt**
  - Flask
  - Requests (HTTP)
  - Anthropic SDK
  - python-dotenv
  - Pillow (image processing)

- **.env.example**
  - DISCOGS_TOKEN
  - ANTHROPIC_API_KEY
  - SECRET_KEY
  - FLASK_ENV

- **start.sh**
  - pip install wrapper
  - Application launcher

### Documentation

- **README.md** (8.9KB)
  - Full feature documentation
  - Architecture overview
  - Setup instructions
  - Route reference
  - Database schema
  - API integration details
  - Mobile optimization notes
  - Troubleshooting guide

- **DEPLOYMENT.md** (6.5KB)
  - Quick start (5 minutes)
  - Detailed installation
  - Production deployment options
  - Backup & restore
  - API key acquisition
  - Comprehensive troubleshooting
  - Network setup for iPhone
  - Tips & tricks

- **PROJECT_INDEX.md** (this file)
  - Component inventory
  - File descriptions
  - Feature matrix
  - Development notes

## Data Storage

- **collection.db** (auto-created)
  - SQLite database
  - 20+ fields per record
  - Indexes on: artist, title, format, UPC
  - Unique constraint on UPC

- **covers/** (directory)
  - Local cover art images
  - Filename format: {uuid}.jpg or {discogs_id}.jpg
  - Subdirectory of app root

## Feature Implementation Matrix

| Feature | File | Route | Status |
|---------|------|-------|--------|
| Browse collection | index.html, app.py | GET / | ✓ |
| Search & filter | index.html, app.js | GET / | ✓ |
| Barcode scan | add.html, app.py | POST /add/barcode | ✓ |
| Photo upload | add.html, app.py | POST /add/photo | ✓ |
| AI recognition | vision.py, add.html | POST /add/photo | ✓ |
| Manual entry | add.html, app.py | POST /add/save | ✓ |
| Duplicate check | database.py, app.py | POST /add/* | ✓ |
| Record detail | record.html, app.py | GET /record/<id> | ✓ |
| Edit record | edit.html, app.py | GET/POST /record/<id>/edit | ✓ |
| Delete record | app.py | POST /record/<id>/delete | ✓ |
| Review queue | review.html, app.py | GET /review | ✓ |
| Manage duplicates | duplicates.html, app.py | GET /duplicates | ✓ |
| Sort generator | sort_order.html, app.py | GET/POST /sort-order | ✓ |
| Statistics | stats.html, app.py | GET /stats | ✓ |
| Cover serving | app.py | GET /covers/<file> | ✓ |

## API Integrations

### Discogs API
- Base: `https://api.discogs.com`
- Methods:
  - Barcode search: GET `/database/search?barcode={upc}`
  - Text search: GET `/database/search?artist={artist}&release_title={title}`
  - Release details: GET `/releases/{id}`
- Authentication: `Discogs token={token}` header
- Rate limit: 0.5s delay enforced in code

### Anthropic Claude Vision
- Model: `claude-haiku-4-5-20251001`
- Input: Base64 image (JPEG/PNG/GIF/WebP)
- Output: JSON with artist/title fields
- Used by: Photo entry mode for album identification

## Database Schema

```
collection (
  id (PK)
  title (TEXT, NOT NULL)
  artist (TEXT, NOT NULL)
  artist_sort (TEXT, "Last, First" format)
  format (TEXT, LP/CD/45/etc)
  year (INTEGER)
  label (TEXT)
  catalog_number (TEXT)
  upc (TEXT, UNIQUE)
  cover_art_path (TEXT, relative to app root)
  genre (TEXT, comma-separated)
  discogs_url (TEXT)
  discogs_id (TEXT)
  shelf_section (TEXT, e.g. "Shelf 1")
  needs_review (INTEGER, 0/1 flag)
  entry_mode (TEXT, barcode/photo/manual)
  notes (TEXT)
  date_added (TEXT, ISO timestamp)
  sort_order (INTEGER, for sorting)
  duplicate_flag (INTEGER, 0/1)
  duplicate_of (INTEGER, FK to id)
  cover_source (TEXT, discogs/own_photo)
)

Indexes:
  idx_artist
  idx_title
  idx_artist_sort
  idx_format
  idx_upc
  idx_discogs_id
```

## Key Code Sections

### Entry Flow: Barcode → Discogs → Save
1. User scans barcode → POST /add/barcode
2. app.py checks duplicate UPC
3. discogs.py searches by barcode
4. discogs.py fetches full release
5. Show cover confirmation to user
6. User selects cover source
7. POST /add/save → database.add_record()
8. Redirect to record detail

### Entry Flow: Photo → Vision → Discogs → Save
1. User uploads photo → POST /add/photo
2. vision.py sends to Claude Vision API
3. Extract artist/title from response
4. Check duplicate fuzzy match
5. discogs.py searches by artist/title
6. Show results to user
7. POST /add/save → database.add_record()
8. Save photo if user chooses it

### Entry Flow: Manual → Save
1. User fills form → /add (manual tab)
2. Optional: upload cover photo
3. POST /add/save with form data
4. database.add_record() inserts
5. Redirect to record detail

## Development Workflow

### Adding Features
1. Modify route in app.py
2. Update/create template as needed
3. Update database.py if schema changes
4. Test with: `python app.py`
5. Update documentation

### Testing
```bash
# Import test
python -c "from app import app; print('OK')"

# Database test
python -c "from database import init_db; init_db(); print('OK')"

# Run dev server
python app.py
```

### Debugging
- Flask debug mode: `app.run(debug=True)`
- Browser console: Ctrl+Shift+J
- Network tab: Monitor API calls
- Server logs: Terminal output

## Performance Characteristics

- Database: Suitable for ~10,000 records
- Cover images: Local disk storage
- Search: Client-side JavaScript (instant)
- API calls: Rate limited at 0.5s/request
- Rendering: Grid layout optimized

## Security Considerations

- CSRF protection via Flask session
- SQL injection prevented (parameterized queries)
- File upload validation (image types only)
- API keys stored in environment variables (not code)
- UPC treated as unique constraint
- File paths secured with secure_filename()

## Scalability Notes

- SQLite for < 10,000 records
- For larger collections: upgrade to PostgreSQL
- Cover images: consider CDN for many files
- Discogs API: rate limit = one request per 0.5s
- Claude Vision: per-image API calls

## File Sizes Summary

```
Backend Code:  ~35 KB
Templates:     ~45 KB
Static Assets: ~6 KB
Documentation: ~15 KB
Total:         ~100 KB
```

## Configuration Options

### Environment Variables
```
DISCOGS_TOKEN=token_from_discogs
ANTHROPIC_API_KEY=key_from_anthropic
SECRET_KEY=random_secret
FLASK_ENV=development|production
```

### Flask Settings (in app.py)
```
Host: 0.0.0.0 (accessible from network)
Port: 5000
Debug: False (production)
Max file size: 50MB
```

## Support & Resources

- **Discogs API**: https://www.discogs.com/developers/
- **Anthropic Claude**: https://docs.anthropic.com/
- **Flask**: https://flask.palletsprojects.com/
- **Tailwind CSS**: https://tailwindcss.com/
- **SQLite**: https://www.sqlite.org/

## Version History

- v1.0 (Initial release)
  - Three entry modes (barcode/photo/manual)
  - Duplicate detection
  - Discogs integration
  - Claude Vision integration
  - Browse/search interface
  - Sort order generator
  - Statistics dashboard
  - Mobile optimized

## License & Attribution

- Built with Flask, SQLite, Tailwind CSS
- Discogs API for metadata
- Anthropic Claude for vision
- No external fonts or build tools

---

**Last Updated**: March 2026
**Status**: Production Ready
**Maintenance**: Low (stable codebase)
