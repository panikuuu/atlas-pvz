'use strict';
let slice={date:'2026-11-25',district:'all',demand:'neutral',window:'day',consent:'0'};
let visiblePlan=null;
let truckPlan=null;

function shiftTruckOrders(){
  return s.orders.filter(o=>o.status==='ASSEMBLED'&&!o.dispatch_id).map(o=>({
    id:o.id,from:o.source,to:o.destination,liters:o.volume_l,grams:o.mass_g,
    due:Date.parse(o.selected_promised_at||o.promised_at)
  }));
}

function truckForm(){
  const points=Object.keys(stations).map(id=>[id,loc(id)]);
  const prior=truckPlan?.config;
  const count=shiftTruckOrders().length;
  const kinds=[['sample','Тестовый набор · девять ПВЗ'],['shift','Текущая смена · '+count+' собранных']];
  dialogBox('Спланировать рейс',
    form('truck-form','<div class="fields">'+
      selectField('Заказы','kind',kinds,prior?.kind||'sample')+
      field('Начало рейса, мск','departure','datetime-local',isoField(Math.max(Math.ceil(Date.parse(s.now)/60000)*60000,prior?.departure||0)),'required min="'+isoField(s.now)+'"')+
      selectField('Начальная точка','start',points,prior?.start||'F')+
      selectField('Конечная точка','end',points,prior?.end||'K')+
      field('Свободный объём, л','liters','number',prior?.liters||24,'required min="0.1" step="0.1"')+
      field('Свободный вес, кг','mass','number',prior?prior.grams/1000:10,'required min="0.01" step="0.01"')+
      '</div><p class="notes">Укажите свободную вместимость перед выездом. Атлас рассчитает последовательность остановок и подготовит маршрутный лист.</p>',
      'Рассчитать рейс'));
}

function calculateTruck(fields){
  const config={kind:fields.kind,start:fields.start,end:fields.end,
    departure:Date.parse(fields.departure+':00+03:00'),liters:Number(fields.liters),grams:Math.round(Number(fields.mass)*1000)};
  if(config.departure<Date.parse(s.now))throw Error('Время выезда уже прошло по часам смены.');
  const orders=config.kind==='sample'?truckSample(config.departure):shiftTruckOrders();
  if(!orders.length)throw Error('В смене нет собранных заказов, ещё не назначенных в рейс.');
  truckPlan=planTruck(orders,config);
  truckPlan.shiftKey=JSON.stringify([s.epoch,shiftTruckOrders()]);
  moveMap(0,0,1);
  dialog.close();
  render();
  document.getElementById('truck-itinerary')?.focus({preventScroll:true});
}

function currentTruckPlan(){
  if(truckPlan?.config.kind==='shift'&&
    (truckPlan.shiftKey!==JSON.stringify([s.epoch,shiftTruckOrders()])||truckPlan.config.departure<Date.parse(s.now))){
    truckPlan=null;
    toast('Смена изменилась. Рассчитайте рейс заново.');
  }
  return truckPlan;
}

