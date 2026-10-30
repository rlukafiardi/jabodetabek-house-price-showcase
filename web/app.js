import { CONFIG } from "./config.js";
import { areaSummary, errorMessage, perM2, perM2Range, rp, rpRange } from "./format.mjs";

const STYLE = "https://tiles.openfreemap.org/styles/positron";
const params = new URLSearchParams(location.search);
const API_BASE = (["localhost", "127.0.0.1"].includes(location.hostname) && params.get("api")) || CONFIG.apiBase;
const REQUEST_TIMEOUT_MS = 70_000;
const SLOW_NOTICE_MS = 4_000;

const $ = (id) => document.getElementById(id);
const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const [meta, kecamatan, h3] = await Promise.all(["meta", "kecamatan", "h3"].map((name) => fetch(`data/${name}.${name === "meta" ? "json" : "geojson"}`).then((r) => r.json())));
const state = { view: "kecamatan", point: null, marker: null, hovered: null };

// ---- about text from the data's own numbers
const pct = (v) => `${Math.round(v * 100)}%`;
$("about-listings").textContent = meta.listings_total.toLocaleString("en-US");
$("about-window").textContent = `${meta.listings_from} to ${meta.listings_to}`;
$("about-min").textContent = meta.min_listings;
$("about-error").textContent = `${(meta.model.holdout_median_error * 100).toFixed(0)}%`;
$("about-likely").textContent = pct(meta.model.coverage_likely);
$("about-possible").textContent = pct(meta.model.coverage_possible);

// ---- legend
function buildLegend() {
  const legend = $("legend");
  const box = el("details"), summary = el("summary", "title", "Median asking price, million Rp per m² of land");
  box.open = window.matchMedia("(min-width: 801px)").matches; // collapsed on phones, where the map needs the room
  box.append(summary);
  meta.labels.forEach((label, i) => {
    const item = el("div", "item");
    const swatch = el("span", "swatch");
    swatch.style.background = meta.colors[i];
    item.append(swatch, el("span", "", label));
    box.append(item);
  });
  const none = el("div", "item"), noneSwatch = el("span", "swatch");
  noneSwatch.style.background = meta.empty_color;
  none.append(noneSwatch, el("span", "", `fewer than ${meta.min_listings} listings`));
  const mixed = el("div", "item");
  mixed.append(el("span", "swatch mixed"), el("span", "", "outlined: mixed prices"));
  box.append(none, mixed);
  legend.replaceChildren(box);
}
buildLegend();

// ---- map
const bounds = [[106.35, -6.80], [107.30, -5.95]];
const map = new maplibregl.Map({ container: "map", style: STYLE, bounds, fitBoundsOptions: { padding: 10 }, attributionControl: { compact: true }, maxBounds: [[105.8, -7.4], [107.9, -5.5]] });
window.__map = map; // a handle for the end-to-end test (tests/e2e.mjs)
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");

const colorExpression = ["case", ["==", ["get", "cls"], -1], meta.empty_color, ["to-color", ["at", ["get", "cls"], ["literal", meta.colors]]]];
const hoverOpacity = (base) => ["case", ["boolean", ["feature-state", "hover"], false], Math.min(base + 0.2, 1), base];

map.on("load", () => {
  const firstLabel = map.getStyle().layers.find((l) => l.type === "symbol")?.id; // keep place names above the colours
  map.addSource("kecamatan", { type: "geojson", data: kecamatan, promoteId: "code" });
  map.addSource("h3", { type: "geojson", data: h3, generateId: true });
  map.addLayer({ id: "kecamatan-fill", type: "fill", source: "kecamatan", paint: { "fill-color": colorExpression, "fill-opacity": hoverOpacity(0.7) } }, firstLabel);
  map.addLayer({ id: "kecamatan-line", type: "line", source: "kecamatan", paint: { "line-color": "#ffffff", "line-width": 0.6, "line-opacity": 0.8 } }, firstLabel);
  map.addLayer({ id: "kecamatan-mixed", type: "line", source: "kecamatan", filter: ["==", ["get", "mixed"], 1], paint: { "line-color": "#111111", "line-width": 2 } }, firstLabel);
  map.addLayer({ id: "h3-fill", type: "fill", source: "h3", layout: { visibility: "none" }, paint: { "fill-color": colorExpression, "fill-opacity": hoverOpacity(0.75) } }, firstLabel);
  map.addLayer({ id: "h3-line", type: "line", source: "h3", layout: { visibility: "none" }, paint: { "line-color": "#ffffff", "line-width": 0.6 } }, firstLabel);
  wireHover("kecamatan-fill", "kecamatan");
  wireHover("h3-fill", "h3");
  map.on("click", (e) => setPoint(e.lngLat.lat, e.lngLat.lng, true));
});

function wireHover(layer, source) {
  map.on("mousemove", layer, (e) => {
    const feature = e.features[0];
    if (!feature || state.view !== (source === "h3" ? "h3" : "kecamatan")) return;
    if (state.hovered) map.setFeatureState(state.hovered, { hover: false });
    state.hovered = { source, id: feature.id };
    map.setFeatureState(state.hovered, { hover: true });
    showArea(feature.properties, source);
    map.getCanvas().style.cursor = "crosshair";
  });
  map.on("mouseleave", layer, () => {
    if (state.hovered) map.setFeatureState(state.hovered, { hover: false });
    state.hovered = null;
    map.getCanvas().style.cursor = "";
  });
}

function showArea(props, source) {
  const box = $("hover");
  const title = source === "h3" ? "Area of about 5 km²" : `${props.name}, ${props.city ?? ""}`.replace(/, $/, "");
  box.replaceChildren(el("b", "", title), document.createTextNode(areaSummary(props, meta.min_listings)));
}

