import { CONFIG } from "./config.js";
import { classLabels, edgeLabel, errorMessage, millions, perM2, perM2Range, rp, rpRange, versusMedian, WARNINGS } from "./format.mjs";
import { BBOX, geocoderUrl, matchAreas, parsePlaces } from "./search.mjs";

const STYLE = "https://tiles.openfreemap.org/styles/positron";
const params = new URLSearchParams(location.search);
const API_BASE = (["localhost", "127.0.0.1"].includes(location.hostname) && params.get("api")) || CONFIG.apiBase;
const REQUEST_TIMEOUT_MS = 70_000;
const SLOW_NOTICE_MS = 4_000;
const GEOCODER_GAP_MS = 1_100; // the free geocoder allows one request per second for the whole site
const isPhone = () => window.matchMedia("(max-width: 800px)").matches;

const $ = (id) => document.getElementById(id);
const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};
const pct = (v) => `${Math.round(v * 100)}%`;

const [meta, kecamatan, h3] = await Promise.all(["meta", "kecamatan", "h3"].map((name) => fetch(`data/${name}.${name === "meta" ? "json" : "geojson"}`).then((r) => r.json())));
for (const f of kecamatan.features) f.properties.label = f.properties.cls >= 0 ? `${f.properties.name}\n${millions(f.properties.median)}` : f.properties.name;
const areas = kecamatan.features.map((f) => f.properties);
const byCode = new Map(kecamatan.features.map((f) => [f.properties.code, f]));
const labels = classLabels(meta.edges);
const readableOn = (hex) => (parseInt(hex.slice(1, 3), 16) * 0.299 + parseInt(hex.slice(3, 5), 16) * 0.587 + parseInt(hex.slice(5, 7), 16) * 0.114 > 150 ? "#1c1a18" : "#ffffff");
const classOf = (millionsPerM2) => meta.edges.slice(1, -1).filter((e) => millionsPerM2 >= e).length;

const state = { view: "kecamatan", point: null, marker: null, hovered: null, selected: null, isolated: null, locked: null, estimateOpen: false };

// ---- the text of "about" from the data's own numbers
$("about-listings").textContent = meta.listings_total.toLocaleString("id-ID");
$("about-window").textContent = `${meta.listings_from} sampai ${meta.listings_to}`;
$("about-min").textContent = meta.min_listings;
$("about-error").textContent = pct(meta.model.holdout_median_error);
$("about-likely").textContent = pct(meta.model.coverage_likely);
$("about-possible").textContent = pct(meta.model.coverage_possible);

// ---- map
const map = new maplibregl.Map({ container: "map", style: STYLE, bounds: [[106.35, -6.80], [107.30, -5.95]], fitBoundsOptions: { padding: isPhone() ? { top: 130, left: 12, right: 12, bottom: 110 } : { top: 70, left: 20, right: 20, bottom: 20 } },
  attributionControl: { compact: true }, maxBounds: [[105.8, -7.4], [107.9, -5.5]] });
window.__map = map; // handles for the end-to-end test (tests/e2e.mjs)
window.__state = state;
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");

const colorExpression = ["case", ["==", ["get", "cls"], -1], meta.empty_color, ["to-color", ["at", ["get", "cls"], ["literal", meta.colors]]]];
const interactive = (base) => ["case", ["boolean", ["feature-state", "hover"], false], Math.min(base + 0.14, 1), ["boolean", ["feature-state", "selected"], false], Math.min(base + 0.14, 1), base];
// the colours fade as you zoom in, so streets and buildings show through at street level
const fillOpacity = (base) => (state.isolated === null ? ["interpolate", ["linear"], ["zoom"], 11.5, interactive(base), 14, interactive(base * 0.5)] : ["case", ["==", ["get", "cls"], state.isolated], 0.96, 0.1]);
const edgeWidth = ["case", ["boolean", ["feature-state", "selected"], false], 3.2, ["boolean", ["feature-state", "hover"], false], 2, 0];

function hatch() {
  const size = 10, canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  ctx.strokeStyle = "#9da1a8"; ctx.lineWidth = 1.2;
  ctx.beginPath(); ctx.moveTo(0, size); ctx.lineTo(size, 0); ctx.moveTo(-2, 2); ctx.lineTo(2, -2); ctx.moveTo(size - 2, size + 2); ctx.lineTo(size + 2, size - 2); ctx.stroke();
  return ctx.getImageData(0, 0, size, size);
}

