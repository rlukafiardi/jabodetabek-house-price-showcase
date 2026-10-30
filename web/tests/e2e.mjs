// End-to-end check in a real Chrome: the map draws prices, hovering explains an area, the H3 toggle works, clicking places a point, and the
// estimate form shows a result from the API. Needs Chrome, the site on :8000 and the API on :8080 with ALLOWED_ORIGINS=http://localhost:8000.
// Usage: node tests/e2e.mjs [screenshot-folder]
import assert from "node:assert/strict";
import puppeteer from "puppeteer-core";

const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const SITE = process.env.SITE || "http://localhost:8000/?api=http://localhost:8080";
const shots = process.argv[2];

const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--window-size=1400,900"] });
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 900 });
const problems = [];
page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
page.on("console", (m) => { if (m.type() === "error" && !/GL Driver|WebGL|ReadPixels|status of 422/.test(m.text()))  problems.push(`console: ${m.text()}`); });
page.on("requestfailed", (r) => problems.push(`request failed: ${r.url()}`));

await page.goto(SITE, { waitUntil: "networkidle2", timeout: 60000 });
await page.waitForFunction(() => document.querySelector("#legend .item"), { timeout: 20000 });
await page.waitForFunction(() => window.__map?.loaded?.() ?? false, { timeout: 30000 }).catch(() => {});
await new Promise((r) => setTimeout(r, 4000));
const shot = async (name) => shots && page.screenshot({ path: `${shots}/${name}.png` });

// the legend and the data
const legend = await page.$$eval("#legend .item", (items) => items.map((i) => i.textContent));
assert.ok(legend.length >= 8, `legend items: ${legend.length}`);
await shot("1-map");

// hover a point in central Jakarta (screen position of Menteng) through the map's own query
const info = await page.evaluate(() => {
  const map = window.__map;
  const features = map.queryRenderedFeatures({ layers: ["kecamatan-fill"] });
  return { rendered: features.length, withPrice: features.filter((f) => f.properties.cls >= 0).length };
});
assert.ok(info.rendered > 100, `kecamatan polygons rendered: ${info.rendered}`);
assert.ok(info.withPrice > 100, `kecamatan with a price: ${info.withPrice}`);

// H3 toggle
await page.click('#toggle button[data-view="h3"]');
await new Promise((r) => setTimeout(r, 1500));
const h3 = await page.evaluate(() => window.__map.queryRenderedFeatures({ layers: ["h3-fill"] }).length);
assert.ok(h3 > 100, `h3 cells rendered: ${h3}`);
await shot("2-h3");
await page.click('#toggle button[data-view="kecamatan"]');
await new Promise((r) => setTimeout(r, 2000)); // let the layer repaint before clicking

// place a point by clicking the map, fill the form, estimate
const box = await (await page.$("#map")).boundingBox();
const where = await page.evaluate(() => { const p = window.__map.project([106.8106, -6.2615]); return { x: p.x, y: p.y }; });
await page.mouse.click(box.x + where.x, box.y + where.y);
await new Promise((r) => setTimeout(r, 500));
const lat = await page.$eval("#lat", (i) => Number(i.value));
assert.ok(Math.abs(lat + 6.2615) < 0.02, `latitude after click: ${lat}`);
const hover = await page.$eval("#hover", (h) => h.textContent);
assert.match(hover, /Kebayoran|listings/, `hover box: ${hover}`);
await page.type("#land_area", "150"); await page.type("#building_area", "200"); await page.type("#bedrooms", "4"); await page.type("#bathrooms", "3");
await page.type("#notes", "rumah mewah cluster");
await page.click("#submit");
await page.waitForFunction(() => document.querySelector("#result .big"), { timeout: 90000 });
const result = await page.$eval("#result", (r) => r.textContent);
assert.match(result, /Likely asking price/); assert.match(result, /Rp \d/); assert.match(result, /Kebayoran Baru/);
await new Promise((r) => setTimeout(r, 1200)); // the page scrolls the result into view
await shot("3-estimate");

// the form refuses coordinates outside the area before asking the API; a point in the sea is refused by the API with a clear message
await page.$eval("#lat", (i) => { i.value = ""; }); await page.type("#lat", "-6.85");
assert.equal(await page.$eval("#lat", (i) => i.validity.valid), false, "latitude -6.85 should be invalid in the form");
await page.$eval("#lat", (i) => { i.value = ""; }); await page.type("#lat", "-5.95");
await page.$eval("#lon", (i) => { i.value = ""; }); await page.type("#lon", "106.5");
await page.click("#submit");
await page.waitForFunction(() => /outside Jabodetabek/.test(document.querySelector("#result")?.textContent ?? ""), { timeout: 30000 })
  .catch(async () => assert.fail(`no refusal message; result shows: ${await page.$eval("#result", (r) => r.textContent)}`));

// a phone: no horizontal scrolling, and the legend starts collapsed
const phone = await browser.newPage();
await phone.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
await phone.goto(SITE, { waitUntil: "networkidle2", timeout: 60000 });
await new Promise((r) => setTimeout(r, 3000));
const widths = await phone.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth, legendOpen: document.querySelector("#legend details").open }));
assert.equal(widths.scroll, widths.inner, `horizontal overflow on a phone: ${JSON.stringify(widths)}`);
assert.equal(widths.legendOpen, false, "the legend should start collapsed on a phone");
if (shots) await phone.screenshot({ path: `${shots}/4-phone.png` });
await browser.close();
assert.deepEqual(problems, [], problems.join("\n"));
console.log("e2e ok:", { legend: legend.length, ...info, h3, result: result.slice(0, 120) });
