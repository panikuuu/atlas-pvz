'use strict';
const stations = {
  A:{x:142,y:210,title:'Центр',letter:'А'}, B:{x:408,y:111,title:'Университет',letter:'Б'},
  C:{x:552,y:257,title:'Райцентр',letter:'В'}, D:{x:704,y:124,title:'Озёрное',letter:'Г'},
  HUB:{x:325,y:293,title:'Хаб',letter:'Х'}
};
let terrain;
function mapTerrain(){
  if(terrain) return terrain;
  let seed=29;
  function rand(){seed=(seed*16807)%2147483647;return seed/2147483647;}
  let blocks='';
  const colors=['#e5e3dc','#dcded9','#e3e4df','#dbddd7','#d8dcd9','#d6e3d2'];
  for(let x=-150;x<940;x+=47) for(let y=-200;y<580;y+=34){
    let w=35+rand()*6,h=22+rand()*5;
    blocks+='<g transform="translate('+x+' '+y+')"><rect width="'+w+'" height="'+h+'" rx="2" fill="'+colors[Math.floor(rand()*colors.length)]+'"/>';
    if(rand()<.75)blocks+='<path d="M5 4h7v13H5z M17 5h15v5H17z" fill="#cdd1ca" opacity=".45"/>';
    blocks+='</g>';
  }
  const streets=['M-80 293Q95 221 190 214T404 142T594 100T865 33','M-70 58Q109 80 195 133T389 201T610 288L882 392','M110 -54Q136 120 213 235T280 435','M454 -46Q428 82 489 176T527 439','M-50 323Q113 340 264 283T563 223T851 152','M628 -31Q645 78 717 143T814 294'];
  const river='M225 -60 C208 16 334 9 324 71 S237 148 275 181 S419 210 433 258 S415 353 470 410';
  terrain='<rect width="800" height="355" fill="#edeee9"/><g transform="rotate(-19 400 175)">'+blocks+'</g>'+
    '<g fill="#d1e1c9" stroke="#c3d8bf" stroke-width="2"><path d="m-12 85 49-43 32 10 29 55-26 27-55-8z"/><path d="m375 54 56-39 87 12 16 38-67 22-29-20-49 12z"/><path d="m599 132 36-46 45 11 25 45-62 26z"/><path d="m69 296 38-38 47 13 35 55-42 43H82z"/><path d="m606 331 42-33 75 15 27 55-127 7z"/></g>'+
    '<path d="'+river+'" fill="none" stroke="#cedfd8" stroke-width="44"/><path d="'+river+'" fill="none" stroke="#acd5df" stroke-width="34"/>'+
    streets.map(d=>'<path d="'+d+'" fill="none" stroke="#d8d7cf" stroke-width="12"/><path d="'+d+'" fill="none" stroke="#faf9f3" stroke-width="9"/>').join('')+
    '<path d="M-20 337Q205 339 400 280T820 269" fill="none" stroke="#c1c3b9" stroke-width="2" stroke-dasharray="6 3"/><g fill="#768d81" font-family="Segoe UI, sans-serif" font-size="11" font-weight="500" letter-spacing="1.6"><text x="48" y="76" transform="rotate(-14 48 76)">СЕВЕРНЫЙ ПАРК</text><text x="612" y="326">ЗАРЕЧЬЕ</text><text x="447" y="59">СОСНОВКА</text></g>';
  return terrain;
}
let zoom=1;
function networkMap(source,destination,mode,activeCount){
  const city=['AB','BA'].includes(source+destination), rural=['CD','DC'].includes(source+destination);
  const reverse=['BA','DC'].includes(source+destination);
  const color='#7152cb',hubColor='#ac752d',neutral='#8b98a5';
  function line(d,c,dash=''){
    return '<path d="'+d+'" fill="none" stroke="#fff" stroke-width="8" opacity=".85"/><path d="'+d+'" fill="none" stroke="'+c+'" stroke-width="4" stroke-linecap="round" '+(dash?'stroke-dasharray="'+dash+'"':'')+'/>';
  }
  const useHub=mode==='HUB', unresolved=mode==='MANUAL_EXCEPTION';
  const points=Object.entries(stations).map(([id,p])=>{
    const active=id===source||id===destination||id==='HUB'&&useHub;
    const fill=id==='HUB'?'#986e38':active?'#5d449f':'#53656f';
    let w=p.title.length*7.8+17;
    return '<g class="map-point" data-point="'+id+'" role="button" tabindex="0" aria-label="'+p.title+'" transform="translate('+p.x+' '+p.y+')">'+
      '<circle r="22" fill="'+fill+'" opacity="'+(active?'.11':'.05')+'"/><circle r="13" fill="'+fill+'" stroke="white" stroke-width="3"/>'+
      '<text text-anchor="middle" y="4" fill="white" font-size="12" font-weight="700">'+p.letter+'</text><rect x="'+(-w/2)+'" y="19" width="'+w+'" height="21" rx="5" fill="white" stroke="#dbdeda"/><text text-anchor="middle" y="33.5" font-size="11.5" fill="#304042" font-weight="600">'+p.title+'</text></g>';
  }).join('');
  let paths=line('M142 210Q210 149 264 154T408 111',city&&!useHub&&!unresolved?color:neutral,city&&!useHub&&!unresolved?'':'5 6')+
    line('M552 257Q600 200 630 197T704 124',rural&&!useHub&&!unresolved?color:neutral,rural&&!useHub&&!unresolved?'':'5 6');
  if(city) paths+=line('M142 210Q226 273 325 293Q400 218 408 111',useHub?hubColor:'#ae9b7e','4 7');
  else if(rural) paths+=line('M552 257Q408 255 325 293Q434 145 704 124',useHub?hubColor:'#ae9b7e','4 7');
  else paths+=line('M142 210Q340 203 552 257',useHub?neutral:color)+line('M142 210Q200 257 325 293L552 257',useHub?hubColor:'#ae9b7e','4 7');
  const m=city?{x:275,y:150,ang:-12}:rural?{x:630,y:196,ang:-26}:{x:345,y:220,ang:8};
  if(reverse)m.ang+=180;
  const routeArrow='<g class="map-point" data-action="compare" role="button" tabindex="0" aria-label="Сравнить маршруты" transform="translate('+m.x+' '+m.y+')"><circle r="14" fill="white" stroke="'+(useHub?neutral:color)+'" stroke-width="2"/><path transform="rotate('+m.ang+')" d="M-6 0h12 M1-5l5 5-5 5" fill="none" stroke="'+(useHub?neutral:color)+'" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.4"/></g>';
  const vx=800/zoom,vy=355/zoom;
  const cx=zoom===1?400:Math.max(vx/2,Math.min(800-vx/2,m.x)),cy=zoom===1?177.5:Math.max(vy/2,Math.min(355-vy/2,m.y));
  return '<svg id="city-map" xmlns="http://www.w3.org/2000/svg" viewBox="'+[cx-vx/2,cy-vy/2,vx,vy].join(' ')+'" preserveAspectRatio="xMidYMid meet" role="group" aria-label="Схема учебной агломерации">'+mapTerrain()+paths+routeArrow+points+'</svg>';
}
