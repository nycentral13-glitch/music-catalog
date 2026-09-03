# Setting Up Your Vinyl Catalog App (Mac)

This is a personal record-collection web app — runs entirely on your own Mac, no
data leaves your computer unless you choose to use the optional Discogs/Claude
lookups described below.

Follow these steps in **Terminal** (Applications → Utilities → Terminal).

## 1. Unzip and move the folder

If you haven't already, unzip the file you were sent and drag the `music-catalog`
folder somewhere easy to find, like your Desktop.

## 2. Open Terminal and go to the folder

```bash
cd ~/Desktop/music-catalog
```

(Adjust the path if you put the folder somewhere else. Tip: you can type `cd ` and then
drag the folder from Finder into the Terminal window — it fills in the path for you.)

## 3. Check you have Python 3

```bash
python3 --version
```

If you see something like `Python 3.9.6`, you're good. If you get
`command not found`, install Python from https://www.python.org/downloads/ first,
then come back to this step.

## 4. Install the required packages

```bash
pip3 install -r requirements.txt --break-system-packages
```

(If that flag throws an error on your system, just run
`pip3 install -r requirements.txt` instead.)

## 5. Set up your API keys (optional but recommended)

The app works without any API keys — you can add records manually. But two
optional integrations make it much faster:

- **Discogs token** — auto-fills artist/title/year/cover art when you scan a
  barcode or search by title. Free account at https://www.discogs.com →
  Settings → Developers → Generate new token.
- **Anthropic API key** — lets you snap a photo of an album cover and have it
  identify the artist/title automatically. Get one at
  https://console.anthropic.com/ (paid, usage-based, but identification calls
  are cheap — a few cents per hundred lookups).

Create your own `.env` file from the template:

```bash
cp .env.example .env
```

Then open `.env` in any text editor (or run `nano .env` right in Terminal) and
paste in your tokens:

```
DISCOGS_TOKEN=your_actual_token_here
ANTHROPIC_API_KEY=your_actual_key_here
SECRET_KEY=pick-any-random-string-here
FLASK_ENV=development
```

You can skip either token and just use manual entry for that feature — the app
won't crash, it'll just skip the lookup.

## 6. Run the app

```bash
python3 app.py
```

You should see something like:

```
* Running on http://127.0.0.1:5000
* Running on http://192.168.x.x:5000
```

Leave this Terminal window open — closing it stops the app. Press `Ctrl+C` in
the Terminal whenever you want to stop it.

## 7. Open it in your browser

Go to **http://localhost:5000** in any browser on your Mac.

## 8. (Optional) Use it from your phone on the same WiFi

Look at the second line in the Terminal output — something like
`http://192.168.1.42:5000`. Type that same address into Safari on your phone,
as long as your phone is on the same WiFi network as your Mac.

## Starting it again later

Once it's set up, you don't need to redo any of the above. Just:

```bash
cd ~/Desktop/music-catalog
python3 app.py
```

Or double-click `start.sh` after right-clicking it once and choosing
**Open With → Terminal** (only needed the very first time, to clear a macOS
security prompt).

## If port 5000 is already in use

Something else on your Mac is already using that port. Find and stop it:

```bash
lsof -i :5000
kill -9 <PID shown in the output>
```

Then run `python3 app.py` again.

## Your data

Everything you add lives in `collection.db` (a small file in this folder) and
your cover art photos live in the `covers/` folder. Back those two up
periodically if you want to be safe — that's your whole collection.
