// ============================================================
// Route safety scoring  (pure maths — no map, no network)
// Works in the browser (window.RouteSafety) and in Node (tests).
//
// A "risk" looks like:
//   { id, title, type, severity (1-3), lat, lng, radius_m, happened_on?, created_at? }
// A route is a list of [lat, lng] points.
// ============================================================
(function (root) {
  'use strict';

  var R = 6371000; // earth radius, metres
  var DEG = Math.PI / 180;

  function haversineM(a, b) {
    var dLat = (b[0] - a[0]) * DEG, dLon = (b[1] - a[1]) * DEG;
    var la1 = a[0] * DEG, la2 = b[0] * DEG;
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.sin(dLon / 2) * Math.sin(dLon / 2) * Math.cos(la1) * Math.cos(la2);
    return 2 * R * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
  }

  // Distance (m) from point p to the segment a-b. Uses a flat local projection,
  // which is accurate to well under a metre for segments this short.
  function distPointToSegmentM(p, a, b) {
    var cos = Math.cos(p[0] * DEG);
    var ax = (a[1] - p[1]) * DEG * R * cos, ay = (a[0] - p[0]) * DEG * R;
    var bx = (b[1] - p[1]) * DEG * R * cos, by = (b[0] - p[0]) * DEG * R;
    var dx = bx - ax, dy = by - ay;
    var len2 = dx * dx + dy * dy;
    var t = len2 === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2));
    var cx = ax + t * dx, cy = ay + t * dy;
    return Math.sqrt(cx * cx + cy * cy);
  }

  function distPointToPolylineM(p, line) {
    if (!line || line.length === 0) return Infinity;
    if (line.length === 1) return haversineM(p, line[0]);
    var best = Infinity;
    for (var i = 1; i < line.length; i++) {
      var d = distPointToSegmentM(p, line[i - 1], line[i]);
      if (d < best) best = d;
    }
    return best;
  }

  // Newer incidents matter more than old ones.
  function recencyWeight(risk, now) {
    var when = risk.happened_on || risk.created_at;
    if (!when) return 1;
    var t = Date.parse(when);
    if (isNaN(t)) return 1;
    var days = (now - t) / 86400000;
    if (days <= 7) return 1;
    if (days <= 30) return 0.7;
    return 0.4;
  }

  function levelFor(score) {
    if (score <= 0) return 'clear';
    if (score <= 3) return 'caution';
    return 'high';
  }

  // Score ONE route. Returns { score, level, hits:[{risk, distM, weight}] }
  function scoreRoute(line, risks, bufferM, now) {
    now = now || Date.now();
    bufferM = bufferM == null ? 300 : bufferM;
    var hits = [], score = 0;
    for (var i = 0; i < risks.length; i++) {
      var r = risks[i];
      if (typeof r.lat !== 'number' || typeof r.lng !== 'number') continue;
      var reach = (r.radius_m || 1000) + bufferM;
      var d = distPointToPolylineM([r.lat, r.lng], line);
      if (d <= reach) {
        var w = (r.severity || 2) * recencyWeight(r, now);
        score += w;
        hits.push({ risk: r, distM: d, weight: w });
      }
    }
    hits.sort(function (a, b) { return b.weight - a.weight; });
    score = Math.round(score * 10) / 10;
    return { score: score, level: levelFor(score), hits: hits };
  }

  // Score several candidate routes and label them.
  // routes: [{ coords:[[lat,lng],...], distance (m), duration (s) }]
  // Returns the same routes plus: score, level, hits, isSafest, isFastest — sorted safest first.
  function rankRoutes(routes, risks, bufferM, now) {
    var out = routes.map(function (r, i) {
      var s = scoreRoute(r.coords, risks, bufferM, now);
      return Object.assign({}, r, { index: i, score: s.score, level: s.level, hits: s.hits });
    });
    var fastest = out.reduce(function (a, b) { return b.duration < a.duration ? b : a; }, out[0]);
    out.sort(function (a, b) { return a.score - b.score || a.duration - b.duration; });
    out.forEach(function (r) { r.isSafest = r === out[0]; r.isFastest = r === fastest; });
    return out;
  }

  // The older hand-made markers in data.js become risks too.
  // Military areas are NOT dangerous to drive past, so they are skipped.
  function fromStaticLocations(list) {
    var out = [];
    (list || []).forEach(function (x) {
      if (x.type === 'accident') out.push({ id: x.id, title: x.name, type: 'accident', severity: 2, lat: x.lat, lng: x.lng, radius_m: 1000, details: x.details, source: 'manual' });
      else if (x.type === 'crime') out.push({ id: x.id, title: x.name, type: 'violence', severity: 2, lat: x.lat, lng: x.lng, radius_m: 1500, details: x.details, source: 'manual' });
    });
    return out;
  }

  var api = {
    haversineM: haversineM,
    distPointToSegmentM: distPointToSegmentM,
    distPointToPolylineM: distPointToPolylineM,
    recencyWeight: recencyWeight,
    levelFor: levelFor,
    scoreRoute: scoreRoute,
    rankRoutes: rankRoutes,
    fromStaticLocations: fromStaticLocations
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.RouteSafety = api;
})(typeof window !== 'undefined' ? window : globalThis);
