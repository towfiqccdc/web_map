// ============================================================
// Emergency services (hospital / police / fire / fuel).
//  * Loads the list from the database (admins edit it in 🔒 Admin → Services);
//    falls back to the last saved copy, then to js/data.js.
//  * The map does NOT show them all. Hospitals, police and the built-in risk spots (blackspots, crime-prone, military) appear only when YOU are within
//    a few km of them (zoom does not matter). Fire and fuel appear only when you pick
//    them in the "Nearby help" panel. Travel away and the pins change with you.
// Uses globals from app.js: map, layers, markers, ICON, LABEL, icon(), esc(), dist().
// ============================================================
(function () {
  'use strict';

  var cfg = window.APP_CONFIG || {};
  var CACHE_KEY = 'emergency_services_cache_v1';
  var COLUMNS = 'id,type,name,lat,lng,phone,icon';
  var TYPES = ['hospital', 'police', 'fire', 'fuel'];
  var RISK_TYPES = ['accident', 'crime', 'military'];
  var NEAR_KM = 5;                             // hospital / police / risk pins appear when you are this close (straight line)
  var PICKED_COUNT = 3;                        // fire / fuel: the nearest few, only while chosen in the Nearby help panel
  var MOVE_M = 50;                             // re-check when you have moved this far

  function safePhone(p) { return /^[+\d][\d\s\-()]{2,28}$/.test(p || '') ? String(p).replace(/[^\d+]/g, '') : ''; }
  function iconOf(x) { return x.icon || ICON[x.type]; }
  window.serviceIcon = iconOf;

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

  // Pins depend only on WHERE YOU ARE (not on zoom or where you pan the map):
  //  - hospital / police within NEAR_KM of you are drawn; farther ones disappear
  //  - fire / fuel are drawn only while chosen in "Nearby help" (nearest few)
  function update() {
    if (typeof map === 'undefined' || typeof layers === 'undefined') return;
    TYPES.concat(RISK_TYPES).forEach(function (t) { layers[t].clearLayers(); });
    if (!userLocation) return;
    RISK_LOCATIONS.forEach(function (x) {                 // blackspots, crime-prone and military areas: same rule
      if (markers[x.id] && layers[x.type] && dist(userLocation, [x.lat, x.lng]) <= NEAR_KM) layers[x.type].addLayer(markers[x.id]);
    });
    var picked = window.nearbyPickedType && window.nearbyPickedType();
    TYPES.forEach(function (t) {
      var always = t === 'hospital' || t === 'police';
      if (!always && picked !== t) return;
      EMERGENCY_SERVICES
        .filter(function (x) { return x.type === t; })
        .map(function (x) { return { x: x, d: dist(userLocation, [x.lat, x.lng]) }; })
        .filter(function (r) { return !always || r.d <= NEAR_KM; })
        .sort(function (a, b) { return a.d - b.d; })
        .slice(0, always ? 20 : PICKED_COUNT)
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

  // follow the person while they travel, so pins and the Nearby list stay current
  function track() {
    if (!navigator.geolocation) return;
    navigator.geolocation.watchPosition(function (p) {
      if (window.userPicked) return;                     // they set the spot by hand: respect that
      var ll = [p.coords.latitude, p.coords.longitude], acc = p.coords.accuracy || 0;
      var moved = userLocation ? dist(userLocation, ll) * 1000 : Infinity;
      // a vaguer fix for the same place (e.g. Wi-Fi/IP guess after a GPS fix) must not replace a better one
      if (userLocation && userAccuracy && acc > userAccuracy * 1.5 && moved <= acc) return;   // our good fix lies inside the vague circle
      if (userLocation && moved < MOVE_M && acc >= (userAccuracy || Infinity)) return;
      setUserLocation(ll, null, acc);                     // moves the blue dot, does not move the map
      locStatus(acc);
      if (window.renderList) window.renderList();         // also redraws the pins
    }, function () { /* location off: nothing to do */ }, { enableHighAccuracy: true, maximumAge: 0, timeout: 30000 });
  }

  document.addEventListener('DOMContentLoaded', function () {
    buildMarkers();                       // built-in list first, so the map works at once
    update();
    reload();
    track();
  });
})();
