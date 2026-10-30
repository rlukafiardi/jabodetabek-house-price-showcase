import assert from "node:assert/strict";
import test from "node:test";

import { geocoderUrl, matchAreas, normalize, parsePlaces } from "../search.mjs";

const areas = [{ code: "1", name: "Kebayoran Baru", city: "Kota Jakarta Selatan" }, { code: "2", name: "Kebayoran Lama", city: "Kota Jakarta Selatan" },
  { code: "3", name: "Menteng", city: "Kota Jakarta Pusat" }, { code: "4", name: "Pondok Gede", city: "Kota Bekasi" }, { code: "5", name: "Tebet", city: "Kota Jakarta Selatan" }];

test("normalize ignores case, accents and punctuation", () => assert.equal(normalize("  Kebáyoran-Baru! "), "kebayoran baru"));

test("matchAreas ranks a name prefix before a word prefix before contained text", () => {
  assert.deepEqual(matchAreas(areas, "keb").map((a) => a.code), ["1", "2"]);
  assert.deepEqual(matchAreas(areas, "gede").map((a) => a.code), ["4"]);
  assert.deepEqual(matchAreas(areas, "ntng").map((a) => a.code), []);
  assert.deepEqual(matchAreas(areas, "bekasi").map((a) => a.code), ["4"], "the city name finds its kecamatan");
});

test("matchAreas needs two characters", () => assert.deepEqual(matchAreas(areas, "k"), []));

test("geocoderUrl is limited to the area and asks for Indonesian names", () => {
  const url = new URL(geocoderUrl("Plaza Indonesia"));
  assert.equal(url.hostname, "nominatim.openstreetmap.org");
  assert.equal(url.searchParams.get("q"), "Plaza Indonesia");
  assert.equal(url.searchParams.get("bounded"), "1");
  assert.equal(url.searchParams.get("viewbox"), "106.4,-5.9,107.3,-6.8");
  assert.equal(url.searchParams.get("accept-language"), "id");
});

test("parsePlaces keeps places inside the area and splits the label", () => {
  const places = parsePlaces([{ lat: "-6.1944", lon: "106.8229", display_name: "Plaza Indonesia, Jalan M.H. Thamrin, Menteng, Jakarta Pusat, DKI Jakarta" },
    { lat: "-7.25", lon: "112.75", display_name: "Surabaya, Jawa Timur" }, { lat: "x", lon: "y", display_name: "bad" }]);
  assert.equal(places.length, 1);
  assert.equal(places[0].label, "Plaza Indonesia");
  assert.equal(places[0].detail, "Jalan M.H. Thamrin, Menteng, Jakarta Pusat");
  assert.deepEqual(parsePlaces(null), []);
});
