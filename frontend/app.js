"use strict";

// Apply saved theme before first paint to avoid flash. Default: dark.
(function () {
  const t = localStorage.getItem("azs_theme") || "dark";
  document.documentElement.dataset.theme = t;
})();

// Ссылки на сообщества. Замените на реальные адреса ваших групп.
const SOCIAL = {
  vk: "https://vk.com",
  tg: "https://t.me",
  max: "https://max.ru",
};

const COLORS = {
  green: "#22c55e", amber: "#84cc16", yellow: "#f5c518",
  red: "#ef4444", black: "#0b0f17", gray: "#64748b",
};
const KNOWN_BRANDS = [
  "Лукойл", "Газпромнефть", "Роснефть", "Татнефть", "Башнефть",
  "Сургутнефтегаз", "Газпром", "Шелл", "ЕКА", "Нефтьмагистраль",
  "Трасса", "Teboil", "Иркутскнефтепродукт",
];

// Официальные логотипы брендов (файл + натуральные пропорции для маркера).
const BRAND_LOGO = {
  "Лукойл":       { f: "lukoil",      w: 388, h: 80 },
  "Роснефть":     { f: "rosneft",     w: 125, h: 80 },
  "Газпромнефть": { f: "gazpromneft", w: 167, h: 80 },
  "Газпром":      { f: "gazprom",     w: 166, h: 80 },
  "Татнефть":     { f: "tatneft",     w: 290, h: 80 },
  "Башнефть":     { f: "bashneft",    w: 104, h: 80 },
  "Teboil":       { f: "teboil",      w: 292, h: 80 },
  "Новатэк":      { f: "novatek",     w: 280, h: 80 },
  "Шелл":         { f: "shell",       w: 220, h: 80 },
};

const state = {
  meta: null,
  fuel: null,            // selected fuel filter
  status: null,          // selected status filter
  brands: new Set(),
  onlyData: false,
  stations: new Map(),   // id -> station
  markers: new Map(),    // id -> marker
  user: null,            // {lat, lon}
  reportStatus: null,
  reportFuel: "",
  selected: null,
};

function deviceId() {
  let id = localStorage.getItem("azs_device");
  if (!id) { id = "dev_" + Math.random().toString(36).slice(2) + Date.now().toString(36); localStorage.setItem("azs_device", id); }
  return id;
}

async function api(path, opts) {
  const r = await fetch("/api" + path, opts);
  if (!r.ok) {
    let msg = "Ошибка";
    try { const j = await r.json(); msg = j.detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return r.json();
}

function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(t._t); t._t = setTimeout(() => (t.hidden = true), 3000);
}

function timeAgo(iso) {
  if (!iso) return "нет данных";
  const d = new Date(iso.replace(" ", "T") + "Z");
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "только что";
  if (s < 3600) return Math.floor(s / 60) + " мин назад";
  if (s < 86400) return Math.floor(s / 3600) + " ч назад";
  return Math.floor(s / 86400) + " дн назад";
}

function distKm(a, b) {
  const R = 6371, toR = (x) => (x * Math.PI) / 180;
  const dLat = toR(b.lat - a.lat), dLon = toR(b.lon - a.lon);
  const x = Math.sin(dLat / 2) ** 2 + Math.cos(toR(a.lat)) * Math.cos(toR(b.lat)) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x));
}

