// End-to-end check in a real Chrome. Needs the site on :8000 and the API on :8080 with ALLOWED_ORIGINS=http://localhost:8000 (make site, make api).
// Covers: the Indonesian interface, the price layers, the legend that isolates a tier, kecamatan search, address search (the geocoder is mocked and
// must be called once per query thanks to the cache), the H3 view, placing a pin, an estimate, both refusals, and a phone.
// Usage: node tests/e2e.mjs [screenshot-folder]
import assert from "node:assert/strict";
import puppeteer from "puppeteer-core";

const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const SITE = process.env.SITE || "http://localhost:8000/?api=http://localhost:8080";
const shots = process.argv[2];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--window-size=1400,900"] });
const problems = [], geocoderCalls = [];

async function open(viewport) {
  const page = await browser.newPage();
  await page.setViewport(viewport);
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error" && !/GL Driver|WebGL|ReadPixels|status of 422/.test(m.text())) problems.push(`console: ${m.text()}`); }); // the 422 is the refusal this test provokes
  page.on("requestfailed", (r) => { if (r.failure()?.errorText !== "net::ERR_ABORTED") problems.push(`request failed: ${r.url()} (${r.failure()?.errorText})`); }); // the map cancels tile downloads when the view jumps
  await page.setRequestInterception(true);
  page.on("request", (req) => {
    if (req.url().startsWith("https://nominatim.openstreetmap.org/")) {
      geocoderCalls.push(req.url());
      return req.respond({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" },
        body: JSON.stringify([{ lat: "-6.1944", lon: "106.8229", display_name: "Plaza Indonesia, Jalan M.H. Thamrin, Menteng, Jakarta Pusat, DKI Jakarta" },
                              { lat: "-7.25", lon: "112.75", display_name: "Plaza Surabaya, Jawa Timur" }]) });
    }
    req.continue();
  });
  await page.goto(SITE, { waitUntil: "networkidle2", timeout: 60000 });
  await page.waitForFunction(() => document.querySelectorAll("#legend .seg").length === 7, { timeout: 30000 });
  await sleep(4000);
  return page;
}
const shot = async (page, name) => shots && page.screenshot({ path: `${shots}/${name}.png` });
const text = (page, selector) => page.$eval(selector, (n) => n.textContent);

const page = await open({ width: 1400, height: 900 });

// the interface is in Indonesian
assert.equal(await page.evaluate(() => document.documentElement.lang), "id");
const visible = await page.evaluate(() => document.body.innerText);
for (const english of ["Estimate", "Likely", "asking", "Search", "Hover", "Kecamatan:"]) assert.ok(!visible.includes(english), `English text on the page: ${english}`);
assert.match(visible, /Hitung harga rumah/);

// price layers and the legend
const layers = await page.evaluate(() => { const f = window.__map.queryRenderedFeatures({ layers: ["kecamatan-fill"] }); return { rendered: f.length, withPrice: f.filter((x) => x.properties.cls >= 0).length }; });
assert.ok(layers.rendered > 100 && layers.withPrice > 100, JSON.stringify(layers));
const legend = await page.$$eval("#legend .seg", (s) => s.map((b) => b.title));
assert.equal(legend.length, 7);
assert.match(legend[0], /^di bawah 4,5 juta per m²: \d+ kecamatan$/);
await shot(page, "1-map");

// pointing at a tier isolates it; leaving restores
await page.hover("#legend .seg:nth-child(7)");
await sleep(400);
assert.match(await page.evaluate(() => JSON.stringify(window.__map.getPaintProperty("kecamatan-fill", "fill-opacity"))), /0\.1/);
await shot(page, "2-isolate");
await page.mouse.move(700, 450);
await sleep(300);
assert.doesNotMatch(await page.evaluate(() => JSON.stringify(window.__map.getPaintProperty("kecamatan-fill", "fill-opacity"))), /"==",\["get","cls"\],6/);

// kecamatan search while typing
await page.type("#q", "kebayoran");
await page.waitForSelector('#suggestions li[role="option"]');
const options = await page.$$eval('#suggestions li[role="option"]', (li) => li.map((n) => n.textContent));
assert.ok(options.some((o) => o.startsWith("Kebayoran Baru")), `suggestions: ${options}`);
assert.equal(geocoderCalls.length, 0, "typing must not call the geocoder");
await page.click('#suggestions li[role="option"]');
await page.waitForFunction(() => !document.getElementById("area").hidden);
assert.match(await text(page, "#area"), /Kebayoran Baru[\s\S]*Rp \d+[,\d]* juta/);
await sleep(1500);
await shot(page, "3-area");

