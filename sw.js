// Clinora service worker: makes the site installable and lets it open without internet.
// Pages are always fetched fresh when online ("network first"); the saved copy is only used offline.
// Private data (/api/...) is never stored.
const CACHE = 'clinora-v2';
const SHELL = ['/', '/index.html', '/i18n.js', '/manifest.json', '/assets/icons/icon-192.png', '/assets/icons/icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  const isImage = url.pathname.startsWith('/assets/');
  if (isImage) {  // images: saved copy first, refreshed in the background
    e.respondWith(caches.open(CACHE).then(async c => {
      const hit = await c.match(req);
      const net = fetch(req).then(r => { if (r.ok) c.put(req, r.clone()); return r; }).catch(() => hit);
      return hit || net;
    }));
    return;
  }
  e.respondWith(fetch(req).then(r => {
    if (r.ok) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
    return r;
  }).catch(() => caches.match(req).then(hit => hit || caches.match('/index.html'))));
});

// Notifications sent by the server (new message, booking, reminder...), shown even when Clinora is closed.
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = { title: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(d.title || 'Clinora', {
    body: d.body || '', icon: '/assets/icons/icon-192.png', badge: '/assets/icons/icon-192.png',
    data: { link: d.link || 'account' }, tag: d.tag || undefined
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const link = String((e.notification.data || {}).link || 'account');
  const url = '/#' + (link.startsWith('reviews:') ? 'directory' : link);
  e.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
    for (const c of list) { if (new URL(c.url).origin === location.origin) { c.navigate(url); return c.focus(); } }
    return clients.openWindow(url);
  }));
});
