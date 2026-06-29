/* АЗС Онлайн Табло — service worker */
const CACHE = "azs-static-v2";
const ASSETS = [
  "/",
  "/index.html",
  "/style.css",
  "/app.js",
  "/manifest.webmanifest",
  "/vendor/leaflet.css",
  "/vendor/leaflet.js",
  "/vendor/MarkerCluster.css",
  "/vendor/MarkerCluster.Default.css",
  "/vendor/leaflet.markercluster.js",
  "/img/logo.png",
  "/img/icon-192.png",
  "/img/icon-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // never cache the API or map tiles — always live
  if (url.pathname.startsWith("/api/") || /basemaps\.cartocdn\.com/.test(url.host)) {
    return;
  }
  // network-first for same-origin assets: always fresh when online,
  // fall back to cache only when offline
  if (url.origin === self.location.origin) {
    e.respondWith(
      fetch(req)
        .then((res) => {
          if (res && res.status === 200) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy));
          }
          return res;
        })
        .catch(() => caches.match(req).then((c) => c || caches.match("/")))
    );
  }
});
