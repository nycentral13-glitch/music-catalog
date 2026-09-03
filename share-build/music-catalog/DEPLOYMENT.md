# Music Catalog - Deployment & Quick Start

## Quick Start (5 minutes)

### Step 1: Configure Environment
```bash
cd /sessions/vibrant-pensive-dirac/mnt/outputs/music-catalog
cp .env.example .env
# Edit .env and add your API keys:
# DISCOGS_TOKEN=from_discogs.com/settings/developers
# ANTHROPIC_API_KEY=from_console.anthropic.com
```

### Step 2: Run the App
```bash
python app.py
```

The app is now running at:
- **Local**: http://localhost:5000
- **Network**: http://<your-ip>:5000

### Step 3: Use on iPhone
1. Find your computer's IP: `ipconfig getifaddr en0` (Mac) or `hostname -I` (Linux)
2. On iPhone, go to: `http://<your-ip>:5000`
3. Use barcode scanner or camera to add records

## Detailed Setup

### Prerequisites
- Python 3.8+
- pip package manager
- USB barcode scanner (optional)
- Discogs API token (free)
- Anthropic API key

### Installation Steps

1. **Clone/Navigate to directory**
   ```bash
   cd /sessions/vibrant-pensive-dirac/mnt/outputs/music-catalog
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Get API Keys**
   - Discogs: https://www.discogs.com/settings/developers (Personal access token)
   - Anthropic: https://console.anthropic.com/ (API key from Billing → API keys)

4. **Create .env file**
   ```bash
   cp .env.example .env
   # Edit with your favorite editor
   nano .env
   ```
   
   Content should be:
   ```
   DISCOGS_TOKEN=your_token_here
   ANTHROPIC_API_KEY=your_key_here
   SECRET_KEY=random-string-here
   FLASK_ENV=development
   ```

5. **Start application**
   ```bash
   python app.py
   ```

6. **Access the app**
   - Desktop: http://localhost:5000
   - iPhone on same network: http://<your-computer-ip>:5000

## Production Deployment

### For Raspberry Pi / Always-On
```bash
# Install systemd service
sudo cp music-catalog.service /etc/systemd/system/
sudo systemctl enable music-catalog
sudo systemctl start music-catalog

# View logs
sudo journalctl -u music-catalog -f
```

### For Docker
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
ENV FLASK_ENV=production
CMD ["python", "app.py"]
```

Build and run:
```bash
docker build -t music-catalog .
docker run -p 5000:5000 -v catalog-data:/app/covers music-catalog
```

### For Cloud Deployment (Heroku/Railway)
1. Create `Procfile`:
   ```
   web: python app.py
   ```

2. Set environment variables in hosting platform

3. Deploy

## Backup & Restore

### Backup Collection
```bash
# Copy database and covers
tar -czf music-catalog-backup.tar.gz collection.db covers/
```

### Restore Collection
```bash
# Extract to new instance
tar -xzf music-catalog-backup.tar.gz
```

## API Keys Reference

### Discogs Token
1. Go to https://www.discogs.com/settings/developers
2. Click "Create an access token"
3. Name it (e.g., "Music Catalog")
4. Copy the token

### Anthropic API Key
1. Go to https://console.anthropic.com/
2. Click "API keys" in sidebar
3. Click "Create new secret key"
4. Copy the key

⚠️ **SECURITY**: Never commit .env to version control. Always keep API keys private.

## Troubleshooting

### Port 5000 in use
```bash
# Find what's using port 5000
lsof -i :5000
# Kill the process
kill -9 <PID>

# Or change port in app.py
app.run(port=5001)
```

### Module not found
```bash
pip install -r requirements.txt --force-reinstall
```

### Discogs API not working
- Check token is valid: https://api.discogs.com/identity (with token in header)
- Check rate limiting: wait 60 seconds between requests
- Check network connectivity

### Claude Vision not working
- Verify API key in .env
- Check image file is valid (JPG/PNG/GIF/WebP)
- Verify account has API access enabled

### Database errors
```bash
# Reset database (WARNING: deletes collection!)
rm collection.db collection.db-journal
python -c "from database import init_db; init_db()"
```

### Cover art not saving
```bash
# Check covers directory exists and is writable
mkdir -p covers
chmod 755 covers
```

## File Structure at a Glance

```
music-catalog/
├── app.py              # Flask routes & logic
├── database.py         # SQLite + queries
├── discogs.py          # Discogs API client
├── vision.py           # Claude Vision integration
├── collection.db       # Your music data (auto-created)
├── covers/             # Album artwork
└── templates/          # HTML pages
```

## Feature Summary

✓ Browse 3,000+ records with album art grid
✓ Barcode scanning with Discogs metadata
✓ Album photo recognition with AI (Claude Vision)
✓ Manual entry for any record
✓ Duplicate detection (UPC & fuzzy matching)
✓ Collection statistics & search
✓ Sort order generator (8-shelf system)
✓ Review queue for quality control
✓ Mobile-optimized (iPhone Safari tested)
✓ Fully offline-capable for browsing
✓ Dark theme UI

## Network Setup for iPhone

1. **Find your computer's IP**
   ```bash
   # Mac
   ipconfig getifaddr en0
   
   # Linux
   hostname -I
   
   # Windows
   ipconfig
   ```

2. **On iPhone**
   - Connect to same WiFi network
   - Open Safari
   - Type: `http://<your-ip>:5000`

3. **Using barcode scanner**
   - Go to Barcode tab
   - Tap text input
   - Scan barcode (scanner will type the number)
   - Press Enter

4. **Using camera**
   - Go to Photo tab
   - Tap "Choose Photo"
   - Select "Take Photo"
   - Take album cover photo
   - AI identifies the album

## Tips & Tricks

### Barcode Scanner Setup
- Most USB barcode scanners work without drivers
- Just plug into USB port
- Tap any input field and scan
- Scanner simulates keyboard input

### Organizing Records
1. Add all records (don't worry about order)
2. Go to /sort-order
3. Click "Generate Sort Order"
4. Print the guide
5. Physically move records to match numbers
6. Update shelf locations as you go

### Backing Up
```bash
# Daily backup
cp collection.db collection.db.bak
tar -czf backup-$(date +%Y%m%d).tar.gz collection.db covers/
```

### Bulk Import
If you have a CSV of records:
```python
import csv
from database import add_record

with open('records.csv') as f:
    for row in csv.DictReader(f):
        add_record({
            'title': row['title'],
            'artist': row['artist'],
            # ... other fields
        })
```

## Support & Docs

- README.md - Full documentation
- Flask docs: https://flask.palletsprojects.com/
- Discogs API: https://www.discogs.com/developers/
- Claude docs: https://docs.anthropic.com/

## Version Info

- Python 3.8+
- Flask 2.x
- SQLite 3.x
- Tailwind CSS (CDN)
- Claude API: claude-haiku-4-5-20251001

Enjoy cataloging! 🎵
