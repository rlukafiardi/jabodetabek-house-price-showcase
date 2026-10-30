import { CONFIG } from "./config.js";
import { affordability, classLabels, compareAsk, edgeLabel, factorLine, errorMessage, millions, parseRupiah, perM2, perM2Range, rp, rpRange, versusMedian, WARNINGS } from "./format.mjs";
import { readShared, shareQuery } from "./share.mjs";
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

const shared = readShared(location.search); // a link someone sent: the same estimate opens
const state = { view: "kecamatan", point: null, marker: null, hovered: null, selected: null, isolated: null, locked: null, estimateOpen: false, step: 1, budget: null };

// ---- the text of "about" from the data's own numbers
$("about-listings").textContent = meta.listings_total.toLocaleString("id-ID");
$("about-window").textContent = `${meta.listings_from} sampai ${meta.listings_to}`;
$("about-min").textContent = meta.min_listings;
$("about-error").textContent = pct(meta.model.holdout_median_error);

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
const budgetOpacity = () => { // areas that fit light up, areas that might fit are softer, the rest fade
  const { amount, land } = state.budget, millions = amount / 1e6;
  return ["case", ["==", ["get", "cls"], -1], 0.06, ["<=", ["*", ["get", "median"], land], millions], 0.95, ["<=", ["*", ["get", "p25"], land], millions], 0.55, 0.06];
};
const fillOpacity = (base) => (state.budget ? budgetOpacity() : state.isolated === null ? ["interpolate", ["linear"], ["zoom"], 11.5, interactive(base), 14, interactive(base * 0.5)] : ["case", ["==", ["get", "cls"], state.isolated], 0.96, 0.1]);
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
    const poi = poiAt(e.point);
    if (poi) { tip.setLngLat(poi.geometry.coordinates).setDOMContent(poiTip(poi.properties)).addTo(map); map.getCanvas().style.cursor = "pointer"; return; }
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
  const poi = poiAt(e.point);
  if (poi) return void tip.setLngLat(poi.geometry.coordinates).setDOMContent(poiTip(poi.properties)).addTo(map); // a tap on a station shows its name, it does not move the pin
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
  const capArea = el("span", `cap you${side(props.median)}`, `di sini ${millions(props.median)}`), capRef = el("span", `cap above${side(o.median)}`, `Jabodetabek ${millions(o.median)}`);
  capArea.style.left = at(props.median); capRef.style.left = at(o.median);
  box.append(el("span", "rail"), band, ref, med, capRef, capArea);
  box.setAttribute("role", "img");
  box.setAttribute("aria-label", `Kisaran harga yang umum ${millions(props.p25)} sampai ${millions(props.p75)} juta per m². Harga umum Jabodetabek ${millions(o.median)} juta.`);
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
    const price = el("div", "price", `Rp ${millions(props.median)} juta`);
    price.append(el("small", "", "per m² tanah · harga umum di sini"));
    card.append(price, el("div", "versus", versusMedian(props.median, meta.overall.median)), track(props));
    card.append(el("p", "note", `Dari ${props.n} iklan. Kisaran harga yang umum: Rp ${millions(props.p25)} – ${millions(props.p75)} juta per m².`));
    if (props.mixed) card.append(el("p", "note warn", "Harga di sini sangat bervariasi (ada kawasan mewah dan kawasan biasa), jadi angka ini hanya gambaran kasar."));
  } else {
    card.append(el("div", "price", "Belum ada harga"),
                el("p", "note", `Baru ${props.n} iklan di sini, belum cukup untuk menampilkan harga (minimal ${meta.min_listings}).`));
  }
  if (source === "kecamatan" && props.cls >= 0) {
    const inList = compare.includes(props.code), full = compare.length >= MAX_COMPARE && !inList;
    const add = el("button", "ghost wide", inList ? "Lihat perbandingan" : full ? `Perbandingan penuh (${MAX_COMPARE} daerah)` : "Bandingkan dengan daerah lain");
    add.type = "button"; add.disabled = full;
    add.addEventListener("click", () => { addCompare(props.code); openRank("compare"); renderArea(props, source); });
    card.append(add);
  }
  if (state.point) {
    const cta = el("button", "primary cta wide", "Perkirakan harga rumah di titik ini");
    cta.addEventListener("click", () => openEstimate());
    card.append(cta);
  }
  card.hidden = false;
}

