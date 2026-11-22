/* Service worker: caches only the public application shell.
   Authenticated HTML and business data are never cached, so shared devices
   cannot leak one user's information to another. */
const VERSION = "salmancollections-shell-v4";
const SHELL = [
  "/static/css/app.css",
  "/static/css/ui.css",
  "/static/js/app.js",
  "/static/js/ui.js",
  "/static/js/charts.js",
  "/static/js/pos.js",
  "/static/js/inventory.js",
  "/static/img/icon-192.png",
  "/static/img/icon-512.png",
  "/offline/",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(VERSION).then((cache) =>
      Promise.allSettled(SHELL.map((url) => cache.add(new Request(url, { cache: "reload" }))))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== VERSION).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  const isStatic = url.pathname.startsWith("/static/");
  const isOfflinePage = url.pathname === "/offline/";
  const isLogin = url.pathname === "/accounts/login/";

  if (isStatic) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(VERSION).then((cache) => cache.put(request, copy));
          }
          return response;
        });
      })
    );
    return;
  }

  if (request.mode === "navigate") {
    if (isOfflinePage) {
      event.respondWith(caches.match("/offline/").then((cached) => cached || fetch(request)));
      return;
    }
    if (isLogin) {
      event.respondWith(
        fetch(request).then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(VERSION).then((cache) => cache.put("/accounts/login/", copy));
          }
          return response;
        }).catch(() => caches.match("/accounts/login/").then((cached) => cached || caches.match("/offline/")))
      );
      return;
    }
    // Authenticated pages are always fetched live; fall back to the offline page.
    event.respondWith(
      fetch(request).catch(() =>
        caches.match("/offline/").then(
          (cached) => cached || new Response("<h1>Offline</h1>", { headers: { "Content-Type": "text/html" } })
        )
      )
    );
  }
});