// features under a clicked point, for touch screens where there is no hover
function describePoint(lat, lon) {
  const point = map.project([lon, lat]);
  const layer = state.view === "h3" ? "h3-fill" : "kecamatan-fill";
  const feature = map.queryRenderedFeatures(point, { layers: [layer] })[0];
  if (feature) showArea(feature.properties, state.view === "h3" ? "h3" : "kecamatan");
}

$("toggle").addEventListener("click", (e) => {
  const view = e.target.dataset?.view;
  if (!view || !map.getLayer("h3-fill")) return;
  state.view = view;
  document.querySelectorAll("#toggle button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === view)));
  const h3View = view === "h3";
  const show = (id, on) => map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
  show("kecamatan-fill", !h3View); show("kecamatan-mixed", !h3View); show("h3-fill", h3View); show("h3-line", h3View);
  map.setPaintProperty("kecamatan-line", "line-color", h3View ? "#9a9a96" : "#ffffff");
  $("hover").textContent = h3View ? "Cells of about 5 km² with at least 5 listings. Hover to see a price." : "Hover or tap an area to see its price.";
});

// ---- the point of the house
function setPoint(lat, lon, fromMap = false) {
  state.point = { lat: Number(lat.toFixed(6)), lon: Number(lon.toFixed(6)) };
  $("lat").value = state.point.lat;
  $("lon").value = state.point.lon;
  if (!state.marker) {
    state.marker = new maplibregl.Marker({ draggable: true, color: "#e34948" }).setLngLat([lon, lat]).addTo(map);
    state.marker.on("dragend", () => { const p = state.marker.getLngLat(); setPoint(p.lat, p.lng, true); });
  } else {
    state.marker.setLngLat([lon, lat]);
  }
  if (!fromMap) map.easeTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 12) });
  else describePoint(lat, lon);
}
for (const id of ["lat", "lon"]) {
  $(id).addEventListener("change", () => {
    const lat = parseFloat($("lat").value), lon = parseFloat($("lon").value);
    if (Number.isFinite(lat) && Number.isFinite(lon)) setPoint(lat, lon);
  });
}
$("locate").addEventListener("click", () => {
  if (!navigator.geolocation) return showResult(el("div", "card error", "This browser cannot share a location."));
  navigator.geolocation.getCurrentPosition((p) => setPoint(p.coords.latitude, p.coords.longitude),
    () => showResult(el("div", "card error", "The location could not be read. Click the map instead.")), { timeout: 10_000 });
});

// ---- the estimate
const showResult = (node) => { $("result").replaceChildren(node); node.scrollIntoView({ block: "nearest", behavior: "smooth" }); };
const optionalNumber = (id) => { const v = $(id).value.trim(); return v === "" ? undefined : Number(v); };

function requestBody() {
  const specs = {};
  for (const id of ["electricity_va", "carport", "car_access", "garage", "maid_rooms", "furnished_level", "water_pam"]) {
    const v = optionalNumber(id);
    if (v !== undefined) specs[id] = v;
  }
  return { lat: state.point.lat, lon: state.point.lon, land_area: Number($("land_area").value), building_area: Number($("building_area").value),
           bedrooms: Number($("bedrooms").value), bathrooms: Number($("bathrooms").value), floors: optionalNumber("floors") ?? null, notes: $("notes").value.trim(), specs };
}

function resultCard(r, landArea) {
  const card = el("div", "card");
  card.append(el("div", "label", "Likely asking price"), el("div", "big", rpRange(...r.likely_range_idr)),
              el("div", "sub", perM2Range(r.likely_range_idr[0] / landArea, r.likely_range_idr[1] / landArea) + " of land"));
  card.append(el("div", "sub", `Estimate ${rp(r.price_idr)} (${perM2(r.price_per_m2_land_idr)})`),
              el("div", "sub", `Possible range ${rpRange(...r.possible_range_idr)}`),
              el("div", "sub", `${r.area.kecamatan}${r.area.city ? `, ${r.area.city}` : ""}`));
  if (r.warnings.length) {
    const list = el("ul");
    r.warnings.forEach((w) => list.append(el("li", "", w)));
    card.append(list);
  }
  const m = meta.model;
  card.append(el("div", "fine", `An asking-price estimate, not a valuation. On listings the model never saw, half of the estimates were within ${(m.holdout_median_error * 100).toFixed(0)}% ` +
                                `of the asking price; the likely range held ${pct(m.coverage_likely)} of them and the possible range ${pct(m.coverage_possible)}.`));
  return card;
}

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!$("form").reportValidity()) return;
  if (!state.point) return showResult(el("div", "card error", "Click the map to place the house first."));
  if (!API_BASE) return showResult(el("div", "card error", "The estimate service is not connected yet. The map works; the estimate will be available soon."));
  const button = $("submit"), land = Number($("land_area").value);
  button.disabled = true;
  showResult(el("div", "card", "Estimating..."));
  const slow = setTimeout(() => showResult(el("div", "card", "Waking the service up. The first request after a quiet period can take up to a minute...")), SLOW_NOTICE_MS);
  const abort = new AbortController(), timer = setTimeout(() => abort.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE}/estimate`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(requestBody()), signal: abort.signal });
    const body = await response.json().catch(() => null);
    showResult(response.ok ? resultCard(body, land) : el("div", "card error", errorMessage(response.status, body)));
  } catch (error) {
    showResult(el("div", "card error", error.name === "AbortError" ? "The service took too long. Please try again." : "The estimate service could not be reached. Please try again in a moment."));
  } finally {
    clearTimeout(slow); clearTimeout(timer); button.disabled = false;
  }
});
