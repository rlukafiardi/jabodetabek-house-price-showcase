import assert from "node:assert/strict";
import test from "node:test";

import { areaSummary, errorMessage, perM2, perM2Range, rp, rpRange } from "../format.mjs";

test("rp picks a readable unit", () => {
  assert.equal(rp(4_903_966_639), "Rp 4.9 bn");
  assert.equal(rp(12_345_000_000), "Rp 12.3 bn");
  assert.equal(rp(850_000_000), "Rp 850 million");
  assert.equal(rp(32_693_111), "Rp 32.7 million");
  assert.equal(rp(90_000), "Rp 90,000");
  assert.equal(rp(NaN), "n/a");
});

test("rpRange uses the unit of the upper end", () => {
  assert.equal(rpRange(4_163_467_676, 7_081_327_826), "Rp 4.16 - 7.08 bn");
  assert.equal(rpRange(850_000_000, 990_000_000), "Rp 850 - 990 million");
  assert.equal(rpRange(900_000_000, 1_400_000_000), "Rp 0.90 - 1.40 bn");
  assert.equal(rpRange(3_940_000_000, 6_700_000_000), "Rp 3.94 - 6.70 bn");
  assert.equal(rpRange(8_000_000_000, 12_000_000_000), "Rp 8.0 - 12.0 bn");
});

test("perM2 is in millions", () => assert.equal(perM2(32_905_711), "Rp 32.9 million per m²"));

test("errorMessage handles a string, a validation list, rate limiting and server errors", () => {
  assert.equal(errorMessage(422, { detail: "The point is outside Jabodetabek." }), "The point is outside Jabodetabek.");
  assert.match(errorMessage(422, { detail: [{ loc: ["body", "land_area"], msg: "Input should be greater than or equal to 15" }] }), /land_area/);
  assert.match(errorMessage(429, {}), /Too many requests/);
  assert.match(errorMessage(500, null), /problem/);
});

test("areaSummary explains a missing price and flags mixed areas", () => {
  assert.match(areaSummary({ n: 3, cls: -1 }, 5), /3 listings: fewer than 5/);
  assert.match(areaSummary({ n: 1, cls: -1 }, 5), /1 listing:/);
  assert.match(areaSummary({ n: 30, cls: 4, median: 14.2, p25: 10, p75: 19, mixed: 1 }, 5), /mixed/);
});

test("perM2Range", () => assert.equal(perM2Range(27_900_000, 47_200_000), "Rp 27.9 - 47.2 million per m²"));
