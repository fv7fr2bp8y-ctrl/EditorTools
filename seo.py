"""Bulgarian landing pages for search engines, plus robots.txt and sitemap.xml.

Each page: one task, H1, title, meta description, short explanation,
FAQ (schema.org FAQPage) and a button to the tool itself.
"""
import html
import json

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

SITE = "https://www.editortools.online"
LASTMOD = "2026-11-12"
router = APIRouter()

FREE = ("Да. Всеки ден имаш 3 транскрипции и 3 озвучавания безплатно, без регистрация. "
        "Ако ти трябват повече, EditorTools Pro дава до 100 на ден за 1,99 € на месец "
        "и се спира по всяко време.")

PAGES = {
    "audio-v-tekst": {
        "title": "Аудио в текст на български, безплатно онлайн | EditorTools",
        "desc": ("Превърни аудио или видео запис в текст на български. Качваш файла, "
                 "изкуственият интелект го транскрибира, а ти копираш или сваляш текста. "
                 "3 файла на ден безплатно."),
        "h1": "Аудио в текст на български",
        "lead": ("Качи запис на интервю, лекция, среща или гласово съобщение и получи текста "
                 "след минути. EditorTools разпознава българска реч и още 7 езика. Готовият "
                 "текст копираш с едно натискане или го сваляш като TXT файл."),
        "cta": "Преобразувай запис в текст",
        "href": "/",
        "steps": [
            "Качи аудио или видео файл до 500 MB: MP3, WAV, M4A, OGG, MP4, MOV и други.",
            "Избери езика на записа или остави „Автоматично“.",
            "Натисни „Транскрибирай“. Текстът се появява ред по ред, докато файлът се обработва.",
        ],
        "uses_title": "За какво го ползват",
        "uses": [
            "Интервюта и подкасти, които трябва да станат статия",
            "Лекции, уебинари и обучения",
            "Срещи, разговори и протоколи",
            "Гласови бележки и диктовки",
            "Видео за YouTube и социалните мрежи",
        ],
        "faq": [
            ("Безплатно ли е?", FREE),
            ("Колко точно разпознава български?",
             "Транскрипцията работи с модела Whisper. При ясен запис без много шум текстът "
             "е много близо до казаното. При силен фон, хора, които говорят едновременно, "
             "или диалект ще има грешки, затова прегледай текста, преди да го използваш. "
             "По-големият модел е по-точен, но работи по-бавно."),
            ("Какви файлове мога да кача?",
             "Аудио и видео файлове до 500 MB: MP3, WAV, M4A, OGG, FLAC, MP4, MOV, WEBM и "
             "други често срещани формати. От видеото се взема само звукът."),
            ("Пазите ли записите ми?",
             "Не. Файлът се обработва на нашия сървър и се изтрива веднага след "
             "транскрипцията. Не искаме регистрация."),
            ("Може ли транскрипция на живо от микрофона?",
             "Да. С бутона „Запис от микрофон“ говориш и текстът се появява веднага. Този "
             "режим използва разпознаването на реч на браузъра и работи най-добре в Chrome."),
        ],
    },
    "subtitri-ot-video": {
        "title": "Субтитри от видео, SRT файл онлайн безплатно | EditorTools",
        "desc": ("Направи субтитри от видео на български. Качваш видеото, получаваш текста с "
                 "времена и сваляш готов SRT файл за YouTube, Premiere Pro или DaVinci Resolve. "
                 "3 файла на ден безплатно."),
        "h1": "Субтитри от видео: готов SRT файл",
        "lead": ("Качи видео и EditorTools ще разпознае речта, ще я раздели на кратки реплики "
                 "с начален и краен час и ще ти даде SRT файл. Качваш го в YouTube или го "
                 "слагаш в програмата за монтаж и субтитрите са на място."),
        "cta": "Направи субтитри",
        "href": "/",
        "steps": [
            "Качи видеото до 500 MB: MP4, MOV, WEBM, MKV и други.",
            "Избери езика, на който се говори във видеото.",
            "Натисни „Транскрибирай“, отвори раздела SRT и натисни „Изтегли“.",
        ],
        "uses_title": "Какво получаваш и какво не",
        "uses": [
            "SRT файл с номерирани реплики и точни времена",
            "Текст без времена, ако ти трябва само стенограма",
            "Репликите следват естествените паузи в речта",
            "Субтитрите не се вграждат в картината: това става в програмата за монтаж",
            "Формат VTT засега няма, само SRT",
        ],
        "faq": [
            ("Безплатно ли е?", FREE),
            ("Как да кача SRT файла в YouTube?",
             "В YouTube Studio отвори видеото, влез в „Субтитри“, добави език и избери качване "
             "на файл с времена. Посочи SRT файла, който свали от EditorTools."),
            ("Мога ли да поправя текста на субтитрите?",
             "Да. SRT файлът е обикновен текст. Отвори го с Notepad или TextEdit и поправи "
             "думите, без да пипаш редовете с часовете. Програмите за монтаж също позволяват "
             "редакция на субтитри."),
            ("Има ли VTT формат?",
             "Засега не, EditorTools дава SRT. Повечето програми за монтаж и платформи "
             "приемат SRT, а ако ти трябва VTT, SRT се преобразува лесно."),
            ("Превежда ли субтитрите на друг език?",
             "Не. Субтитрите са на езика, на който се говори във видеото. Превод няма."),
        ],
    },
    "tekst-v-govor": {
        "title": "Текст в говор на български, озвучаване онлайн | EditorTools",
        "desc": ("Постави текст на български и го чуй на глас след секунди. 10 гласа с "
                 "изкуствен интелект, без регистрация, 3 озвучавания на ден безплатно."),
        "h1": "Текст в говор на български",
        "lead": ("Постави текст, избери глас и натисни „Прочети текста“. EditorTools озвучава "
                 "текста с изкуствен интелект (Google Gemini) и го пуска направо в браузъра. "
                 "Удобно е да чуеш сценарий, преди да го запишеш, да провериш как звучи текст "
                 "или да слушаш, вместо да четеш."),
        "cta": "Озвучи текст",
        "href": "/#free-tts-anchor",
        "steps": [
            "Напиши или постави текста в полето „Свободен текст“.",
            "Избери един от 10-те гласа: 5 мъжки и 5 женски.",
            "Натисни „Прочети текста“ и слушай.",
        ],
        "uses_title": "За какво е удобно",
        "uses": [
            "Да чуеш сценарий или реклама, преди да ги запишеш",
            "Да провериш ритъма и дължината на текст",
            "Да слушаш статия или бележки, вместо да ги четеш",
            "Да чуеш на глас текст от транскрипция с бутона „Прочети всичко“",
        ],
        "faq": [
            ("Безплатно ли е?", FREE),
            ("Звучи ли естествено на български?",
             "Гласовете са на Google Gemini и четат български с естествена интонация. "
             "Понякога ударението в редки думи и имена не е вярно, затова чуй целия текст, "
             "преди да разчиташ на него."),
            ("Колко гласа има?",
             "10 гласа: 5 мъжки и 5 женски. Избираш ги от падащото меню до бутона."),
            ("Мога ли да сваля аудиото като файл?",
             "Засега не. Озвучаването се слуша направо в браузъра."),
            ("Къде отива текстът ми?",
             "Текстът се изпраща към Google Gemini, за да се генерира гласът. Пазим резултата "
             "за кратко в паметта на сървъра, за да не го генерираме два пъти. Не искаме "
             "регистрация и нямаш профил с текстове."),
        ],
    },
}

