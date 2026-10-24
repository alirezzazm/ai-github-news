/* Minimal service worker: cache static assets, network-first for pages. */
var CACHE = "aign-static-v1";
var ASSETS = ["/static/css/app.css", "/static/js/app.js", "/static/fonts/Vazirmatn-Regular.woff2", "/static/fonts/Vazirmatn-Medium.woff2", "/static/fonts/Vazirmatn-Bold.woff2", "/static/img/icon.svg"];
self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(ASSETS).catch(function () {}); }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (keys) { return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); })); }));
});
self.addEventListener("fetch", function (e) {
  var url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/static/")) {
    e.respondWith(caches.match(e.request).then(function (hit) {
      return hit || fetch(e.request).then(function (res) { var copy = res.clone(); caches.open(CACHE).then(function (c) { c.put(e.request, copy); }); return res; });
    }));
    return;
  }
  if (url.pathname.startsWith("/admin") || url.pathname.startsWith("/api")) return;
  e.respondWith(fetch(e.request).then(function (res) {
    var copy = res.clone(); caches.open(CACHE).then(function (c) { c.put(e.request, copy); }); return res;
  }).catch(function () { return caches.match(e.request); }));
});
