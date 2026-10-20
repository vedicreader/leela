"""Generate every app-icon asset from `packaging/assets/leela-logo.png`.

Icon Composer (`Leela.icon`) and the ICNS are built here together so they cannot drift. The plate
and its rounded corners are drawn rather than baked into the artwork, which is what lets Icon
Composer supply the material and tint the mark as a shape.

The artwork is one sheet of four: the mark plated and bare, in dark ink on paper and in white ink
on charcoal. `mark` takes a bare quadrant, keys out the paper it was drawn on, and trims to the ink,
so what comes back is the stroke alone at a size the plate can be drawn around. The tab icon ships
as both inks, chosen by `prefers-color-scheme`; the app icon is the white one on the charcoal plate,
which is the plated quadrant of the design.
"""

import base64, io
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT/'packaging'/'assets'
SHEET = ASSETS/'leela-logo.png'
#: Which quadrant of the sheet each bare mark is, as (column, row), and whether its ink is the dark
#: one. The plated pair on the left is the reference for `GROUND`, not a source.
QUADRANTS = {'light': ((1, 0), True), 'dark': ((1, 1), False)}
INK = {'light': (26, 26, 30), 'dark': (250, 250, 249)}
GROUND = '#24262b'       # the charcoal plate of the design's own dark icon
PLATE = 'dark'           # white ink, which is what reads on it
MARGIN = .06             # around the trimmed ink, so the stroke is not flush to the plate
#: Committed, unlike the icons: they ship in the wheel, which has no build step to draw them. Kept
#: honest by `test_the_favicon_is_the_mark_it_is_generated_from`.
FAVICONS = {'light': ROOT/'leela'/'static'/'favicon.svg',
            'dark': ROOT/'leela'/'static'/'favicon-dark.svg'}
FAVICON_PX = 64          # the plate stops carrying the mark's line work below this


def quadrant(which):
    "One quarter of the sheet, which is laid out as two columns by two rows."
    im = Image.open(SHEET).convert('RGB')
    w, h = im.width//2, im.height//2
    cx, cy = which
    return im.crop((cx*w, cy*h, (cx+1)*w, (cy+1)*h))

def mark(variant=PLATE, size=1024):
    """One bare mark as the stroke alone: paper keyed out, trimmed to the ink, centred square.

    The cutoff comes from the corners rather than a constant. The paper is not pure white and the
    charcoal is not pure black, so a fixed threshold left the whole dark quadrant faintly opaque and
    the trim found nothing to trim.
    """
    where, dark_ink = QUADRANTS[variant]
    g = quadrant(where).convert('L')
    a = g.point(lambda v: 255 - v) if dark_ink else g
    corners = [a.getpixel(p) for p in ((0, 0), (a.width-1, 0), (0, a.height-1), (a.width-1, a.height-1))]
    lo, hi = max(corners) + 22, 210
    a = a.point(lambda v: 0 if v <= lo else 255 if v >= hi else int((v - lo) * 255 / (hi - lo)))
    ink = Image.new('RGB', g.size, INK[variant]); ink.putalpha(a)
    cut = ink.crop(a.getbbox())
    side = max(cut.size); pad = int(side * MARGIN)
    out = Image.new('RGBA', (side + 2*pad, side + 2*pad), (0, 0, 0, 0))
    out.alpha_composite(cut, ((out.width - cut.width)//2, (out.height - cut.height)//2))
    return out.resize((size, size), Image.LANCZOS)


def png_href(im):
    "One image as a base64 PNG data URI body."
    buf = io.BytesIO(); im.save(buf, 'PNG', optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def image(size):
    scale = size / 1024
    q = lambda value: max(1, round(value * scale))
    im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    plate = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle((q(64), q(64), q(960), q(960)), radius=q(224), fill=GROUND)
    im.alpha_composite(plate)
    im.alpha_composite(mark(size=q(896)), (q(64), q(64)))
    return im


def svg():
    "The mark as the flat artwork `iconmage create` takes: no plate, since it supplies its own."
    return ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            'viewBox="0 0 1024 1024" width="1024" height="1024">\n'
            f'  <image width="1024" height="1024" xlink:href="data:image/png;base64,{png_href(mark())}"/>\n'
            '</svg>\n')


def favicon(variant=PLATE, size=FAVICON_PX):
    """One variant's line work as a tab icon: a committed SVG, so a page costs no extra request.

    No plate. A tab strip is the browser's own colour, and the point of shipping both is that the
    ink sits on it directly.
    """
    href = png_href(mark(variant, size=size))
    return ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 {size} {size}" width="{size}" height="{size}">\n'
            f'  <image width="{size}" height="{size}" xlink:href="data:image/png;base64,{href}"/>\n'
            '</svg>\n')


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS/'Leela.svg').write_text(svg())
    for variant, path in FAVICONS.items(): path.write_text(favicon(variant))
    iconset = ASSETS/'Leela.iconset'; iconset.mkdir(exist_ok=True)
    for points in (16, 32, 128, 256, 512):
        image(points).save(iconset/f'icon_{points}x{points}.png')
        image(points * 2).save(iconset/f'icon_{points}x{points}@2x.png')
    image(1024).save(ASSETS/'Leela.png')
    image(256).save(ASSETS/'Leela.ico', sizes=[(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)])
    import shutil, subprocess
    if shutil.which('iconutil'):
        subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(ASSETS/'Leela.icns')], check=True, stdin=subprocess.DEVNULL)
        print(ASSETS/'Leela.icns')
    print(ASSETS/'Leela.ico')


if __name__ == '__main__': main()
