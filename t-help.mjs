import {chromium} from 'playwright';
const U=(f,q='')=>`http://127.0.0.1:5002/canvas?path=/home/user/leela/examples/canvas/${f}.canvas.md&fresh=1${q}`;
const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium-1194/chrome-linux/chrome'});
const p = await b.newPage({viewport:{width:1400, height:1100}, deviceScaleFactor:2});
p.on('pageerror', e=>console.log('PAGEERROR', e.message));
await p.goto(U('a-sales-funnel'), {waitUntil:'networkidle'}); await p.waitForTimeout(2500);

// 1. margin ask
await p.fill('#cv-askform input', 'what is cac?');
await p.press('#cv-askform input', 'Enter');
await p.waitForTimeout(2500);
console.log('THREAD:', (await p.locator('#cv-thread').innerText()).replace(/\n/g,' | ').slice(0,300));
console.log('bricks now', await p.locator('.cv-brick').count());
await p.screenshot({path:'shots/h1-ask.png'});

// 2. inline ask on a selection
await p.evaluate(() => {
  const el = document.querySelector('.cv-brick.cv-text .cv-prose');
  const r = document.createRange(); r.selectNodeContents(el.querySelector('p') || el);
  const s = getSelection(); s.removeAllRanges(); s.addRange(r);
});
await p.keyboard.press('Control+k');
await p.waitForTimeout(400);
console.log('inline visible', await p.locator('#cv-inline').isVisible());
await p.fill('#cv-inline input', 'tighten this');
await p.screenshot({path:'shots/h2-inline.png'});
await p.press('#cv-inline input', 'Enter');
await p.waitForTimeout(2200);
console.log('first para now:', (await p.locator('.cv-brick.cv-text .cv-prose').first().innerText()).slice(0,200));
await p.screenshot({path:'shots/h3-tightened.png'});
console.log('trail:', (await p.locator('#cv-trail').innerText()).replace(/\n/g,' | '));
await b.close();
