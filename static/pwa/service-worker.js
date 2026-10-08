/* Network-only: never persist account, cart, order or store responses offline. */
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (event) { event.waitUntil(self.clients.claim()); });
self.addEventListener('fetch', function (event) {
    if (event.request.method !== 'GET' || event.request.mode !== 'navigate') return;
    event.respondWith(fetch(event.request).catch(function () {
        return new Response('<!doctype html><html lang="en"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ZuuVi · Offline</title><body style="font:18px system-ui;padding:32px;max-width:600px;margin:auto"><h1>You’re offline</h1><p>Connect to the internet to shop, place orders, or manage your store.</p><p>Orders and changes cannot be submitted offline.</p><button onclick="location.reload()" style="padding:12px;font:inherit">Try again</button></body></html>', {status:503,headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'}});
    }));
});