map.on("load", () => {
  const firstLabel = map.getStyle().layers.find((l) => l.type === "symbol")?.id; // place names of the basemap stay above the colours
  map.addImage("hatch", hatch());
  map.addSource("kecamatan", { type: "geojson", data: kecamatan, promoteId: "code" });
  map.addSource("h3", { type: "geojson", data: h3, generateId: true });
  const fade = { "fill-opacity-transition": { duration: 250 } };
  map.addLayer({ id: "kecamatan-fill", type: "fill", source: "kecamatan", paint: { "fill-color": colorExpression, "fill-opacity": fillOpacity(0.78), ...fade } }, firstLabel);
  map.addLayer({ id: "kecamatan-nodata", type: "fill", source: "kecamatan", filter: ["==", ["get", "cls"], -1], paint: { "fill-pattern": "hatch", "fill-opacity": 0.8 } }, firstLabel);
  map.addLayer({ id: "kecamatan-line", type: "line", source: "kecamatan", paint: { "line-color": "#ffffff", "line-width": 0.7, "line-opacity": 0.85 } }, firstLabel);
  map.addLayer({ id: "kecamatan-mixed", type: "line", source: "kecamatan", filter: ["==", ["get", "mixed"], 1], paint: { "line-color": "#1c1a18", "line-width": 1.6, "line-dasharray": [2, 1.4] } }, firstLabel);
  map.addLayer({ id: "kecamatan-edge", type: "line", source: "kecamatan", paint: { "line-color": "#1c1a18", "line-width": edgeWidth } }, firstLabel);
  map.addLayer({ id: "kecamatan-labels", type: "symbol", source: "kecamatan", minzoom: 10.8, layout: { "text-field": ["get", "label"], "text-font": ["Noto Sans Bold"], "text-size": 11.5, "text-max-width": 7 },
    paint: { "text-color": "#1c1a18", "text-halo-color": "rgba(255,255,255,0.9)", "text-halo-width": 1.4 } });
  map.addLayer({ id: "h3-fill", type: "fill", source: "h3", layout: { visibility: "none" }, paint: { "fill-color": colorExpression, "fill-opacity": fillOpacity(0.82), ...fade } }, firstLabel);
  map.addLayer({ id: "h3-line", type: "line", source: "h3", layout: { visibility: "none" }, paint: { "line-color": "#ffffff", "line-width": 0.8 } }, firstLabel);
  map.addLayer({ id: "h3-edge", type: "line", source: "h3", layout: { visibility: "none" }, paint: { "line-color": "#1c1a18", "line-width": edgeWidth } }, firstLabel);
  wireHover("kecamatan-fill", "kecamatan");
  wireHover("h3-fill", "h3");
  map.on("click", onMapClick);
  buildLegend();
});

const fillLayer = () => (state.view === "h3" ? "h3-fill" : "kecamatan-fill");
const sourceName = () => (state.view === "h3" ? "h3" : "kecamatan");

// a short tooltip while the pointer moves; a click pins the full card
const tip = new maplibregl.Popup({ closeButton: false, closeOnClick: false, className: "tip", offset: 8 });
function tipContent(props) {
  const box = el("div");
  box.append(el("b", "", state.view === "h3" ? "Area sekitar 5 km²" : props.name),
             el("span", "", props.cls >= 0 ? `Rp ${millions(props.median)} juta per m²` : `${props.n} iklan, belum ada harga`));
  return box;
}

function wireHover(layer, source) {
  map.on("mousemove", layer, (e) => {
    const feature = e.features[0];
    if (!feature || sourceName() !== source) return;
    if (state.hovered?.id !== feature.id) {
      if (state.hovered) map.setFeatureState(state.hovered, { hover: false });
      state.hovered = { source, id: feature.id };
      map.setFeatureState(state.hovered, { hover: true });
    }
    tip.setLngLat(e.lngLat).setDOMContent(tipContent(feature.properties)).addTo(map);
    map.getCanvas().style.cursor = "crosshair";
  });
  map.on("mouseleave", layer, () => {
    if (state.hovered) map.setFeatureState(state.hovered, { hover: false });
    state.hovered = null;
    tip.remove();
    map.getCanvas().style.cursor = "";
  });
}

