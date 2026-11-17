// ============================================================
// "Safe journey" planner: From -> To, shows which route has the
// fewest reported risks. Runs after js/app.js (uses its `map`,
// `userLocation`, `esc`, `PROJECT_ROUTES`, `RISK_LOCATIONS`).
// ============================================================
(function () {
  'use strict';

  var cfg = window.APP_CONFIG || {};
  var RS = window.RouteSafety;
  var riskState = { risks: [], state: 'loading' };
  var fromCoord = null;               // set when "use my location" is chosen
  var routeLayers = [];               // polylines currently on the map
  var ranked = [];                    // scored routes from the last search
  var selected = 0;
  var liveLayer;

  var LEVEL = {
    clear:   { color: '#16a34a', text: 'No reported incidents' },
    caution: { color: '#d97706', text: 'Some reported risk' },
    high:    { color: '#dc2626', text: 'High reported risk' }
  };
  var TYPE_ICON = { accident: '⚠️', violence: '🚨', other: '❗' };
  var SEV_COLOR = { 1: '#f59e0b', 2: '#f97316', 3: '#dc2626' };

  function $(id) { return document.getElementById(id); }
  function safeUrl(u) { return /^https?:\/\//i.test(u || '') ? u : ''; }

  function ageText(r) {
    var when = r.happened_on || r.created_at;
    var t = Date.parse(when || '');
    if (isNaN(t)) return '';
    var d = Math.floor((Date.now() - t) / 86400000);
    return d <= 0 ? 'today' : d === 1 ? '1 day ago' : d + ' days ago';
  }

  function fmtDuration(sec) {
    var m = Math.round(sec / 60);
    return m < 60 ? m + ' min' : Math.floor(m / 60) + ' h ' + (m % 60) + ' min';
  }

  // ---------- risk areas on the map --------------------------------
  function drawRiskAreas() {
    liveLayer.clearLayers();
    riskState.risks.forEach(function (r) {
      var c = SEV_COLOR[r.severity] || SEV_COLOR[2];
      var circle = L.circle([r.lat, r.lng], { radius: r.radius_m || 1000, color: c, weight: 2, fillColor: c, fillOpacity: 0.28 });
      var link = safeUrl(r.source_url);
      circle.bindPopup(
        '<b>' + (TYPE_ICON[r.type] || '❗') + ' ' + esc(r.title) + '</b>' +
        '<div style="font-size:11px;color:#667085">' + esc(r.type) + ' · severity ' + esc(r.severity) +
        (ageText(r) ? ' · ' + esc(ageText(r)) : '') + '</div>' +
        (link ? '<p style="font-size:12px"><a href="' + esc(link) + '" target="_blank" rel="noopener noreferrer">Read the news report</a></p>' : '')
      );
      liveLayer.addLayer(circle);
    });
  }

  function dataNotice() {
    var s = riskState.state;
    if (s === 'live') return '';
    if (s === 'cached') return 'Offline: using risk data saved ' + new Date(riskState.savedAt).toLocaleString() + '.';
    if (s === 'not-configured') return 'Live risk database is not connected yet — using the built-in markers only.';
    if (s === 'error') return 'Could not load live risk data — using the built-in markers only.';
    return 'Loading risk data…';
  }

  function allRisks() {
    return riskState.risks.concat(RS.fromStaticLocations(window.RISK_LOCATIONS || []));
  }

  // ---------- place search -----------------------------------------
  function parseLatLng(text) {
    var m = /^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$/.exec(text);
    if (!m) return null;
    var a = parseFloat(m[1]), b = parseFloat(m[2]);
    return (a >= 20.5 && a <= 26.7 && b >= 88 && b <= 92.8) ? [a, b] : null;
  }

  function geocode(text) {
    var direct = parseLatLng(text);
    if (direct) return Promise.resolve({ coord: direct, name: direct[0].toFixed(4) + ', ' + direct[1].toFixed(4) });
    var url = cfg.GEOCODER_URL + '?format=jsonv2&limit=1&countrycodes=bd&accept-language=en&q=' + encodeURIComponent(text);
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error('Place search failed (' + r.status + ')');
      return r.json();
    }).then(function (rows) {
      if (!rows.length) throw new Error('Could not find "' + text + '" in Bangladesh. Try a bigger nearby town.');
      return { coord: [parseFloat(rows[0].lat), parseFloat(rows[0].lon)], name: rows[0].display_name.split(',').slice(0, 2).join(',') };
    });
  }

  function resolveEnd(inputId, override) {
    var text = $(inputId).value.trim();
    if (override) return Promise.resolve({ coord: override, name: 'My location' });
    if (!text) return Promise.reject(new Error('Please enter both From and To.'));
    return geocode(text);
  }

  // ---------- routing ------------------------------------------------
  function fetchRoutes(a, b) {
    var url = cfg.ROUTING_URL + '/' + a[1] + ',' + a[0] + ';' + b[1] + ',' + b[0] +
      '?alternatives=true&overview=full&geometries=geojson&steps=false';
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error('Routing service error (' + r.status + ')');
      return r.json();
    }).then(function (j) {
      if (!j.routes || !j.routes.length) throw new Error('No driving route found between these places.');
      return j.routes.map(function (r) {
        return { coords: r.geometry.coordinates.map(function (p) { return [p[1], p[0]]; }), distance: r.distance, duration: r.duration };
      });
    });
  }

  // ---------- drawing the result -------------------------------------
  function clearRoutes() {
    routeLayers.forEach(function (l) { map.removeLayer(l); });
    routeLayers = [];
  }

  function drawRoutes() {
    clearRoutes();
    ranked.forEach(function (r, i) {
      if (i === selected) return;
      routeLayers.push(L.polyline(r.coords, { color: '#f2f4f7', weight: 5, opacity: 0.85, dashArray: '8 8' }).addTo(map)
        .on('click', function () { selected = i; drawRoutes(); renderResults(); }));
    });
    var best = ranked[selected];
    if (best) {
      routeLayers.push(L.polyline(best.coords, { color: '#ffffff', weight: 13, opacity: 0.95 }).addTo(map));          // outline
      routeLayers.push(L.polyline(best.coords, { color: LEVEL[best.level].color, weight: 8, opacity: 1 }).addTo(map));
    }
    if (routeLayers.length) map.fitBounds(L.featureGroup(routeLayers).getBounds(), { padding: [40, 40] });
  }

  function renderResults() {
    var box = $('journeyResults');
    var html = ranked.map(function (r, i) {
      var lv = LEVEL[r.level];
      var badges = (r.isSafest ? '<span class="badge good">Lowest risk</span>' : '') + (r.isFastest ? '<span class="badge">Fastest</span>' : '');
      var hits = r.hits.slice(0, 3).map(function (h) {
        return '<li>' + (TYPE_ICON[h.risk.type] || '❗') + ' ' + esc(h.risk.title) +
          (ageText(h.risk) ? ' <small>(' + esc(ageText(h.risk)) + ')</small>' : '') + '</li>';
      }).join('');
      var more = r.hits.length > 3 ? '<li><small>+ ' + (r.hits.length - 3) + ' more</small></li>' : '';
      return '<article class="route-card' + (i === selected ? ' selected' : '') + '" data-i="' + i + '">' +
        '<div class="rc-top"><b style="color:' + lv.color + '">● ' + lv.text + '</b>' + badges + '</div>' +
        '<div class="meta"><span>' + (r.distance / 1000).toFixed(1) + ' km</span><span>' + fmtDuration(r.duration) + '</span><span>' + r.hits.length + ' reported risk' + (r.hits.length === 1 ? '' : 's') + '</span></div>' +
        (r.hits.length ? '<ul class="rc-hits">' + hits + more + '</ul>' : '') +
        '</article>';
    }).join('');
    var note = dataNotice();
    box.innerHTML = '<div class="rc-clear"><button id="clearJourney" class="small" type="button">✕ Clear route</button></div>' + html +
      (note ? '<p class="journey-note warn">' + esc(note) + '</p>' : '') +
      '<p class="journey-note">Based on approved reports only. “No reported incidents” is not a guarantee of safety — stay alert and follow official advice.</p>';
    $('clearJourney').onclick = clearJourney;
    box.querySelectorAll('.route-card').forEach(function (el) {
      el.onclick = function () { selected = parseInt(el.dataset.i, 10); drawRoutes(); renderResults(); };
    });
  }

  // Back to the normal map (also brings the "Nearby emergency services" box back)
  function clearJourney() {
    clearRoutes();
    ranked = [];
    $('journeyResults').innerHTML = '';
    setStatus('');
    document.body.classList.remove('journey-active');
  }

  function setStatus(msg, isError) {
    var s = $('journeyStatus');
    s.textContent = msg || '';
    s.className = 'journey-status' + (isError ? ' error' : '');
  }

  function planJourney() {
    var btn = $('planBtn');
    btn.disabled = true;
    setStatus('Finding routes…');
    $('journeyResults').innerHTML = '';
    clearRoutes();

    Promise.all([resolveEnd('fromInput', fromCoord), resolveEnd('toInput', null)])
      .then(function (ends) {
        return fetchRoutes(ends[0].coord, ends[1].coord).then(function (routes) {
          ranked = RS.rankRoutes(routes, allRisks(), cfg.ROUTE_BUFFER_M, Date.now());
          selected = 0;
          setStatus(ends[0].name + '  →  ' + ends[1].name);
          document.body.classList.add('journey-active');
          drawRoutes();
          renderResults();
        });
      })
      .catch(function (e) { setStatus(e.message || 'Something went wrong.', true); })
      .then(function () { btn.disabled = false; });
  }

  // ---------- wiring ---------------------------------------------------
  function setMode(mode) {
    document.querySelectorAll('.mode-tabs button').forEach(function (b) { b.classList.toggle('active', b.dataset.mode === mode); });
    $('modeJourney').classList.toggle('hidden', mode !== 'journey');
    $('modeProject').classList.toggle('hidden', mode !== 'project');
  }

  function start() {
    liveLayer = L.layerGroup().addTo(map);
    layers.live = liveLayer;            // lets the "Layers" checkbox control it

    document.querySelectorAll('.mode-tabs button').forEach(function (b) { b.onclick = function () { setMode(b.dataset.mode); }; });

    // phones: the planner starts folded to one bar so the map stays visible
    var panel = document.querySelector('.route-panel'), tog = $('rpToggle');
    function fold(on) { panel.classList.toggle('rp-collapsed', on); tog.setAttribute('aria-expanded', String(!on)); }
    tog.onclick = function () { fold(!panel.classList.contains('rp-collapsed')); };
    if (window.matchMedia('(max-width:700px)').matches) fold(true);
    $('planBtn').onclick = planJourney;
    ['fromInput', 'toInput'].forEach(function (id) {
      $(id).addEventListener('keydown', function (e) { if (e.key === 'Enter') planJourney(); });
    });
    $('fromInput').addEventListener('input', function () { fromCoord = null; });
    $('useMyLoc').onclick = function () {
      if (!userLocation) { setStatus('Your location is not available yet — allow location access.', true); return; }
      fromCoord = userLocation.slice();
      $('fromInput').value = 'My location';
      setStatus('');
    };

    window.PlannerAPI = { reloadRisks: reloadRisks };
    reloadRisks();
  }

  function reloadRisks() {
    return RiskStore.loadRisks().then(function (res) {
      riskState = res;
      drawRiskAreas();
      if (ranked.length) { ranked = RS.rankRoutes(ranked, allRisks(), cfg.ROUTE_BUFFER_M, Date.now()); selected = 0; drawRoutes(); renderResults(); }
    });
  }

  document.addEventListener('DOMContentLoaded', start);
})();
