/* Offline shell for a shop counter with patchy signal.
 *
 * The cache name carries the build id, so a deploy makes this file different,
 * the browser installs the new worker, and every older cache is dropped. The
 * previous version used a fixed name and never expired: a phone that had once
 * installed the app kept serving the bundle it cached on day one, so fixes
 * shipped for a week never reached the person who reported the bug.
 */
const BUILD = "__BUILD_ID__";
const SHELL = `galla-shell-${BUILD}`;
const PRECACHE = ["/", "/index.html", "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;          // never serve stale money

  // Network first, cache only as a fallback for genuinely being offline. The
  // shop should get today's app whenever it can reach the internet at all.
  event.respondWith(
    fetch(request)
      .then((response) => {
        const copy = response.clone();
        caches.open(SHELL).then((c) => c.put(request, copy));
        return response;
      })
      .catch(() => caches.match(request).then((hit) => hit || caches.match("/index.html")))
  );
});