/* ---------------- map ---------------- */
let map, cluster, baseLayer;
const TILES = {
  dark: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
  light: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
};
function setBaseLayer(theme) {
  if (!map) return;
  const url = TILES[theme] || TILES.dark;
  if (baseLayer) map.removeLayer(baseLayer);
  baseLayer = L.tileLayer(url, {
    maxZoom: 20, subdomains: "abcd",
    attribution: "© OpenStreetMap, © CARTO",
  }).addTo(map);
  if (baseLayer.bringToBack) baseLayer.bringToBack();
}
function initMap() {
  map = L.map("map", { zoomControl: true, preferCanvas: true }).setView([55.75, 37.62], 11);
  setBaseLayer(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  cluster = L.markerClusterGroup({ maxClusterRadius: 55, disableClusteringAtZoom: 13, chunkedLoading: true });
  map.addLayer(cluster);
  map.on("moveend", debounce(loadStations, 350));
}

const PUMP_SVG = '<svg viewBox="0 0 24 24" width="15" height="15" fill="#fff"><path d="M19.77 7.23l.01-.01-3.72-3.72L15 4.56l2.11 2.11c-.94.36-1.61 1.26-1.61 2.33 0 1.38 1.12 2.5 2.5 2.5.36 0 .69-.08 1-.21v7.21c0 .55-.45 1-1 1s-1-.45-1-1V14c0-1.1-.9-2-2-2h-1V5c0-1.1-.9-2-2-2H6c-1.1 0-2 .9-2 2v16h10v-7.5h1.5v5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V9c0-.69-.28-1.32-.73-1.77zM12 10H6V5h6v5z"/></svg>';
function markerIcon(color, stale, brand) {
  const c = COLORS[color] || COLORS.gray;
  const fresh = !stale && color && color !== "gray";
  const logo = BRAND_LOGO[brand];
  if (logo) {
    const lh = 18;                                   // высота логотипа
    const lw = Math.min(64, Math.round(lh * logo.w / logo.h));
    const cw = lw + 14;                              // ширина чипа
    const ch = lh + 13;                              // высота тела чипа
    const total = ch + 7;                            // + хвостик
    return L.divIcon({
      className: "",
      html: `<div class="azs-brand ${stale ? "stale" : ""} ${fresh ? "fresh" : ""}" style="--sc:${c};width:${cw}px;height:${ch}px">`
          + `<img src="/img/brands/${logo.f}.png" alt="" style="height:${lh}px;width:${lw}px" draggable="false">`
          + `<span class="azs-sdot" style="background:${c}"></span></div>`,
      iconSize: [cw, total], iconAnchor: [cw / 2, total], popupAnchor: [0, -total + 2],
    });
  }
  return L.divIcon({
    className: "",
    html: `<div class="azs-pin ${stale ? "stale" : ""} ${fresh ? "fresh" : ""}" style="background:${c};color:${c}"><span class="azs-pin-ic">${PUMP_SVG}</span></div>`,
    iconSize: [28, 36], iconAnchor: [14, 34], popupAnchor: [0, -32],
  });
}

const LABEL_ZOOM = 13;
function updateLabels() {
  const show = map.getZoom() >= LABEL_ZOOM;
  state.markers.forEach((m, id) => {
    const has = !!m.getTooltip();
    if (show && !has) {
      const s = state.stations.get(id);
      m.bindTooltip(esc(s.name || "АЗС"), { permanent: true, direction: "top", offset: [0, -34], className: "azs-label" });
    } else if (!show && has) {
      m.unbindTooltip();
    }
  });
}

const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

async function loadStations() {
  if (map.getZoom() < 6) { setListEmpty("Приблизьте карту, чтобы увидеть заправки."); return; }
  const b = map.getBounds();
  const params = new URLSearchParams({ bbox: [b.getSouth(), b.getWest(), b.getNorth(), b.getEast()].join(",") });
  if (state.fuel) params.set("fuel", state.fuel);
  if (state.status) params.set("status", state.status);
  if (state.brands.size) params.set("brands", [...state.brands].join(","));
  if (state.onlyData) params.set("only_with_data", "true");
  let data;
  try { data = await api("/stations?" + params); } catch (e) { return; }

  cluster.clearLayers();
  state.stations.clear();
  state.markers.clear();
  const markers = [];
  for (const s of data.stations) {
    state.stations.set(s.id, s);
    const m = L.marker([s.lat, s.lon], { icon: markerIcon(s.color, s.stale, s.brand) });
    m.on("click", () => openStation(s.id));
    state.markers.set(s.id, m);
    markers.push(m);
  }
  cluster.addLayers(markers);
  updateLabels();
  document.getElementById("list-count").textContent = data.count + " на карте";
  renderList();
}

/* ---------------- list ---------------- */
function setListEmpty(msg) {
  document.getElementById("station-list").innerHTML = `<div class="empty">${msg}</div>`;
}
function renderList() {
  const el = document.getElementById("station-list");
  let arr = [...state.stations.values()];
  if (state.user) {
    arr.forEach((s) => (s._d = distKm(state.user, s)));
    arr.sort((a, b) => a._d - b._d);
    document.getElementById("list-title").textContent = "Ближайшие АЗС";
  } else {
    arr.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
  }
  arr = arr.slice(0, 120);
  if (!arr.length) { setListEmpty("В этой области нет заправок. Подвиньте карту."); return; }
  el.innerHTML = arr.map((s) => `
    <div class="st-item" data-id="${s.id}">
      ${BRAND_LOGO[s.brand]
        ? `<div class="st-logo" style="--sc:${COLORS[s.color] || COLORS.gray}"><img src="/img/brands/${BRAND_LOGO[s.brand].f}.png" alt=""></div>`
        : `<div class="st-dot" style="background:${COLORS[s.color] || COLORS.gray}"></div>`}
      <div class="st-main">
        <div class="st-name">${esc(s.name)}</div>
        <div class="st-meta">${s.brand ? esc(s.brand) + " · " : ""}${s.status ? statusLabel(s.status) : "нет данных"}${s.stale ? " · устарело" : ""}</div>
      </div>
      ${s._d != null ? `<div class="st-dist">${s._d < 1 ? Math.round(s._d * 1000) + " м" : s._d.toFixed(1) + " км"}</div>` : ""}
    </div>`).join("");
  el.querySelectorAll(".st-item").forEach((it) =>
    it.addEventListener("click", () => {
      const id = +it.dataset.id, s = state.stations.get(id);
      map.setView([s.lat, s.lon], Math.max(map.getZoom(), 15));
      openStation(id);
    }));
}

const esc = (s) => (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const statusLabel = (s) => (state.meta?.status_labels?.[s]) || s;
const fuelLabel = (f) => (state.meta?.fuel_labels?.[f]) || f;

/* ---------------- filters ---------------- */
function buildFilters() {
  const fuelEl = document.getElementById("fuel-chips");
  fuelEl.innerHTML = state.meta.fuel_types.map((f) => `<div class="chip" data-fuel="${f}">${fuelLabel(f)}</div>`).join("");
  fuelEl.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
    const f = c.dataset.fuel;
    state.fuel = state.fuel === f ? null : f;
    fuelEl.querySelectorAll(".chip").forEach((x) => x.classList.toggle("active", x.dataset.fuel === state.fuel));
    loadStations();
  }));

  const stEl = document.getElementById("status-chips");
  stEl.innerHTML = state.meta.statuses.map((s) =>
    `<div class="chip" data-status="${s}"><span class="dot" style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${COLORS[state.meta.status_color[s]]};margin-right:5px"></span>${statusLabel(s)}</div>`).join("");
  stEl.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
    const s = c.dataset.status;
    state.status = state.status === s ? null : s;
    stEl.querySelectorAll(".chip").forEach((x) => x.classList.toggle("active", x.dataset.status === state.status));
    loadStations();
  }));

  const brEl = document.getElementById("brand-chips");
  brEl.innerHTML = KNOWN_BRANDS.map((b) => `<div class="chip" data-brand="${esc(b)}">${esc(b)}</div>`).join("");
  brEl.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
    const b = c.dataset.brand;
    if (state.brands.has(b)) state.brands.delete(b); else state.brands.add(b);
    c.classList.toggle("active");
    loadStations();
  }));

  document.getElementById("only-data").addEventListener("change", (e) => {
    state.onlyData = e.target.checked; loadStations();
  });

  // legend
  document.getElementById("legend").innerHTML =
    state.meta.statuses.map((s) =>
      `<div class="row"><span class="dot" style="background:${COLORS[state.meta.status_color[s]]}"></span>${statusLabel(s)}</div>`).join("") +
    `<div class="row"><span class="dot" style="background:${COLORS.gray}"></span>Нет данных</div>`;
}

