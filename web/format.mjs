// Formatting for the Indonesian interface: numbers with a decimal comma and "miliar" / "juta". Pure functions, tested in tests/format.test.mjs.

const nf = (digits) => new Intl.NumberFormat("id-ID", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const num = (value, digits = 0) => nf(digits).format(value);

/** "Rp 4,9 miliar", "Rp 850 juta" or "Rp 90.000". */
export function rp(value) {
  if (!Number.isFinite(value)) return "tidak tersedia";
  if (value >= 1e9) return `Rp ${num(value / 1e9, value >= 1e10 ? 1 : 2)} miliar`;
  if (value >= 1e6) return `Rp ${num(value / 1e6, value >= 1e8 ? 0 : 1)} juta`;
  return `Rp ${num(Math.round(value))}`;
}

/** A range in the unit of its upper end, both ends at the same precision: "Rp 4,16 – 7,08 miliar", "Rp 850 – 990 juta". */
export function rpRange(low, high) {
  const [divisor, unit, digits] = high >= 1e10 ? [1e9, " miliar", 1] : high >= 1e9 ? [1e9, " miliar", 2] : [1e6, " juta", high >= 1e8 ? 0 : 1];
  return `Rp ${num(low / divisor, digits)} – ${num(high / divisor, digits)}${unit}`;
}

/** Price per m² of land in millions: "Rp 32,9 juta per m²". */
export function perM2(value) {
  return `Rp ${num(value / 1e6, value >= 1e8 ? 0 : 1)} juta per m²`;
}

/** "Rp 27,9 – 47,2 juta per m²". */
export function perM2Range(low, high) {
  const digits = high >= 1e8 ? 0 : 1;
  return `Rp ${num(low / 1e6, digits)} – ${num(high / 1e6, digits)} juta per m²`;
}

/** A median in millions of rupiah per m², as the map data stores it: 14.4 becomes "14,4". */
export const millions = (value) => num(value, value >= 100 ? 0 : 1);

/** An edge of a price class: "4,5" or "9" (no trailing ",0"). */
export const edgeLabel = (v) => num(v, Number.isInteger(v) ? 0 : 1);

/** Legend labels from the class edges (millions of Rp per m²): "di bawah 4,5", "4,5–7", ..., "24 ke atas". */
export function classLabels(edges) {
  const n = edgeLabel;
  const inner = edges.slice(1, -2).map((a, i) => `${n(a)}–${n(edges[i + 2])}`);
  return [`di bawah ${n(edges[1])}`, ...inner, `${n(edges[edges.length - 2])} ke atas`];
}

/** How far a price is from a reference, in words: "37% di atas median Jabodetabek". */
export function versusMedian(value, median) {
  const diff = Math.round((value / median - 1) * 100);
  if (value / median >= 2) return `${num(value / median, 1)}× median Jabodetabek`;
  if (Math.abs(diff) < 3) return "setara dengan median Jabodetabek";
  return `${Math.abs(diff)}% ${diff > 0 ? "di atas" : "di bawah"} median Jabodetabek`;
}

const FIELDS = { lat: "lintang", lon: "bujur", land_area: "luas tanah", building_area: "luas bangunan", bedrooms: "jumlah kamar tidur", bathrooms: "jumlah kamar mandi",
  floors: "jumlah lantai", notes: "catatan", electricity_va: "daya listrik", carport: "carport", car_access: "akses mobil", garage: "garasi", maid_rooms: "kamar pembantu",
  furnished_level: "kondisi furnitur", water_pam: "sumber air" };

/** A readable message in Indonesian from an API error (FastAPI sends a code object, a list of validation errors, or a status). */
export function errorMessage(status, body) {
  if (status === 429) return "Terlalu banyak permintaan. Tunggu satu menit lalu coba lagi.";
  const detail = body && body.detail;
  if (detail && detail.code === "outside_area") return "Titik ini di luar wilayah Jabodetabek. Pilih lokasi di dalam area peta yang berwarna.";
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0];
    const field = Array.isArray(first.loc) ? first.loc.filter((p) => p !== "body" && p !== "specs").pop() : undefined;
    const label = FIELDS[field] ?? "isian";
    if (first.type === "missing") return `Isi ${label} terlebih dahulu.`;
    if (first.type?.startsWith("greater_than")) return `${label[0].toUpperCase()}${label.slice(1)} minimal ${num(first.ctx?.ge ?? first.ctx?.gt)}.`;
    if (first.type?.startsWith("less_than")) return `${label[0].toUpperCase()}${label.slice(1)} maksimal ${num(first.ctx?.le ?? first.ctx?.lt)}.`;
    if (first.type === "string_too_long") return "Catatan terlalu panjang (maksimal 2.000 karakter).";
    return `Periksa kembali ${label}.`;
  }
  return status >= 500 ? "Layanan estimasi sedang bermasalah. Coba lagi sebentar lagi." : "Permintaan tidak dapat diproses.";
}

/** Warning codes from the API, in Indonesian. */
export const WARNINGS = {
  large_plot: "Tanah di atas 300 m² lebih sulit diperkirakan, jadi kisarannya lebih lebar.",
  take_over: "Rumah take over (over kredit) dijual dengan biaya pengalihan, bukan harga rumahnya. Estimasi ini tidak berlaku untuk rumah seperti itu.",
  auction: "Rumah lelang biasanya dijual di bawah harga pasar, jadi estimasi ini bisa terlalu tinggi.",
};
