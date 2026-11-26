/* Google Analytics 4 with Consent Mode v2.
   Nothing is stored and no GA cookies are set until the visitor clicks "Приемам".
   The choice is kept in localStorage ('et-consent' = granted | denied). */
(function () {
  var GA_ID = 'G-75J6ZETMF6';
  var KEY = 'et-consent';
  window.dataLayer = window.dataLayer || [];
  function gtag() { dataLayer.push(arguments); }
  window.gtag = gtag;

  var saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) {}

  gtag('consent', 'default', {
    analytics_storage: 'denied',
    ad_storage: 'denied',
    ad_user_data: 'denied',
    ad_personalization: 'denied',
    wait_for_update: 500
  });
  if (saved === 'granted') gtag('consent', 'update', { analytics_storage: 'granted' });

  gtag('js', new Date());
  gtag('config', GA_ID);
  var s = document.createElement('script');
  s.async = true;
  s.src = 'https://www.googletagmanager.com/gtag/js?id=' + GA_ID;
  document.head.appendChild(s);

  var TEXT = {
    bg: ['Ползваме Google Analytics, за да видим кое се ползва и да подобрим сайта. Само ако разрешиш.', 'Приемам', 'Само необходимите', 'Поверителност'],
    en: ['We use Google Analytics to see what is used and improve the site. Only if you allow it.', 'Accept', 'Necessary only', 'Privacy'],
    de: ['Wir nutzen Google Analytics, um zu sehen, was genutzt wird, und die Seite zu verbessern. Nur mit deiner Zustimmung.', 'Akzeptieren', 'Nur notwendige', 'Datenschutz'],
    fr: ['Nous utilisons Google Analytics pour voir ce qui est utilisé et améliorer le site. Seulement avec ton accord.', 'Accepter', 'Nécessaires uniquement', 'Confidentialité'],
    es: ['Usamos Google Analytics para ver qué se usa y mejorar el sitio. Solo si lo permites.', 'Aceptar', 'Solo necesarias', 'Privacidad']
  };
  function lang() {
    var l = '';
    try { l = localStorage.getItem('et-ui-lang') || ''; } catch (e) {}
    if (!l) l = (document.documentElement.lang || navigator.language || 'bg');
    l = l.slice(0, 2).toLowerCase();
    return TEXT[l] ? l : 'bg';
  }

  function choose(value) {
    try { localStorage.setItem(KEY, value); } catch (e) {}
    gtag('consent', 'update', { analytics_storage: value });
    var b = document.getElementById('et-consent');
    if (b) b.remove();
  }

  function show() {
    if (document.getElementById('et-consent')) return;
    var t = TEXT[lang()];
    var b = document.createElement('div');
    b.id = 'et-consent';
    b.setAttribute('role', 'dialog');
    b.setAttribute('aria-label', t[3]);
    b.style.cssText = 'position:fixed;left:12px;right:12px;bottom:12px;z-index:99999;max-width:560px;margin:0 auto;' +
      'background:#1d1b2e;color:#f2f1fa;border:1px solid #3a3658;border-radius:14px;padding:14px 16px;' +
      'box-shadow:0 8px 30px rgba(0,0,0,.35);font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif';
    var p = document.createElement('p');
    p.style.cssText = 'margin:0 0 10px';
    p.textContent = t[0] + ' ';
    var a = document.createElement('a');
    a.href = '/privacy.html';
    a.textContent = t[3];
    a.style.cssText = 'color:#a99cff';
    p.appendChild(a);
    var row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end';
    function btn(label, primary, value) {
      var x = document.createElement('button');
      x.type = 'button';
      x.textContent = label;
      x.style.cssText = 'cursor:pointer;border-radius:10px;padding:9px 14px;font:600 14px system-ui,sans-serif;' +
        (primary ? 'background:#5B4BE8;color:#fff;border:1px solid #5B4BE8' : 'background:transparent;color:#f2f1fa;border:1px solid #4a4670');
      x.addEventListener('click', function () { choose(value); });
      return x;
    }
    row.appendChild(btn(t[2], false, 'denied'));
    row.appendChild(btn(t[1], true, 'granted'));
    b.appendChild(p);
    b.appendChild(row);
    document.body.appendChild(b);
  }
  window.etConsentOpen = show;

  if (saved !== 'granted' && saved !== 'denied') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', show);
    else show();
  }
})();
