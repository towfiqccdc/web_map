// Run with:  node tests/routesafety.test.js
const assert = require('assert');
const RS = require('../js/routesafety.js');

const NOW = Date.parse('2026-11-17T00:00:00Z');
// Two straight "roads" west->east: A along lat 23.80, B along lat 23.90 (~11 km north)
const roadA = [[23.80, 90.40], [23.80, 90.50], [23.80, 90.60]];
const roadB = [[23.80, 90.40], [23.90, 90.50], [23.80, 90.60]];

// 1. distance maths
assert(Math.abs(RS.haversineM([23.8, 90.4], [23.9, 90.4]) - 11120) < 60, 'haversine ~11.1 km per 0.1 deg lat');
assert(RS.distPointToPolylineM([23.8, 90.45], roadA) < 1, 'point on line = 0 m');
const d = RS.distPointToPolylineM([23.81, 90.50], roadA);       // 0.01 deg north of road A
assert(Math.abs(d - 1112) < 20, 'point 0.01 deg off the line ~1.1 km, got ' + d);
const far = RS.distPointToPolylineM([23.8, 90.9], roadA);   // 0.3 deg east of the road's end = ~30.5 km
assert(far > 30000 && far < 31000, 'point beyond the segment end measures to the end point, got ' + far);

// 2. a risk that sits on road A only
const risk = { id: 'r1', title: 'Crash', type: 'accident', severity: 3, lat: 23.80, lng: 90.50, radius_m: 1000, happened_on: '2026-11-16' };
const sA = RS.scoreRoute(roadA, [risk], 300, NOW);
const sB = RS.scoreRoute(roadB, [risk], 300, NOW);
assert.strictEqual(sA.hits.length, 1); assert.strictEqual(sA.score, 3); assert.strictEqual(sA.level, 'caution');
assert.strictEqual(sB.hits.length, 0); assert.strictEqual(sB.score, 0); assert.strictEqual(sB.level, 'clear');

// 3. recency: same risk, 40 days old, counts 0.4x
const old = Object.assign({}, risk, { happened_on: '2026-10-08' });
assert.strictEqual(RS.scoreRoute(roadA, [old], 300, NOW).score, 1.2);
// 3 days old = full weight; 20 days = 0.7x
assert.strictEqual(RS.scoreRoute(roadA, [Object.assign({}, risk, { happened_on: '2026-11-14' })], 300, NOW).score, 3);
assert.strictEqual(RS.scoreRoute(roadA, [Object.assign({}, risk, { happened_on: '2026-10-28' })], 300, NOW).score, 2.1);

// 4. levels
assert.strictEqual(RS.levelFor(0), 'clear'); assert.strictEqual(RS.levelFor(3), 'caution'); assert.strictEqual(RS.levelFor(3.1), 'high');

// 5. ranking: A is shorter/faster but has the risk; B is longer but clear -> B is safest, A fastest
const ranked = RS.rankRoutes([
  { coords: roadA, distance: 20000, duration: 1500 },
  { coords: roadB, distance: 26000, duration: 1900 }
], [risk], 300, NOW);
assert.strictEqual(ranked[0].distance, 26000); assert(ranked[0].isSafest && !ranked[0].isFastest);
assert(ranked[1].isFastest && !ranked[1].isSafest);
// no risks at all -> safest is the fastest one
const r2 = RS.rankRoutes([{ coords: roadB, distance: 26000, duration: 1900 }, { coords: roadA, distance: 20000, duration: 1500 }], [], 300, NOW);
assert.strictEqual(r2[0].duration, 1500); assert(r2[0].isSafest && r2[0].isFastest);

// 6. a risk whose radius is too small to reach the road is ignored; bad data is skipped
assert.strictEqual(RS.scoreRoute(roadA, [Object.assign({}, risk, { lat: 23.85, radius_m: 500 })], 300, NOW).hits.length, 0);
assert.strictEqual(RS.scoreRoute(roadA, [{ title: 'bad', lat: 'x', lng: null }], 300, NOW).hits.length, 0);

// 7. static markers: accident+crime become risks, military is ignored
const st = RS.fromStaticLocations([{ id: 'a', type: 'accident', name: 'A', lat: 1, lng: 2 }, { id: 'c', type: 'crime', name: 'C', lat: 1, lng: 2 }, { id: 'm', type: 'military', name: 'M', lat: 1, lng: 2 }, { id: 'h', type: 'hospital', name: 'H', lat: 1, lng: 2 }]);
assert.deepStrictEqual(st.map(x => x.type), ['accident', 'violence']);

console.log('all routesafety tests passed');
