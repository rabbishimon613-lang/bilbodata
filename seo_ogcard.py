#!/usr/bin/env python3
"""Render the shared 1200x630 social card at assets/og-card.png.

The old og:image was the 1.1 MB portrait logo, which crops badly in every
feed and is slow to fetch. This draws the same marks at card proportions.

    python3 seo_ogcard.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
W, H = 1200, 630
BG, INK, DIM, MUT, ACCENT, LIVE = "#000000", "#f3f4f5", "#8b909a", "#585d66", "#5b8def", "#4ad991"

FONT_DIRS = ["/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts"]


def font(names, size):
    for n in names:
        for d in FONT_DIRS:
            p = os.path.join(d, n)
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except OSError:
                    pass
    return ImageFont.load_default()


f_big = font(["HelveticaNeue.ttc", "Helvetica.ttc", "Arial.ttf"], 74)
f_sub = font(["HelveticaNeue.ttc", "Helvetica.ttc", "Arial.ttf"], 32)
f_mono = font(["Menlo.ttc", "Courier New.ttf"], 21)

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

# hairline frame, matching the site's 1px panel borders
d.rectangle([40, 40, W - 41, H - 41], outline="#1b1c1f")

# logo
pup = Image.open(os.path.join(ROOT, "assets", "bilbo-pup.png")).convert("RGBA")
ph = 150
pup = pup.resize((int(pup.width * ph / pup.height), ph), Image.LANCZOS)
img.paste(pup, (86, 96), pup)

d.text((86 + pup.width + 26, 128), "BILBO DATA", font=f_big, fill=INK)
d.text((86 + pup.width + 30, 212), "SITUATIONAL AWARENESS FOR EVERY SIDEWALK",
       font=f_mono, fill=MUT)

d.text((86, 320), "Live vehicle counts off New York City's", font=f_sub, fill=DIM)
d.text((86, 364), "917 public traffic cameras.", font=f_sub, fill=INK)

# status strip
y = 470
d.line([86, y, W - 86, y], fill="#1b1c1f")
d.ellipse([88, y + 30, 100, y + 42], fill=LIVE)
d.text((112, y + 26), "OPEN DATA", font=f_mono, fill=DIM)
d.text((260, y + 26), "NO FACES", font=f_mono, fill=DIM)
d.text((400, y + 26), "NO PLATE NUMBERS", font=f_mono, fill=DIM)
d.text((W - 86 - d.textlength("bilbodata.vercel.app", font=f_mono), y + 26),
       "bilbodata.vercel.app", font=f_mono, fill=ACCENT)

out = os.path.join(ROOT, "assets", "og-card.png")
img.save(out, optimize=True)
print(f"{out}  {W}x{H}  {os.path.getsize(out) // 1024} KB")
