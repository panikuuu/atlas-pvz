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
  south:{x:228,y:344}, bridge:{x:521,y:287}, fork:{x:734,y:245}, mill:{x:918,y:260}};
const roads=[
  ['E','A',[[92,148],[137,148]]],['E','north',[[172,93],[190,118]]],
  ['A','west',[[195,215]]],['west','north',[[244,152]]],['north','B',[[315,132]]],
  ['F','A',[[89,300],[150,291]]],['F','south',[[161,378],[180,344]]],
  ['A','south',[[194,266],[194,321]]],['south','HUB',[[278,350],[306,383]]],
  ['HUB','B',[[380,289],[368,230],[368,161]]],
  ['west','bridge',[[288,207],[338,247],[401,258],[461,284]]],
  ['HUB','bridge',[[427,383],[451,344],[498,332]]],
  ['bridge','fork',[[552,266],[612,250],[677,252]]],
  ['bridge','C',[[566,287],[599,307]]],['C','fork',[[679,295],[700,259]]],
  ['fork','D',[[762,237],[797,191],[831,191]]],['D','mill',[[899,185],[907,226]]],
  ['mill','K',[[947,272]]],['K','J',[[927,349],[864,365]]],
  ['J','C',[[788,386],[749,388],[712,350],[665,337]]],
  ['G','fork',[[645,116],[645,166],[700,211]]],['B','G',[[405,104],[450,119],[504,114],[547,89]]]
];
// Geometry for a road is shared by the road surface, route strokes and direction arrows.
const roadGraph=new Map(Object.keys(junctions).map(id=>[id,[]]));
for(const [from,to,bends] of roads){
  const coords=[junctions[from],...bends.map(([x,y])=>({x,y})),junctions[to]];
  const length=coords.slice(1).reduce((n,p,i)=>n+Math.hypot(p.x-coords[i].x,p.y-coords[i].y),0);
  roadGraph.get(from).push({to,coords,length});
  roadGraph.get(to).push({to:from,coords:[...coords].reverse(),length});
}
function roadRoute(start,end){
  const pending=[{id:start,dist:0,edges:[]}], visited=new Set();
  while(pending.length){
    pending.sort((a,b)=>a.dist-b.dist);
    const item=pending.shift();
    if(item.id===end)return item.edges;
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
  return '<path d="'+edges.map(e=>pathOf(e.coords)).join(' ')+'" fill="none" stroke="'+color+'" stroke-width="'+width+'" stroke-linejoin="round" stroke-linecap="round" '+(dotted?'stroke-dasharray="2 7"':'')+'/>';
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
function pointMarkers(active=[],interactive=true){
  return Object.entries(stations).map(([id,p])=>{
    const label=(['Деревня','Село'].includes(p.area)?(p.area==='Село'?'с. ':'д. '):'')+p.title;
    const fill=active.includes(id)?'#ad292f':id==='HUB'?'#89642f':'#455d60';
    return '<g transform="translate('+p.x+' '+p.y+')" '+(interactive?'class="map-point" role="button" tabindex="0" data-point="'+id+'" aria-label="'+label+'"':'')+'><circle r="14" fill="'+fill+'" stroke="#fffdf6" stroke-width="3"/><text y="4" text-anchor="middle" fill="white" font-size="12" font-weight="bold">'+p.letter+'</text><text class="map-name" text-anchor="middle" y="30">'+label+'</text></g>';
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
  const river='M481 -22C394 85 537 166 477 228S455 342 501 405S526 487 489 540';
  const allRoads=roads.map(([from,to])=>roadGraph.get(from).find(e=>e.to===to));
  terrain='<defs><pattern id="fields" width="12" height="12" patternUnits="userSpaceOnUse" patternTransform="rotate(28)"><rect width="12" height="12" fill="#e7dfb9"/><path d="M2 0v12" stroke="#d8cfa6" stroke-width="2"/></pattern></defs>'+
    '<rect width="1040" height="510" fill="#e9edda"/><path d="M437 0H0v510h470l-34-89 13-97-24-84 29-87z" fill="#ecebe3"/>'+buildings+
    '<path d="M492 5l103 12-26 128-70-13zM584 162l75 12 24 61-99 23-34-27zM766 253l104-29 24 80-99 38-49-41zM553 382l105-25 68 99-145 43zM891 419l119-52 43 89-123 43z" fill="url(#fields)"/>'+
    '<path d="M630 34q101-63 206-9l28 69-116 22-74-33zM169 12h110l-7 72-67 12-43-23z" fill="#cbdac0"/>'+trees+
    '<path d="M864 16q64-20 126 32l-11 39-58 8-15-23-40-12z" fill="#a8cdd2"/>'+
    '<path d="'+river+'" fill="none" stroke="#c8d9c0" stroke-width="38"/><path d="'+river+'" fill="none" stroke="#aed3d8" stroke-width="24"/>'+hamlets+
    routeStroke(allRoads,'#c9c4b6',12)+routeStroke(allRoads,'#fffdf5',9)+
    '<g class="map-district"><text x="25" y="38">ГОРОДСКОЙ ОКРУГ</text><text x="624" y="480">СЕЛЬСКИЙ РАЙОН</text></g>';
  return terrain;
}
let zoom=1;
function networkMap(source,destination,mode){
  const direct=routeEdges(source,destination),hub=routeEdges(source,destination,true);
  const via=mode==='HUB',active=Boolean(mode)&&mode!=='MANUAL_EXCEPTION';
  const chosen=via?hub:direct;
  const midpoint=along(chosen,.50),w=mapWidth/zoom,h=mapHeight/zoom;
  const x=Math.max(0,Math.min(mapWidth-w,midpoint.x-w/2)),y=Math.max(0,Math.min(mapHeight-h,midpoint.y-h/2));
  const color=via?'#946624':active?'#b72d32':'#84918c';
  const inactive=[['A','B'],['C','D']].filter(([a,b])=>!(a===source && b===destination || b===source && a===destination))
    .map(([a,b])=>routeStroke(roadRoute(a,b),'#8b9898',2,true)).join('');
  const layers=via?routeStroke(direct,'#84918c',3,true)+routeStroke(hub,color,4,true):
    routeStroke(hub,'#a78d66',3,true)+routeStroke(direct,color,4,!active);
  return '<svg id="city-map" viewBox="'+[x,y,w,h].join(' ')+'" aria-label="Дороги и пункты учебной агломерации" role="group">'+mapTerrain()+inactive+layers+
    '<g class="map-point" role="button" tabindex="0" data-action="compare" aria-label="Сравнить маршруты">'+arrow(midpoint,color)+'</g>'+
    pointMarkers(via?[source,destination,'HUB']:[source,destination])+'</svg>';
}
