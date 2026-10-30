// A result as a link: the form values go into the URL, so the same estimate opens for whoever gets the link.
const KEYS = { land_area: "lt", building_area: "lb", bedrooms: "kt", bathrooms: "km", floors: "lantai" };
const SPEC_KEYS = { electricity_va: "va", carport: "carport", car_access: "akses", garage: "garasi", maid_rooms: "art", furnished_level: "furnitur", water_pam: "air" };
const NOTES_MAX = 300;
const LIMITS = { lat: [-6.8, -5.9], lon: [106.4, 107.3], land_area: [15, 5000], building_area: [15, 3000], bedrooms: [1, 8], bathrooms: [1, 8], floors: [1, 6] };

/** Query string (without "?") for an estimate request body. */
export function shareQuery(body) {
  const q = new URLSearchParams({ lat: body.lat, lon: body.lon });
  for (const [field, key] of Object.entries(KEYS)) if (body[field] !== null && body[field] !== undefined) q.set(key, body[field]);
  for (const [field, key] of Object.entries(SPEC_KEYS)) if (body.specs?.[field] !== undefined) q.set(key, body.specs[field]);
  if (body.notes) q.set("catatan", body.notes.slice(0, NOTES_MAX));
  return q.toString();
}

/** Form values from a shared link, or null when a required value is missing or outside the form's limits (a broken or edited link). */
export function readShared(search) {
  const q = new URLSearchParams(search), get = (key) => (q.has(key) && q.get(key).trim() !== "" ? Number(q.get(key)) : undefined);
  const values = { lat: get("lat"), lon: get("lon") };
  for (const [field, key] of Object.entries(KEYS)) values[field] = get(key);
  for (const [field, [min, max]] of Object.entries(LIMITS)) {
    const v = values[field];
    if (v === undefined) { if (field === "floors") continue; return null; }
    if (!Number.isFinite(v) || v < min || v > max) return null;
  }
  const specs = {};
  for (const [field, key] of Object.entries(SPEC_KEYS)) { const v = get(key); if (Number.isFinite(v)) specs[field] = v; }
  return { ...values, specs, notes: (q.get("catatan") ?? "").slice(0, NOTES_MAX) };
}
