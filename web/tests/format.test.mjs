import assert from "node:assert/strict";
import test from "node:test";

import { classLabels, distanceLabel, edgeLabel, errorMessage, factorLine, nearest, millions, perM2, perM2Range, rp, rpRange, versusMedian, WARNINGS } from "../format.mjs";

test("rp uses miliar and juta with a decimal comma", () => {
  assert.equal(rp(4_903_966_639), "Rp 4,90 miliar");
  assert.equal(rp(12_345_000_000), "Rp 12,3 miliar");
  assert.equal(rp(850_000_000), "Rp 850 juta");
  assert.equal(rp(32_693_111), "Rp 32,7 juta");
  assert.equal(rp(90_000), "Rp 90.000");
  assert.equal(rp(NaN), "tidak tersedia");
});

test("rpRange has the same precision on both ends, in the unit of the upper end", () => {
  assert.equal(rpRange(4_163_467_676, 7_081_327_826), "Rp 4,16 – 7,08 miliar");
  assert.equal(rpRange(3_940_000_000, 6_700_000_000), "Rp 3,94 – 6,70 miliar");
  assert.equal(rpRange(850_000_000, 990_000_000), "Rp 850 – 990 juta");
  assert.equal(rpRange(900_000_000, 1_400_000_000), "Rp 0,90 – 1,40 miliar");
  assert.equal(rpRange(8_000_000_000, 12_000_000_000), "Rp 8,0 – 12,0 miliar");
});

test("per m² values are in juta", () => {
  assert.equal(perM2(32_905_711), "Rp 32,9 juta per m²");
  assert.equal(perM2Range(27_900_000, 47_200_000), "Rp 27,9 – 47,2 juta per m²");
  assert.equal(millions(14.4), "14,4");
});

test("classLabels from the class edges", () => {
  assert.deepEqual(classLabels([0.5, 4.5, 7, 9, 12, 16, 24, 70]), ["di bawah 4,5", "4,5–7", "7–9", "9–12", "12–16", "16–24", "24 ke atas"]);
});

test("edgeLabel drops a trailing zero", () => {
  assert.equal(edgeLabel(9), "9");
  assert.equal(edgeLabel(4.5), "4,5");
});

test("versusMedian in words", () => {
  assert.equal(versusMedian(40.4, 14.4), "2,8× harga umum Jabodetabek");
  assert.equal(versusMedian(20, 14.4), "39% di atas harga umum Jabodetabek");
  assert.equal(versusMedian(7, 14.4), "51% di bawah harga umum Jabodetabek");
  assert.equal(versusMedian(14.5, 14.4), "setara dengan harga umum Jabodetabek");
});

test("errorMessage in Indonesian for codes, validation lists, rate limits and server errors", () => {
  assert.match(errorMessage(422, { detail: { code: "outside_area", message: "x" } }), /di luar wilayah Jabodetabek/);
  assert.equal(errorMessage(422, { detail: [{ loc: ["body", "land_area"], type: "greater_than_equal", ctx: { ge: 15 } }] }), "Luas tanah minimal 15.");
  assert.equal(errorMessage(422, { detail: [{ loc: ["body", "bedrooms"], type: "less_than_equal", ctx: { le: 8 } }] }), "Jumlah kamar tidur maksimal 8.");
  assert.equal(errorMessage(422, { detail: [{ loc: ["body", "specs", "furnished_level"], type: "less_than_equal", ctx: { le: 2 } }] }), "Kondisi furnitur maksimal 2.");
  assert.match(errorMessage(422, { detail: [{ loc: ["body", "land_area"], type: "missing" }] }), /Isi luas tanah/);
  assert.match(errorMessage(429, {}), /Terlalu banyak permintaan/);
  assert.match(errorMessage(500, null), /bermasalah/);
});

test("every warning code the API can send has a translation", () => {
  assert.deepEqual(Object.keys(WARNINGS).sort(), ["auction", "large_plot", "take_over"]);
});

test("factorLine says direction and strength in words, never a number", () => {
  assert.equal(factorLine({ code: "location", effect: 0.4 }).text, "Menaikkan banyak");
  assert.equal(factorLine({ code: "land", effect: -0.15 }).text, "Menurunkan cukup");
  assert.equal(factorLine({ code: "rooms", effect: 0.03 }).text, "Menaikkan sedikit");
  assert.ok(!/\d/.test(factorLine({ code: "land", effect: -0.31 }).text));
});

test("distanceLabel uses metres under a kilometre and a decimal comma above", () => {
  assert.equal(distanceLabel(847), "850 m");
  assert.equal(distanceLabel(2340), "2,3 km");
});

const point = (name, lon, lat) => ({ properties: { name, kind: "toll" }, geometry: { coordinates: [lon, lat] } });
test("nearest keeps only points in range, nearest first, and merges points of one place", () => {
  const spots = [point("far", 106.9, -6.2), point("a", 106.801, -6.2), point("a-booth", 106.8012, -6.2), point("b", 106.81, -6.2), point("c", 106.82, -6.2), point("d", 106.83, -6.2)];
  const found = nearest(spots, -6.2, 106.8, { maxM: 5000, count: 3, mergeM: 500 });
  assert.deepEqual(found.map((p) => p.name), ["a", "b", "c"]);
  assert.deepEqual(nearest(spots, -6.2, 107.5, { maxM: 5000 }), [], "nothing in range gives an empty list, not the closest far one");
});
