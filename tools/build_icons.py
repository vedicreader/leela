"""Generate every app-icon asset from the turtle artwork in `packaging/assets`.

Icon Composer (`Leela.icon`) and the ICNS are built here together so they cannot drift. The plate
and its rounded corners are drawn rather than baked into the artwork, which is what lets Icon
Composer supply the material and tint the mark as a shape.

The artwork comes as two whole drawings, `leela-turtle-light` and `leela-turtle-dark`: the same
turtle in navy ink on cream and in cream ink on navy. Both carry their own background, and
`leela-turtle-mask` is the line work's silhouette, so `mark` uses it as an alpha channel and gets
the ink on its own. The tab icon ships as both, chosen by `prefers-color-scheme`; the app icon is
the cream one, which is what reads on the navy plate.
"""

import base64, io
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT/'packaging'/'assets'
MARKS = {'light': ASSETS/'leela-turtle-light.png', 'dark': ASSETS/'leela-turtle-dark.png'}
MASK = ASSETS/'leela-turtle-mask.png'
GROUND = '#06203C'
PLATE = 'dark'           # the cream line work: the plate it sits on is navy
#: Committed, unlike the icons: they ship in the wheel, which has no build step to draw them. Kept
#: honest by `test_the_favicon_is_the_mark_it_is_generated_from`.
FAVICONS = {'light': ROOT/'leela'/'static'/'favicon.svg',
            'dark': ROOT/'leela'/'static'/'favicon-dark.svg'}
FAVICON_PX = 64          # the plate stops carrying the mark's line work below this


def mark(variant=PLATE):
    "The turtle's line work with its own background masked away."
    im = Image.open(MARKS[variant]).convert('RGBA')
    im.putalpha(Image.open(MASK).convert('L'))
    return im


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
    im.alpha_composite(mark().resize((q(896), q(896)), Image.LANCZOS), (q(64), q(64)))
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
    href = png_href(mark(variant).resize((size, size), Image.LANCZOS))
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
        subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(ASSETS/'Leela.icns')], check=True)
        print(ASSETS/'Leela.icns')
    print(ASSETS/'Leela.ico')


if __name__ == '__main__': main()