// address search: only on Enter, once per query, cached
await page.$eval("#q", (i) => { i.value = ""; });
await page.type("#q", "plaza indonesia");
assert.equal(geocoderCalls.length, 0, "typing must not call the geocoder");
await page.keyboard.press("Enter");
await page.waitForFunction(() => [...document.querySelectorAll('#suggestions li[role="option"]')].some((li) => li.textContent.startsWith("Plaza Indonesia")), { timeout: 15000 });
assert.equal(geocoderCalls.length, 1);
assert.equal(await page.$$eval('#suggestions li[role="option"]', (li) => li.length), 1, "a place outside Jabodetabek must be filtered out");
await page.keyboard.press("Enter"); await page.keyboard.press("Enter"); // resubmitting the same query uses the cache
await sleep(1500);
assert.equal(geocoderCalls.length, 1, "the same query must not call the geocoder again");
await page.click('#suggestions li[role="option"]');
await page.waitForFunction(() => Math.abs(Number(document.getElementById("lat").value) + 6.1944) < 0.001);
await page.waitForFunction(() => /Menteng/.test(document.getElementById("area").textContent), { timeout: 20000 });

// the finer view (back to the whole region first: the search flew to street level)
await page.evaluate(() => window.__map.jumpTo({ center: [106.85, -6.37], zoom: 9.3 }));
await page.click('#views [data-view="h3"]');
await sleep(3000);
const cells = await page.evaluate(() => window.__map.queryRenderedFeatures({ layers: ["h3-fill"] }).length);
assert.ok(cells > 100, `h3 cells rendered: ${cells}`);
await shot(page, "4-h3");
await page.click('#views [data-view="kecamatan"]');
await sleep(2000);

// estimate: place a pin on the map, fill the form, ask the API
await page.click("#open-estimate");
await page.waitForSelector("#estimate:not([hidden])");
await page.evaluate(() => window.__map.jumpTo({ center: [106.8106, -6.2615], zoom: 10.5 }));
await sleep(2500);
const box = await (await page.$("#map")).boundingBox();
const where = await page.evaluate(() => { const p = window.__map.project([106.8106, -6.2615]); return { x: p.x, y: p.y }; });
await page.mouse.click(box.x + where.x, box.y + where.y);
await sleep(600);
assert.ok(Math.abs(Number(await page.$eval("#lat", (i) => i.value)) + 6.2615) < 0.02);
await page.type("#land_area", "150"); await page.type("#building_area", "200"); await page.type("#bedrooms", "4"); await page.type("#bathrooms", "3");
await page.type("#notes", "rumah mewah cluster");
await page.click("#submit");
await page.waitForFunction(() => document.querySelector("#result .big"), { timeout: 90000 });
const result = await text(page, "#result");
assert.match(result, /Kisaran harga paling mungkin/); assert.match(result, /Rp \d+,\d+ – \d+,\d+ miliar/); assert.match(result, /Kebayoran Baru/); assert.match(result, /kisaran lebar \(80%\)/);
await sleep(1200);
await shot(page, "5-estimate");

// refusals: the form stops coordinates outside the area; a point in the sea is refused by the API in Indonesian
await page.$eval("#lat", (i) => { i.value = ""; }); await page.type("#lat", "-6.85");
assert.equal(await page.$eval("#lat", (i) => i.validity.valid), false);
await page.$eval("#lat", (i) => { i.value = ""; }); await page.type("#lat", "-5.95");
await page.$eval("#lon", (i) => { i.value = ""; }); await page.type("#lon", "106.5");
await page.click("#submit");
await page.waitForFunction(() => /di luar wilayah Jabodetabek/.test(document.querySelector("#result")?.textContent ?? ""), { timeout: 30000 })
  .catch(async () => assert.fail(`no refusal message; result shows: ${await text(page, "#result")}`));

// a phone
const phone = await open({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
const layout = await phone.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth, legendCollapsed: document.getElementById("legend").classList.contains("collapsed") }));
assert.equal(layout.scroll, layout.inner, `horizontal overflow: ${JSON.stringify(layout)}`);
assert.equal(layout.legendCollapsed, true);
await shot(phone, "6-phone");
await phone.click("#open-estimate");
await sleep(500);
const sheet = await phone.$eval("#estimate", (n) => { const r = n.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, inner: window.innerHeight }; });
assert.ok(sheet.top >= 0 && sheet.bottom <= sheet.inner + 1, `the estimate sheet does not fit: ${JSON.stringify(sheet)}`);
await shot(phone, "7-phone-estimate");

await browser.close();
assert.deepEqual(problems, [], problems.join("\n"));
console.log("e2e ok:", { legend: legend.length, ...layers, cells, geocoderCalls: geocoderCalls.length, result: result.slice(0, 110) });
