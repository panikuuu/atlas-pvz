'use strict';
const mapWidth=1040, mapHeight=510;
const stations={
  A:{x:150,y:215,letter:'А',title:'Центр',area:'Город'},
  B:{x:352,y:121,letter:'Б',title:'Университет',area:'Город'},
  C:{x:647,y:303,letter:'В',title:'Райцентр',area:'Посёлок'},
  D:{x:871,y:165,letter:'Г',title:'Озёрное',area:'Село'},
  HUB:{x:366,y:383,letter:'Х',title:'Хаб',area:'Промзона'},
  E:{x:92,y:93,letter:'Д',title:'Северный',area:'Город'},
  F:{x:89,y:378,letter:'Е',title:'Вокзальный',area:'Город'},
  G:{x:603,y:95,letter:'Ж',title:'Боровое',area:'Деревня'},
  J:{x:821,y:407,letter:'З',title:'Луговая',area:'Деревня'},
  K:{x:966,y:303,letter:'И',title:'Мельницы',area:'Деревня'}
};
const junctions={...stations, west:{x:241,y:203}, north:{x:280,y:132},
  south:{x:228,y:344}, northBank:{x:446,y:112}, northBridge:{x:510,y:112},
  southBank:{x:445,y:278}, bridge:{x:521,y:278},
  fork:{x:734,y:245}, mill:{x:918,y:260}};
