const CACHE = 'khub-v1';
const PRECACHE = ['/', '/web/index.html', '/web/style.css', '/web/script.js', '/web/login.html'];

self.addEventListener('install', function(e) {
  e.waitUntil(caches.open(CACHE).then(function(c) { return c.addAll(PRECACHE); }).then(function(){ return self.skipWaiting(); }));
});

self.addEventListener('activate', function(e) {
  e.waitUntil(clients.claim());
});

self.addEventListener('fetch', function(e) {
  e.respondWith(
    caches.match(e.request).then(function(r) { return r || fetch(e.request).catch(function(){ return new Response('离线', {status:503}); }); })
  );
});
