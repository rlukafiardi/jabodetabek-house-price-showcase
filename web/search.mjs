// Search helpers: instant matching of kecamatan names from the map data, and the request to and parsing of the free OpenStreetMap geocoder
// (Nominatim). Its policy allows search on submit at moderate traffic with caching, and forbids search-as-you-type, so only the kecamatan names
// are matched while typing. Pure functions, tested in tests/search.test.mjs.

export const BBOX = { west: 106.4, south: -6.8, east: 107.3, north: -5.9 }; // the area the API accepts

export const normalize = (text) => text.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, " ").trim();

/** Kecamatan whose name matches the query: whole-name prefix first, then word prefix, then contained text. */
export function matchAreas(areas, query, limit = 6) {
  const q = normalize(query);
  if (q.length < 2) return [];
  const scored = [];
  for (const area of areas) {
    const name = normalize(area.name), city = normalize(area.city ?? "");
    const score = name.startsWith(q) ? 0 : name.split(" ").some((w) => w.startsWith(q)) ? 1 : name.includes(q) ? 2 : `${name} ${city}`.includes(q) ? 3 : null;
    if (score !== null) scored.push({ area, score });
  }
  return scored.sort((a, b) => a.score - b.score || a.area.name.localeCompare(b.area.name)).slice(0, limit).map((s) => s.area);
}

/** The geocoder request for a place name, limited to the area the API accepts. */
export function geocoderUrl(query) {
  const params = new URLSearchParams({ q: query, format: "jsonv2", limit: "6", countrycodes: "id", "accept-language": "id", bounded: "1",
    viewbox: `${BBOX.west},${BBOX.north},${BBOX.east},${BBOX.south}` });
  return `https://nominatim.openstreetmap.org/search?${params}`;
}

/** Places from a geocoder answer: a short label, the rest as detail, inside the area only. */
export function parsePlaces(results) {
  return (Array.isArray(results) ? results : []).map((r) => ({ lat: Number(r.lat), lon: Number(r.lon), full: String(r.display_name ?? "") }))
    .filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon) && p.lat >= BBOX.south && p.lat <= BBOX.north && p.lon >= BBOX.west && p.lon <= BBOX.east)
    .map((p) => { const parts = p.full.split(",").map((s) => s.trim()); return { lat: p.lat, lon: p.lon, label: parts[0] || "Tempat", detail: parts.slice(1, 4).join(", ") }; });
}
