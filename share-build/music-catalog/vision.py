import anthropic, base64, json, os, re, io
from PIL import Image, ImageOps

def identify_album_cover(image_data, media_type=None):
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return None
    try:
        img = Image.open(io.BytesIO(image_data))
        out = io.BytesIO()
        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')
        img.save(out, format='JPEG', quality=90)
        image_data = out.getvalue()
        media_type = 'image/jpeg'
    except:
        media_type = media_type or 'image/jpeg'
    image_b64 = base64.standard_b64encode(image_data).decode('utf-8')
    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=512,
            messages=[{"role":"user","content":[
                {"type":"image","source":{"type":"base64","media_type":media_type,"data":image_b64}},
                {"type":"text","text":'You are identifying a vinyl record or CD cover from a photo. Your primary method is reading printed text visible in the image.\n\n1. Look for the artist name and album title printed on the cover, spine, or label. These are almost always present as text somewhere in the image.\n2. Read that text carefully and return it exactly. Do not guess based on visual style, genre aesthetics, or what the cover art looks like.\n3. If you can read the text clearly, return it. If the text is partially obscured but you can make it out, return it.\n4. Only if there is genuinely no readable text anywhere should you attempt identification from visual content alone — and in that case, return your best reading, not a guess based on mood or genre.\n5. "artist" = band or musician name. "title" = album name. Never swap them.\n\nReturn ONLY raw JSON with no markdown: {"artist": "Band Name", "title": "Album Title"}'}
            ]}])
        raw = message.content[0].text.strip()
        print(f"Claude raw response: {raw}")
        # Extract JSON object even if model added prose before/after it
        match = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
        if not match:
            return None
        result = json.loads(match.group())
        artist = result.get('artist','').strip()
        title = result.get('title','').strip()
        if not artist and not title:
            return None
        print(f"Identified: artist='{artist}', title='{title}'")
        return {'artist': artist, 'title': title}
    except Exception as e:
        print(f"Vision error: {e}")
        return None

def identify_record_from_image(file_path):
    try:
        with open(file_path, 'rb') as f:
            return identify_album_cover(f.read())
    except Exception as e:
        print(f"File error: {e}")
        return None

def process_cover_photo(image_data):
    """Auto-rotate, remove background, and crop to square.
    Returns processed JPEG bytes, or original bytes if processing fails."""
    try:
        img = Image.open(io.BytesIO(image_data))

        # 1. Fix phone EXIF orientation
        img = ImageOps.exif_transpose(img)

        # 2. Remove background using rembg (returns RGBA)
        try:
            from rembg import remove
            img_rgba = remove(img)
        except Exception as e:
            print(f"Background removal skipped: {e}")
            img_rgba = img.convert('RGBA')

        # 3. Crop to bounding box of non-transparent pixels (removes empty border)
        bbox = img_rgba.getbbox()
        if bbox:
            img_rgba = img_rgba.crop(bbox)

        # 4. Crop to square from center
        w, h = img_rgba.size
        side = min(w, h)
        left = (w - side) // 2
        top  = (h - side) // 2
        img_rgba = img_rgba.crop((left, top, left + side, top + side))

        # 5. Flatten onto white background and save as JPEG
        bg = Image.new('RGB', img_rgba.size, (255, 255, 255))
        bg.paste(img_rgba, mask=img_rgba.split()[3])

        out = io.BytesIO()
        bg.save(out, format='JPEG', quality=92)
        return out.getvalue()

    except Exception as e:
        print(f"Cover photo processing failed: {e}")
        return image_data