NAV_LABEL = {
    "audio-v-tekst": "Аудио в текст",
    "subtitri-ot-video": "Субтитри от видео",
    "tekst-v-govor": "Текст в говор",
}

CSS = """
:root{--page:#F4F4F1;--surface:#FFFFFF;--ink:#17171C;--body:#46454F;--muted:#8A8A94;
--border:#EFEFEA;--accent:#5B4BE8;--accent-ink:#4B3CC4;--accent-soft:#F3F0FF}
@media (prefers-color-scheme:dark){:root{--page:#0E0C18;--surface:#1A1726;--ink:#F4F3F9;
--body:#CBC8DB;--muted:#9A96B0;--border:rgba(255,255,255,.08);--accent:#8B7BFF;
--accent-ink:#C6BCFF;--accent-soft:rgba(124,107,255,.15)}}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Geist,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--page);
color:var(--body);line-height:1.6}
.wrap{max-width:760px;margin:0 auto;padding:24px 16px 64px}
header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:36px}
.brand{display:flex;align-items:center;gap:10px;color:var(--ink);font-weight:800;text-decoration:none}
.brand img{width:32px;height:32px;border-radius:9px}
.top-link{color:var(--accent-ink);font-size:14px;font-weight:600;text-decoration:none}
h1{color:var(--ink);font-size:clamp(28px,6vw,42px);line-height:1.15;letter-spacing:-.02em;margin-bottom:16px}
.lead{font-size:18px;margin-bottom:24px}
.cta{display:inline-block;background:var(--accent);color:#fff;font-weight:700;font-size:16px;
padding:14px 24px;border-radius:12px;text-decoration:none}
.cta:hover{filter:brightness(1.08)}
.note{color:var(--muted);font-size:14px;margin-top:10px}
h2{color:var(--ink);font-size:22px;margin:44px 0 14px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:20px 22px}
ol,ul{padding-left:22px}
li{margin:6px 0}
details{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:14px 18px;margin-bottom:10px}
summary{color:var(--ink);font-weight:700;cursor:pointer}
details p{margin-top:8px}
.more{display:flex;flex-wrap:wrap;gap:10px}
.more a{background:var(--accent-soft);color:var(--accent-ink);padding:9px 14px;border-radius:10px;
text-decoration:none;font-weight:600;font-size:14px}
footer{margin-top:56px;color:var(--muted);font-size:13px}
footer a{color:var(--accent-ink)}
"""

