#!/usr/bin/env python
"Render a canvas document as its literate page. Leela does the work; this only picks the file."

import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from leela.blocks.canvas.app import branch_page, page
from leela.blocks.canvas.doc import Canvas
from leela.blocks.canvas.explain import capture, explain, replay

SRC, OUT = 'docs/change.canvas.md', 'media/canvas-change.html'

if __name__ == '__main__':
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--src', default=SRC, help='the canvas document')
    a.add_argument('--out', default=OUT, help='where to write the page')
    a.add_argument('--base', default='origin/main', help='what to diff against for the file list')
    a.add_argument('--prompts', help='write the drafting prompts here and stop')
    a.add_argument('--answers', help='fill the snippet bodies from this file of answers')
    a.add_argument('--overwrite', action='store_true', help='redraft a snippet that has a body')
    a.add_argument('--reviews', action='store_true',
                   help='every bundle as a review, so each file sits under the prose about it')
    args = a.parse_args()
    doc = Canvas.load(args.src)
    if args.prompts:
        explain(doc, capture(args.prompts), root='.', overwrite=True)
        print(f'prompts for {len(doc.of("snippet", "diff"))} brick(s) -> {args.prompts}')
        raise SystemExit
    if args.answers:
        got = explain(doc, replay(args.answers), root='.', overwrite=args.overwrite)
        doc.save()
        print(f'{len(got)} brick(s) drafted')
    r = (branch_page if args.reviews else page)(doc, args.out, args.base)
    print(f'{len(r["changed"])} file(s) changed, {len(r["unclaimed"])} claimed by nobody')
    print(r['path'])