const roads=[
  ['E','A',[[92,148],[137,148]]],['E','north',[[172,93],[190,118]]],
  ['A','west',[[195,215]]],['west','north',[[244,152]]],['north','B',[[315,132]]],
  ['F','A',[[89,300],[150,291]]],['F','south',[[161,378],[180,344]]],
  ['A','south',[[194,266],[194,321]]],['south','HUB',[[278,350],[306,383]]],
  ['HUB','B',[[380,289],[368,230],[368,161]]],
  ['west','southBank',[[288,207],[338,247],[401,258]]],
  ['HUB','southBank',[[419,357],[438,319]]],['southBank','bridge',[]],
  ['bridge','fork',[[552,266],[612,250],[677,252]]],
  ['bridge','C',[[566,287],[599,307]]],['C','fork',[[679,295],[700,259]]],
  ['fork','D',[[762,237],[797,191],[831,191]]],['D','mill',[[899,185],[907,226]]],
  ['mill','K',[[947,272]]],['K','J',[[927,349],[864,365]]],
  ['J','C',[[788,386],[749,388],[712,350],[665,337]]],
  ['G','fork',[[645,116],[645,166],[700,211]]],
  ['B','northBank',[[405,104]]],['northBank','northBridge',[]],
  ['northBridge','G',[[547,89]]]
];
// Geometry for a road is shared by the road surface, route strokes and direction arrows.
const roadGraph=new Map(Object.keys(junctions).map(id=>[id,[]]));
for(const [from,to,bends] of roads){
  const coords=[junctions[from],...bends.map(([x,y])=>({x,y})),junctions[to]];
  const length=coords.slice(1).reduce((n,p,i)=>n+Math.hypot(p.x-coords[i].x,p.y-coords[i].y),0);
  roadGraph.get(from).push({to,coords,length});
  roadGraph.get(to).push({to:from,coords:[...coords].reverse(),length});
}
const roadPaths=new Map();
function roadRoute(start,end){
  if(!roadGraph.has(start)||!roadGraph.has(end))throw Error('Неизвестная точка на карте');
  const key=start+'→'+end;
  if(roadPaths.has(key))return roadPaths.get(key);
  const pending=[{id:start,dist:0,edges:[]}], visited=new Set();
  while(pending.length){
    pending.sort((a,b)=>a.dist-b.dist);
    const item=pending.shift();
    if(item.id===end){roadPaths.set(key,item.edges);return item.edges;}
    if(visited.has(item.id))continue;
    visited.add(item.id);
    for(const edge of roadGraph.get(item.id)){
      if(!visited.has(edge.to))pending.push({id:edge.to,dist:item.dist+edge.length,edges:[...item.edges,edge]});
    }
  }
  throw Error('Нет дороги между '+start+' и '+end);
}
function pathOf(points){
  return points.map((p,i)=>(i?'L':'M')+p.x+' '+p.y).join(' ');
}
function routeEdges(a,b,viaHub=false){
  return viaHub?[...roadRoute(a,'HUB'),...roadRoute('HUB',b)]:roadRoute(a,b);
}
function routeStroke(edges,color,width,dotted=false){
  let last=null;
  const d=edges.map(({coords})=>{
    const path=last===coords[0]?pathOf(coords).replace(/^M\S+ \S+ /,''):pathOf(coords);
    last=coords.at(-1);
    return path;
  }).join(' ');
  return '<path d="'+d+'" fill="none" stroke="'+color+'" stroke-width="'+width+'" stroke-linejoin="round" stroke-linecap="round" '+(dotted?'stroke-dasharray="2 7"':'')+'/>';
}
function along(edges,fraction){
  let remaining=edges.reduce((n,e)=>n+e.length,0)*fraction;
  for(const e of edges)for(let i=1;i<e.coords.length;i++){
    const a=e.coords[i-1],b=e.coords[i],dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy);
    if(remaining<=len)return {x:a.x+dx*remaining/len,y:a.y+dy*remaining/len,angle:Math.atan2(dy,dx)*180/Math.PI};
    remaining-=len;
  }
}
function arrow(p,color){
  return '<g transform="translate('+p.x+' '+p.y+')"><circle r="11" fill="white" stroke="'+color+'" stroke-width="2"/><path d="M-5 0H5M1 -4l4 4-4 4" fill="none" stroke="'+color+'" stroke-width="2" transform="rotate('+p.angle+')"/></g>';
}
function pointMarkers(active=[],interactive=true,stops=[]){
  return Object.entries(stations).map(([id,p])=>{
    const label=(['Деревня','Село'].includes(p.area)?(p.area==='Село'?'с. ':'д. '):'')+p.title;
    const visits=stops.flatMap((s,i)=>s.id===id?[i+1]:[]);
    const fill=visits.length?'#086b60':active.includes(id)?'#ad292f':id==='HUB'?'#89642f':'#455d60';
    return '<g transform="translate('+p.x+' '+p.y+')" '+(interactive?'class="map-point" role="button" tabindex="0" data-point="'+id+'" aria-label="'+label+(visits.length?', остановки '+visits.join(', '):'')+'"':'')+'><circle r="14" fill="'+fill+'" stroke="#fffdf6" stroke-width="3"/><text y="4" text-anchor="middle" fill="white" font-size="'+(visits.length>1?9:12)+'" font-weight="bold">'+(visits.join('·')||p.letter)+'</text><text class="map-name" text-anchor="middle" y="30">'+label+'</text></g>';
  }).join('');
}
let terrain;
function mapTerrain(){
  if(terrain)return terrain;
  let buildings='',trees='',hamlets='';
  let seed=7321;
  function random(){
    seed=(seed*16807)%2147483647;
    return seed/2147483647;
  }
  // City blocks end at the river. The opposite bank contains separated hamlets and cultivated strips.
  for(let x=-18;x<435;x+=52)for(let y=-10;y<532;y+=47){
    if((x>170 && x<290 && y<95)||(x>330 && y>390))continue;
    const width=34+Math.floor(11*random()),height=27+Math.floor(10*random());
    buildings+='<rect x="'+x+'" y="'+y+'" width="'+width+'" height="'+height+'" rx="3" fill="#deded3"/>'+
      '<path transform="translate('+x+' '+y+')" d="M5 5h19v6H11v17H5zM28 13h10v18H28z" fill="#c5c7bf"/>';
  }
  for(const [x,y,nx,ny] of [[588,258,5,4],[841,137,4,2],[565,70,4,2],[782,379,4,2],[923,279,4,2]]){
    for(let i=0;i<nx;i++)for(let j=0;j<ny;j++){
      const px=x+i*17+(j%2)*4,py=y+j*20+(i%2)*3;
      hamlets+='<g transform="translate('+px+' '+py+') rotate(-12)"><rect x="-2" y="-3" width="15" height="15" fill="#d5dcb9"/><rect width="10" height="7" fill="#bc9a7c"/><path d="M0 3h10" stroke="#977c69"/></g>';
    }
  }
  for(let i=0;i<95;i++){
    const x=Math.round(638+random()*220),y=Math.round(9+random()*111);
    if(((x-750)/109)**2+((y-62)/55)**2<1)trees+='<circle cx="'+x+'" cy="'+y+'" r="6" fill="#b2c7a4"/>';
  }
  const river='M481 -22C460 85 487 124 489 170S462 251 478 278S472 354 501 405S526 487 489 540';
  const allRoads=roads.map(([from,to])=>roadGraph.get(from).find(e=>e.to===to));
  const crossings=[roadRoute('northBank','northBridge')[0],roadRoute('southBank','bridge')[0]];
  terrain='<defs><pattern id="fields" width="12" height="12" patternUnits="userSpaceOnUse" patternTransform="rotate(28)"><rect width="12" height="12" fill="#e7dfb9"/><path d="M2 0v12" stroke="#d8cfa6" stroke-width="2"/></pattern></defs>'+
    '<rect width="1040" height="510" fill="#e9edda"/><path d="M437 0H0v510h470l-34-89 13-97-24-84 29-87z" fill="#ecebe3"/>'+buildings+
    '<path d="M492 5l103 12-26 128-70-13zM584 162l75 12 24 61-99 23-34-27zM766 253l104-29 24 80-99 38-49-41zM553 382l105-25 68 99-145 43zM891 419l119-52 43 89-123 43z" fill="url(#fields)"/>'+
    '<path d="M630 34q101-63 206-9l28 69-116 22-74-33zM169 12h110l-7 72-67 12-43-23z" fill="#cbdac0"/>'+trees+
    '<path d="M864 16q64-20 126 32l-11 39-58 8-15-23-40-12z" fill="#a8cdd2"/>'+
    '<path d="'+river+'" fill="none" stroke="#c8d9c0" stroke-width="38"/><path d="'+river+'" fill="none" stroke="#aed3d8" stroke-width="24"/>'+hamlets+
    routeStroke(allRoads,'#c9c4b6',12)+routeStroke(crossings,'#898d7f',15)+routeStroke(allRoads,'#fffdf5',9)+
    '<g class="map-district"><text x="25" y="38">ГОРОДСКОЙ ОКРУГ</text><text x="624" y="480">СЕЛЬСКИЙ РАЙОН</text></g>';
  return terrain;
}
function networkMap(source,destination,mode,plan=null){
  if(plan?.stops.length){
    const edges=plan.legs.flatMap(leg=>leg.edges);
    const color='#087366';
    const arrows=[];
    for(const leg of plan.legs){
      const position=along(leg.edges,.53);
      if(position&&arrows.every(p=>Math.hypot(position.x-p.x,position.y-p.y)>44)&&
        plan.stops.every(stop=>Math.hypot(position.x-stations[stop.id].x,position.y-stations[stop.id].y)>28)){
        arrows.push(position);
      }
    }
    return mapSvg(routeStroke(edges,'#fffdf5',9)+routeStroke(edges,color,5)+
      arrows.map(p=>arrow(p,color)).join('')+pointMarkers([],true,plan.stops));
  }
  const direct=routeEdges(source,destination),hub=routeEdges(source,destination,true);
  const via=mode==='HUB',active=Boolean(mode)&&mode!=='MANUAL_EXCEPTION';
  const chosen=via?hub:direct;
  const midpoint=along(chosen,.50);
  const color=via?'#946624':active?'#b72d32':'#84918c';
  const inactive=[['A','B'],['C','D']].filter(([a,b])=>!(a===source && b===destination || b===source && a===destination))
    .map(([a,b])=>routeStroke(roadRoute(a,b),'#8b9898',2,true)).join('');
  const layers=via?routeStroke(direct,'#84918c',3,true)+routeStroke(hub,color,4,true):
    routeStroke(hub,'#a78d66',3,true)+routeStroke(direct,color,4,!active);
  return mapSvg(inactive+layers+
    (midpoint?'<g class="map-point" role="button" tabindex="0" data-action="compare" aria-label="Сравнить маршруты">'+arrow(midpoint,color)+'</g>':'')+
    pointMarkers(via?[source,destination,'HUB']:[source,destination]));
}
function mapSvg(content){
  return '<svg id="city-map" viewBox="'+mapViewBox()+'" aria-label="Дороги и пункты учебной агломерации" role="group">'+mapTerrain()+content+'</svg>';
}
const mapCamera={x:0,y:0,scale:1};
function mapViewBox(){
  return [mapCamera.x,mapCamera.y,mapWidth/mapCamera.scale,mapHeight/mapCamera.scale].join(' ');
}
function moveMap(x,y,scale=mapCamera.scale){
  mapCamera.scale=Math.max(1,Math.min(7,scale));
  mapCamera.x=Math.max(0,Math.min(mapWidth-mapWidth/mapCamera.scale,x));
  mapCamera.y=Math.max(0,Math.min(mapHeight-mapHeight/mapCamera.scale,y));
  if(typeof document!=='undefined')document.querySelector('#city-map')?.setAttribute('viewBox',mapViewBox());
}
function zoomMap(factor,point){
  const target=Math.max(1,Math.min(7,mapCamera.scale*factor));
  const pivot=point||{x:mapCamera.x+mapWidth/mapCamera.scale/2,y:mapCamera.y+mapHeight/mapCamera.scale/2};
  const ratio=mapCamera.scale/target;
  moveMap(pivot.x-(pivot.x-mapCamera.x)*ratio,pivot.y-(pivot.y-mapCamera.y)*ratio,target);
}