function onMapClick(e) {
  setPoint(e.lngLat.lat, e.lngLat.lng);
  const feature = map.queryRenderedFeatures(e.point, { layers: [fillLayer()] })[0];
  if (feature) selectArea(feature.id, sourceName(), feature.properties);
  else clearSelection();
}

// ---- area card
function track(props) {
  const o = meta.overall, max = o.scale_max, frac = (v) => Math.sqrt(Math.min(Math.max(v / max, 0), 1)), at = (v) => `${frac(v) * 100}%`; // a square-root scale gives the many cheaper areas room
  const side = (v) => (frac(v) > 0.72 ? " right" : frac(v) < 0.14 ? " left" : "");
  const box = el("div", "track");
  const band = el("span", "band");
  band.style.left = at(props.p25); band.style.width = `calc(${at(props.p75)} - ${at(props.p25)})`; band.style.setProperty("--c", meta.colors[props.cls]);
  const med = el("span", "tick"), ref = el("span", "tick ref");
  med.style.left = at(props.median); ref.style.left = at(o.median);
  const capArea = el("span", `cap you${side(props.median)}`, `median ${millions(props.median)}`), capRef = el("span", `cap above${side(o.median)}`, `Jabodetabek ${millions(o.median)}`);
  capArea.style.left = at(props.median); capRef.style.left = at(o.median);
  box.append(el("span", "rail"), band, ref, med, capRef, capArea);
  box.setAttribute("role", "img");
  box.setAttribute("aria-label", `Separuh iklan berharga ${millions(props.p25)} sampai ${millions(props.p75)} juta per m². Median Jabodetabek ${millions(o.median)} juta.`);
  return box;
}

function renderArea(props, source) {
  const card = $("area");
  const close = el("button", "icon", "");
  close.setAttribute("aria-label", "Tutup");
  close.innerHTML = '<svg aria-hidden="true" viewBox="0 0 20 20" width="18" height="18"><path d="m5 5 10 10M15 5 5 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
  close.addEventListener("click", clearSelection);
  const heading = el("div");
  heading.append(el("h3", "", source === "h3" ? "Area sekitar 5 km²" : props.name));
  if (source !== "h3" && props.city) heading.append(el("div", "city", props.city));
  const top = el("div", "top");
  top.append(heading, close);
  card.replaceChildren(top);
  if (props.cls >= 0) {
    const price = el("div", "price", `Rp ${millions(props.median)} juta `);
    price.append(el("small", "", "per m² tanah (median)"));
    card.append(price, el("div", "versus", versusMedian(props.median, meta.overall.median)), track(props));
    card.append(el("p", "note", `Dari ${props.n} iklan. Separuh rumah berharga Rp ${millions(props.p25)} – ${millions(props.p75)} juta per m².`));
    if (props.mixed) card.append(el("p", "note warn", "Harga di sini sangat beragam (ada kawasan premium dan kawasan biasa), jadi median bukan satu harga tipikal."));
  } else {
    card.append(el("div", "price", "Belum ada harga"),
                el("p", "note", `Baru ${props.n} ${props.n === 1 ? "iklan" : "iklan"} di sini, belum cukup untuk menampilkan harga (minimal ${meta.min_listings}).`));
  }
  if (state.point) {
    const cta = el("button", "primary cta wide", "Hitung harga rumah di titik ini");
    cta.addEventListener("click", () => openEstimate());
    card.append(cta);
  }
  card.hidden = false;
}

function selectArea(id, source, props) {
  if (state.selected) map.setFeatureState(state.selected, { selected: false });
  state.selected = { source, id };
  map.setFeatureState(state.selected, { selected: true });
  renderArea(props, source);
}
function clearSelection() {
  if (state.selected) map.setFeatureState(state.selected, { selected: false });
  state.selected = null;
  $("area").hidden = true;
}

