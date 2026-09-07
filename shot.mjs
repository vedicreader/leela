import {chromium} from 'playwright';
const [url, out, w='1440', h='1000', full='1', wait='2500'] = process.argv.slice(2);
const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium-1194/chrome-linux/chrome'});
const p = await b.newPage({viewport:{width:+w, height:+h}, deviceScaleFactor:2});
await p.goto(url, {waitUntil:'networkidle'});
await p.waitForTimeout(+wait);
if (full === '1') await scrollThrough(p);
await p.screenshot({path: out, fullPage: full === '1'});
await b.close();

/* An iframe below the fold is never painted, so a full-page shot of it comes back blank. */
export async function scrollThrough(p) {
  const H = await p.evaluate(() => document.body.scrollHeight);
  for (let y = 0; y < H; y += 600) { await p.evaluate(v => scrollTo(0, v), y); await p.waitForTimeout(160); }
  await p.evaluate(() => scrollTo(0, 0)); await p.waitForTimeout(500);
}