function bindMapControls(svg){
  if(!svg)return;
  const pointers=new Map();
  let moved=false;
  const point=(x,y)=>new DOMPoint(x,y).matrixTransform(svg.getScreenCTM().inverse());
  svg.addEventListener('wheel',event=>{
    event.preventDefault();
    const delta=event.deltaMode===1?event.deltaY*16:event.deltaY;
    zoomMap(Math.exp(-Math.max(-180,Math.min(180,delta))*.003),point(event.clientX,event.clientY));
  },{passive:false});
  svg.addEventListener('pointerdown',event=>{
    if(event.button!==0)return;
    if(!pointers.size)moved=false;
    pointers.set(event.pointerId,{x:event.clientX,y:event.clientY,startX:event.clientX,startY:event.clientY});
  });
  svg.addEventListener('pointermove',event=>{
    const previous=pointers.get(event.pointerId);
    if(!previous)return;
    const {clientX:x,clientY:y}=event;
    const other=[...pointers.entries()].find(([id])=>id!==event.pointerId)?.[1];
    if(!moved&&!other&&Math.hypot(x-previous.startX,y-previous.startY)<5)return;
    moved=true;
    if(!svg.hasPointerCapture(event.pointerId))svg.setPointerCapture(event.pointerId);
    svg.classList.add('is-panning');
    if(other){
      const before=Math.hypot(previous.x-other.x,previous.y-other.y);
      const after=Math.hypot(x-other.x,y-other.y);
      const midpoint=point((previous.x+other.x)/2,(previous.y+other.y)/2);
      if(before>0&&after>0)zoomMap(after/before,midpoint);
      const updated=point((x+other.x)/2,(y+other.y)/2);
      moveMap(mapCamera.x+midpoint.x-updated.x,mapCamera.y+midpoint.y-updated.y);
    }else{
      const from=point(previous.x,previous.y),to=point(x,y);
      moveMap(mapCamera.x+from.x-to.x,mapCamera.y+from.y-to.y);
    }
    pointers.set(event.pointerId,{...previous,x,y});
  });
  for(const name of ['pointerup','pointercancel','lostpointercapture','pointerleave']){
    svg.addEventListener(name,event=>{
      if(name==='pointerleave'&&svg.hasPointerCapture(event.pointerId))return;
      pointers.delete(event.pointerId);
      if(!pointers.size)svg.classList.remove('is-panning');
    });
  }
  svg.addEventListener('click',event=>{
    if(moved&&event.detail>0)event.stopPropagation();
    moved=false;
  });
}