// ---- legend: a ramp you can point at to isolate one price tier
function legendCounts() {
  const counts = new Array(meta.classes).fill(0);
  const features = state.view === "h3" ? h3.features : kecamatan.features;
  features.forEach((f) => { if (f.properties.cls >= 0) counts[f.properties.cls] += 1; });
  return { counts, nodata: state.view === "h3" ? 0 : kecamatan.features.filter((f) => f.properties.cls < 0).length };
}

function setIsolation(k) {
  state.isolated = k;
  for (const layer of ["kecamatan-fill", "h3-fill"]) if (map.getLayer(layer)) map.setPaintProperty(layer, "fill-opacity", fillOpacity(layer === "h3-fill" ? 0.82 : 0.78));
  document.querySelectorAll("#legend .seg").forEach((b, i) => b.setAttribute("aria-pressed", String(state.locked === i)));
}

function buildLegend() {
  const legend = $("legend");
  const { counts, nodata } = legendCounts();
  const unit = state.view === "h3" ? "area" : "kecamatan";
  const head = el("button", "title");
  head.type = "button";
  head.append(el("span", "", "Median harga per m² tanah (juta Rp)"));
  head.insertAdjacentHTML("beforeend", '<svg aria-hidden="true" viewBox="0 0 12 12" width="12" height="12"><path d="m2 4 4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>');
  head.addEventListener("click", () => { const c = legend.classList.toggle("collapsed"); head.setAttribute("aria-expanded", String(!c)); });
  const body = el("div", "body"), ramp = el("div", "ramp"), ticks = el("div", "ticks"), keys = el("div", "keys");
  meta.colors.forEach((color, i) => {
    const seg = el("button", "seg", String(counts[i]));
    seg.type = "button";
    seg.style.setProperty("--c", color); seg.style.setProperty("--fg", readableOn(color));
    seg.setAttribute("aria-pressed", "false");
    seg.setAttribute("aria-label", `${labels[i]} juta per m²: ${counts[i]} ${unit}`);
    seg.title = `${labels[i]} juta per m²: ${counts[i]} ${unit}`;
    seg.addEventListener("mouseenter", () => { if (state.locked == null) setIsolation(i); });
    seg.addEventListener("mouseleave", () => { if (state.locked == null) setIsolation(null); });
    seg.addEventListener("focus", () => { if (state.locked == null) setIsolation(i); });
    seg.addEventListener("blur", () => { if (state.locked == null) setIsolation(null); });
    seg.addEventListener("click", () => { state.locked = state.locked === i ? null : i; setIsolation(state.locked); });
    ramp.append(seg);
  });
  meta.edges.slice(1, -1).forEach((edge, i) => { const t = el("span", "", edgeLabel(edge)); t.style.left = `${((i + 1) / meta.classes) * 100}%`; ticks.append(t); });
  const nodataKey = el("span"); nodataKey.append(el("i", "swatch nodata"), document.createTextNode(`tanpa harga (kurang dari ${meta.min_listings} iklan)${state.view === "h3" ? "" : `: ${nodata}`}`));
  const mixedKey = el("span"); mixedKey.append(el("i", "swatch mixed"), document.createTextNode("garis putus-putus: harga beragam"));
  keys.append(...(state.view === "h3" ? [] : [nodataKey, mixedKey]));
  body.append(ramp, ticks, keys);
  legend.replaceChildren(head, body);
  const collapsed = legend.dataset.init ? legend.classList.contains("collapsed") : isPhone();
  legend.dataset.init = "1";
  legend.classList.toggle("collapsed", collapsed);
  head.setAttribute("aria-expanded", String(!collapsed));
}

