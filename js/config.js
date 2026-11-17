// ============================================================
// SETTINGS — the only file you need to edit to connect the map
// to your Supabase database.
//
// Both values come from: Supabase dashboard -> Project Settings -> API
//   SUPABASE_URL      "Project URL"
//   SUPABASE_ANON_KEY "anon public" key
//
// The anon key is MEANT to be public (it is visible in any website).
// It can only read approved risk areas — see supabase/schema.sql.
// NEVER paste the "service_role" key here.
// ============================================================
window.APP_CONFIG = {
  SUPABASE_URL: "",       // e.g. "https://abcdxyz.supabase.co"
  SUPABASE_ANON_KEY: "",  // e.g. "eyJhbGciOi..."

  // Routing service. The free public OSRM demo is fine for testing but has
  // no guarantee; for real use, host your own or use a paid/keyed provider
  // that speaks the same OSRM API.
  ROUTING_URL: "https://router.project-osrm.org/route/v1/driving",

  // Place search (free OpenStreetMap service; do not hammer it)
  GEOCODER_URL: "https://nominatim.openstreetmap.org/search",

  // How far from the route line (metres) a risk area still counts
  ROUTE_BUFFER_M: 300
};