/* ---------------- station detail ---------------- */
async function openStation(id) {
  let d;
  try { d = await api("/stations/" + id); } catch (e) { toast(e.message); return; }
  state.selected = d;
  state.reportStatus = null; state.reportFuel = "";
  const subbed = (localStorage.getItem("azs_subs") || "").split(",").includes(String(id));
  const card = document.getElementById("station-card");
  card.innerHTML = `
    <div class="modal-head">
      <h3>Заправка</h3>
      <button class="modal-close" data-close="station-modal">✕</button>
    </div>
    <div class="sc-top">
      <div class="sc-title">${esc(d.name)}</div>
      ${d.brand ? `<div class="sc-brand">${esc(d.brand)}</div>` : ""}
      ${d.address ? `<div class="sc-addr">${esc(d.address)}</div>` : ""}
      <div><span class="sc-status" style="background:${hexA(d.color)};color:${COLORS[d.color] || "#cbd5e1"}">
        <span style="width:11px;height:11px;border-radius:50%;background:${COLORS[d.color] || COLORS.gray};display:inline-block"></span>
        ${d.status ? statusLabel(d.status) : "Нет данных"}</span>
        ${d.stale ? '<span class="badge-stale">данные устарели</span>' : ""}
      </div>
      <div class="sc-updated">Обновлено: ${timeAgo(d.last_report)}${d.confirms ? " · подтверждений: " + d.confirms : ""}</div>
    </div>

    ${renderFuelGrid(d)}

    <div class="section">
      <h4>Сообщить о статусе</h4>
      <div class="statusbtns" id="rep-status">
        ${state.meta.statuses.map((s) => `<button class="sbtn" data-s="${s}"><span class="dot" style="background:${COLORS[state.meta.status_color[s]]}"></span>${statusLabel(s)}</button>`).join("")}
      </div>
      <div class="row-inline">
        <select id="rep-fuel">
          <option value="">Топливо: все</option>
          ${state.meta.fuel_types.map((f) => `<option value="${f}">${fuelLabel(f)}</option>`).join("")}
        </select>
      </div>
      <div class="row-inline"><textarea id="rep-comment" placeholder="Комментарий (необязательно): очередь, цены, табло…"></textarea></div>
      <div class="row-inline"><input type="file" id="rep-photo" accept="image/*" capture="environment" /></div>
      <div class="actions">
        <button class="btn primary block" id="rep-submit">Отправить</button>
      </div>
    </div>

    <div class="section">
      <h4>Действия</h4>
      <div class="actions">
        <button class="btn ghost" id="btn-route">🧭 Маршрут</button>
        <button class="btn ghost" id="btn-sub">${subbed ? "🔕 Отписаться" : "🔔 Подписаться"}</button>
      </div>
    </div>

    <div class="section">
      <h4>Последние отчёты</h4>
      <div id="reports">${renderReports(d.reports)}</div>
    </div>`;

  card.querySelector('[data-close]').addEventListener("click", closeModals);
  card.querySelectorAll("#rep-status .sbtn").forEach((b) => b.addEventListener("click", () => {
    state.reportStatus = b.dataset.s;
    card.querySelectorAll("#rep-status .sbtn").forEach((x) => x.classList.toggle("active", x === b));
  }));
  card.querySelector("#rep-submit").addEventListener("click", submitReport);
  card.querySelector("#btn-route").addEventListener("click", () => routeTo(d));
  card.querySelector("#btn-sub").addEventListener("click", () => toggleSub(d.id));
  bindVotes(card);
  show("station-modal");
}

