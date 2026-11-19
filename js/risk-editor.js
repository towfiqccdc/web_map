// ============================================================
// Risk editor — lives on the MAIN page (no separate admin page).
//   🔒 Admin button -> sign in -> add a risk by tapping the map,
//   approve / reject what the daily news job found, edit or stop active risks.
// Security does NOT depend on this file: the database rules
// (supabase/schema.sql) only let admins change anything.
// The sign-in library is downloaded only when someone clicks "Admin".
// ============================================================
(function () {
  'use strict';

  var cfg = window.APP_CONFIG || {};
  var SB_LIB = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.js';
  var COLORS = { 1: '#f59e0b', 2: '#f97316', 3: '#dc2626' };

  var sb = null, rows = [], tab = 'new', current = null, point = null, city = 'all', cat = 'all';
  var marker = null, circle = null, pendingLayer = null;
  var svcRows = [], svcCurrent = null;
  var ICONS = ['🏥', '🚑', '💊', '🩺', '🚔', '🛡️', '🚓', '🚒', '🔥', '⛽', '🛢️', '🔧', '📞', '🏢'];
  var built = false;

  function $(id) { return document.getElementById(id); }
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]; }); }
  function safeUrl(u) { return /^https?:\/\//i.test(u || '') ? u : ''; }
  function show(el, on) {
    var node = typeof el === 'string' ? $(el) : el;
    node.classList.toggle('hidden', !on);
    if (node.id === 'apEditor' || node.id === 'svcEditor') syncSide();
  }
  // the editor lives in its own panel beside the list, so the list never moves
  function syncSide() {
    var side = $('adminSide');
    if (!side) return;
    var on = !$('apEditor').classList.contains('hidden') || !$('svcEditor').classList.contains('hidden');
    side.classList.toggle('hidden', !on);
    document.body.classList.toggle('admin-side-open', on);
  }
  function isoDate(d) { return d.toISOString().slice(0, 10); }
  function addDays(n) { return new Date(Date.now() + n * 86400000); }
  function say(msg, kind) {
    ['apMsg', 'sideMsg'].forEach(function (id) { var m = $(id); if (m) { m.className = 'ap-msg' + (kind ? ' ' + kind : ''); m.textContent = msg || ''; } });
  }

  // ---------- build the panel (once) ------------------------------------
  function build() {
    if (built) return;
    built = true;
    var el = document.createElement('section');
    el.id = 'adminPanel';
    el.className = 'admin-panel panel hidden';
    el.innerHTML =
      '<div class="heading"><b>Admin</b><button id="apClose" class="round" type="button" aria-label="Close">×</button></div>' +
      '<div id="apNotice" class="ap-msg hidden"></div>' +
      '<div id="apLogin" class="hidden">' +
        '<p class="ap-hint">Only emails added as admins can change risk areas.</p>' +
        '<label for="apEmail">Email</label><input id="apEmail" type="email" autocomplete="username">' +
        '<label for="apPass">Password</label><input id="apPass" type="password" autocomplete="current-password">' +
        '<button id="apSignIn" class="primary" type="button">Sign in</button>' +
      '</div>' +
      '<div id="apMain" class="hidden">' +
        '<div class="ap-user"><small id="apWho"></small><button id="apOut" class="small" type="button">Sign out</button></div>' +
        '<div class="mode-tabs" id="apTabs">' +
          '<button data-t="new" class="active">+ Risk</button>' +
          '<button data-t="pending">Review <span id="apCP"></span></button>' +
          '<button data-t="active">Active <span id="apCA"></span></button>' +
          '<button data-t="svc">Services</button>' +
        '</div>' +
        '<div id="apCities" class="city-tabs hidden"></div>' +
        '<div id="apCats" class="city-tabs cat-tabs hidden"></div>' +
        '<div id="apList"></div>' +
        '<div id="svcBox" class="hidden">' +
          '<button id="svcNew" class="btn blue" type="button">+ Add an emergency service</button>' +
          '<input id="svcFind" type="search" placeholder="Search by name…" style="margin-top:8px">' +
          '<div id="svcList"></div>' +
        '</div>' +
      '</div>' +
      '<div id="apMsg" class="ap-msg"></div>';
    document.body.appendChild(el);

    var side = document.createElement('section');
    side.id = 'adminSide';
    side.className = 'admin-side panel hidden';
    side.innerHTML =
      '<div class="heading"><b id="sideTitle">Details</b><button id="sideClose" class="round" type="button" aria-label="Close details">×</button></div>' +
        '<div id="apEditor" class="ap-editor hidden">' +
          '<b id="apEdTitle">Edit</b>' +
          '<label for="fTitle">What happened, and where</label><input id="fTitle" maxlength="200" placeholder="e.g. Hijack gang active at night near Madhabdi">' +
          '<div class="ap-row"><div><label for="fType">Type</label><select id="fType"><option value="accident">Accident</option><option value="violence">Violence / crime</option><option value="other">Other</option></select></div>' +
          '<div><label for="fSev">Severity</label><select id="fSev"><option value="1">1 – low</option><option value="2" selected>2 – medium</option><option value="3">3 – high</option></select></div></div>' +
          '<div class="ap-row"><div><label for="fRadius">Radius (metres)</label><input id="fRadius" type="number" min="200" max="20000" step="100" value="2000"></div>' +
          '<div><label for="fExpires">Stops counting on</label><input id="fExpires" type="date"></div></div>' +
          '<label for="fHappened">Date it happened</label><input id="fHappened" type="date">' +
          '<div class="ap-hint">📍 <span id="fLoc">Tap the map to choose the place (drag the pin to adjust)</span></div>' +
          '<div class="ap-hint" id="fSource"></div>' +
          '<div class="ap-hint ap-orig" id="fOrig"></div>' +
          '<div class="ap-actions" id="apActions"></div>' +
        '</div>' +
          '<div id="svcEditor" class="ap-editor hidden">' +
            '<b id="svcEdTitle">Service</b>' +
            '<label for="sName">Name</label><input id="sName" maxlength="150" placeholder="e.g. Narsingdi Sadar Hospital">' +
            '<div class="ap-row"><div><label for="sType">Type</label><select id="sType"><option value="hospital">Hospital</option><option value="police">Police</option><option value="fire">Fire station</option><option value="fuel">Fuel station</option></select></div>' +
            '<div><label for="sIcon">Icon</label><select id="sIcon"></select></div></div>' +
            '<label for="sPhone">Phone (optional)</label><input id="sPhone" type="tel" maxlength="30" placeholder="e.g. 01712345678">' +
            '<div class="ap-hint">📍 <span id="sLoc">Tap the map to choose the place (drag the pin to adjust)</span></div>' +
            '<div class="ap-actions" id="svcActions"></div>' +
          '</div>' +
      '<div id="sideMsg" class="ap-msg"></div>';
    document.body.appendChild(side);
    $('sideClose').onclick = closeSide;

    $('apClose').onclick = close;
    $('apSignIn').onclick = signIn;
    $('apPass').addEventListener('keydown', function (e) { if (e.key === 'Enter') signIn(); });
    $('apOut').onclick = function () { sb.auth.signOut().then(function () { resetEditor(); $('adminBtn').textContent = '🔒 Admin'; showLogin(); }); };
    $('apTabs').querySelectorAll('button').forEach(function (b) { b.onclick = function () { setTab(b.dataset.t); }; });
    ['fSev', 'fRadius'].forEach(function (id) { $(id).addEventListener('input', drawCircle); });
    $('sIcon').innerHTML = '<option value="">Default for the type</option>' + ICONS.map(function (i) { return '<option value="' + i + '">' + i + '</option>'; }).join('');
    $('svcNew').onclick = newService;
    $('svcFind').addEventListener('input', renderServices);
    map.on('click', function (e) {
      if ($('adminPanel').classList.contains('hidden')) return;
      if ((tab === 'svc' && svcCurrent) || current) setPoint([e.latlng.lat, e.latlng.lng]);
    });
  }

  // × on the side panel: back to the list
  function closeSide() {
    current = null; svcCurrent = null;
    show('apEditor', false); show('svcEditor', false);
    clearEditorMap(); say('');
    renderList(); renderServices(); drawPending();
  }

  function scrollToSelected(box) {
    var sel = box && box.querySelector('.ap-item.sel');
    if (sel && sel.scrollIntoView) sel.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  // ---------- open / close / sign in ---------------------------------------
  function loadLib() {
    if (window.supabase) return Promise.resolve();
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = SB_LIB; s.onload = resolve;
      s.onerror = function () { reject(new Error('Could not load the sign-in tool. Check your internet connection.')); };
      document.head.appendChild(s);
    });
  }

  function open() {
    build();
    show('adminPanel', true);
    document.body.classList.add('admin-open');
    if (!cfg.SUPABASE_URL || !cfg.SUPABASE_ANON_KEY) {
      show('apLogin', false); show('apMain', false);
      var n = $('apNotice'); n.textContent = 'The risk database is not connected yet. Fill in js/config.js first.'; n.className = 'ap-msg err'; return;
    }
    say('Loading…');
    loadLib().then(function () {
      sb = sb || window.supabase.createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY);
      if (cfg.ADMIN_OPEN) return enterOpen();            // TEST MODE: no sign-in (see js/config.js)
      return sb.auth.getSession();
    }).then(function (r) {
      if (cfg.ADMIN_OPEN) return;
      var session = r.data && r.data.session;
      if (!session) { say(''); showLogin(); return; }
      return enterIfAdmin(session);
    }).catch(function (e) { say(e.message, 'err'); });
  }

  function close() {
    show('adminPanel', false);
    document.body.classList.remove('admin-open');
    resetEditor();
  }

  function showLogin() { show('apMain', false); show('apLogin', true); }

  function signIn() {
    say('Signing in…');
    sb.auth.signInWithPassword({ email: $('apEmail').value.trim(), password: $('apPass').value }).then(function (r) {
      if (r.error) { say(r.error.message, 'err'); return; }
      $('apPass').value = '';
      return enterIfAdmin(r.data.session);
    });
  }

  // TEST MODE (ADMIN_OPEN in js/config.js): no sign-in. Works only while the database is also opened
  // (supabase/open_admin_for_testing.sql). To lock again: ADMIN_OPEN=false and run supabase/lock_admin.sql.
  function enterOpen() {
    say('');
    $('apWho').textContent = '⚠️ Open test mode — no sign-in. Anyone with this link can change data.';
    $('apOut').classList.add('hidden');
    show('apLogin', false); show('apMain', true);
    setTab(tab);
    return loadRows();
  }

  function enterIfAdmin(session) {
    return sb.rpc('is_admin').then(function (res) {
      if (res.data !== true) {
        return sb.auth.signOut().then(function () {
          showLogin();
          say(session.user.email + ' is not an admin. Ask the owner to add this email.', 'err');
        });
      }
      say('');
      $('apWho').textContent = session.user.email;
      $('adminBtn').textContent = '🔓 Admin';
      show('apLogin', false); show('apMain', true);
      setTab(tab);
      loadRows();
    });
  }

  // ---------- map helpers -------------------------------------------------------
  function setPoint(p, pan) {
    point = p;
    $('fLoc').textContent = $('sLoc').textContent = p[0].toFixed(5) + ', ' + p[1].toFixed(5);
    if (!marker) {
      marker = L.marker(p, { draggable: true, zIndexOffset: 2000 }).addTo(map);
      marker.on('dragend', function () { var ll = marker.getLatLng(); setPoint([ll.lat, ll.lng]); });
    } else marker.setLatLng(p);
    drawCircle();
    if (pan) map.setView(p, Math.max(map.getZoom(), 11));
  }

  function drawCircle() {
    if (circle) { map.removeLayer(circle); circle = null; }
    if (!point || tab === 'svc') return;
    var c = COLORS[$('fSev').value] || COLORS[2];
    circle = L.circle(point, { radius: parseInt($('fRadius').value, 10) || 2000, color: c, weight: 2, fillColor: c, fillOpacity: 0.3, interactive: false }).addTo(map);
  }

  function clearEditorMap() {
    if (marker) { map.removeLayer(marker); marker = null; }
    if (circle) { map.removeLayer(circle); circle = null; }
    point = null;
  }

  function drawPending() {
    if (!pendingLayer) pendingLayer = L.layerGroup().addTo(map);
    pendingLayer.clearLayers();
    if (tab === 'svc') {                                   // show every service so you can see what is missing
      svcRows.forEach(function (r) {
        L.circleMarker([r.lat, r.lng], { radius: 7, color: '#fff', weight: 2, fillColor: '#1769aa', fillOpacity: 1 })
          .on('click', function () { editService(r); }).bindTooltip(r.name).addTo(pendingLayer);
      });
      return;
    }
    if (tab !== 'pending' && tab !== 'active') return;
    tabRows().filter(itemOk).forEach(function (r) {
      var fill = tab === 'pending' ? '#f79009' : (COLORS[r.severity] || COLORS[2]);
      L.circleMarker([r.lat, r.lng], { radius: 9, color: '#fff', weight: 2, fillColor: fill, fillOpacity: 1 })
        .on('click', function () { edit(r); }).bindTooltip((tab === 'pending' ? 'Pending: ' : '') + r.title).addTo(pendingLayer);
    });
  }

  // ---------- data -------------------------------------------------------------------
  function isActive(r) { return r.status === 'approved' && (!r.expires_at || Date.parse(r.expires_at) > Date.now()); }

  // ---------- city filter tabs ------------------------------------------------------------
  // The city is worked out from the map position, so it also works for rows saved before this existed.
  var CITIES = [['Dhaka', 23.78, 90.40, 22], ['Gazipur', 23.99, 90.42, 18], ['Narayanganj', 23.62, 90.50, 15], ['Narsingdi', 23.92, 90.72, 20],
                ['Brahmanbaria', 23.96, 91.11, 30], ['Cumilla', 23.46, 91.18, 20], ['Sylhet', 24.90, 91.87, 30], ['Chattogram', 22.34, 91.83, 30]];
  function kmBetween(a, b, c, d) {
    var x = (c - a) * 111, y = (d - b) * 111 * Math.cos(a * Math.PI / 180);
    return Math.sqrt(x * x + y * y);
  }
  function cityOf(r) {
    var best = 'Other', bd = 1e9;
    CITIES.forEach(function (c) { var d = kmBetween(r.lat, r.lng, c[1], c[2]); if (d <= c[3] && d < bd) { bd = d; best = c[0]; } });
    return best;
  }
  function cityOk(r) { return city === 'all' || cityOf(r) === city; }

  // ---------- incident type tabs ------------------------------------------------------------
  // Worked out from the headline (and the Bangla original), so it also covers rows saved earlier.
  var CATS = [
    ['accident', 'Road accident', /accident|crash|collision|collid|run over|ran over|hit-and-run|overturn|rammed|mowed|দুর্ঘটনা|চাপা/i],
    ['robbery', 'Robbery / theft', /robb|hijack|mugg|dacoit|bandit|extort|theft|stole|snatch|loot|ছিনতাই|ডাকাতি|চাঁদাবাজি/i],
    ['arson', 'Arson / torched', /set fire|set on fire|torch|arson|ablaze|burn|vandali|আগুন|অগ্নিসংযোগ|ভাঙচুর/i],
    ['bomb', 'Bomb / blast', /bomb|cocktail|blast|explosion|explod|crude|ককটেল|বোমা|বিস্ফোরণ/i],
    ['blockade', 'Blockade / strike', /blockad|block|hartal|strike|barricad|road ?block|congestion|ultimatum|অবরোধ|হরতাল|ধর্মঘট/i],
    ['political', 'Political', /politic|\bBNP\b|Awami|Jamaat|\bleague\b|rally|procession|activists|clash|party|election|supporters|student|\bmob\b|রাজনৈতিক|সংঘর্ষ|মিছিল/i],
    ['killed', 'Killed', /killed|\bdead\b|\bdie[sd]?\b|death|shot dead|stabbed|murder|body found|নিহত|মৃত্যু|খুন/i]
  ];
  function catsOf(r) {
    var t = (r.title || '') + ' ' + (r.title_original || ''), out = [];
    CATS.forEach(function (c) { if (c[2].test(t)) out.push(c[0]); });
    if (!out.length) out.push('other');
    return out;
  }
  function catName(k) { for (var i = 0; i < CATS.length; i++) if (CATS[i][0] === k) return CATS[i][1]; return 'Other'; }
  function catOk(r) { return cat === 'all' || catsOf(r).indexOf(cat) > -1; }
  function itemOk(r) { return cityOk(r) && catOk(r); }
  function tabRows() { return rows.filter(function (r) { return tab === 'pending' ? r.status === 'pending' : isActive(r); }); }
  function renderCities() {
    var box = $('apCities');
    if (tab !== 'pending' && tab !== 'active') { box.classList.add('hidden'); return; }
    var all = tabRows(), counts = {};
    all.forEach(function (r) { var c = cityOf(r); counts[c] = (counts[c] || 0) + 1; });
    if (city !== 'all' && !counts[city]) city = 'all';
    var names = CITIES.map(function (c) { return c[0]; }).concat(['Other']).filter(function (n) { return counts[n]; });
    if (names.length < 2) { box.classList.add('hidden'); city = 'all'; return; }      // nothing to filter
    box.classList.remove('hidden');
    box.innerHTML = [['all', 'All', all.length]].concat(names.map(function (n) { return [n, n, counts[n]]; })).map(function (t) {
      return '<button type="button" class="city-tab' + (city === t[0] ? ' active' : '') + '" data-c="' + esc(t[0]) + '">' + esc(t[1]) + ' <i>' + t[2] + '</i></button>';
    }).join('');
    box.querySelectorAll('button').forEach(function (b) {
      b.onclick = function () {
        city = b.dataset.c; closeSide();                      // closeSide re-renders the list and the markers
        var pts = tabRows().filter(itemOk).map(function (r) { return [r.lat, r.lng]; });
        if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.3), { maxZoom: 13 });
      };
    });
  }

  function renderCats() {
    var box = $('apCats');
    if (tab !== 'pending' && tab !== 'active') { box.classList.add('hidden'); return; }
    var base = tabRows().filter(cityOk), counts = {};      // counts follow the city you picked
    base.forEach(function (r) { catsOf(r).forEach(function (k) { counts[k] = (counts[k] || 0) + 1; }); });
    if (cat !== 'all' && !counts[cat]) cat = 'all';
    var keys = CATS.map(function (c) { return c[0]; }).concat(['other']).filter(function (k) { return counts[k]; });
    if (!keys.length) { box.classList.add('hidden'); return; }
    box.classList.remove('hidden');
    box.innerHTML = [['all', 'All types', base.length]].concat(keys.map(function (k) { return [k, catName(k), counts[k]]; })).map(function (t) {
      return '<button type="button" class="city-tab' + (cat === t[0] ? ' active' : '') + '" data-k="' + esc(t[0]) + '">' + esc(t[1]) + ' <i>' + t[2] + '</i></button>';
    }).join('');
    box.querySelectorAll('button').forEach(function (b) {
      b.onclick = function () {
        cat = b.dataset.k; closeSide();
        var pts = tabRows().filter(itemOk).map(function (r) { return [r.lat, r.lng]; });
        if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.3), { maxZoom: 13 });
      };
    });
  }

  function loadRows() {
    return sb.from('risk_areas').select('*').order('created_at', { ascending: false }).limit(500).then(function (r) {
      if (r.error) { say(r.error.message, 'err'); return; }
      rows = r.data || [];
      $('apCP').textContent = '(' + rows.filter(function (x) { return x.status === 'pending'; }).length + ')';
      $('apCA').textContent = '(' + rows.filter(isActive).length + ')';
      renderList();
      drawPending();
      translateBangla();
    });
  }

  // ---------- Bangla -> English titles ----------------------------------------------------
  // Old rows (and any the daily job could not translate) are translated here, once, and saved
  // back so the next load is instant. Uses the free MyMemory service; nothing is sent but the headline.
  var BN = /[\u0980-\u09FF]/, translating = false;
  function mm(text) {
    return fetch('https://api.mymemory.translated.net/get?q=' + encodeURIComponent(text) + '&langpair=bn|en')
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var t = j && j.responseData && j.responseData.translatedText;
        if (!t || String(j.responseStatus) !== '200' || /MYMEMORY/i.test(t) || BN.test(t) || t === text) return null;
        return t.replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, '&');
      }).catch(function () { return null; });
  }
  function translateTitle(title) {
    var m = /^([^:]{2,40}: )?(.*?)( - ([^-]{2,60}))?$/.exec(title);
    var place = m[1] || '', head = m[2], outlet = m[4] || '';
    return mm(head).then(function (h) {
      if (!h) return null;
      if (!outlet || !BN.test(outlet)) return place + h + (outlet ? ' - ' + outlet : '');
      return mm(outlet).then(function (o) { return place + h + ' - ' + (o || outlet.replace(BN, '').trim() || 'news'); });
    });
  }
  function translateBangla() {
    if (translating || !sb) return;
    var todo = rows.filter(function (r) { return r.title && BN.test(r.title) && !r.title_original; }).slice(0, 40);
    if (!todo.length) return;
    translating = true;
    var chain = Promise.resolve(), changed = 0;
    todo.forEach(function (r) {
      chain = chain.then(function () { return translateTitle(r.title); }).then(function (en) {
        if (!en) return;
        var orig = r.title;
        r.title = en; r.title_original = orig; changed++;
        if ($('fTitle') && current && current.id === r.id) { $('fTitle').value = en; $('fOrig').textContent = 'Original headline: ' + orig; }
        renderList();
        return sb.from('risk_areas').update({ title: en, title_original: orig }).eq('id', r.id);
      });
    });
    chain.then(function () { translating = false; if (todo.length && !changed) say('Could not translate right now (free service busy). Titles stay in Bangla; try again later.', 'err'); },
               function () { translating = false; });
  }

  function renderList() {
    var box = $('apList');
    renderCities();
    renderCats();
    if (tab === 'svc') { box.innerHTML = ''; return; }
    if (tab === 'new') {
      box.innerHTML = '<button id="apNewBtn" class="btn blue" type="button">+ Add a risk area</button>' +
        '<div class="ap-empty">Fill in the form that opens beside this panel, then tap the map to place it.</div>';
      $('apNewBtn').onclick = newManual;
      return;
    }
    var items = tabRows().filter(itemOk);
    if (!items.length) { box.innerHTML = '<div class="ap-empty">' + (tab === 'pending' ? 'Nothing waiting for approval.' : 'No active risk areas.') + '</div>'; return; }
    box.innerHTML = items.map(function (r) {
      var src = safeUrl(r.source_url);
      return '<div class="ap-item' + (current && current.id === r.id ? ' sel' : '') + '" data-id="' + esc(r.id) + '">' +
        '<span class="pill ' + esc(r.source) + '">' + esc(r.source) + '</span><span class="pill">' + esc(r.type) + ' · sev ' + esc(r.severity) + '</span>' +
        catsOf(r).slice(0, 3).map(function (k) { return '<span class="pill cat">' + esc(catName(k)) + '</span>'; }).join('') +
        '<div class="ap-titlerow"><b>' + esc(r.title) + '</b>' +
        (src ? '<a class="ap-link" href="' + esc(src) + '" target="_blank" rel="noopener noreferrer" title="Open the news report">↗ news</a>' : '') + '</div>' +
        '<small>' + (r.place_text ? 'Matched place: ' + esc(r.place_text) + ' · ' : '') + esc((r.happened_on || r.created_at || '').slice(0, 10)) + '</small>' +
        (r.title_original ? '<small class="ap-orig">Original: ' + esc(r.title_original) + '</small>' : '') + '</div>';
    }).join('');
    box.querySelectorAll('.ap-item').forEach(function (el) {
      el.onclick = function (ev) {
        if (ev.target.closest('a')) return;                       // the news link opens the news, not the editor
        edit(rows.filter(function (r) { return r.id === el.dataset.id; })[0]);
      };
    });
    scrollToSelected(box);
  }

  // ---------- editor ---------------------------------------------------------------------
  function fill(r) {
    $('fTitle').value = r.title || '';
    $('fType').value = r.type || 'accident';
    $('fSev').value = String(r.severity || 2);
    $('fRadius').value = r.radius_m || 2000;
    $('fHappened').value = r.happened_on || '';
    $('fExpires').value = r.expires_at ? r.expires_at.slice(0, 10) : '';
    var src = safeUrl(r.source_url);
    $('fSource').innerHTML = src ? 'Source: <a href="' + esc(src) + '" target="_blank" rel="noopener noreferrer">open the news report</a> — check the place before approving.' : '';
    $('fOrig').textContent = r.title_original ? 'Original headline: ' + r.title_original : '';
    say('');
  }

  function buttons(list) {
    var box = $('apActions');
    box.innerHTML = list.map(function (b) { return '<button class="btn ' + b[1] + '" data-act="' + b[0] + '" type="button">' + b[2] + '</button>'; }).join('');
    box.querySelectorAll('button').forEach(function (b) { b.onclick = function () { act(b.dataset.act); }; });
  }

  function edit(r) {
    current = r; show('apEditor', true);
    $('sideTitle').textContent = $('apEdTitle').textContent = r.status === 'pending' ? 'Review this report' : 'Edit active risk';
    fill(r); clearEditorMap(); setPoint([r.lat, r.lng], true);
    buttons(r.status === 'pending'
      ? [['approve', 'ok', 'Approve'], ['reject', 'bad', 'Reject']]
      : [['save', 'blue', 'Save changes'], ['expire', '', 'Stop counting now'], ['delete', 'bad', 'Delete']]);
    renderList();
  }

  function newManual() {
    current = {}; show('apEditor', true);
    $('sideTitle').textContent = $('apEdTitle').textContent = 'Add a risk area';
    fill({ severity: 2, radius_m: 2000, happened_on: isoDate(new Date()), expires_at: addDays(90).toISOString() });
    clearEditorMap();
    buttons([['create', 'ok', 'Add (goes live now)']]);
    say('Tap the map to place it.');
  }

  function resetEditor() {
    current = null; svcCurrent = null;
    if ($('apEditor')) show('apEditor', false);
    if ($('svcEditor')) svcEditing(false);
    if (built) clearEditorMap();
    if (pendingLayer) pendingLayer.clearLayers();
  }

  function setTab(t) {
    tab = t;
    $('apTabs').querySelectorAll('button').forEach(function (b) { b.classList.toggle('active', b.dataset.t === t); });
    current = null; svcCurrent = null; show('apEditor', false); svcEditing(false); clearEditorMap();
    show('svcBox', t === 'svc');
    if (t === 'svc') { say(''); loadServices(); }
    renderList(); drawPending();
  }

  function readForm() {
    var title = $('fTitle').value.trim();
    if (!title) throw new Error('Please write what happened.');
    if (!point) throw new Error('Please tap the map to choose the place.');
    var radius = parseInt($('fRadius').value, 10);
    if (!(radius >= 200 && radius <= 20000)) throw new Error('Radius must be between 200 and 20000 metres.');
    return {
      title: title, type: $('fType').value, severity: parseInt($('fSev').value, 10),
      lat: point[0], lng: point[1], radius_m: radius,
      happened_on: $('fHappened').value || null,
      expires_at: $('fExpires').value ? new Date($('fExpires').value + 'T23:59:59').toISOString() : null
    };
  }

  function act(name) {
    var q, f;
    try {
      if (name === 'approve') { f = readForm(); if (!f.expires_at) f.expires_at = addDays(30).toISOString(); f.status = 'approved'; q = sb.from('risk_areas').update(f).eq('id', current.id); }
      else if (name === 'save') { f = readForm(); q = sb.from('risk_areas').update(f).eq('id', current.id); }
      else if (name === 'reject') q = sb.from('risk_areas').update({ status: 'rejected' }).eq('id', current.id);   // kept, so the news job never re-adds it
      else if (name === 'expire') q = sb.from('risk_areas').update({ expires_at: new Date().toISOString() }).eq('id', current.id);
      else if (name === 'delete') { if (!confirm('Delete this risk area permanently?')) return; q = sb.from('risk_areas').delete().eq('id', current.id); }
      else if (name === 'create') { f = readForm(); if (!f.expires_at) f.expires_at = addDays(90).toISOString(); f.source = 'manual'; f.status = 'approved'; q = sb.from('risk_areas').insert(f); }
    } catch (e) { say(e.message, 'err'); return; }

    say('Saving…');
    q.then(function (r) {
      if (r.error) { say(r.error.message, 'err'); return; }
      var wasNew = name === 'create';
      current = null; show('apEditor', false); clearEditorMap();
      loadRows().then(function () { say('Saved ✓', 'good'); });
      if (window.PlannerAPI) window.PlannerAPI.reloadRisks();   // the public map updates at once
    });
  }


  // ---------- emergency services ---------------------------------------------------------------
  var TYPE_NAME = { hospital: 'Hospital', police: 'Police', fire: 'Fire station', fuel: 'Fuel station' };
  var DEFAULT_ICON = { hospital: '🏥', police: '🚔', fire: '🚒', fuel: '⛽' };

  function loadServices() {
    return sb.from('emergency_services').select('*').order('name', { ascending: true }).limit(2000).then(function (r) {
      if (r.error) { say(r.error.message, 'err'); return; }
      svcRows = r.data || [];
      renderServices(); drawPending();
    });
  }

  function renderServices() {
    var box = $('svcList'), q = $('svcFind').value.trim().toLowerCase();
    var items = svcRows.filter(function (r) { return !q || r.name.toLowerCase().indexOf(q) > -1 || r.type.indexOf(q) > -1; });
    if (!items.length) { box.innerHTML = '<div class="ap-empty">No services found.</div>'; return; }
    box.innerHTML = items.map(function (r) {
      return '<div class="ap-item' + (svcCurrent && svcCurrent.id === r.id ? ' sel' : '') + '" data-id="' + esc(r.id) + '">' +
        '<span class="pill">' + esc(TYPE_NAME[r.type] || r.type) + '</span> <b>' + esc((r.icon || DEFAULT_ICON[r.type] || '') + ' ' + r.name) + '</b>' +
        '<small>' + (r.phone ? esc(r.phone) : 'no phone saved') + '</small></div>';
    }).join('');
    box.querySelectorAll('.ap-item').forEach(function (el) {
      el.onclick = function () { editService(svcRows.filter(function (r) { return r.id === el.dataset.id; })[0]); };
    });
    scrollToSelected(box);
  }

  function svcButtons(list) {
    var b = $('svcActions');
    b.innerHTML = list.map(function (x) { return '<button class="btn ' + x[1] + '" data-act="' + x[0] + '" type="button">' + x[2] + '</button>'; }).join('');
    b.querySelectorAll('button').forEach(function (btn) { btn.onclick = function () { svcAct(btn.dataset.act); }; });
  }

  function fillService(r) {
    $('sName').value = r.name || ''; $('sType').value = r.type || 'hospital';
    $('sIcon').value = r.icon || ''; $('sPhone').value = r.phone || '';
    $('sLoc').textContent = r.lat ? r.lat.toFixed(5) + ', ' + r.lng.toFixed(5) : 'Tap the map to choose the place (drag the pin to adjust)';
  }

  function svcEditing(on) { show('svcEditor', on); }

  function newService() {
    svcCurrent = {}; svcEditing(true); $('sideTitle').textContent = $('svcEdTitle').textContent = 'Add an emergency service';
    fillService({}); clearEditorMap(); renderServices();
    svcButtons([['create', 'ok', 'Add service'], ['cancel', '', 'Cancel']]);
    say('Tap the map where it is.');
  }

  function editService(r) {
    svcCurrent = r; svcEditing(true); $('sideTitle').textContent = $('svcEdTitle').textContent = 'Edit service';
    fillService(r); clearEditorMap(); setPoint([r.lat, r.lng], true); renderServices();
    svcButtons([['save', 'blue', 'Save changes'], ['cancel', '', 'Cancel'], ['delete', 'bad', 'Delete']]);
    say('');
  }

  function readService() {
    var name = $('sName').value.trim();
    if (name.length < 2) throw new Error('Please type the name.');
    if (!point) throw new Error('Please tap the map to choose the place.');
    var phone = $('sPhone').value.trim();
    if (phone && !/^[+\d][\d\s\-()]{2,28}$/.test(phone)) throw new Error('Phone can only have digits, spaces, + - ( ).');
    return { name: name, type: $('sType').value, icon: $('sIcon').value || null, phone: phone || null, lat: point[0], lng: point[1] };
  }

  function svcAct(name) {
    var q, f;
    if (name === 'cancel') { svcCurrent = null; svcEditing(false); clearEditorMap(); say(''); renderServices(); return; }
    try {
      if (name === 'create') { f = readService(); q = sb.from('emergency_services').insert(f); }
      else if (name === 'save') { f = readService(); q = sb.from('emergency_services').update(f).eq('id', svcCurrent.id); }
      else if (name === 'delete') { if (!confirm('Delete "' + svcCurrent.name + '" permanently?')) return; q = sb.from('emergency_services').delete().eq('id', svcCurrent.id); }
    } catch (e) { say(e.message, 'err'); return; }
    say('Saving…');
    q.then(function (r) {
      if (r.error) { say(r.error.message, 'err'); return; }
      var wasNew = name === 'create';
      svcCurrent = null; svcEditing(false); clearEditorMap();
      loadServices().then(function () { say('Saved ✓', 'good'); });
      if (window.ServiceStore) window.ServiceStore.reload();      // the public map updates at once
    });
  }

  // ---------- start ---------------------------------------------------------------------------
  function hasStoredSession() {
    try { for (var i = 0; i < localStorage.length; i++) { var k = localStorage.key(i); if (/^sb-.*-auth-token$/.test(k)) return true; } } catch (e) { /* storage blocked */ }
    return false;
  }

  document.addEventListener('DOMContentLoaded', function () {
    var btn = $('adminBtn');
    if (!btn) return;
    if (hasStoredSession() || cfg.ADMIN_OPEN) btn.textContent = '🔓 Admin';
    btn.onclick = function () {
      var p = $('adminPanel');
      if (p && !p.classList.contains('hidden')) close(); else open();
    };
  });
})();
