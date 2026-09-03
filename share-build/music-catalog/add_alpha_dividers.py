#!/usr/bin/env python3
"""
Creates A-Z alphabet divider records in the collection database.
Run this on the Mac while Flask is stopped, or it will handle the lock gracefully.
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'collection.db')

conn = sqlite3.connect(DB_PATH, timeout=10)
cur  = conn.cursor()

# Remove any existing divider records
cur.execute("DELETE FROM collection WHERE notes = 'alpha-divider'")
deleted = cur.rowcount
if deleted:
    print(f"Removed {deleted} existing divider records.")

for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
    cur.execute('''
        INSERT INTO collection
            (title, artist, artist_sort, format, genre, cover_art_path,
             notes, date_added, duplicate_flag)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        f'— {letter} —',
        letter,
        letter,
        'LP',
        'Rock',
        f'covers/divider_{letter}.jpg',
        'alpha-divider',
        datetime.now().strftime('%Y-%m-%d'),
        0
    ))
    print(f"  Inserted divider: {letter}")

conn.commit()
conn.close()
print("\nDone — 26 alphabet divider records added.")
