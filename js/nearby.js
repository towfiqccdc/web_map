// ============================================================
// "Nearby help" panel.
//   Collapsed: one tap-able button per service showing the nearest one
//              (🏥 Hospital 2.3 km), plus a permanent "Call 999" button.
//   Tap a button: the closest few of that type, each with Route / Navigate
//              (and Call, if you add a "phone" to that place in data.js).
// Uses globals from app.js: map, userLocation, markers, EMERGENCY_SERVICES,
// ICON, LABEL, nearest(), routeTo(), setUserLocation(), locateUser(), esc().
// ============================================================
(function () {
  'use strict';

  var ROAD_FACTOR = 1.3;     // straight line -> rough road distance
  var SPEED_KMH = 35;        // rough average speed
  var expanded = false, showAll = false, picking = false;

  function $(id) { return document.getElementById(id); }

  function estimate(straightKm) {
    var km = straightKm * ROAD_FACTOR;
    return { km: km, min: Math.max(1, Math.round(km / SPEED_KMH * 60)) };
  }
  function fmtKm(km) { return (km < 10 ? km.toFixed(1) : String(Math.round(km))) + ' km'; }
  function fmtMin(m) { return m < 60 ? m + ' min' : Math.floor(m / 60) + ' h ' + (m % 60) + ' min'; }
  function safePhone(p) { return /^[+\d][\d\s\-()]{2,20}$/.test(p || '') ? p.replace(/[^\d+]/g, '') : ''; }

  function card(x) {
    var e = estimate(x.d);
    var phone = safePhone(x.phone);
    return '<article class="svc" data-id="' + esc(x.id) + '">' +
      '<div class="svc-ico t-' + esc(x.type) + '">' + ICON[x.type] + '</div>' +
      '<div class="svc-main"><b>' + esc(x.name) + '</b>' +
      '<small>' + esc(LABEL[x.type]) + ' · ≈ ' + fmtKm(e.km) + ' · ~' + fmtMin(e.min) + '</small></div>' +
      '<div class="svc-act">' +
      '<button type="button" class="go" data-act="route" data-id="' + esc(x.id) + '">Route</button>' +
      '<a class="nav" target="_blank" rel="noopener noreferrer" href="https://www.google.com/maps/dir/?api=1&destination=' + x.lat + ',' + x.lng + '">Navigate</a>' +
      (phone ? '<a class="tel" href="tel:' + phone + '">Call</a>' : '') +
      '</div></article>';
  }

  function updateQuick() {
    document.querySelectorAll('#nbQuick button').forEach(function (b) {
      var t = b.dataset.type, d = b.querySelector('.q-dist');
      var n = userLocation ? nearest([t])[0] : null;
      d.textContent = n ? fmtKm(estimate(n.d).km) : '–';
      b.classList.toggle('active', expanded && currentFilter === t);
    });
  }

  // (re)draws everything in the panel; app.js calls this after the location changes
  window.renderList = function () {
    var has = !!userLocation;
    $('nbLocate').classList.toggle('hidden', has);
    $('nbQuick').classList.toggle('hidden', !has);
    $('nbList').classList.toggle('hidden', !has || !expanded);
    $('nbToggle').setAttribute('aria-expanded', String(has && expanded));
    $('nbToggle').textContent = has && expanded ? '▼' : '▲';
    $('nearby').classList.toggle('open', has && expanded);
    document.body.classList.toggle('nb-open', has && expanded);
    updateQuick();
    if (!has || !expanded) return;

    var all = currentFilter === 'all' ? nearest() : nearest([currentFilter]);
    var shown = all.slice(0, showAll ? 10 : 3);
    $('serviceList').innerHTML = shown.length ? shown.map(card).join('') : '<p class="nb-empty">Nothing of this kind is listed yet.</p>';
    $('nbMore').classList.toggle('hidden', all.length <= 3);
    $('nbMore').textContent = showAll ? 'Show fewer' : 'Show more (' + Math.min(10, all.length) + ')';
  };

  function open(type) {
    if (expanded && currentFilter === type) { expanded = false; }
    else { expanded = true; currentFilter = type; showAll = false; }
    renderList();
  }

  function start() {
    document.querySelectorAll('#nbQuick button').forEach(function (b) { b.onclick = function () { open(b.dataset.type); }; });
    $('nbToggle').onclick = function () { expanded = !expanded; if (expanded && !currentFilter) currentFilter = 'all'; renderList(); };
    $('nbHead').querySelector('.nb-title').onclick = function () { $('nbToggle').click(); };
    $('nbMore').onclick = function () { showAll = !showAll; renderList(); };
    $('nbRefresh').onclick = locateUser;

    $('serviceList').addEventListener('click', function (ev) {
      var btn = ev.target.closest('[data-act="route"]');
      if (btn) { routeTo(btn.dataset.id); return; }
      if (ev.target.closest('a')) return;                 // Navigate / Call links work normally
      var c = ev.target.closest('.svc');
      if (!c) return;
      var s = EMERGENCY_SERVICES.filter(function (x) { return x.id === c.dataset.id; })[0];
      if (s) { map.setView([s.lat, s.lng], 15); if (markers[s.id]) markers[s.id].openPopup(); }
    });

    // "tap the map to say where you are" — for phones with location switched off
    $('pickLocBtn').onclick = function () {
      picking = true;
      $('locationStatus').textContent = 'Tap the map where you are';
      $('pickLocBtn').textContent = 'Waiting for your tap on the map…';
    };
    map.on('click', function (e) {
      if (!picking) return;
      picking = false;
      $('pickLocBtn').textContent = 'Or tap the map to set where you are';
      setUserLocation([e.latlng.lat, e.latlng.lng], null);
      $('locationStatus').textContent = 'Using the spot you tapped';
      renderList();
    });

    // the old (default) filter was 'all' — start on the most important one
    currentFilter = 'hospital';
    renderList();
  }

  document.addEventListener('DOMContentLoaded', start);
})();