function truckItinerary(plan){
  const {config,stops,included,rejected,peakLiters,peakGrams,km,finish}=plan;
  const clock=new Intl.DateTimeFormat('ru-RU',{timeZone:'Europe/Moscow',hour:'2-digit',minute:'2-digit'});
  const time=value=>clock.format(value);
  const duration=Math.ceil((finish-config.departure)/60000);
  const minutes=value=>Math.floor(value/60)+' ч '+value%60+' мин';
  const orders=list=>list.map(o=>esc(o.id)).join(', ');
  const content=stops.map((stop,i)=>{
    const operations=[
      stop.drop.length?'<span class="truck-drop">Выгрузить '+stop.drop.length+'</span>':'',
      stop.pickup.length?'<span class="truck-pickup">Забрать '+stop.pickup.length+'</span>':''
    ].join('');
    const ids=[stop.drop.length?'Выгрузка · '+orders(stop.drop):'',stop.pickup.length?'Погрузка · '+orders(stop.pickup):''].filter(Boolean).join('<br>');
    return '<li><button class="truck-stop" data-action="truck-stop" data-id="'+i+'" title="Показать на карте">'+
      '<span class="truck-number">'+(i+1)+'</span><span><strong>'+esc(loc(stop.id))+'</strong><small>'+
      time(stop.arrive)+(stop.leave>stop.arrive?'–'+time(stop.leave):'')+'</small></span></button>'+
      '<div class="truck-operations">'+(operations||'<span>'+(!i?'Точка старта':'Точка завершения')+'</span>')+'</div>'+
      '<div class="truck-load" title="Загрузка после остановки">'+num(stop.liters)+' л · '+num(stop.grams/1000)+' кг</div>'+
      (ids?'<details><summary>Номера заказов</summary><div>'+ids+'</div></details>':'')+'</li>';
  }).join('');
  const unplanned=rejected.length?'<details class="truck-exceptions"><summary>Вне плана · '+rejected.length+'</summary><ul>'+
    rejected.map(o=>'<li>'+esc(o.id)+' · '+esc(loc(o.from)+' → '+loc(o.to))+' · '+esc(o.reason)+'</li>').join('')+'</ul></details>':'';
  const economics=included.length?'<details class="truck-economics"><summary>Оценка дополнительной стоимости</summary>'+
    dl([['Крюк к плановому пути',num(plan.extraKm)+' км'],['Дополнительные расходы и скидки',money(plan.extraCost)],
      ['Те же посылки через хаб',money(plan.hubCost)],['Разница в пользу рейса',signed(plan.hubCost-plan.extraCost)]])+
    '<p class="micro">Расчёт по модельным ставкам для уже запланированной машины.</p></details>':'';
  return '<section id="truck-itinerary" class="panel truck-itinerary" tabindex="-1"><div class="panel-head"><div><h2>Маршрутный лист</h2><small>'+
    (config.kind==='sample'?'Тестовые заказы':'Собранные заказы смены')+' · '+esc(tm(config.departure))+' мск</small></div>'+
    '<div class="section-actions">'+button('truck-form','Пересчитать','filter')+
    button('truck-export','Скачать','download',false,included.length?'':'disabled')+button('truck-clear','К рейсам','route')+'</div></div>'+
    '<div class="truck-totals">'+dl([['В рейсе',included.length+' из '+(included.length+rejected.length)+' зак.'],
      ['Путь по дорогам',num(km)+' км'],['Время рейса',minutes(duration)],
      ['Пиковая загрузка',num(peakLiters)+' / '+num(config.liters)+' л · '+num(peakGrams/1000)+' / '+num(config.grams/1000)+' кг']])+'</div>'+
    (included.length?'<ol class="truck-timeline">'+content+'</ol>':empty('При заданных условиях ни один заказ не вошёл в рейс.'))+
    unplanned+economics+'</section>';
}

function exportTruck(){
  const plan=currentTruckPlan();
  if(!plan?.included.length)return;
  const date=value=>new Date(value).toISOString();
  const body={source:plan.config.kind,departure:date(plan.config.departure),finish:date(plan.finish),distance_km:plan.km,
    stops:plan.stops.map(stop=>({point:stop.id,name:loc(stop.id),arrive:date(stop.arrive),leave:date(stop.leave),
      pick_up:stop.pickup.map(o=>o.id),unload:stop.drop.map(o=>o.id),liters:stop.liters,mass_g:stop.grams})),
    legs:plan.legs.map(leg=>({from:leg.from,to:leg.to,km:leg.km,roads:leg.edges.map(edge=>edge.to)})),
    unassigned:plan.rejected.map(o=>({id:o.id,reason:o.reason}))};
  const url=URL.createObjectURL(new Blob([JSON.stringify(body,null,2)],{type:'application/json'}));
  const link=document.createElement('a');
  link.href=url;
  link.download='atlas-route.json';
  link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
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

