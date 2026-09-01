/* Daily Manna service worker — makes generated articles readable offline / when
   the Mac is asleep or VPN is off. Network-first (so you get fresh articles when
   online), falling back to the on-device cache when the network isn't there. */
// Bump this on any change to index.html or sw.js. activate() deletes every cache
// that is not the current name, so moving the version is what forces a phone
// holding an old app to throw it away. Leaving it pinned at v1 meant iPhones
// kept serving a stale index.html long after a fix had shipped.
const CACHE = "daily-manna-v4";
const SHELL = ["./", "./index.html", "./plan.json", "./manifest.json", "./icon.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET") return;                  // never touch love/generate POSTs
  if (url.origin !== self.location.origin) return;   // ignore the Mac/tailnet API (cross-origin)
  if (url.pathname.includes("/api/")) return;        // never cache the generator API
  if (req.headers.has("range")) return;              // audio seeks — 206s can't be cached
  e.respondWith(
    fetch(req)
      .then((res) => {
        // Only full 200s are cacheable; Cache.put rejects on a 206.
        if (res && res.status === 200) {
          const copy = res.clone();
          // Store under a plain GET for this URL rather than `req` itself:
          // the app fetches with cache:"no-store", and Safari refuses to put a
          // no-store request into a Cache, so on iOS nothing was ever saved for
          // offline and every lookup below missed.
          caches.open(CACHE)
            .then((c) => c.put(new Request(req.url, { mode: "same-origin" }), copy))
            .catch(() => {});
        }
        return res;
      })
      .catch(() =>
        // Match by URL, ignoring the request's cache mode/headers, so a
        // no-store fetch can still find the copy stored above.
        caches.match(req.url, { ignoreVary: true }).then((m) =>
          m || (req.mode === "navigate" ? caches.match("./index.html") : Response.error())
        )
      )
  );
});
