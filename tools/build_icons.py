"""Generate every app-icon asset from Leela's mark.

`leela-mark.png` is the one source: the mark lifted off its plate, on transparency. macOS 26 draws
`Leela.icon` through Icon Composer and everything before it reads the ICNS, so both are built here
and cannot drift. The plate and its rounded corners are drawn rather than baked into the artwork,
which is what lets Icon Composer supply the material and tint the mark as a shape.
"""

import base64
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT/'packaging'/'assets'
MARK = ASSETS/'leela-mark.png'
GROUND = '#06203C'


def image(size):
    scale = size / 1024
    q = lambda value: max(1, round(value * scale))
    im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    plate = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle((q(64), q(64), q(960), q(960)), radius=q(224), fill=GROUND)
    im.alpha_composite(plate)
    mark = Image.open(MARK).convert('RGBA').resize((q(896), q(896)), Image.LANCZOS)
    im.alpha_composite(mark, (q(64), q(64)))
    return im


def svg():
    "The mark as the flat artwork `iconmage create` takes: no plate, since it supplies its own."
    href = base64.b64encode(MARK.read_bytes()).decode()
    return ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            'viewBox="0 0 1024 1024" width="1024" height="1024">\n'
            f'  <image width="1024" height="1024" xlink:href="data:image/png;base64,{href}"/>\n'
            '</svg>\n')


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS/'Leela.svg').write_text(svg())
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
