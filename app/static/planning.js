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
    const hub=edge.direct===0;
    const edges=routeEdges(edge.source,edge.destination,hub);
    const color=hub?'#946624':'#b72d32';
    const width=Math.min(6,2+edge.orders/6);
    const target=along(edges,.4);
    return '<g data-action="plan-edge" data-id="'+index+'" role="button" tabindex="0" aria-label="'+esc(loc(edge.source)+' → '+loc(edge.destination))+'">'+routeStroke(edges,color,width,hub)+arrow(target,color)+'</g>';
  }).join('');
  const points=pointMarkers([],false);
  const rows=response.edges.map((e,i)=>[linkButton('plan-edge',i,loc(e.source)+' → '+loc(e.destination)),num(e.orders),num(e.direct)+' / '+num(e.hub),signed(e.savings)]);
  dialogBox('План сети по окнам','<div class="stack"><div class="notice">'+esc(prof(response.profile))+' · 28 дней · синтетический спрос из книги</div>'+form('plan-filter','<div class="fields">'+inputs+'</div>','Показать срез')+
    '<svg viewBox="0 0 1040 510" aria-label="Направления выбранного среза">'+mapTerrain()+routes+points+'</svg><p class="micro">Красный — есть прямые отправления, пунктир — хаб. Толщина линии показывает число заказов. Нажмите на направление для расчёта.</p>'+
    table(['Направление','Заказы','Прямо / хаб','Эффект маршрутизации'],rows)+'</div>');
}
function planEdge(id){
  const e=visiblePlan?.edges[Number(id)];
  if(!e)return;
  dialogBox(loc(e.source)+' → '+loc(e.destination),'<div class="stack">'+dl([['Дата среза',visiblePlan.date],['SKU',e.sku],['Выбор',modes[e.mode]],['Попутная / отдельная / хаб',e.shared+' / '+e.dedicated+' / '+e.hub],['Загрузка попутного места',e.shared+' / '+e.shared_slots],['База через хаб для локального запаса',money(e.hub_reference)],['Экономия рейса',signed(e.savings)],['Индекс',e.index==null?'Нет оценки':num(e.index)+' из 100'],['Эффект размещения до координации',signed(e.expected_program_delta)]])+button('network-plan','К выбранному срезу','map')+'</div>');
}

