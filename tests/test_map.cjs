// Both dispatch views must stay on the painted road network as stations and roads change.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname,'../app/static/map.js'),'utf8');
const truck = fs.readFileSync(path.join(__dirname,'../app/static/truck.js'),'utf8');
const network = JSON.parse(fs.readFileSync(path.join(__dirname,'../app/static/roads.json'),'utf8'));
const model = vm.runInNewContext(source+'\n'+truck+
  '\n;loadRoads(network);({stations,roadGraph,routeEdges,pathOf,mapTerrain,networkMap,planTruck,truckSample,moveMap,zoomMap,mapViewBox})',{network});
assert.equal(Object.keys(model.stations).length,10);
const terrain = model.mapTerrain();
const painted = coords => {
  const d = model.pathOf(coords);
  return terrain.includes(d) || terrain.includes('L'+d.slice(1));
};
for (const pair of ['AB','BA','CD','DC','AC']) {
  for (const viaHub of [false,true]) {
    const edges = model.routeEdges(pair[0],pair[1],viaHub);
    let current = pair[0];
    for (const edge of edges) {
      assert(model.roadGraph.get(current).includes(edge));
      assert(painted(edge.coords) || painted([...edge.coords].reverse()));
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
for(const start of Object.keys(model.stations)){
  for(const end of Object.keys(model.stations)){
    if(start===end)continue;
    const path=model.routeEdges(start,end);
    assert.equal(path[0].coords[0], model.stations[start]);
    assert.equal(path.at(-1).to,end);
    assert(path.every((edge,i)=>i===0||path[i-1].coords.at(-1)===edge.coords[0]));
  }
}
for(const [a,b] of [['northBank','northBridge'],['southBank','bridge']]){
  assert(terrain.includes(model.pathOf(model.roadGraph.get(a).find(e=>e.to===b).coords)));
}

const departure=Date.parse('2026-11-26T06:00:00Z');
const orders=model.truckSample(departure);
const config={start:'F',end:'K',departure,liters:24,grams:10000};
const plan=model.planTruck(orders,config);
assert.equal(plan.included.length,orders.length);
assert(plan.separateCost>0&&plan.extraCost>0&&plan.hubCost>0);
assert.equal(new Set(plan.stops.map(stop=>stop.id)).size,9);
assert.equal(plan.stops[0].id,'F');
assert.equal(plan.stops.at(-1).id,'K');
assert.equal(plan.stops.at(-1).orders,0);
assert.equal(plan.stops.at(-1).liters,0);
assert(!/undefined|NaN/.test(model.networkMap('A','B','SHARED_TRIP',plan)));
assert(plan.legs.every(leg=>leg.edges.map(edge=>edge.to).join()===model.routeEdges(leg.from,leg.to).map(edge=>edge.to).join()));
assert(plan.stops.some(stop=>stop.drop.length&&stop.pickup.length));
const onboard=new Set();
for(const stop of plan.stops){
  assert(stop.liters<=config.liters&&stop.grams<=config.grams);
  for(const order of stop.drop)assert(onboard.delete(order.id));
  for(const order of stop.pickup){assert(!onboard.has(order.id));onboard.add(order.id);}
  assert.equal(onboard.size,stop.orders);
}
const tight=model.planTruck(orders, {...config,liters:3,grams:900});
assert(tight.included.length>0&&tight.rejected.length>0);
assert(tight.peakLiters<=3&&tight.peakGrams<=900);
const late=model.planTruck([{...orders[0],due:departure+60000}],config);
assert.equal(late.included.length,0);
const round=model.planTruck([{...orders[0],from:'K',to:'F',due:departure+8*3600000}],{...config,end:'F'});
assert.equal(round.included.length,1);
assert.equal(round.stops.at(-1).drop.length,1);
const exchange=model.planTruck([orders[0],{...orders[1],from:'A',to:'B',liters:2,grams:600}],{...config,end:'B',liters:2,grams:600});
assert.equal(exchange.included.length,2);
assert(exchange.stops.some(stop=>stop.id==='A'&&stop.drop.length===1&&stop.pickup.length===1));
model.moveMap(0,0,1);
model.zoomMap(7,{x:300,y:250});
assert(Number(model.mapViewBox().split(' ')[2])<150);
model.moveMap(1e4,1e4);
let [x,y,w,h]=model.mapViewBox().split(' ').map(Number);
assert(x+w<=1040&&y+h<=510);
model.moveMap(0,0,1);
assert.equal(model.mapViewBox(),'0 0 1040 510');
console.log('PASS: all road connections; nine stops, deadlines, unload-before-load, capacity and zoom.');