function hexA(color) {
  const c = COLORS[color] || COLORS.gray;
  return c + "22";
}

function renderFuelGrid(d) {
  const fuels = d.fuels && d.fuels.length ? d.fuels : state.meta.fuel_types;
  return `<div class="fuel-grid">` + fuels.map((f) => {
    const fs = d.fuel_statuses[f];
    const color = fs ? state.meta.status_color[fs.status] : "gray";
    return `<div class="fuel-cell">
      <div class="fl">${fuelLabel(f)}</div>
      <div class="fs"><span class="fdot" style="background:${COLORS[color] || COLORS.gray}"></span>${fs ? statusLabel(fs.status) : "—"}</div>
    </div>`;
  }).join("") + `</div>`;
}

function renderReports(reports) {
  if (!reports.length) return `<div class="muted" style="font-size:13px">Пока нет отчётов. Будьте первым!</div>`;
  return reports.map((r) => `
    <div class="report" data-rid="${r.id}">
      <div class="rdot" style="background:${COLORS[state.meta.status_color[r.status]] || COLORS.gray}"></div>
      <div class="rbody">
        <div class="rstatus">${statusLabel(r.status)}${r.fuel_type ? " · " + fuelLabel(r.fuel_type) : ""} <span class="rtime">· ${timeAgo(r.created_at)}</span></div>
        ${r.comment ? `<div class="rcomment">${esc(r.comment)}</div>` : ""}
        ${r.photo ? `<img class="rphoto" loading="lazy" src="/api/photos/${esc(r.photo)}" />` : ""}
        <div class="rvote">
          <button class="vbtn" data-act="confirm" data-rid="${r.id}">👍 Подтвердить (${r.confirms || 0})</button>
          <button class="vbtn" data-act="dispute" data-rid="${r.id}">⚠️ Не так</button>
        </div>
      </div>
    </div>`).join("");
}

