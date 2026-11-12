const CACHE_NAME = 'editortools-v14';
const CORE_ASSETS = ['/', '/manifest.json'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  // Никога не кеширай API повикванията — винаги мрежа
  if (['/transcribe', '/tts', '/stream', '/pro', '/track', '/stats'].some((p) => url.pathname.startsWith(p))) {
    return;
  }
  // Pages: network first so updates show up at once; cache only when offline.
  // Each page is cached under its own path, so /bg/... never replaces the tool at '/'.
  if (event.request.mode === 'navigate') {
    const key = url.pathname;
    event.respondWith(
      fetch(event.request)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE_NAME).then((c) => c.put(key, copy));
          }
          return res;
        })
        .catch(() => caches.match(key).then((r) => r || caches.match('/')))
    );
    return;
  }
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
