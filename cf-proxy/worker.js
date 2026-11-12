/**
 * Cloudflare Worker — reverse proxy за www.editortools.online → Google Cloud Run.
 *
 * Настройка:
 *   1. Смени UPSTREAM с реалния адрес на Space-а (username-spacename.hf.space).
 *   2. Deploy на Worker-а.
 *   3. Worker → Settings → Domains & Routes → Add Custom Domain → editortools.online
 *      (Cloudflare прави DNS записа и TLS сертификата сам — без ръчен CNAME.)
 *
 * Проксира ВСИЧКИ методи и пътища, вкл. POST multipart (/transcribe, /tts),
 * като пренаписва Host към hf.space. За посетителя URL-ът си остава editortools.online.
 */

const UPSTREAM = "https://editortools-488956559838.europe-west1.run.app";

export default {
  async fetch(request) {
    const incoming = new URL(request.url);
    const upstream = new URL(UPSTREAM);

    // Насочи заявката към Space-а, запазвайки path + query
    const target = new URL(incoming.pathname + incoming.search, upstream);

    // Копирай хедърите, махни Host (fetch го задава сам от target hostname —
    // точно това HF ползва за маршрутизация към Space-а)
    const headers = new Headers(request.headers);
    headers.delete("host");
    headers.set("X-Forwarded-Host", incoming.hostname);
    headers.set("X-Forwarded-Proto", "https");

    // FastAPI отговаря на HEAD с 405, а проверките на Google ползват HEAD.
    const isHead = request.method === "HEAD";
    // The page, the service worker and the manifest must never come from Cloudflare's cache,
    // or visitors keep an old version of the site for hours.
    const fresh = ["/", "/sw.js", "/manifest.json", "/index.html"].includes(incoming.pathname);
    if (fresh) target.searchParams.set("_fresh", Date.now().toString());
    const proxied = new Request(target.toString(), {
      ...(fresh ? { cache: "no-store" } : {}),
      method: isHead ? "GET" : request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
      redirect: "manual",
    });

    try {
      const resp = await fetch(proxied);
      // Пусни отговора както е (стрийминг, статуси, хедъри се запазват)
      const headers = new Headers(resp.headers);
      if (fresh) headers.set("Cache-Control", "no-cache");
      return new Response(isHead ? null : resp.body, {
        status: resp.status,
        statusText: resp.statusText,
        headers,
      });
    } catch (err) {
      // Cloud Run се стартира наново след период без заявки.
      return new Response(
        "Приложението се събужда след период на неактивност — това отнема до минута. " +
          "Моля, опресни страницата след малко. 🙏",
        {
          status: 502,
          headers: {
            "content-type": "text/plain; charset=utf-8",
            "retry-after": "30",
          },
        }
      );
    }
  },
};