# Same anonymous analytics as the tool: no cookies, no storage.
TRACK_JS = """
(function(){try{var q=new URLSearchParams(location.search),f=new FormData();
f.append('event','pageview');f.append('ui_lang','bg');
var tz='';try{tz=Intl.DateTimeFormat().resolvedOptions().timeZone||''}catch(e){}
f.append('country',tz);f.append('path',location.pathname);f.append('ref',document.referrer||'');
['utm_source','utm_medium','utm_campaign'].forEach(function(k){f.append(k,q.get(k)||'')});
fetch('/track',{method:'POST',body:f,keepalive:true}).catch(function(){});
document.querySelectorAll('a.cta').forEach(function(a){a.addEventListener('click',function(){
var g=new FormData();g.append('event','seo_cta');g.append('ui_lang','bg');g.append('extra',location.pathname);
g.append('path',location.pathname);fetch('/track',{method:'POST',body:g,keepalive:true}).catch(function(){})})})
}catch(e){}})();
"""


def _e(s: str) -> str:
    return html.escape(s, quote=True)


def render(slug: str) -> str:
    p = PAGES[slug]
    url = f"{SITE}/bg/{slug}"
    faq_ld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in p["faq"]
        ],
    }
    ld = json.dumps(faq_ld, ensure_ascii=False).replace("</", "<\\/")
    steps = "".join(f"<li>{_e(s)}</li>" for s in p["steps"])
    uses = "".join(f"<li>{_e(s)}</li>" for s in p["uses"])
    faq = "".join(f"<details><summary>{_e(q)}</summary><p>{_e(a)}</p></details>" for q, a in p["faq"])
    more = "".join(f'<a href="/bg/{s}">{_e(NAV_LABEL[s])}</a>' for s in PAGES if s != slug)
    return f"""<!DOCTYPE html>
<html lang="bg"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_e(p['title'])}</title>
<meta name="description" content="{_e(p['desc'])}">
<link rel="canonical" href="{url}">
<link rel="alternate" hreflang="bg" href="{url}">
<link rel="alternate" hreflang="x-default" href="{url}">
<meta property="og:type" content="website">
<meta property="og:locale" content="bg_BG">
<meta property="og:title" content="{_e(p['h1'])} | EditorTools">
<meta property="og:description" content="{_e(p['desc'])}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE}/icons/icon-512.png">
<meta name="theme-color" content="#5B4BE8">
<link rel="icon" href="/icons/icon-192.png?v=2">
<link rel="apple-touch-icon" href="/icons/icon-192.png?v=2">
<style>{CSS}</style>
<script type="application/ld+json">{ld}</script>
</head><body><div class="wrap">
<header>
  <a class="brand" href="/"><img src="/icons/icon-192.png?v=2" alt="" width="32" height="32">EditorTools</a>
  <a class="top-link" href="{p['href']}">Към инструмента</a>
</header>
<main>
  <h1>{_e(p['h1'])}</h1>
  <p class="lead">{_e(p['lead'])}</p>
  <a class="cta" href="{p['href']}">{_e(p['cta'])}</a>
  <p class="note">Без регистрация. 3 пъти на ден безплатно.</p>

  <h2>Как работи</h2>
  <div class="card"><ol>{steps}</ol></div>

  <h2>{_e(p['uses_title'])}</h2>
  <div class="card"><ul>{uses}</ul></div>

  <h2>Често задавани въпроси</h2>
  {faq}

  <h2>Опитай сега</h2>
  <a class="cta" href="{p['href']}">{_e(p['cta'])}</a>

  <h2>Още инструменти</h2>
  <div class="more">{more}</div>
</main>
<footer>© 2026 EditorTools · <a href="/privacy.html">Поверителност</a> ·
<a href="mailto:support@editortools.online">support@editortools.online</a></footer>
</div>
<script>{TRACK_JS}</script>
</body></html>"""


_cache = {slug: render(slug) for slug in PAGES}


def _page(slug: str):
    async def handler():
        return HTMLResponse(_cache[slug])
    return handler


for _slug in PAGES:
    router.add_api_route(f"/bg/{_slug}", _page(_slug), methods=["GET"], response_class=HTMLResponse)


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots():
    return ("User-agent: *\n"
            "Allow: /\n"
            "Disallow: /stats\n"
            "Disallow: /pro/\n"
            "Disallow: /stream/\n"
            f"\nSitemap: {SITE}/sitemap.xml\n")


@router.get("/sitemap.xml")
async def sitemap():
    urls = [("/", "1.0")] + [(f"/bg/{s}", "0.8") for s in PAGES] + [("/privacy.html", "0.2")]
    items = []
    for path, prio in urls:
        loc = SITE + path
        alt = ""
        if path.startswith("/bg/"):
            alt = (f'<xhtml:link rel="alternate" hreflang="bg" href="{loc}"/>'
                   f'<xhtml:link rel="alternate" hreflang="x-default" href="{loc}"/>')
        items.append(f"<url><loc>{loc}</loc>{alt}<lastmod>{LASTMOD}</lastmod>"
                     f"<priority>{prio}</priority></url>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "\n".join(items) + "\n</urlset>\n")
    return Response(xml, media_type="application/xml")
