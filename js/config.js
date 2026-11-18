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
  SUPABASE_URL: "https://qftuuhanfemsbjihzaeu.supabase.co",
  SUPABASE_ANON_KEY: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFmdHV1aGFuZmVtc2JqaWh6YWV1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTQ4ODM1NjUsImV4cCI6MjExMDQ1OTU2NX0.zmfWYbouN6XH1RudynF8jaHAaNLtxwLzbJYu0TIIm-I",

  // Routing service. The free public OSRM demo is fine for testing but has
  // no guarantee; for real use, host your own or use a paid/keyed provider
  // that speaks the same OSRM API.
  ROUTING_URL: "https://router.project-osrm.org/route/v1/driving",

  // LIVE TRAFFIC overlay (optional). Leave empty and the Traffic button simply opens
  // Google Maps with its traffic layer. For an in-map layer, get a free key at
  // developer.tomtom.com and paste a tile address like this (replace YOUR_KEY):
  //   "https://api.tomtom.com/traffic/map/4/tile/flow/relative0/{z}/{x}/{y}.png?key=YOUR_KEY"
  // (Check TomTom's "Raster Flow Tiles" page for the current address and for coverage.)
  TRAFFIC_TILE_URL: "",
  TRAFFIC_ATTRIBUTION: "Traffic © TomTom",

  // TEST MODE: true = the 🔒 Admin panel opens with no sign-in. Anyone with the site link can then add,
  // change or delete risk areas and emergency services (the database was opened for testing too).
  // Before real use: set this to false AND run supabase/lock_admin.sql.
  ADMIN_OPEN: true,

  // Place search (free OpenStreetMap service; do not hammer it)
  GEOCODER_URL: "https://nominatim.openstreetmap.org/search",

  // How far from the route line (metres) a risk area still counts
  ROUTE_BUFFER_M: 300
};