function bindVotes(card) {
  card.querySelectorAll(".vbtn").forEach((b) => b.addEventListener("click", async () => {
    try {
      await api(`/reports/${b.dataset.rid}/${b.dataset.act === "confirm" ? "confirm" : "flag"}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_id: deviceId(), kind: b.dataset.act }),
      });
      toast(b.dataset.act === "confirm" ? "Спасибо за подтверждение!" : "Спасибо, отметили");
      openStation(state.selected.id);
    } catch (e) { toast(e.message); }
  }));
}

async function submitReport() {
  if (!state.reportStatus) { toast("Выберите статус"); return; }
  const fd = new FormData();
  fd.append("station_id", state.selected.id);
  fd.append("status", state.reportStatus);
  fd.append("fuel_type", document.getElementById("rep-fuel").value || "");
  fd.append("comment", document.getElementById("rep-comment").value || "");
  fd.append("device_id", deviceId());
  const photo = document.getElementById("rep-photo").files[0];
  if (photo) fd.append("photo", photo);
  const btn = document.getElementById("rep-submit");
  btn.disabled = true; btn.textContent = "Отправка…";
  try {
    await api("/report", { method: "POST", body: fd });
    toast("Спасибо! Статус обновлён");
    await openStation(state.selected.id);
    loadStations();
  } catch (e) { toast(e.message); btn.disabled = false; btn.textContent = "Отправить"; }
}

function routeTo(d) {
  const from = state.user ? `${state.user.lat},${state.user.lon}~` : "";
  const url = `https://yandex.ru/maps/?rtext=${state.user ? state.user.lat + "," + state.user.lon : ""}~${d.lat},${d.lon}&rtt=auto`;
  window.open(url, "_blank");
}

async function toggleSub(id) {
  let subs = (localStorage.getItem("azs_subs") || "").split(",").filter(Boolean);
  const has = subs.includes(String(id));
  try {
    if (has) {
      await api(`/subscribe?station_id=${id}&device_id=${deviceId()}`, { method: "DELETE" });
      subs = subs.filter((x) => x !== String(id)); toast("Вы отписались");
    } else {
      await api("/subscribe", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ station_id: id, device_id: deviceId() }) });
      subs.push(String(id)); toast("Подписка оформлена 🔔");
    }
    localStorage.setItem("azs_subs", subs.join(","));
    openStation(id);
  } catch (e) { toast(e.message); }
}

/* ---------------- geolocation ---------------- */
function locate() {
  if (!navigator.geolocation) { toast("Геолокация недоступна"); return; }
  toast("Определяем местоположение…");
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      state.user = { lat: pos.coords.latitude, lon: pos.coords.longitude };
      if (window._uMarker) map.removeLayer(window._uMarker);
      window._uMarker = L.circleMarker([state.user.lat, state.user.lon], {
        radius: 8, color: "#fff", weight: 2, fillColor: COLORS.green, fillOpacity: 1,
      }).addTo(map).bindPopup("Вы здесь");
      map.setView([state.user.lat, state.user.lon], 14);
    },
    () => toast("Не удалось определить местоположение"),
    { enableHighAccuracy: true, timeout: 10000 }
  );
}