// ---- views
$("views").addEventListener("click", (e) => {
  const view = e.target.dataset?.view;
  if (!view || view === state.view || !map.getLayer("h3-fill")) return;
  state.view = view;
  state.locked = null;
  setIsolation(null);
  clearSelection();
  tip.remove();
  document.querySelectorAll("#views button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === view)));
  const h3View = view === "h3", show = (id, on) => map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
  for (const id of ["kecamatan-fill", "kecamatan-nodata", "kecamatan-mixed", "kecamatan-edge", "kecamatan-labels"]) show(id, !h3View);
  for (const id of ["h3-fill", "h3-line", "h3-edge"]) show(id, h3View);
  map.setPaintProperty("kecamatan-line", "line-color", h3View ? "#a3a29e" : "#ffffff");
  buildLegend();
});

// ---- the pin
function setPoint(lat, lon) {
  state.point = { lat: Number(lat.toFixed(6)), lon: Number(lon.toFixed(6)) };
  $("lat").value = state.point.lat;
  $("lon").value = state.point.lon;
  if (!state.marker) {
    const dot = el("div", "pin");
    state.marker = new maplibregl.Marker({ element: dot, draggable: true, anchor: "bottom" }).setLngLat([lon, lat]).addTo(map);
    state.marker.on("dragend", () => { const p = state.marker.getLngLat(); setPoint(p.lat, p.lng); selectUnder(p.lng, p.lat); });
  } else {
    state.marker.setLngLat([lon, lat]);
  }
}
function selectUnder(lon, lat) {
  const feature = map.queryRenderedFeatures(map.project([lon, lat]), { layers: [fillLayer()] })[0];
  if (feature) selectArea(feature.id, sourceName(), feature.properties);
}
for (const id of ["lat", "lon"]) {
  $(id).addEventListener("change", () => {
    const lat = parseFloat($("lat").value), lon = parseFloat($("lon").value);
    if (Number.isFinite(lat) && Number.isFinite(lon)) { setPoint(lat, lon); map.easeTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 12) }); }
  });
}
$("locate").addEventListener("click", () => {
  if (!navigator.geolocation) return showResult(el("div", "card error", "Peramban ini tidak bisa membagikan lokasi."));
  navigator.geolocation.getCurrentPosition((p) => { setPoint(p.coords.latitude, p.coords.longitude); map.easeTo({ center: [p.coords.longitude, p.coords.latitude], zoom: 14 }); },
    () => showResult(el("div", "card error", "Lokasi tidak terbaca. Klik peta untuk menaruh pin.")), { timeout: 10_000 });
});

// ---- search: kecamatan names while typing, addresses and places on Enter
const search = { items: [], active: -1, cache: new Map(), last: 0 };
const box = $("suggestions"), input = $("q");

function showSuggestions(entries) {
  search.items = entries.filter((e) => e.action);
  search.active = -1;
  box.replaceChildren(...entries.map((e) => {
    if (e.group) { const heading = el("li", "group", e.group); heading.setAttribute("role", "presentation"); return heading; }
    const li = el("li", "", e.label);
    li.setAttribute("role", "option");
    if (e.detail) li.append(el("small", "", e.detail));
    if (e.action) li.addEventListener("click", () => run(e));
    else li.style.cursor = "default";
    e.node = li;
    return li;
  }));
  box.hidden = entries.length === 0;
  input.setAttribute("aria-expanded", String(!box.hidden));
}
function highlight(i) {
  search.items.forEach((item, k) => item.node.setAttribute("aria-selected", String(k === i)));
  search.active = i;
  search.items[i]?.node.scrollIntoView({ block: "nearest" });
}
function localEntries(q) {
  const matches = matchAreas(areas, q);
  const entries = matches.length ? [{ group: "Kecamatan" }, ...matches.map((a) => ({ label: a.name, detail: a.city ?? "", action: () => goToArea(a.code) }))] : [];
  if (q.trim().length >= 3) entries.push({ group: "Alamat atau tempat" }, { label: `Cari “${q.trim()}”`, detail: "Tekan Enter untuk mencari alamat, mal, atau tempat", action: () => runGeocoder(q.trim()) });
  return entries;
}
function run(entry) { entry.action(); box.hidden = true; input.setAttribute("aria-expanded", "false"); }

function bboxOf(feature) {
  const coords = JSON.stringify(feature.geometry.coordinates).match(/-?\d+\.\d+/g).map(Number);
  let w = 999, s = 999, e = -999, n = -999;
  for (let i = 0; i < coords.length; i += 2) { w = Math.min(w, coords[i]); e = Math.max(e, coords[i]); s = Math.min(s, coords[i + 1]); n = Math.max(n, coords[i + 1]); }
  return [[w, s], [e, n]];
}
function goToArea(code) {
  const feature = byCode.get(code);
  if (!feature) return;
  if (state.view !== "kecamatan") document.querySelector('#views [data-view="kecamatan"]').click();
  input.value = feature.properties.name;
  map.fitBounds(bboxOf(feature), { padding: { top: 90, left: isPhone() ? 20 : 380, right: 40, bottom: isPhone() ? 260 : 60 }, maxZoom: 13.5, duration: 900 });
  selectArea(code, "kecamatan", feature.properties);
}

