import assert from "node:assert/strict";
import test from "node:test";
import { compareAsk, parseRupiah } from "../format.mjs";
import { readShared, shareQuery } from "../share.mjs";

test("parseRupiah reads prices the way people type them", () => {
  assert.equal(parseRupiah("4,5 miliar"), 4.5e9);
  assert.equal(parseRupiah("Rp 4,5 M"), 4.5e9);
  assert.equal(parseRupiah("4500 juta"), 4.5e9);
  assert.equal(parseRupiah("850jt"), 8.5e8);
  assert.equal(parseRupiah("1.250 juta"), 1.25e9);
  assert.equal(parseRupiah("Rp 4.500.000.000"), 4.5e9);
  assert.equal(parseRupiah("4500000000"), 4.5e9);
});

test("parseRupiah refuses what it cannot read", () => {
  for (const text of ["", "abc", "4500", "4,5 kilo", "5 juta", "9999 miliar", "-3 miliar"]) assert.ok(Number.isNaN(parseRupiah(text)), text);
});

const estimate = { price_idr: 4.6e9, likely_range_idr: [3.9e9, 6.6e9], possible_range_idr: [3.2e9, 9.1e9] };
test("compareAsk places an ad price against both ranges", () => {
  assert.equal(compareAsk(4.6e9, estimate).where, "inside");
  assert.match(compareAsk(4.6e9, estimate).text, /sekitar sama dengan perkiraan/);
  assert.equal(compareAsk(7e9, estimate).where, "above-likely");
  assert.equal(compareAsk(3.5e9, estimate).where, "below-likely");
  assert.equal(compareAsk(12e9, estimate).where, "above");
  assert.equal(compareAsk(2e9, estimate).where, "below");
  assert.match(compareAsk(5.06e9, estimate).text, /10% di atas perkiraan/);
});

const body = { lat: -6.2615, lon: 106.8106, land_area: 150, building_area: 200, bedrooms: 4, bathrooms: 3, floors: null, notes: "rumah baru, cluster", specs: { carport: 2, water_pam: 1 } };
test("a shared link round-trips the form values", () => {
  const back = readShared(shareQuery(body));
  assert.deepEqual({ ...back, specs: undefined }, { lat: -6.2615, lon: 106.8106, land_area: 150, building_area: 200, bedrooms: 4, bathrooms: 3, floors: undefined, specs: undefined, notes: "rumah baru, cluster" });
  assert.deepEqual(back.specs, { carport: 2, water_pam: 1 });
});

test("a broken or edited link is ignored, not half-applied", () => {
  assert.equal(readShared(""), null);
  assert.equal(readShared("lat=-6.2&lon=106.8"), null);
  assert.equal(readShared(shareQuery(body).replace("lt=150", "lt=99999")), null);
  assert.equal(readShared(shareQuery(body).replace("lat=-6.2615", "lat=abc")), null);
  assert.equal(readShared(shareQuery({ ...body, lat: 10 })), null);
});

test("notes in a link are capped", () => {
  assert.equal(readShared(shareQuery({ ...body, notes: "x".repeat(900) })).notes.length, 300);
});

import { affordability, factorLine } from "../format.mjs";

test("factorLine turns an API factor into words in Indonesian", () => {
  assert.deepEqual(factorLine({ code: "location", effect: 0.261 }), { label: "Lokasi dan akses transportasi", hint: "jarak ke pusat kota, stasiun, dan tol", up: true, percent: 26, text: "naik 26%" });
  assert.equal(factorLine({ code: "land", effect: -0.249 }).text, "turun 25%");
  assert.equal(factorLine({ code: "new_thing", effect: 0.1, label: "Something" }).label, "Something");
});

test("affordability compares a typical house on the land size with the budget", () => {
  const area = { cls: 3, median: 12, p25: 8 };
  assert.equal(affordability(area, 1.3e9, 100), "fit"); // 12 M x 100 = 1.2 billion
  assert.equal(affordability(area, 1.0e9, 100), "maybe"); // only the cheaper quarter, 0.8 billion
  assert.equal(affordability(area, 0.5e9, 100), "over");
  assert.equal(affordability({ cls: -1, median: null, p25: null }, 9e12, 100), "none");
});
