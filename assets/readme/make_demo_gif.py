"""Builds assets/readme/demo.gif from the screenshots in assets/readme/screens/.  Run: python3 assets/readme/make_demo_gif.py  (needs Pillow)"""
from PIL import Image, ImageDraw, ImageFont
W, H, BAR = 800, 499, 44
S = "assets/readme/screens/"
shots = [("1-website.jpg", "Website: AI receptionist, map and 139 languages"),
         ("2-booking.jpg", "Book a real doctor: free slots, clinic or video"),
         ("3-doctor-page.jpg", "Every doctor gets a public page Google can find"),
         ("4-app.jpg", "Installed phone app: its own home screen and tabs"),
         ("5-dashboard.jpg", "Doctor dashboard: visits, earnings, busiest hours")]
try:
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 19)
except OSError:
    font = ImageFont.load_default()

def frame(name, label, i):
    im = Image.open(S + name).convert("RGB")
    canvas = Image.new("RGB", (W, H + BAR), (11, 14, 26))
    if im.width < im.height:  # phone screenshot: centre it on a soft background
        ph = im.resize((int(im.width * H / im.height), H), Image.LANCZOS)
        bg = Image.new("RGB", (W, H), (18, 22, 42))
        bg.paste(ph, ((W - ph.width) // 2, 0))
        im = bg
    else:
        im = im.resize((W, H), Image.LANCZOS)
    canvas.paste(im, (0, 0))
    d = ImageDraw.Draw(canvas)
    d.rectangle([0, H, W, H + BAR], fill=(17, 20, 38))
    d.rectangle([0, H, int(W * (i + 1) / len(shots)), H + 3], fill=(124, 92, 255))  # progress bar
    d.text((16, H + 12), f"{i + 1}/{len(shots)}  {label}", fill=(235, 238, 255), font=font)
    d.text((W - 16, H + 12), "clinora-cwxu.onrender.com", fill=(140, 150, 190), font=font, anchor="ra")
    return canvas

frames, durations = [], []
base = [frame(n, l, i) for i, (n, l) in enumerate(shots)]
for i, f in enumerate(base):
    frames.append(f); durations.append(2300)
    nxt = base[(i + 1) % len(base)]
    for k in (2,):
        frames.append(Image.blend(f, nxt, 0.5)); durations.append(120)
pal = [fr.quantize(colors=128, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG) for fr in frames]
pal[0].save("assets/readme/demo.gif", save_all=True, append_images=pal[1:], duration=durations, loop=0, optimize=True)
import os; print(os.path.getsize("assets/readme/demo.gif") // 1024, "KB")
