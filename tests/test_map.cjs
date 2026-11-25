// Both dispatch views must stay on the painted road network as stations and roads change.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname,'../app/static/map.js'),'utf8');
const model = vm.runInNewContext(source+';({stations,roadGraph,routeEdges,pathOf,mapTerrain,networkMap})');
assert.equal(Object.keys(model.stations).length,10);
const terrain = model.mapTerrain();
for (const pair of ['AB','BA','CD','DC','AC']) {
  for (const viaHub of [false,true]) {
    const edges = model.routeEdges(pair[0],pair[1],viaHub);
    let current = pair[0];
    for (const edge of edges) {
      assert(model.roadGraph.get(current).includes(edge));
      const reverse = model.pathOf([...edge.coords].reverse());
      assert(terrain.includes(model.pathOf(edge.coords)) || terrain.includes(reverse));
      current = edge.to;
    }
    assert.equal(current,pair[1]);
    if (viaHub) assert(edges.some(edge=>edge.to==='HUB'));
  }
  const svg=model.networkMap(pair[0],pair[1],'HUB');
  assert.equal((svg.match(/data-point=/g)||[]).length,10);
  assert(!/undefined|NaN/.test(svg));
}
console.log('PASS: ten locations and all five directional lanes on shared road geometry.');