/* ---------------- analytics ---------------- */
async function openAnalytics() {
  show("analytics-modal");
  const body = document.getElementById("analytics-body");
  body.innerHTML = '<div class="muted">Загрузка…</div>';
  try {
    const a = await api("/analytics");
    const maxH = Math.max(1, ...a.by_hour.map((h) => h.total));
    body.innerHTML = `
      <div class="an-cards">
        <div class="an-card"><div class="v">${a.totals.stations.toLocaleString("ru")}</div><div class="l">АЗС на карте</div></div>
        <div class="an-card"><div class="v">${a.totals.reports_24h}</div><div class="l">Отчётов за 24ч</div></div>
        <div class="an-card"><div class="v">${a.totals.reports_total}</div><div class="l">Всего отчётов</div></div>
      </div>
      <h4 style="color:var(--muted);font-size:12px;text-transform:uppercase">Регионы (по отчётам)</h4>
      <table class="an"><tr><th>Регион</th><th>Нет топлива</th><th>Очереди</th><th>Есть</th></tr>
      ${a.by_region.map((r) => `<tr><td>${esc(r.region)}</td><td style="color:var(--red)">${r.no_fuel}</td><td style="color:var(--yellow)">${r.queues}</td><td style="color:var(--green)">${r.have}</td></tr>`).join("") || '<tr><td colspan=4 class="muted">Пока нет данных</td></tr>'}
      </table>
      <h4 style="color:var(--muted);font-size:12px;text-transform:uppercase;margin-top:18px">Активность по часам (7 дней)</h4>
      <div class="bars">${Array.from({ length: 24 }, (_, h) => {
        const rec = a.by_hour.find((x) => x.hour === h);
        const v = rec ? rec.total : 0;
        return `<div class="bar" style="height:${Math.round((v / maxH) * 100)}%" title="${h}:00 — ${v}">${h % 6 === 0 ? `<span>${h}</span>` : ""}</div>`;
      }).join("")}</div>
      <div style="height:18px"></div>`;
  } catch (e) { body.innerHTML = `<div class="muted">${e.message}</div>`; }
}