async function runGeocoder(query) {
  const key = query.toLowerCase();
  showSuggestions([{ group: "Mencari…" }]);
  let places = search.cache.get(key);
  if (!places) {
    const wait = search.last + GEOCODER_GAP_MS - Date.now();
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    try {
      search.last = Date.now();
      const response = await fetch(geocoderUrl(query), { headers: { accept: "application/json" } });
      if (!response.ok) throw new Error(String(response.status));
      places = parsePlaces(await response.json());
      search.cache.set(key, places);
    } catch {
      return showSuggestions([{ group: "Pencarian alamat sedang tidak tersedia. Coba cari nama kecamatan." }]);
    }
  }
  if (!places.length) return showSuggestions([{ group: "Tidak ditemukan di Jabodetabek. Coba nama jalan atau tempat lain." }]);
  showSuggestions([{ group: "Hasil pencarian" }, ...places.map((p) => ({ label: p.label, detail: p.detail, action: () => goToPlace(p) }))]);
}
function goToPlace(place) {
  input.value = place.label;
  setPoint(place.lat, place.lon);
  map.flyTo({ center: [place.lon, place.lat], zoom: 15, duration: 1100 });
  map.once("idle", () => selectUnder(place.lon, place.lat));
}

input.addEventListener("input", () => showSuggestions(localEntries(input.value)));
input.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    if (!search.items.length) return;
    e.preventDefault();
    highlight((search.active + (e.key === "ArrowDown" ? 1 : -1) + search.items.length) % search.items.length);
  } else if (e.key === "Escape") { box.hidden = true; input.setAttribute("aria-expanded", "false"); }
});
$("search").addEventListener("submit", (e) => {
  e.preventDefault();
  if (search.active >= 0) return run(search.items[search.active]);
  const q = input.value.trim();
  if (q.length >= 2) runGeocoder(q);
});
document.addEventListener("click", (e) => { if (!$("search").contains(e.target)) { box.hidden = true; input.setAttribute("aria-expanded", "false"); } });

// ---- the estimate panel
// keep the map's visible centre clear of the open panel, so a pin is never hidden behind it
function fitPadding() {
  if (!state.estimateOpen) return map.easeTo({ padding: { top: 0, bottom: 0, left: 0, right: 0 }, duration: 300 });
  map.easeTo({ padding: isPhone() ? { top: 110, bottom: Math.round(window.innerHeight * 0.6), left: 0, right: 0 } : { top: 0, bottom: 0, left: 0, right: 410 }, duration: 300 });
}
function openEstimate() {
  state.estimateOpen = true;
  $("estimate").hidden = false;
  $("open-estimate").setAttribute("aria-expanded", "true");
  if (isPhone()) $("area").hidden = true;
  fitPadding();
}
function closeEstimate() {
  state.estimateOpen = false;
  $("estimate").hidden = true;
  $("open-estimate").setAttribute("aria-expanded", "false");
  fitPadding();
}
$("open-estimate").addEventListener("click", () => (state.estimateOpen ? closeEstimate() : openEstimate()));
$("close-estimate").addEventListener("click", closeEstimate);

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

function rangeBar(r) {
  const [wideLow, wideHigh] = r.possible_range_idr, [low, high] = r.likely_range_idr;
  const min = wideLow * 0.94, max = wideHigh * 1.05, at = (v) => `${((v - min) / (max - min)) * 100}%`;
  const box = el("div", "range");
  const wide = el("span", "wide-band"), likely = el("span", "likely-band"), point = el("span", "point");
  wide.style.left = at(wideLow); wide.style.width = `calc(${at(wideHigh)} - ${at(wideLow)})`;
  likely.style.left = at(low); likely.style.width = `calc(${at(high)} - ${at(low)})`;
  likely.style.setProperty("--c", meta.colors[Math.min(classOf(r.price_per_m2_land_idr / 1e6), meta.classes - 1)]);
  point.style.left = at(r.price_idr);
  const top = el("span", "top-cap", `perkiraan ${rp(r.price_idr)}`);
  top.style.left = at(r.price_idr);
  const capL = el("span", "cap", rp(wideLow)), capR = el("span", "cap right", rp(wideHigh));
  capL.style.left = at(wideLow); capR.style.left = at(wideHigh);
  box.append(el("span", "rail"), wide, likely, point, top, capL, capR);
  box.setAttribute("role", "img");
  box.setAttribute("aria-label", `Kisaran paling mungkin ${rpRange(low, high)}, kisaran lebar ${rpRange(wideLow, wideHigh)}, perkiraan ${rp(r.price_idr)}.`);
  return box;
}

