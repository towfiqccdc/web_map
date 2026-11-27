// ============================================================
// Loads the APPROVED risk areas from Supabase (read-only, public key).
// If the network is down it falls back to the last copy saved in
// the browser, so the planner still works with weak signal.
// ============================================================
(function (root) {
  'use strict';

  var CACHE_KEY = 'risk_areas_cache_v1';
  var COLUMNS = 'id,title,type,severity,lat,lng,radius_m,source,source_url,place_text,happened_on,created_at,expires_at,also_in';

  function readCache() {
    try {
      var c = JSON.parse(localStorage.getItem(CACHE_KEY) || 'null');
      return c && Array.isArray(c.risks) ? c : null;
    } catch (e) { return null; }
  }

  function writeCache(risks) {
    try { localStorage.setItem(CACHE_KEY, JSON.stringify({ savedAt: Date.now(), risks: risks })); } catch (e) { /* storage blocked: fine */ }
  }

  // Resolves to { risks, state, savedAt }
  //   state: 'live' | 'cached' | 'not-configured' | 'error'
  function loadRisks() {
    var cfg = root.APP_CONFIG || {};
    if (!cfg.SUPABASE_URL || !cfg.SUPABASE_ANON_KEY) {
      return Promise.resolve({ risks: [], state: 'not-configured' });
    }
    var url = cfg.SUPABASE_URL.replace(/\/+$/, '') + '/rest/v1/risk_areas' +
      '?select=' + COLUMNS + '&status=eq.approved&order=created_at.desc&limit=1000';

    return fetch(url, {
      headers: { apikey: cfg.SUPABASE_ANON_KEY, Authorization: 'Bearer ' + cfg.SUPABASE_ANON_KEY }
    }).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    }).then(function (rows) {
      var now = Date.now();
      // The database already hides expired rows; this is a second safety net.
      var risks = rows.filter(function (r) { return !r.expires_at || Date.parse(r.expires_at) > now; });
      writeCache(risks);
      return { risks: risks, state: 'live', savedAt: now };
    }).catch(function () {
      var c = readCache();
      if (c) return { risks: c.risks, state: 'cached', savedAt: c.savedAt };
      return { risks: [], state: 'error' };
    });
  }

  root.RiskStore = { loadRisks: loadRisks };
})(window);
