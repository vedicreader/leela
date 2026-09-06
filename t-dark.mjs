import {chromium} from 'playwright';
const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium-1194/chrome-linux/chrome'});
const p = await b.newPage({viewport:{width:1440, height:1500}, deviceScaleFactor:2});
p.on('pageerror', e => console.log('PAGEERROR', e.message));
await p.route('**/*', r => /127\.0\.0\.1|localhost/.test(r.request().url()) ? r.continue() : r.abort());
await p.goto('http://127.0.0.1:5002/canvas?path=/home/user/leela/examples/canvas/an-animal-cell.canvas.md&fresh=1', {waitUntil:'load'});
await p.waitForTimeout(3000);
await p.click('#cv-theme'); await p.waitForTimeout(2200);
console.log('theme:', await p.evaluate(() => document.body.dataset.theme));
await p.screenshot({path:'out/shots/ui-dark.png'});
// format bar
await p.click('.cv-prose p', {clickCount:3}); await p.waitForTimeout(500);
console.log('format bar:', await p.locator('#cv-format').isVisible());
await p.screenshot({path:'out/shots/ui-format.png'});
await b.close();
