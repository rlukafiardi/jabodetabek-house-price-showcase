// Formatting helpers for prices and API errors. Pure functions, tested in tests/format.test.mjs (node --test).

const trim = (n, digits) => Number(n.toFixed(digits)).toString();

/** Rupiah as "Rp 4.9 bn" (miliar), "Rp 850 million" (juta) or "Rp 90,000". */
export function rp(value) {
  if (!Number.isFinite(value)) return "n/a";
  if (value >= 1e9) return `Rp ${trim(value / 1e9, value >= 1e10 ? 1 : 2)} bn`;
  if (value >= 1e6) return `Rp ${trim(value / 1e6, value >= 1e8 ? 0 : 1)} million`;
  return `Rp ${Math.round(value).toLocaleString("en-US")}`;
}

/** A range in the unit of its upper end, both ends at the same precision: "Rp 4.16 - 7.08 bn", "Rp 850 - 990 million". */
export function rpRange(low, high) {
  const [divisor, unit, digits] = high >= 1e10 ? [1e9, " bn", 1] : high >= 1e9 ? [1e9, " bn", 2] : [1e6, " million", high >= 1e8 ? 0 : 1];
  return `Rp ${(low / divisor).toFixed(digits)} - ${(high / divisor).toFixed(digits)}${unit}`;
}

/** Price per m² of land in millions: "Rp 32.9 million per m²". */
export function perM2(value) {
  return `Rp ${trim(value / 1e6, value >= 1e8 ? 0 : 1)} million per m²`;
}

/** A per-m² range in millions, same precision on both ends: "Rp 27.9 - 47.2 million per m²". */
export function perM2Range(low, high) {
  const digits = high >= 1e8 ? 0 : 1;
  return `Rp ${(low / 1e6).toFixed(digits)} - ${(high / 1e6).toFixed(digits)} million per m²`;
}

/** A readable message from an API error body (FastAPI sends a string or a list of validation errors). */
export function errorMessage(status, body) {
  if (status === 429) return "Too many requests. Please wait a minute and try again.";
  const detail = body && body.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0];
    const field = Array.isArray(first.loc) ? first.loc.filter((p) => p !== "body").join(" ") : "input";
    return `Please check ${field}: ${first.msg}.`;
  }
  return status >= 500 ? "The estimate service had a problem. Please try again in a moment." : "The request could not be completed.";
}

/** Median price for the hover box, or why there is none. */
export function areaSummary(props, minListings) {
  const n = props.n ?? 0;
  if (props.cls === -1 || props.median == null) return `${n} ${n === 1 ? "listing" : "listings"}: fewer than ${minListings}, so no price is shown`;
  const spread = props.mixed ? " Prices here are mixed (premium and ordinary pockets)." : "";
  return `Median Rp ${props.median} million per m² of land (middle half: ${props.p25}-${props.p75}), ${n} listings.${spread}`;
}
