"""Generate macOS ICNS and Windows ICO from Leela's geometric app mark."""

from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT/'packaging'/'assets'


def image(size):
    scale = size / 1024
    im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    q = lambda value: round(value * scale)
    d.rounded_rectangle((q(64), q(64), q(960), q(960)), radius=q(224), fill='#171b20')
    d.polygon([(q(300), q(258)), (q(438), q(258)), (q(438), q(634)),
               (q(728), q(634)), (q(728), q(766)), (q(300), q(766))], fill='#f4f7f9')
    d.rounded_rectangle((q(696), q(696), q(792), q(792)), radius=q(24), fill='#4b8fbd')
    return im


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
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