function resultCard(r, landArea) {
  const card = el("div", "card");
  card.append(el("div", "label", "Kisaran harga paling mungkin"), el("div", "big", rpRange(...r.likely_range_idr)),
              el("div", "sub", `${perM2Range(r.likely_range_idr[0] / landArea, r.likely_range_idr[1] / landArea)} tanah`), rangeBar(r));
  const legendLine = el("div", "legend-line");
  const a = el("span"), b = el("span");
  const i1 = el("i"), i2 = el("i");
  i1.style.background = meta.colors[Math.min(classOf(r.price_per_m2_land_idr / 1e6), meta.classes - 1)]; i2.style.background = "var(--sand)";
  a.append(i1, document.createTextNode("paling mungkin (50%)")); b.append(i2, document.createTextNode("kisaran lebar (80%)"));
  legendLine.append(a, b);
  card.append(legendLine);
  const feature = kecamatan.features.find((f) => f.properties.name === r.area.kecamatan && (!r.area.city || f.properties.city === r.area.city))
    ?? kecamatan.features.find((f) => f.properties.name === r.area.kecamatan);
  const props = feature?.properties;
  card.append(el("div", "sub", `Perkiraan ${rp(r.price_idr)} (${perM2(r.price_per_m2_land_idr)})`));
  card.append(el("div", "sub", `${r.area.kecamatan}${r.area.city ? `, ${r.area.city}` : ""}${props?.cls >= 0 ? `. Median iklan di sini: Rp ${millions(props.median)} juta per m².` : ""}`));
  if (r.warnings.length) {
    const list = el("ul");
    r.warnings.forEach((w) => list.append(el("li", "", WARNINGS[w.code] ?? w.message)));
    card.append(list);
  }
  const m = meta.model;
  card.append(el("div", "fine", `Ini perkiraan harga seperti yang biasa tertera di iklan, bukan harga transaksi atau penilaian resmi. Pada iklan yang belum pernah dilihat model, separuh perkiraan meleset kurang dari ` +
                                `${pct(m.holdout_median_error)} dari harga iklannya; kisaran paling mungkin memuat ${pct(m.coverage_likely)} harga sebenarnya dan kisaran lebar ${pct(m.coverage_possible)}.`));
  return card;
}

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!$("form").reportValidity()) return;
  if (!state.point) return showResult(el("div", "card error", "Klik peta untuk menaruh pin di lokasi rumah terlebih dahulu."));
  if (!API_BASE) return showResult(el("div", "card error", "Layanan perkiraan harga belum terhubung. Petanya sudah bisa dipakai; perkiraan harga segera tersedia."));
  const button = $("submit"), land = Number($("land_area").value);
  button.disabled = true;
  showResult(el("div", "card", "Menghitung…"));
  const slow = setTimeout(() => showResult(el("div", "card", "Layanan sedang dibangunkan. Permintaan pertama setelah lama tidak dipakai bisa memakan waktu hingga satu menit…")), SLOW_NOTICE_MS);
  const abort = new AbortController(), timer = setTimeout(() => abort.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE}/estimate`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(requestBody()), signal: abort.signal });
    const body = await response.json().catch(() => null);
    showResult(response.ok ? resultCard(body, land) : el("div", "card error", errorMessage(response.status, body)));
  } catch (error) {
    showResult(el("div", "card error", error.name === "AbortError" ? "Layanan terlalu lama menjawab. Silakan coba lagi." : "Layanan perkiraan tidak dapat dihubungi. Silakan coba lagi sebentar lagi."));
  } finally {
    clearTimeout(slow); clearTimeout(timer); button.disabled = false;
  }
});
