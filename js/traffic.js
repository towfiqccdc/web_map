// ============================================================
// Live traffic button.
//  - If js/config.js has TRAFFIC_TILE_URL (e.g. a TomTom key): shows a live traffic
//    layer ON this map, refreshed every 2 minutes.
//  - If not: the button opens Google Maps with its traffic layer, centred on
//    whatever you are looking at (no key and no terms-of-service problem).
// ============================================================
(function () {
  'use strict';

  var cfg = window.APP_CONFIG || {};
  var layer = null, timer = null, on = false;
  var REFRESH_MS = 120000;

  function $(id) { return document.getElementById(id); }

  function withStamp(url) {
    return url + (url.indexOf('?') > -1 ? '&' : '?') + 't=' + Date.now();   // defeats the browser cache so tiles are fresh
  }

  function googleTrafficUrl() {
    var c = map.getCenter(), z = Math.min(map.getZoom(), 17);
    return 'https://www.google.com/maps/@' + c.lat.toFixed(5) + ',' + c.lng.toFixed(5) + ',' + z + 'z/data=!5m1!1e1';
  }

  function setOn(v) {
    on = v;
    $('trafficBtn').classList.toggle('on', on);
    $('trafficBtn').setAttribute('aria-pressed', String(on));
    $('trafficLegend').classList.toggle('hidden', !on);
    if (on) {
      layer = layer || L.tileLayer(withStamp(cfg.TRAFFIC_TILE_URL), { maxZoom: 18, opacity: 0.9, zIndex: 450, attribution: cfg.TRAFFIC_ATTRIBUTION || '' });
      layer.addTo(map);
      timer = setInterval(function () { layer.setUrl(withStamp(cfg.TRAFFIC_TILE_URL)); }, REFRESH_MS);
    } else {
      if (layer) map.removeLayer(layer);
      clearInterval(timer);
    }
  }

  function start() {
    var btn = $('trafficBtn');
    if (!cfg.TRAFFIC_TILE_URL) {
      btn.textContent = 'Traffic ↗';
      btn.title = 'Opens Google Maps with live traffic for this area';
      btn.onclick = function () { window.open(googleTrafficUrl(), '_blank', 'noopener'); };
      return;
    }
    btn.title = 'Show or hide live traffic';
    btn.onclick = function () { setOn(!on); };
  }

  document.addEventListener('DOMContentLoaded', start);
})();
