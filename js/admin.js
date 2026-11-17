// ============================================================
// Admin page: approve / reject risk areas found in the news,
// and add your own by clicking on the map.
// Security does NOT depend on this file: the database rules
// (supabase/schema.sql) only let admins change anything.
// ============================================================
(function () {
  'use strict';

  var cfg = window.APP_CONFIG || {};
  function $(id) { return document.getElementById(id); }
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]; }); }
  function safeUrl(u) { return /^https?:\/\//i.test(u || '') ? u : ''; }
  function show(id, on) { $(id).classList.toggle('hidden', !on); }
  function isoDate(d) { return d.toISOString().slice(0, 10); }
  function addDays(n) { return new Date(Date.now() + n * 86400000); }

  if (!cfg.SUPABASE_URL || !cfg.SUPABASE_ANON_KEY) { show('setup', true); return; }

  var sb = window.supabase.createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY);
  var map, marker, circle;
  var rows = [], tab = 'pending', current = null;   // current = row being edited, or {} for a new manual one
  var point = null;                                  // [lat, lng] of the editor marker

  var COLORS = { 1: '#f59e0b', 2: '#f97316', 3: '#dc2626' };

  // ---------- login ----------------------------------------------------
  function checkSession() {
    sb.auth.getSession().then(function (r) {
      var s = r.data && r.data.session;
      if (!s) { show('loginBox', true); show('app', false); return; }
      sb.rpc('is_admin').then(function (res) {
        if (res.data === true) { $('who').textContent = s.user.email; show('loginBox', false); show('app', true); startApp(); }
        else {
          sb.auth.signOut();
          show('app', false); show('loginBox', true);
          $('loginMsg').className = 'msg err';
          $('loginMsg').textContent = s.user.email + ' is not in the admins table.';
        }
      });
    });
  }

  $('loginBtn').onclick = function () {
    $('loginMsg').className = 'msg'; $('loginMsg').textContent = 'Signing in…';
    sb.auth.signInWithPassword({ email: $('email').value.trim(), password: $('password').value }).then(function (r) {
      if (r.error) { $('loginMsg').className = 'msg err'; $('loginMsg').textContent = r.error.message; return; }
      checkSession();
    });
  };
  $('password').addEventListener('keydown', function (e) { if (e.key === 'Enter') $('loginBtn').click(); });
  $('logoutBtn').onclick = function () { sb.auth.signOut().then(function () { location.reload(); }); };

  // ---------- map ------------------------------------------------------
  function initMap() {
    if (map) return;
    map = L.map('map').setView([23.9, 90.6], 8);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap contributors' }).addTo(map);
    map.on('click', function (e) { if (current) setPoint([e.latlng.lat, e.latlng.lng]); });
  }

  function setPoint(p, pan) {
    point = p;
    $('fLoc').textContent = p[0].toFixed(5) + ', ' + p[1].toFixed(5);
    if (!marker) {
      marker = L.marker(p, { draggable: true }).addTo(map);
      marker.on('dragend', function () { var ll = marker.getLatLng(); setPoint([ll.lat, ll.lng]); });
    } else marker.setLatLng(p);
    drawCircle();
    if (pan) map.setView(p, Math.max(map.getZoom(), 11));
  }

  function drawCircle() {
    if (circle) { map.removeLayer(circle); circle = null; }
    if (!point) return;
    var c = COLORS[$('fSev').value] || COLORS[2];
    circle = L.circle(point, { radius: parseInt($('fRadius').value, 10) || 2000, color: c, weight: 1, fillColor: c, fillOpacity: 0.18 }).addTo(map);
  }
  ['fSev', 'fRadius'].forEach(function (id) { $(id).addEventListener('input', drawCircle); });

  function clearEditorMap() {
    if (marker) { map.removeLayer(marker); marker = null; }
    if (circle) { map.removeLayer(circle); circle = null; }
    point = null;
  }

  // ---------- list -------------------------------------------------------
  function isActive(r) { return r.status === 'approved' && (!r.expires_at || Date.parse(r.expires_at) > Date.now()); }

  function load() {
    return sb.from('risk_areas').select('*').order('created_at', { ascending: false }).limit(500).then(function (r) {
      if (r.error) { $('list').innerHTML = '<div class="msg err">' + esc(r.error.message) + '</div>'; return; }
      rows = r.data || [];
      $('cPending').textContent = '(' + rows.filter(function (x) { return x.status === 'pending'; }).length + ')';
      $('cActive').textContent = '(' + rows.filter(isActive).length + ')';
      renderList();
    });
  }

  function renderList() {
    var box = $('list');
    if (tab === 'new') { box.innerHTML = '<div class="empty">Click the map to place the risk, then fill in the form below.</div>'; return; }
    var items = rows.filter(function (r) { return tab === 'pending' ? r.status === 'pending' : isActive(r); });
    if (!items.length) { box.innerHTML = '<div class="empty">' + (tab === 'pending' ? 'Nothing waiting for approval.' : 'No active risk areas.') + '</div>'; return; }
    box.innerHTML = items.map(function (r) {
      return '<div class="item' + (current && current.id === r.id ? ' sel' : '') + '" data-id="' + esc(r.id) + '">' +
        '<span class="pill ' + esc(r.source) + '">' + esc(r.source) + '</span><span class="pill">' + esc(r.type) + ' · sev ' + esc(r.severity) + '</span><br>' +
        '<b>' + esc(r.title) + '</b>' +
        '<small>' + (r.place_text ? 'Matched place: ' + esc(r.place_text) + ' · ' : '') + esc((r.happened_on || r.created_at || '').slice(0, 10)) + '</small></div>';
    }).join('');
    box.querySelectorAll('.item').forEach(function (el) {
      el.onclick = function () { edit(rows.filter(function (r) { return r.id === el.dataset.id; })[0]); };
    });
  }

  // ---------- editor -------------------------------------------------------
  function fill(r) {
    $('fTitle').value = r.title || '';
    $('fType').value = r.type || 'accident';
    $('fSev').value = String(r.severity || 2);
    $('fRadius').value = r.radius_m || 2000;
    $('fHappened').value = r.happened_on || '';
    $('fExpires').value = r.expires_at ? r.expires_at.slice(0, 10) : '';
    var src = safeUrl(r.source_url);
    $('fSource').innerHTML = src ? 'Source: <a href="' + esc(src) + '" target="_blank" rel="noopener noreferrer">open the news report</a> — check the location is right before approving.' : '';
    $('edMsg').textContent = ''; $('edMsg').className = 'msg';
  }

  function buttons(list) {
    $('edActions').innerHTML = list.map(function (b) { return '<button class="btn ' + b[1] + '" data-act="' + b[0] + '" type="button">' + b[2] + '</button>'; }).join('');
    $('edActions').querySelectorAll('button').forEach(function (b) { b.onclick = function () { act(b.dataset.act); }; });
  }

  function edit(r) {
    current = r; show('editor', true);
    $('edTitle').textContent = r.status === 'pending' ? 'Review this report' : 'Edit active risk';
    fill(r);
    clearEditorMap();
    setPoint([r.lat, r.lng], true);
    buttons(r.status === 'pending'
      ? [['approve', 'ok', 'Approve'], ['reject', 'bad', 'Reject']]
      : [['save', 'primary', 'Save changes'], ['expire', '', 'Stop counting now'], ['delete', 'bad', 'Delete']]);
    renderList();
  }

  function newManual() {
    current = {}; show('editor', true);
    $('edTitle').textContent = 'Add a risk area by hand';
    fill({ severity: 2, radius_m: 2000, happened_on: isoDate(new Date()), expires_at: addDays(90).toISOString() });
    clearEditorMap();
    buttons([['create', 'ok', 'Add (goes live immediately)']]);
    $('edMsg').textContent = 'Click the map to choose the location.';
    renderList();
  }

  function readForm() {
    var title = $('fTitle').value.trim();
    if (!title) throw new Error('Please write a title.');
    if (!point) throw new Error('Please click the map to choose the location.');
    var radius = parseInt($('fRadius').value, 10);
    if (!(radius >= 200 && radius <= 20000)) throw new Error('Radius must be between 200 and 20000 metres.');
    return {
      title: title, type: $('fType').value, severity: parseInt($('fSev').value, 10),
      lat: point[0], lng: point[1], radius_m: radius,
      happened_on: $('fHappened').value || null,
      expires_at: $('fExpires').value ? new Date($('fExpires').value + 'T23:59:59').toISOString() : null
    };
  }

  function say(msg, kind) { $('edMsg').className = 'msg' + (kind ? ' ' + kind : ''); $('edMsg').textContent = msg; }

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
      say('Done.', 'good');
      current = null; show('editor', false); clearEditorMap();
      if (tab === 'new') setTab('active'); else load();
    });
  }

  // ---------- tabs / start ---------------------------------------------------
  function setTab(t) {
    tab = t;
    document.querySelectorAll('#tabs button').forEach(function (b) { b.classList.toggle('active', b.dataset.tab === t); });
    current = null; show('editor', false); if (map) clearEditorMap();
    if (t === 'new') newManual(); else { load(); }
  }

  var started = false;
  function startApp() {
    if (started) return; started = true;
    initMap();
    document.querySelectorAll('#tabs button').forEach(function (b) { b.onclick = function () { setTab(b.dataset.tab); }; });
    setTab('pending');
    setTimeout(function () { map.invalidateSize(); }, 200);
  }

  checkSession();
})();