function selectArea(id, source, props) {
  dismissWelcome();
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
  head.append(el("span", "", "Harga umum per m² tanah (juta Rp)"));
  head.insertAdjacentHTML("beforeend", '<svg aria-hidden="true" viewBox="0 0 12 12" width="12" height="12"><path d="m2 4 4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>');
  head.addEventListener("click", () => { const c = legend.classList.toggle("collapsed"); head.setAttribute("aria-expanded", String(!c)); });
  const body = el("div", "body"), ramp = el("div", "ramp"), ticks = el("div", "ticks"), keys = el("div", "keys");
  meta.colors.forEach((color, i) => {
    const seg = el("button", "seg", "");
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
  const nodataKey = el("span"); nodataKey.append(el("i", "swatch nodata"), document.createTextNode(`belum ada harga (iklan terlalu sedikit)${state.view === "h3" ? "" : `: ${nodata}`}`));
  const mixedKey = el("span"); mixedKey.append(el("i", "swatch mixed"), document.createTextNode("garis putus-putus: harga sangat bervariasi"));
  keys.append(...(state.view === "h3" ? [] : [nodataKey, mixedKey]));
  const ends = el("div", "ends");
  ends.append(el("span", "", "Lebih murah"), el("span", "", "Lebih mahal"));
  body.append(ramp, ticks, ends, keys);
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

// ---- welcome card: a first-visit guide, reopened by the "?" button
const welcome = $("welcome");
const store = { get() { try { return localStorage.getItem("welcome-seen") === "1"; } catch { return false; } }, set() { try { localStorage.setItem("welcome-seen", "1"); } catch { /* private window: it shows again next visit */ } } };
function showWelcome(on) {
  welcome.hidden = !on;
  $("help").setAttribute("aria-expanded", String(on));
  document.body.classList.toggle("welcoming", on);
  if (!on) store.set();
}
function dismissWelcome() { if (!welcome.hidden) showWelcome(false); }
$("welcome-ramp").append(...meta.colors.map((c) => { const i = el("i"); i.style.background = c; return i; }));
$("welcome-close").addEventListener("click", dismissWelcome);
$("welcome-map").addEventListener("click", dismissWelcome);
$("welcome-estimate").addEventListener("click", () => { dismissWelcome(); openEstimate(); });
$("help").addEventListener("click", () => showWelcome(welcome.hidden));
if (!store.get() && !shared) showWelcome(true);

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
  const under = map.getLayer("kecamatan-fill") && map.getLayoutProperty("kecamatan-fill", "visibility") !== "none"
    ? map.queryRenderedFeatures(map.project([lon, lat]), { layers: ["kecamatan-fill"] })[0]?.properties : null;
  $("picked").textContent = under ? `Lokasi dipilih: ${under.name}${under.city ? `, ${under.city}` : ""}` : "Lokasi dipilih di peta";
  $("picked").classList.add("done");
  $("next1").disabled = false;
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
  map.fitBounds(bboxOf(feature), { padding: { top: 90, left: isPhone() ? 20 : 380, right: !isPhone() && !$("rank").hidden ? 420 : 40, bottom: isPhone() ? 260 : 60 }, maxZoom: 13.5, duration: 900 });
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
const syncPanels = () => document.body.classList.toggle("panel-open", state.estimateOpen || !$("rank").hidden);
function showStep(n) {
  state.step = n;
  document.querySelectorAll("#form .step").forEach((section) => { section.hidden = Number(section.dataset.step) !== n; });
  $("form").hidden = n === 3;
  document.querySelectorAll("#steps button").forEach((b) => {
    const k = Number(b.dataset.step);
    b.setAttribute("aria-current", String(k === n));
    b.classList.toggle("done", k < n);
    b.disabled = k === 3 && !$("result").querySelector(".card:not(.error)");
  });
  $("estimate").scrollTop = 0;
}
$("steps").addEventListener("click", (e) => { const k = Number(e.target.dataset?.step); if (k && (k === 1 || state.point)) showStep(k); });
$("next1").addEventListener("click", () => showStep(2));
$("back2").addEventListener("click", () => showStep(1));
// a field that fails in a hidden step or a closed fold cannot be focused: go to it
$("form").addEventListener("invalid", (e) => {
  if (e.target.validity.valueMissing) e.target.setCustomValidity("Isi dulu.");
  showFieldError(e.target, e.target.validationMessage);
  const section = e.target.closest(".step"), fold = e.target.closest("details");
  if (fold) fold.open = true;
  if (section && Number(section.dataset.step) !== state.step) showStep(Number(section.dataset.step));
}, true);

function openEstimate() {
  dismissWelcome();
  closeRank();
  state.estimateOpen = true;
  $("estimate").hidden = false;
  syncPanels();
  $("open-estimate").setAttribute("aria-expanded", "true");
  if (isPhone()) $("area").hidden = true;
  fitPadding();
}
function closeEstimate() {
  state.estimateOpen = false;
  $("estimate").hidden = true;
  syncPanels();
  $("open-estimate").setAttribute("aria-expanded", "false");
  fitPadding();
}
showStep(1);
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
  const top = el("span", "top-cap", "perkiraan");
  top.style.left = at(r.price_idr);
  const capL = el("span", "cap", rp(wideLow)), capR = el("span", "cap right", rp(wideHigh));
  capL.style.left = at(wideLow); capR.style.left = at(wideHigh);
  box.append(el("span", "rail"), wide, likely, point, top, capL, capR);
  box.dataset.min = min; box.dataset.max = max;
  box.setAttribute("role", "img");
  box.setAttribute("aria-label", `Biasanya antara ${rpRange(low, high)}, bisa juga antara ${rpRange(wideLow, wideHigh)}, perkiraan ${rp(r.price_idr)}.`);
  return box;
}

function resultCard(r, landArea) {
  const card = el("div", "card");
  const colour = meta.colors[Math.min(classOf(r.price_per_m2_land_idr / 1e6), meta.classes - 1)];
  card.append(el("div", "label", "Perkiraan harga rumah ini"), el("div", "big", rp(r.price_idr)),
              el("div", "range-line", `Biasanya dijual antara ${rpRange(...r.likely_range_idr)}`),
              el("div", "sub", `${perM2(r.price_per_m2_land_idr)} tanah`), rangeBar(r));
  const legendLine = el("div", "legend-line");
  const a = el("span"), b = el("span");
  const i1 = el("i"), i2 = el("i");
  i1.style.background = colour; i2.style.background = "var(--sand)";
  a.append(i1, document.createTextNode("biasanya")); b.append(i2, document.createTextNode("bisa juga sampai di sini, tapi lebih jarang"));
  legendLine.append(a, b);
  card.append(legendLine);
  card.append(askBlock(r));
  const why = whyBlock(r);
  if (why) card.append(why);
  const feature = kecamatan.features.find((f) => f.properties.name === r.area.kecamatan && (!r.area.city || f.properties.city === r.area.city))
    ?? kecamatan.features.find((f) => f.properties.name === r.area.kecamatan);
  const props = feature?.properties;
  card.append(el("div", "where", `${r.area.kecamatan}${r.area.city ? `, ${r.area.city}` : ""}${props?.cls >= 0 ? `. Harga umum iklan di sini: Rp ${millions(props.median)} juta per m² tanah.` : ""}`));
  if (r.warnings.length) {
    const list = el("ul");
    r.warnings.forEach((w) => list.append(el("li", "", WARNINGS[w.code] ?? w.message)));
    card.append(list);
  }
  const m = meta.model;
  card.append(el("div", "fine", `Ini perkiraan harga seperti di iklan, bukan harga jual sebenarnya dan bukan penilaian resmi. Perkiraan bisa meleset sekitar ${pct(m.holdout_median_error)} dari harga iklan, jadi anggap ini titik awal, bukan angka pasti.`));
  const actions = el("div", "actions");
  const edit = el("button", "ghost", "Ubah data"), another = el("button", "ghost", "Rumah lain");
  edit.type = another.type = "button";
  edit.addEventListener("click", () => showStep(2));
  another.addEventListener("click", () => { $("form").reset(); $("result").replaceChildren(); showStep(1); });
  actions.append(edit, another);
  const share = el("button", "ghost wide share", "Bagikan hasil");
  share.type = "button";
  share.addEventListener("click", () => shareResult(r, share, card));
  card.append(actions, share);
  return card;
}

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!$("form").reportValidity()) return;
  if (Number($("lat").value) !== state.point?.lat || Number($("lon").value) !== state.point?.lon) setPoint(Number($("lat").value), Number($("lon").value)); // Enter in a coordinate field submits before its change event
  if (!state.point) return showResult(el("div", "card error", "Klik peta untuk menaruh pin di lokasi rumah dulu."));
  if (!API_BASE) return showResult(el("div", "card error", "Layanan perkiraan harga belum terhubung. Petanya sudah bisa dipakai; perkiraan harga segera tersedia."));
  const button = $("submit"), land = Number($("land_area").value);
  state.lastBody = requestBody();
  button.disabled = true;
  showResult(el("div", "card", "Memperkirakan…"));
  const slow = setTimeout(() => showResult(el("div", "card", "Memuat layanan. Permintaan pertama setelah lama tidak dipakai bisa memakan waktu sampai 1 menit, tunggu sebentar…")), SLOW_NOTICE_MS);
  const abort = new AbortController(), timer = setTimeout(() => abort.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE}/estimate`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(requestBody()), signal: abort.signal });
    const body = await response.json().catch(() => null);
    showResult(response.ok ? resultCard(body, land) : el("div", "card error", errorMessage(response.status, body)));
    if (response.ok) showStep(3);
  } catch (error) {
    showResult(el("div", "card error", error.name === "AbortError" ? "Layanan terlalu lama menjawab. Coba lagi." : "Layanan perkiraan tidak dapat dihubungi. Coba lagi sebentar lagi."));
  } finally {
    clearTimeout(slow); clearTimeout(timer); button.disabled = false;
  }
});

// ---- ranking of areas, filtered by city or regency
const rank = { city: "", sort: "desc" };
const MAX_COMPARE = 3; // areas in the comparison
const compare = [];
let compareLand = "";
const priced = kecamatan.features.map((f) => f.properties).filter((p) => p.cls >= 0);
const cities = [...new Set(priced.map((p) => p.city).filter(Boolean))].sort((a, b) => a.localeCompare(b, "id"));
$("rank-city").replaceChildren(new Option(`Semua (${priced.length} daerah)`, ""), ...cities.map((c) => new Option(`${c} (${priced.filter((p) => p.city === c).length})`, c)));

function buildRank() {
  const rows = priced.filter((p) => !rank.city || p.city === rank.city).sort((a, b) => (rank.sort === "desc" ? b.median - a.median : a.median - b.median));
  $("rank-note").textContent = `${rows.length} daerah dengan harga umum per m² tanah. Klik untuk melihat di peta.`;
  $("rank-list").replaceChildren(...rows.map((p, i) => {
    const li = el("li", "rank-item"), b = el("button", "rank-row");
    b.type = "button";
    b.style.setProperty("--c", meta.colors[p.cls]);
    const name = el("span", "name");
    name.append(el("b", "", p.name), el("small", "", `${rank.city ? "" : `${p.city ?? ""} · `}${p.n} iklan${p.mixed ? " · harga bervariasi" : ""}`));
    b.append(el("span", "no", String(i + 1)), name, el("span", "val", `${millions(p.median)} jt`));
    b.addEventListener("click", () => { if (isPhone()) closeRank(); goToArea(p.code); });
    const pick = el("button", "pick", compare.includes(p.code) ? "✓" : "+");
    pick.type = "button";
    pick.setAttribute("aria-pressed", String(compare.includes(p.code)));
    pick.setAttribute("aria-label", `${compare.includes(p.code) ? "Hapus" : "Tambah"} ${p.name} ${compare.includes(p.code) ? "dari" : "ke"} perbandingan`);
    pick.disabled = compare.length >= MAX_COMPARE && !compare.includes(p.code);
    pick.addEventListener("click", () => { toggleCompare(p.code); });
    li.append(b, pick);
    return li;
  }));
  $("rank-list").scrollTop = 0;
}
function openRank(tab = "rank") {
  dismissWelcome();
  setTab(tab);
  if (state.estimateOpen) closeEstimate();
  $("rank").hidden = false;
  syncPanels();
  $("open-rank").setAttribute("aria-expanded", "true");
  if (isPhone()) $("area").hidden = true;
}
function closeRank() {
  $("rank").hidden = true;
  syncPanels();
  $("open-rank").setAttribute("aria-expanded", "false");
}
$("open-rank").addEventListener("click", () => ($("rank").hidden ? openRank() : closeRank()));
$("close-rank").addEventListener("click", closeRank);
$("rank-city").addEventListener("change", (e) => { rank.city = e.target.value; buildRank(); });
$("rank-sort").addEventListener("click", (e) => {
  const sort = e.target.dataset?.sort;
  if (!sort) return;
  rank.sort = sort;
  document.querySelectorAll("#rank-sort button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.sort === sort)));
  buildRank();
});
buildRank();

// ---- check an ad price against the estimate
function askBlock(r) {
  const form = el("form", "ask"), label = el("label", "", "Sudah lihat harga di iklan? Bandingkan di sini"), input = el("input");
  input.type = "text"; input.inputMode = "decimal"; input.autocomplete = "off"; input.placeholder = "mis. 4,5 miliar atau 4500 juta"; input.maxLength = 30;
  label.append(input);
  const go = el("button", "ghost", "Bandingkan"), out = el("div", "ask-out");
  go.type = "submit"; out.setAttribute("role", "status");
  form.append(label, go, out);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const ask = parseRupiah(input.value), bar = form.closest(".card")?.querySelector(".range");
    bar?.querySelector(".ask-tick")?.remove();
    if (Number.isNaN(ask)) { out.className = "ask-out bad"; out.textContent = "Tulis harganya dengan satuan, mis. 4,5 miliar atau 4500 juta."; return; }
    const verdict = compareAsk(ask, r);
    out.className = `ask-out ${verdict.where}`; out.textContent = verdict.text;
    const min = Number(bar?.dataset.min), max = Number(bar?.dataset.max);
    if (bar && ask >= min && ask <= max) {
      const tick = el("span", "ask-tick", "iklan");
      tick.style.left = `${((ask - min) / (max - min)) * 100}%`;
      bar.append(tick);
    }
  });
  return form;
}

// ---- share a result as a link
async function shareResult(r, button, card) {
  const url = `${location.origin}${location.pathname}?${shareQuery(state.lastBody)}`;
  const text = `Perkiraan harga rumah: ${rp(r.price_idr)} (biasanya ${rpRange(...r.likely_range_idr)}) di ${r.area.kecamatan}`;
  const done = (message) => { button.textContent = message; setTimeout(() => { button.textContent = "Bagikan hasil"; }, 2500); };
  try {
    if (navigator.share) { await navigator.share({ title: "Perkiraan harga rumah", text, url }); return; }
  } catch (error) {
    if (error.name === "AbortError") return;
  }
  try {
    await navigator.clipboard.writeText(url);
    done("Link disalin ✓");
  } catch {
    let box = card.querySelector(".share-link");
    if (!box) { box = el("input", "share-link"); box.readOnly = true; button.after(box); }
    box.value = url; box.select(); done("Salin link di bawah");
  }
}

// ---- compare 2-3 areas
function addCompare(code) { if (!compare.includes(code) && compare.length < MAX_COMPARE) compare.push(code); refreshCompare(); }
function toggleCompare(code) {
  const i = compare.indexOf(code);
  if (i >= 0) compare.splice(i, 1); else addCompare(code);
  refreshCompare();
}
function refreshCompare() {
  $("compare-count").textContent = compare.length;
  buildRank();
  buildCompare();
  if (!$("area").hidden && state.selected) { const f = byCode.get(state.selected.id); if (f && state.selected.source === "kecamatan") renderArea(f.properties, "kecamatan"); }
}
function setTab(tab) {
  document.querySelectorAll("#rank-tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
  $("rank-view").hidden = tab !== "rank";
  $("compare-view").hidden = tab !== "compare";
  $("budget-view").hidden = tab !== "budget";
  $("rank-title").textContent = { rank: "Peringkat harga daerah", compare: "Bandingkan daerah", budget: "Cari daerah sesuai budget" }[tab];
}
$("rank-tabs").addEventListener("click", (e) => { const tab = e.target.dataset?.tab; if (tab) setTab(tab); });

function buildCompare() {
  const view = $("compare-view");
  const picked = compare.map((code) => byCode.get(code)?.properties).filter(Boolean);
  if (picked.length < 2) {
    const hint = el("p", "hint", picked.length ? "Pilih satu daerah lagi untuk mulai membandingkan." : "Pilih 2 atau 3 daerah untuk dibandingkan. Pakai tombol + di tab Peringkat, atau tombol Bandingkan di kartu daerah pada peta.");
    view.replaceChildren(hint, ...picked.map((p) => compareHead(p)));
    return;
  }
  const top = Math.max(...picked.map((p) => p.median)), low = picked.reduce((a, b) => (b.median < a.median ? b : a)), high = picked.reduce((a, b) => (b.median > a.median ? b : a));
  const grid = el("div", "cmp-grid");
  grid.style.setProperty("--n", String(picked.length));
  for (const p of picked) {
    const col = el("div", "cmp-col");
    const bar = el("div", "cmp-bar"), fill = el("i");
    fill.style.width = `${(p.median / top) * 100}%`; fill.style.background = meta.colors[p.cls];
    bar.append(fill);
    col.append(compareHead(p), el("div", "cmp-price", `Rp ${millions(p.median)} juta`), el("small", "", "per m² tanah"), bar,
               el("div", "cmp-row", `Kisaran umum ${millions(p.p25)} – ${millions(p.p75)} juta`),
               el("div", "cmp-row", `${p.n} iklan`), el("div", "cmp-row", versusMedian(p.median, meta.overall.median)));
    if (p.mixed) col.append(el("div", "cmp-row warn", "Harga di sini sangat bervariasi"));
    const total = el("div", "cmp-total"); total.dataset.median = p.median;
    col.append(total);
    grid.append(col);
  }
  const gap = Math.round((1 - low.median / high.median) * 100);
  const land = el("label", "cmp-land", "Kalau tanahmu seluas (m²)"), input = el("input");
  input.type = "number"; input.min = "15"; input.max = "5000"; input.inputMode = "decimal"; input.placeholder = "mis. 100"; input.value = compareLand;
  land.append(input);
  const fillTotals = () => grid.querySelectorAll(".cmp-total").forEach((n) => {
    const area = Number(compareLand);
    n.textContent = area >= 15 ? `Tanah ${area} m² sekitar ${rp(Number(n.dataset.median) * 1e6 * area)}` : "";
  });
  input.addEventListener("input", () => { compareLand = input.value; fillTotals(); });
  fillTotals();
  const verdict = gap < 3 ? "Harga umum daerah-daerah ini hampir sama." : `${low.name} paling murah, sekitar ${gap}% di bawah ${high.name}.`;
  view.replaceChildren(el("p", "cmp-verdict", verdict), grid, land,
                       el("p", "hint", "Angka tanah di atas kasar: harga umum per m² dikali luas, belum termasuk bangunan."));
}
function compareHead(p) {
  const head = el("div", "cmp-head"), name = el("button", "cmp-name"), remove = el("button", "cmp-x", "✕");
  name.type = remove.type = "button";
  name.append(el("b", "", p.name), el("small", "", p.city ?? ""));
  remove.setAttribute("aria-label", `Hapus ${p.name} dari perbandingan`);
  name.addEventListener("click", () => { if (isPhone()) closeRank(); goToArea(p.code); });
  remove.addEventListener("click", () => toggleCompare(p.code));
  head.append(name, remove);
  return head;
}
buildCompare();

// ---- layers to consider: public OpenStreetMap places and lines, loaded the first time they are switched on
const COLORS = { krl: "#1f4fb4", mrt: "#0a7d5a", lrt: "#7b3fb8", busway: "#0f8f95", bus: "#0f8f95", toll: "#3b4350", river: "#3a8fd6", canal: "#3a8fd6", mall: "#c2337c", hospital: "#d6262c", university: "#a77300" };
const KIND_LABEL = { krl: "Stasiun kereta", mrt: "Stasiun MRT", lrt: "Stasiun LRT", busway: "Halte Transjakarta", bus: "Halte bus", toll: "Gerbang tol", mall: "Mal", hospital: "Rumah sakit", university: "Kampus" };
const dot = (min, a, b, c, d) => ({ minzoom: min, paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, a, 11, b, 14, c, 16, d], "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.2 } });
const STATION_COLOR = ["match", ["get", "kind"], "krl", COLORS.krl, "mrt", COLORS.mrt, "lrt", COLORS.lrt, "#555555"];
const place = (key, label, kind) => ({ key, group: "Fasilitas", label, swatches: [COLORS[kind]], layers: [{ id: key, file: "layer_places", type: "circle", filter: ["==", ["get", "kind"], kind], poi: true, ...dot(9.5, 2, 3.5, 5.5, 7), color: COLORS[kind] }] });
const LAYER_DEFS = [
  { key: "stations", group: "Transportasi", label: "Stasiun kereta, MRT, LRT", swatches: [COLORS.krl, COLORS.mrt, COLORS.lrt], layers: [
    { id: "rail", file: "layer_rail", type: "line", minzoom: 8.5, paint: { "line-color": "#5b6573", "line-width": 1.3, "line-opacity": 0.8 } },
    { id: "stations", file: "layer_stations", type: "circle", poi: true, ...dot(8.5, 4, 5, 7, 9), color: STATION_COLOR },
    { id: "names", file: "layer_stations", type: "symbol", minzoom: 12, layout: { "text-field": ["get", "name"], "text-font": ["Noto Sans Bold"], "text-size": 11.5, "text-offset": [0, 1], "text-anchor": "top", "text-max-width": 8 },
      paint: { "text-color": "#1c1a18", "text-halo-color": "rgba(255,255,255,0.92)", "text-halo-width": 1.5 } } ] },
  { key: "busway", group: "Transportasi", label: "Halte bus (Transjakarta dan lainnya)", swatches: [COLORS.busway], layers: [{ id: "busway", file: "layer_busway", type: "circle", poi: true, ...dot(9, 1.6, 2.6, 4.2, 6), color: COLORS.busway }] },
  { key: "toll", group: "Transportasi", label: "Gerbang tol", swatches: [COLORS.toll], layers: [{ id: "toll", file: "layer_toll", type: "circle", poi: true, ...dot(8.5, 3, 4.5, 6, 8), color: COLORS.toll }] },
  { key: "rivers", group: "Lingkungan", label: "Sungai dan kanal", swatches: [COLORS.river], line: true, layers: [{ id: "rivers", file: "layer_rivers", type: "line", minzoom: 8.5,
    paint: { "line-color": COLORS.river, "line-opacity": 0.85, "line-width": ["interpolate", ["linear"], ["zoom"], 9, 0.8, 14, 2.6] } }] },
  { key: "flood", group: "Lingkungan", label: "Rawan banjir (BNPB InaRISK)", swatches: ["#9ecae1", "#4f93d1", "#12418a"],
    note: "Biru muda: rendah, biru: sedang, biru tua: tinggi. Tiga tingkat ini kami bagi sendiri dari indeks 0–1 milik BNPB, ketelitian sekitar 30 m. Area tanpa warna berarti tidak ditandai rawan di data BNPB, bukan pasti aman.",
    layers: [{ id: "flood", image: "layer_flood", type: "raster", minzoom: 8.5, paint: { "raster-opacity": 1 } }] },
  place("mall", "Mal", "mall"), place("hospital", "Rumah sakit", "hospital"), place("university", "Kampus", "university"),
];
const layerId = (def, layer) => `lyr-${def.key}-${layer.id}`;
const poiIds = LAYER_DEFS.flatMap((def) => def.layers.filter((l) => l.poi).map((l) => layerId(def, l)));

function setLayer(def, on) {
  if (on) {
    for (const l of def.layers) {
      if (map.getLayer(layerId(def, l))) continue;
      const source = l.image ?? l.file;
      if (!map.getSource(source)) {
        const [west, south, east, north] = meta.flood_bounds;
        map.addSource(source, l.image ? { type: "image", url: `data/${l.image}.png`, coordinates: [[west, north], [east, north], [east, south], [west, south]] } : { type: "geojson", data: `data/${l.file}.geojson` });
      }
      const spec = { id: layerId(def, l), type: l.type, source, ...(l.minzoom && { minzoom: l.minzoom }), ...(l.filter && { filter: l.filter }), ...(l.layout && { layout: l.layout }) };
      spec.paint = l.type === "circle" ? { ...l.paint, "circle-color": l.color } : l.paint;
      // an area layer goes under every point and line layer already on the map, so switching order never hides a station behind it
      const below = l.type === "fill" || l.type === "raster" ? map.getStyle().layers.find((x) => x.id.startsWith("lyr-"))?.id ?? "kecamatan-labels" : "kecamatan-labels";
      map.addLayer(spec, below);
    }
  }
  for (const l of def.layers) if (map.getLayer(layerId(def, l))) map.setLayoutProperty(layerId(def, l), "visibility", on ? "visible" : "none");
}

const poiAt = (point) => {
  const ids = poiIds.filter((id) => map.getLayer(id) && map.getLayoutProperty(id, "visibility") !== "none");
  if (!ids.length) return undefined;
  return map.queryRenderedFeatures([[point.x - 6, point.y - 6], [point.x + 6, point.y + 6]], { layers: ids })[0];
};
function poiTip(props) {
  const box = el("div");
  box.append(el("b", "", props.name || KIND_LABEL[props.kind]), ...(props.name ? [el("span", "", KIND_LABEL[props.kind])] : []));
  return box;
}

(function buildLayerPanel() {
  const panel = $("layers"), body = $("layers-body"), title = panel.querySelector(".title");
  title.addEventListener("click", () => { const c = panel.classList.toggle("collapsed"); title.setAttribute("aria-expanded", String(!c)); });
  let group = null;
  for (const def of LAYER_DEFS) {
    if (def.group !== group) { group = def.group; body.append(el("div", "group", group)); }
    const chip = el("label", "chip"), box = el("input");
    box.type = "checkbox"; box.dataset.layer = def.key;
    const swatches = el("span", "sw");
    def.swatches.forEach((c) => { const i = el("i"); i.style.background = c; if (def.line) i.classList.add("line"); swatches.append(i); });
    chip.append(box, swatches, document.createTextNode(def.label));
    box.addEventListener("change", () => { if (!map.getLayer("kecamatan-labels")) { box.checked = false; return; } setLayer(def, box.checked); if (note) note.hidden = !box.checked; }); // the map is not ready yet
    body.append(chip);
    const note = def.note ? el("p", "layer-note", def.note) : null; // the note shows while its layer is on
    if (note) { note.hidden = true; body.append(note); }
  }
  // the flood layer is a generalised copy of BNPB's data (published on the owner's decision, no terms found); the full map stays at the source
  body.append(el("div", "group", "Sumber"));
  const flood = el("a", "chip link", "Peta risiko banjir lengkap di InaRISK (BNPB) ↗");
  flood.href = "https://inarisk.bnpb.go.id/"; flood.target = "_blank"; flood.rel = "noopener noreferrer";
  body.append(flood);
})();

// ---- open a shared link: fill the form, drop the pin and run the estimate
if (shared) {
  map.once("idle", () => {
    const set = (id, value) => { $(id).value = value ?? ""; };
    for (const id of ["land_area", "building_area", "bedrooms", "bathrooms", "floors"]) set(id, shared[id]);
    for (const [id, value] of Object.entries(shared.specs)) set(id, value);
    set("notes", shared.notes);
    map.jumpTo({ center: [shared.lon, shared.lat], zoom: 13 });
    setPoint(shared.lat, shared.lon);
    openEstimate();
    showStep(2);
    if (API_BASE) $("form").requestSubmit();
  });
}

// ---- form checks: say what is wrong while typing, and keep impossible numbers out (no minus, no "e", whole numbers where a count is expected)
const fmtNumber = (n) => n.toLocaleString("id-ID");
function showFieldError(input, message) {
  const field = input.closest(".f");
  if (!field) return;
  let err = field.querySelector(".err");
  if (!err) { err = el("small", "err"); err.setAttribute("role", "alert"); field.append(err); }
  err.textContent = message;
  input.closest(".box")?.classList.toggle("bad", message !== "");
}
function checkNumber(input) {
  const v = input.value.trim(), n = Number(v), min = Number(input.min), max = Number(input.max);
  let message = "";
  if (input.validity.badInput) message = "Isi dengan angka.";
  else if (v !== "" && (n < min || n > max)) message = `Isi angka ${fmtNumber(min)} sampai ${fmtNumber(max)}.`;
  else if (v !== "" && input.step === "1" && !Number.isInteger(n)) message = "Isi angka bulat.";
  input.setCustomValidity(message);
  showFieldError(input, message);
}
for (const input of document.querySelectorAll("#form input[type=number]")) {
  input.addEventListener("input", () => checkNumber(input));
  input.addEventListener("blur", () => checkNumber(input));
  if (input.id === "lat" || input.id === "lon") continue; // coordinates can be negative decimals
  const blocked = ["e", "E", "+", "-", ...(input.step === "1" ? [".", ","] : [])];
  input.addEventListener("keydown", (e) => { if (blocked.includes(e.key)) e.preventDefault(); });
}

// ---- why this price: what pushes the price per m² up or down compared with a typical house in the data
function whyBlock(r) {
  if (!r.factors?.length) return null;
  const box = el("details", "why"), list = el("ul");
  box.append(el("summary", "", "Apa yang bikin harganya segitu?"));
  box.append(el("p", "hint", "Dibanding rumah biasa di Jabodetabek (yang paling umum di data iklan kami), ini yang paling menaikkan atau menurunkan perkiraan harga per m² tanah:"));
  for (const factor of r.factors) {
    const line = factorLine(factor), item = el("li"), name = el("span", "name");
    name.append(el("b", "", line.label), ...(line.hint ? [el("small", "", line.hint)] : []));
    item.append(name, el("b", line.up ? "up" : "down", line.text));
    list.append(item);
  }
  box.append(list);
  if (r.factors.some((f) => f.code === "notes" && Math.abs(f.effect) >= 0.25)) box.append(el("p", "hint warn", "Catatanmu berpengaruh besar di perkiraan ini. Tulis fakta tentang rumahnya saja (kondisi, fasilitas), bukan kata-kata promosi."));
  box.append(el("p", "hint", "Ini gambaran kasar. Faktor-faktor ini saling berkaitan, jadi persennya tidak bisa dijumlahkan."));
  return box;
}

// ---- budget: which areas fit what you can spend
function applyBudget(budget) {
  state.budget = budget;
  setIsolation(state.isolated);
  $("budget-chip").hidden = !budget;
  if (budget) $("budget-chip-text").textContent = `Budget ${rp(budget.amount)} · tanah ${budget.land} m²`;
}
$("budget-clear").addEventListener("click", () => { applyBudget(null); buildBudget(); });

let budgetForm = { amount: "", land: "100", city: "" };
function buildBudget() {
  const view = $("budget-view");
  const form = el("form", "budget-form"), amount = el("input"), land = el("input"), amountLabel = el("label", "", "Budget kamu"), landLabel = el("label", "", "Luas tanah yang dicari (m²)");
  amount.type = "text"; amount.inputMode = "decimal"; amount.placeholder = "mis. 1,5 miliar"; amount.value = budgetForm.amount; amount.autocomplete = "off"; amount.maxLength = 30; amount.id = "budget-amount";
  land.type = "number"; land.min = "15"; land.max = "5000"; land.step = "any"; land.value = budgetForm.land; land.id = "budget-land";
  amountLabel.append(amount); landLabel.append(land);
  const go = el("button", "primary wide", "Tampilkan di peta"), error = el("div", "ask-out bad");
  go.type = "submit"; error.setAttribute("role", "alert");
  form.append(amountLabel, landLabel, go, error);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const value = parseRupiah(amount.value), area = Number(land.value);
    budgetForm = { ...budgetForm, amount: amount.value, land: land.value };
    if (Number.isNaN(value)) { error.textContent = "Tulis budget dengan satuan, mis. 1,5 miliar atau 1500 juta."; return; }
    if (!(area >= 15 && area <= 5000)) { error.textContent = "Luas tanah antara 15 dan 5.000 m²."; return; }
    error.textContent = "";
    applyBudget({ amount: value, land: area });
    buildBudget();
  });
  view.replaceChildren(form);
  if (!state.budget) return view.append(el("p", "hint", "Isi budget dan luas tanah, nanti daerah yang harganya cukup menyala di peta. Hitungannya kasar: harga umum per m² dikali luas tanah, sudah termasuk bangunan seperti di iklan."));

  const { amount: budget, land: size } = state.budget;
  const rows = priced.map((p) => ({ p, status: affordability(p, budget, size) }));
  const count = (status) => rows.filter((row) => row.status === status).length;
  const city = el("select"); city.id = "budget-city";
  city.append(new Option("Semua kota / kabupaten", ""), ...cities.map((c) => new Option(c, c)));
  city.value = budgetForm.city;
  city.addEventListener("change", () => { budgetForm.city = city.value; buildBudget(); });
  const listFor = (status, title) => {
    const group = rows.filter((row) => row.status === status && (!budgetForm.city || row.p.city === budgetForm.city)).sort((a, b) => b.p.median - a.p.median);
    const block = el("div", "budget-group");
    block.append(el("div", "group-title", `${title} (${group.length})`));
    const list = el("ol", "budget-list");
    for (const { p } of group) {
      const item = el("li"), button = el("button", "rank-row");
      button.type = "button"; button.style.setProperty("--c", meta.colors[p.cls]);
      const name = el("span", "name");
      name.append(el("b", "", p.name), el("small", "", p.city ?? ""));
      button.append(name, el("span", "val", `≈ ${rp(p.median * 1e6 * size)}`));
      button.addEventListener("click", () => { if (isPhone()) closeRank(); goToArea(p.code); });
      item.append(button); list.append(item);
    }
    block.append(list);
    return block;
  };
  view.append(el("p", "cmp-verdict", `${count("fit")} daerah cukup, ${count("maybe")} mungkin, ${count("over")} di luar budget.`),
              el("label", "", "Lihat di"), city, listFor("fit", "Cukup: harga umumnya muat"), listFor("maybe", "Mungkin: hanya yang di bawah harga umum"),
              el("p", "hint", `${count("none")} daerah belum ada harganya, jadi tidak dihitung.`));
}
buildBudget();
