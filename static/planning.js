'use strict';
let slice={date:'2026-11-25',district:'all',demand:'neutral',window:'day',consent:'0'};
let visiblePlan=null;
async function openPlan(){
  const response=await api('map?'+new URLSearchParams({view:'plan',...slice}));
  visiblePlan=response;
  const opts=(name,label,choices)=>selectField(label,name,choices,slice[name]);
  const inputs=field('Дата','date','date',slice.date,'required min="2026-11-23" max="2026-12-20"')+
    opts('district','Район',[['all','Вся агломерация'],['city','Город'],['rural','Село']])+
    opts('demand','Спрос',[['low','Низкий'],['neutral','Нейтральный'],['high','Высокий']])+
    opts('window','Окно',[['day','Основное'],['late','Добровольно выбранное позднее']])+
    opts('consent','Согласны на перенос',['0','5','15','30'].map(i=>[i,i+'%']));
  const routes=response.edges.map((edge,index)=>{
    const p=stations[edge.source],q=stations[edge.destination];
    const dx=q.x-p.x,dy=q.y-p.y,dist=Math.hypot(dx,dy),offset=12;
    const x=p.x-dy/dist*offset,y=p.y+dx/dist*offset;
    const endX=x+dx-dx/dist*20,endY=y+dy-dy/dist*20;
    const fill=edge.direct?'#6447af':'#846538';
    return '<g role="button" tabindex="0" data-action="plan-edge" data-id="'+index+'" aria-label="'+esc(loc(edge.source)+' → '+loc(edge.destination))+'"><title>'+esc(loc(edge.source)+' → '+loc(edge.destination)+' · '+signed(edge.savings))+'</title><path d="M'+x+' '+y+' L'+endX+' '+endY+'" stroke="transparent" stroke-width="18"/><path d="M'+x+' '+y+' L'+endX+' '+endY+'" stroke="'+fill+'" stroke-width="'+Math.min(7,2+edge.orders/5)+'" '+(edge.direct?'':'stroke-dasharray="7 5"')+'/>'+'<path transform="translate('+endX+' '+endY+') rotate('+Math.atan2(dy,dx)*180/Math.PI+')" d="M0 0l-10 -5v10z" fill="'+fill+'"/></g>';
  }).join('');
  const points=response.points.map(p=>'<g transform="translate('+stations[p.id].x+' '+stations[p.id].y+')"><circle r="12" fill="#283e54" stroke="white" stroke-width="2"/><text text-anchor="middle" y="4" fill="white" font-size="12">'+stations[p.id].letter+'</text><text text-anchor="middle" y="29" fill="#23354a" paint-order="stroke" stroke="white" stroke-width="4" font-size="13">'+esc(p.name)+'</text></g>').join('');
  const rows=response.edges.map((e,i)=>[linkButton('plan-edge',i,loc(e.source)+' → '+loc(e.destination)),num(e.orders),num(e.direct)+' / '+num(e.hub),signed(e.savings)]);
  dialogBox('План сети по окнам','<div class="stack"><div class="notice">'+esc(prof(response.profile))+' · 28 дней · синтетический спрос из книги</div>'+form('plan-filter','<div class="fields">'+inputs+'</div>','Показать срез')+
    '<svg viewBox="0 0 800 355" aria-label="Направления выбранного среза">'+mapTerrain()+routes+points+'</svg><p class="micro">Фиолетовый — есть прямые отправления, пунктир — хаб. Толщина линии показывает число заказов. Нажмите на направление для расчёта.</p>'+
    table(['Направление','Заказы','Прямо / хаб','Эффект маршрутизации'],rows)+'</div>');
}
function planEdge(id){
  const e=visiblePlan?.edges[Number(id)];
  if(!e)return;
  dialogBox(loc(e.source)+' → '+loc(e.destination),'<div class="stack">'+dl([['Дата среза',visiblePlan.date],['SKU',e.sku],['Выбор',modes[e.mode]],['Попутная / отдельная / хаб',e.shared+' / '+e.dedicated+' / '+e.hub],['Загрузка попутного места',e.shared+' / '+e.shared_slots],['База через хаб для локального запаса',money(e.hub_reference)],['Экономия рейса',signed(e.savings)],['Индекс',e.index==null?'Нет оценки':num(e.index)+' из 100'],['Эффект размещения до координации',signed(e.expected_program_delta)]])+button('network-plan','К выбранному срезу','map')+'</div>');
}

