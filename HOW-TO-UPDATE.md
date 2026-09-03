# Updating Your Vinyl Catalog — v7

These steps replace the app code only. Your records, cover art, and settings are never touched.

---

## Before you start

Make sure the app is running on port 5001. Open a new Terminal window for the commands below.

---

## Step 1 — Stop the app

```bash
lsof -ti :5001 | xargs kill -9
```

---

## Step 2 — Unzip the update

Double-click **music-catalog-5001-v7.zip** to unzip it.  
You'll get a folder called `share-build` containing `music-catalog` inside it.

---

## Step 3 — Copy the new code files into your folder

Run these commands in Terminal, replacing `~/Desktop/music-catalog` with wherever your catalog folder lives:

```bash
MINE=~/Desktop/music-catalog
SRC=~/Downloads/share-build/music-catalog   # adjust if unzipped elsewhere

cp "$SRC/app.py"       "$MINE/app.py"
cp "$SRC/database.py"  "$MINE/database.py"
cp "$SRC/discogs.py"   "$MINE/discogs.py"
cp -r "$SRC/templates/" "$MINE/templates/"
```

> **Do NOT copy** `collection.db`, `.env`, or `covers/` — those aren't in the zip and your existing ones stay untouched.

---

## Step 4 — Restart

```bash
cd ~/Desktop/music-catalog && python3 app.py
```

Open **http://localhost:5001** in your browser.

---

## What's new in v7

- **Export → Excel (.xlsx)** — download your collection as a spreadsheet
- **Export → CSV** — plain text spreadsheet option
- **Export → PDF + Covers** — printable list with album art thumbnails; vinyl in indigo, CDs in teal, 45s in pink
- **Discogs sync error list** now downloads as .xlsx
- Library App button removed (replaced by PDF + Covers export)
