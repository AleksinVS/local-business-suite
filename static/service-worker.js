const CACHE_PREFIX = "local-business-suite-pwa-";
const CACHE_VERSION = `${CACHE_PREFIX}v4`;
const STATIC_CACHE = `${CACHE_VERSION}:static`;
const STATIC_ASSETS = [
  "/static/src/css/app.css?v=pwa-v4",
  "/static/src/js/pwa.js?v=pwa-v4",
  "/static/src/js/notifications.js?v=pwa-v4"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(STATIC_ASSETS)).catch(() => undefined)
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key.startsWith(CACHE_PREFIX) && key !== STATIC_CACHE)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

async function networkFirstStatic(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(STATIC_CACHE);
      await cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    const cached = await caches.match(request);
    if (cached) return cached;
    throw error;
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (!url.pathname.startsWith("/static/")) return;
  if (url.pathname.startsWith("/static/dist/copilotkit/")) return;
  if (url.pathname.startsWith("/static/src/ai_ui/")) return;

  event.respondWith(networkFirstStatic(request));
});
