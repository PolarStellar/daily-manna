/* Daily Manna service worker — makes generated articles readable offline / when
   the Mac is asleep or VPN is off. Network-first (so you get fresh articles when
   online), falling back to the on-device cache when the network isn't there. */
const CACHE = "daily-manna-v1";
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
  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() =>
        caches.match(req).then((m) =>
          m || (req.mode === "navigate" ? caches.match("./index.html") : Response.error())
        )
      )
  );
});
