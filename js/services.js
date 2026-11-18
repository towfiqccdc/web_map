// ============================================================
// Emergency services (hospital / police / fire / fuel).
//  * Loads the list from the database (admins edit it in 🔒 Admin → Services);
//    falls back to the last saved copy, then to js/data.js.
//  * The map does NOT show them all. It shows only the few closest to the middle of
//    the screen, hospitals and police first. Fire and fuel appear only when you pick
//    them in the "Nearby help" panel. Move away and the pins change with you.
// Uses globals from app.js: map, layers, markers, ICON, LABEL, icon(), esc(), dist().
// ============================================================
(function () {
  'use strict';

  var cfg = window.APP_CONFIG || {};
  var CACHE_KEY = 'emergency_services_cache_v1';
  var COLUMNS = 'id,type,name,lat,lng,phone,icon';
  var TYPES = ['hospital', 'police', 'fire', 'fuel'];
  var SHOW = { hospital: 4, police: 4 };      // always-on types and how many to show
  var PICKED_COUNT = 5;                        // when fire/fuel is chosen in the panel
  var MIN_ZOOM = 11;                           // zoomed further out than this: no service pins at all

  function safePhone(p) { return /^[+\d][\d\s\-()]{2,28}$/.test(p || '') ? String(p).replace(/[^\d+]/g, '') : ''; }
  function iconOf(x) { return x.icon || ICON[x.type]; }
  window.serviceIcon = iconOf;

  function radiusKm(z) { return z >= 14 ? 4 : z >= 13 ? 8 : z >= 12 ? 15 : 25; }

  function popup(x) {
    var ph = safePhone(x.phone);
    return '<b>' + esc(iconOf(x)) + ' ' + esc(x.name) + '</b>' +
      '<div style="font-size:11px;color:#667085">' + esc(LABEL[x.type]) + '</div>' +
      '<p style="font-size:12px;margin:6px 0 0">' +
      (ph ? '<a href="tel:' + ph + '">📞 ' + esc(x.phone) + '</a> · ' : '') +
      '<a target="_blank" rel="noopener noreferrer" href="https://www.google.com/maps/dir/?api=1&destination=' + x.lat + ',' + x.lng + '">Navigate</a></p>';
  }

  function buildMarkers() {
    TYPES.forEach(function (t) { layers[t].clearLayers(); });
    Object.keys(markers).forEach(function (k) { if (markers[k] && markers[k]._isService) delete markers[k]; });
    EMERGENCY_SERVICES.forEach(function (x) {
      var m = L.marker([x.lat, x.lng], { icon: icon(x.type, false, x.icon) }).bindPopup(popup(x));
      m._isService = true; m._svc = x;
      markers[x.id] = m;
    });
  }

  // draw only what is close to the middle of the screen
  function update() {
    if (typeof map === 'undefined' || typeof layers === 'undefined') return;
    TYPES.forEach(function (t) { layers[t].clearLayers(); });
    var z = map.getZoom();
    if (z < MIN_ZOOM) return;
    var c = map.getCenter(), center = [c.lat, c.lng], limit = radiusKm(z);
    var want = {};
    Object.keys(SHOW).forEach(function (t) { want[t] = SHOW[t]; });
    var picked = window.nearbyPickedType && window.nearbyPickedType();
    if (picked && picked !== 'all') want[picked] = Math.max(want[picked] || 0, PICKED_COUNT);
    Object.keys(want).forEach(function (t) {
      EMERGENCY_SERVICES
        .filter(function (x) { return x.type === t; })
        .map(function (x) { return { x: x, d: dist(center, [x.lat, x.lng]) }; })
        .filter(function (r) { return r.d <= limit; })
        .sort(function (a, b) { return a.d - b.d; })
        .slice(0, want[t])
        .forEach(function (r) { if (markers[r.x.id]) layers[t].addLayer(markers[r.x.id]); });
    });
  }
  window.updateServiceMarkers = update;

  // zoom to one service from the list and open its card
  window.focusService = function (id) {
    var x = EMERGENCY_SERVICES.filter(function (s) { return s.id === id; })[0];
    if (!x) return;
    map.setView([x.lat, x.lng], 15);
    var openIt = function () { update(); var m = markers[id]; if (m && m._map) m.openPopup(); };
    openIt();
    map.once('moveend', openIt);
  };

  // ---------- loading --------------------------------------------------------
  function apply(rows) {
    var clean = rows.filter(function (r) { return TYPES.indexOf(r.type) > -1 && isFinite(r.lat) && isFinite(r.lng) && r.name; });
    EMERGENCY_SERVICES.length = 0;
    clean.forEach(function (r) { EMERGENCY_SERVICES.push({ id: String(r.id), type: r.type, name: r.name, lat: +r.lat, lng: +r.lng, phone: r.phone || '', icon: r.icon || '' }); });
    buildMarkers(); update();
    if (window.renderList) window.renderList();
  }

  function readCache() { try { var c = JSON.parse(localStorage.getItem(CACHE_KEY) || 'null'); return c && Array.isArray(c.rows) ? c.rows : null; } catch (e) { return null; } }
  function writeCache(rows) { try { localStorage.setItem(CACHE_KEY, JSON.stringify({ savedAt: Date.now(), rows: rows })); } catch (e) { /* storage blocked */ } }

  function reload() {
    if (!cfg.SUPABASE_URL || !cfg.SUPABASE_ANON_KEY) return Promise.resolve('not-configured');
    var url = cfg.SUPABASE_URL.replace(/\/+$/, '') + '/rest/v1/emergency_services?select=' + COLUMNS + '&order=name.asc&limit=2000';
    return fetch(url, { headers: { apikey: cfg.SUPABASE_ANON_KEY, Authorization: 'Bearer ' + cfg.SUPABASE_ANON_KEY } })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (rows) { writeCache(rows); apply(rows); return 'live'; })
      .catch(function () { var c = readCache(); if (c) { apply(c); return 'cached'; } return 'builtin'; });
  }
  window.ServiceStore = { reload: reload };

  document.addEventListener('DOMContentLoaded', function () {
    buildMarkers();                       // built-in list first, so the map works at once
    map.on('moveend', update);
    update();
    reload();
  });
})();