/* ---------------- subscriptions ---------------- */
async function openSubs() {
  show("subs-modal");
  const body = document.getElementById("subs-body");
  body.innerHTML = '<div class="muted">Загрузка…</div>';
  try {
    const d = await api("/subscriptions?device_id=" + deviceId());
    if (!d.subscriptions.length) { body.innerHTML = '<div class="muted">У вас нет подписок. Откройте заправку и нажмите «🔔 Подписаться», чтобы получать уведомления о появлении топлива.</div>'; return; }
    body.innerHTML = d.subscriptions.map((s) => `
      <div class="st-item" data-id="${s.station_id}" style="border-radius:10px;border:1px solid var(--line);margin-bottom:8px">
        <div class="st-dot" style="background:${COLORS[s.color] || COLORS.gray}"></div>
        <div class="st-main"><div class="st-name">${esc(s.name)}</div>
        <div class="st-meta">${s.brand ? esc(s.brand) + " · " : ""}${s.status ? statusLabel(s.status) : "нет данных"} · ${timeAgo(s.last_report)}</div></div>
      </div>`).join("");
    body.querySelectorAll(".st-item").forEach((it) => it.addEventListener("click", () => { closeModals(); openStation(+it.dataset.id); }));
  } catch (e) { body.innerHTML = `<div class="muted">${e.message}</div>`; }
}

/* ---------------- search ---------------- */
async function doSearch(q) {
  q = q.trim();
  if (!q) return;
  // first try local match among loaded stations
  const local = [...state.stations.values()].find((s) =>
    (s.name || "").toLowerCase().includes(q.toLowerCase()) || (s.brand || "").toLowerCase().includes(q.toLowerCase()));
  if (local) { map.setView([local.lat, local.lon], 15); openStation(local.id); return; }
  // else geocode the place via Nominatim
  try {
    const r = await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=ru&q=${encodeURIComponent(q)}`, { headers: { "Accept-Language": "ru" } });
    const j = await r.json();
    if (j.length) map.setView([+j[0].lat, +j[0].lon], 13);
    else toast("Ничего не найдено");
  } catch (e) { toast("Ошибка поиска"); }
}

/* ---------------- modals & ui ---------------- */
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem("azs_theme", t);
  const btn = document.getElementById("btn-theme");
  if (btn) {
    btn.textContent = t === "light" ? "☀️" : "🌙";
    btn.title = t === "light" ? "Тёмная тема" : "Светлая тема";
  }
  setBaseLayer(t === "light" ? "light" : "dark");
}
function toggleTheme() {
  const cur = document.documentElement.dataset.theme === "light" ? "light" : "dark";
  applyTheme(cur === "light" ? "dark" : "light");
}

function show(id) { document.getElementById(id).hidden = false; }
function closeModals() { document.querySelectorAll(".modal").forEach((m) => (m.hidden = true)); }

function bindUI() {
  document.getElementById("btn-locate").addEventListener("click", locate);
  document.getElementById("btn-analytics").addEventListener("click", openAnalytics);
  document.getElementById("btn-subs").addEventListener("click", openSubs);
  applyTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  document.getElementById("btn-theme").addEventListener("click", toggleTheme);
  const link = (id, url) => { const a = document.getElementById(id); if (a) a.href = url; };
  link("comm-vk", SOCIAL.vk); link("comm-tg", SOCIAL.tg); link("comm-max", SOCIAL.max);
  document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", closeModals));
  document.querySelectorAll(".modal").forEach((m) => m.addEventListener("click", (e) => { if (e.target === m) closeModals(); }));
  const panel = document.getElementById("panel");
  const refitMap = () => { if (map) setTimeout(() => map.invalidateSize(), 340); };
  document.getElementById("panel-toggle").addEventListener("click", () => { panel.classList.add("collapsed"); refitMap(); });
  document.getElementById("panel-open").addEventListener("click", () => { panel.classList.toggle("collapsed"); refitMap(); });
  document.getElementById("search").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(e.target.value); });
}

/* ---------------- boot ---------------- */
async function boot() {
  initMap();
  bindUI();
  try {
    state.meta = await api("/meta");
    buildFilters();
    document.getElementById("stats-foot").textContent =
      `${state.meta.stations_count.toLocaleString("ru")} АЗС · обновлено ${state.meta.last_import || "—"}`;
  } catch (e) { toast("Не удалось загрузить настройки"); }
  await loadStations();
  // auto-locate softly on load
  if (navigator.geolocation) setTimeout(locate, 600);
}
boot();
