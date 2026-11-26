'use strict';

let fleetDay=null,fleetDraft=null,fleetSettings=null,fleetSelected=null,fleetFocus=null;
let fleetFormState=null,fleetPoint='',unifiedRun=null;
const fleetNames={pickup:'Погрузить',drop:'Выгрузить к выдаче',relay_drop:'Передать в буфер',relay_pickup:'Забрать из буфера'};
const fleetPriceNames={diesel:'Дизель, ₽/л',consumption:'Расход топлива, л/100 км',wear:'Обслуживание, ₽/км',
  driver_hour:'Работа водителя, ₽/ч',pvz_hour:'Компенсация работы ПВЗ, ₽/ч',
  pvz_internal_hour:'Себестоимость труда ПВЗ, ₽/ч',packing:'Упаковка, ₽/посылку',
  rebate:'Скидка продавцу, ₽/посылку',expected_extra_risk:'Доп. риски, ₽/посылку',transfer_handling:'Доплата за передачу, ₽/посылку',
  transfer_internal:'Себестоимость буфера ПВЗ, ₽/посылку',dedicated_fixed:'Выделенный выезд, ₽/машину',hub_city:'Устранимые расходы хаба, город, ₽/посылку',
  hub_rural:'Устранимые расходы хаба, село, ₽/посылку',coordination_day:'Координация, ₽/день'};
const fleetCostNames={fuel:'Топливо',wear:'Обслуживание машины',driver:'Время водителя',pvz:'Работа ПВЗ',dispatch:'Дополнительный выезд',
  packing:'Упаковка',rebate:'Снижение тарифной выручки',expected_extra_risk:'Ожидаемые дополнительные расходы',transfer_handling:'Доплата за передачу'};
const fleetClock=min=>{const t=Math.floor(min);return String(Math.floor(t/60)).padStart(2,'0')+':'+String(t%60).padStart(2,'0');};
function fleetTime(minute){
  const seconds=Math.round(minute*60);
  const day=Math.floor(seconds/86400), sameDay=seconds-day*86400;
  const clock=fleetClock(sameDay/60);
  return clock+(sameDay%60?':'+String(sameDay%60).padStart(2,'0'):'')+(day?' ('+(day>0?'+':'')+day+' д)':'');
}
const fleetDuration=value=>{const [h,m]=value.split(':').map(Number);return h*60+m;};
const fleetTruckStates={PLANNED:'К выезду',RUNNING:'В пути',DONE:'Завершён'};

async function loadFleet(){
  const currentRole=role;
  const result=await api('fleet');
  if(role!==currentRole)return;
  fleetDay=result.day;
  fleetSettings=result.settings;
  unifiedRun=result.unified||null;
  if(['map','fleet','demo','portfolio','ledger'].includes(activePage))render();
}

function fleetDefaults(scenario){
  const preset=fleetSettings.scenarios[scenario]||fleetSettings.scenarios.weekday;
  const now=fleetDuration(isoField(s.now).slice(11,16));
  const trucks=preset.trucks.map((v,i)=>scenario==='live'?{...v,id:'М'+(i+1),start_min:Math.min(1320,Math.max(now,v.start_min))}:({...v}));
  for(const v of trucks) if(v.end_min<=v.start_min)v.end_min=Math.min(1439,v.start_min+90);
  const contract=s.profile||'pilot';
  return {scenario,trucks,prices:{...fleetSettings.prices,rebate:fleetSettings.contracts[contract].rebate},
    allow_transfer:true,contract,targets:{rwb_per_order:100,seller_per_order:100,pvz_per_day:100}};
}

function captureFleetForm(){
  const form=document.getElementById('fleet-plan-form');
  if(!form)return;
  const fields=new FormData(form);
  fleetFormState.contract=fields.get('fleet_contract');
  fleetFormState.prices=Object.fromEntries(Object.keys(fleetPriceNames).map(key=>[key,Number(fields.get('price_'+key))]));
  fleetFormState.targets=Object.fromEntries(Object.keys(fleetFormState.targets).map(key=>[key,Math.round(Number(fields.get(key))*100)]));
  fleetFormState.allow_transfer=fields.has('fleet_transfer');
  fleetFormState.trucks=fleetFormState.trucks.map((v,i)=>{
    const read=key=>fields.get('fleet_'+i+'_'+key);
    return {id:read('id'),start:read('start'),end:read('end'),start_min:fleetDuration(read('start_min')),end_min:fleetDuration(read('end_min')),
      liters:Number(read('liters')),kg:Number(read('kg')),planned:read('planned')==='yes'};
  });
}

function fleetForm(scenario){
  if(!fleetSettings)return;
  if(scenario)fleetFormState=fleetDefaults(scenario);
  if(!fleetFormState)fleetFormState=fleetDefaults('weekday');
  const points=Object.keys(stations).map(id=>[id,loc(id)]);
  const scenarios=Object.entries(fleetSettings.scenarios).map(([key,preset])=>[key,preset.title]).concat([['live','Собранные заказы смены']]);
  const vehicles=fleetFormState.trucks.map((v,i)=>{
    const name=key=>'fleet_'+i+'_'+key;
    return '<fieldset class="fleet-vehicle"><legend>Машина '+(i+1)+'</legend><div class="fields">'+
      field('Название',name('id'),'text',v.id,'required maxlength="20"')+
      selectField('Тип выезда',name('planned'),[['yes','Уже в расписании'],['no','Дополнительная машина']],v.planned?'yes':'no')+
      selectField('Старт',name('start'),points,v.start)+selectField('Финиш',name('end'),points,v.end)+
      field('Выезд, мск',name('start_min'),'time',fleetClock(v.start_min),'required')+
      field('Финиш до, мск',name('end_min'),'time',fleetClock(v.end_min),'required')+
      field('Свободно, л',name('liters'),'number',v.liters,'required min=".01" step="any"')+
      field('Свободно, кг',name('kg'),'number',v.kg,'required min=".01" step="any"')+
      '</div>'+button('fleet-remove','Убрать машину','close',false,'data-id="'+i+'" '+(fleetFormState.trucks.length===1?'disabled':''))+'</fieldset>';
  }).join('');
  const rates=Object.entries(fleetPriceNames).map(([key,label])=>field(label,'price_'+key,'number',fleetFormState.prices[key],'required min="0" max="10000" step="any"')).join('');
  const targets=Object.entries({rwb_per_order:'RWB, ₽/заказ',seller_per_order:'Продавец, ₽/заказ',pvz_per_day:'ПВЗ, ₽/день'})
    .map(([key,label])=>field(label,key,'number',fleetFormState.targets[key]/100,'required min=".01" max="10000" step=".01"')).join('');
  const description=fleetSettings.scenarios[fleetFormState.scenario]?.description;
  dialogBox('Параметры работы парка',form('fleet-plan-form','<div class="stack">'+
    selectField('Рабочий день','fleet_scenario',scenarios,fleetFormState.scenario)+
    (description?'<p class="notes">'+esc(description)+'</p>':'')+
    selectField('Договор для модели','fleet_contract',Object.keys(fleetSettings.contracts).map(key=>[key,prof(key)]),fleetFormState.contract)+
    '<label><input type="checkbox" name="fleet_transfer" '+(fleetFormState.allow_transfer?'checked':'')+'> Разрешить передачу через ПВЗ</label>'+
    vehicles+button('fleet-add','Добавить машину','plus',false,fleetFormState.trucks.length>=6?'disabled':'')+
    '<details><summary>Целевые значения прибыли для договора</summary><div class="fields">'+targets+'</div></details>'+
    '<details><summary>Топливо, ставки и сравнение с хабом</summary><div class="fields">'+rates+'</div></details></div>','Рассчитать парк'));
}

function changeFleetVehicles(remove){
  captureFleetForm();
  if(remove!==undefined)fleetFormState.trucks.splice(remove,1);
  else{
    let n=1;
    while(fleetFormState.trucks.some(v=>v.id==='М'+n))n++;
    fleetFormState.trucks.push({id:'М'+n,start:'A',end:'B',start_min:600,end_min:930,liters:150,kg:120,planned:false});
  }
  fleetForm();
}

async function calculateFleet(){
  captureFleetForm();
  const result=await api('fleet',{action:'plan',...fleetFormState});
  fleetDraft=result.plan;
  fleetSelected=null;
  fleetFocus=null;
  fleetPoint='';
  moveMap(0,0,1);
  dialog.close();
  render();
}

async function fleetCommand(action,data={}){
  const request=action==='confirm'?{action,...fleetDraft.request,fingerprint:fleetDraft.fingerprint}:
    {action,day_id:fleetDay.id,version:fleetDay.version,truck:fleetSelected,...data};
  const response=await api('fleet',request);
  fleetDay=response.day;
  fleetDraft=null;
  fleetFocus=null;
  dialog.close();
  await refresh();
}

function fleetEconomics(view){
  const e=view.economics;
  const rates=view.prices;
  return '<section class="panel spaced"><div class="panel-head"><h2>Экономика рабочего дня</h2>'+
    '<a class="btn" href="/economics.md" download="economics.md">Скачать расчётную методику</a></div><div class="panel-body">'+
    stats([['truck','Через парк',num(e.units)+' / '+num(e.total_units)],['route','С передачей в ПВЗ',num(e.relayed_units)],
      ['trend','Эффект после координации',signed(e.savings)],['target','Порог расходов хаба',e.units?money(e.break_even_per_unit)+' / шт.':'—']])+
    table(['Схема','Ожидаемые расходы'],[
      ['Все через хаб',money(e.all_hub)],['Парк без передачи между машинами',money(view.without_relay)],
      ['Выбранная схема парка + остаток через хаб',money(e.total)]])+
    (e.active_trial_delta<0?'<p class="notice">При запуске парка в этих условиях результат составил бы '+signed(e.active_trial_delta)+'. План оставляет заказы на базовой схеме.</p>':'')+
    '<details><summary>Из чего складывается результат</summary>'+table(['Статья','Сумма'],[
      ...Object.entries(e.costs).map(([key,value])=>[esc(fleetCostNames[key]||key),money(value)]),
      ['Координация',money(e.coordination)],['Отправления, оставшиеся на хабе',money(e.remaining_hub)]])+
    '<p class="notes">Дизель '+num(rates.diesel)+' ₽/л, расходы хаба '+num(rates.hub_city)+' ₽ в городе и '+num(rates.hub_rural)+' ₽ с сельским плечом на посылку. Все сценарии сравниваются на одинаковом потоке.</p></details>'+
    (e.hub_remaining.length?'<details><summary>Передано в базовую схему · '+num(e.total_units-e.units)+' посылок</summary>'+
      table(['Партия','Направление','Посылки'],e.hub_remaining.map(b=>[esc(b.id),esc(loc(b.from)+' → '+loc(b.to)),num(b.qty)]))+'</details>':'')+
    '</div></section>'+fleetPoints(e);
}

function fleetPoints(e){
  if(!e.by_pvz)return '';
  const sum=key=>e.by_pvz.reduce((total,p)=>total+p[key],0);
  const finances=p=>[esc(loc(p.point)),num(p.requested),num(p.hub),money(p.baseline),money(p.actual),signed(p.rwb_effect)];
  const partners=p=>[esc(loc(p.point)),num(p.pickup),num(p.drop),num(p.relay_drop+p.relay_pickup),num(p.work_minutes)+' мин',
    money(p.pvz_revenue),money(p.pvz_cost),signed(p.pvz_margin),money(p.seller_rebate)];
  return '<section class="panel spaced"><div class="panel-head"><h2>Экономика по ПВЗ</h2></div><div class="panel-body stack">'+
    '<p class="notes">Результат RWB относится к ПВЗ выдачи. Если точка только отправляет груз, её работа видна в расчёте для партнёров.</p>'+
    table(['ПВЗ выдачи','Заказы','Через хаб','База через хаб','Расходы по плану','Эффект RWB'],[
      ...e.by_pvz.map(finances),['<strong>Всего</strong>',num(sum('requested')),num(sum('hub')),money(sum('baseline')),
        money(sum('actual')),signed(sum('rwb_effect'))]])+
    '<details><summary>Работа и экономика партнёров</summary>'+
    '<p class="notes">Приём и передача на промежуточной точке считаются двумя операциями. Скидка продавцам показана по ПВЗ выдачи.</p>'+
    table(['ПВЗ','Погружено','Выгружено к выдаче','Операции в буфере','Труд','Компенсация','Себестоимость','Маржа ПВЗ','Скидка продавцам'],[
      ...e.by_pvz.map(partners),['<strong>Всего</strong>',num(sum('pickup')),num(sum('drop')),num(sum('relay_drop')+sum('relay_pickup')),
        num(sum('work_minutes'))+' мин',money(sum('pvz_revenue')),money(sum('pvz_cost')),signed(sum('pvz_margin')),money(sum('seller_rebate'))]])+
    '</details></div></section>';
}

function fleetTrips(view){
  const active=view===fleetDay;
  const routes=view.trucks.filter(v=>v.used);
  const truck=routes.find(v=>v.id===fleetSelected)||routes[0];
  if(!truck)return panel('Маршрутные листы',empty('Машины остаются на базовом расписании.'));
  fleetSelected=truck.id;
  const focused=fleetFocus??truck.cursor??0;
  const activeStop=active&&truck.status==='RUNNING'?truck.stops[truck.cursor]:null;
  const plan={stops:truck.stops.map(v=>({id:v.point})),legs:truck.stops.slice(1).map((v,i)=>truckLeg(truck.stops[i].point,v.point)),focus:focused};
  const zoomTools='<div class="map-tools">'+[['minus','Уменьшить'],['plus','Увеличить'],['fit','Вся сеть']].map(([a,v])=>'<button data-action="zoom-'+a+'" title="'+v+'" aria-label="'+v+'">'+icon(a,15)+'</button>').join('')+'</div>';
  const choices=view.trucks.map(v=>button('fleet-truck',fleetTruckName(v)+' · '+(v.used?(fleetTruckStates[v.status]||num(v.km)+' км'):'Без добавочных заказов'),'truck',
    v.id===truck.id,'data-id="'+esc(v.id)+'" '+(v.used?'':'disabled'))).join('');
  const stops=truck.stops.map((v,i)=>[linkButton('fleet-stop',i,String(i+1)+'. '+loc(v.point)),
    esc(fleetClock(v.arrive))+'–'+esc(fleetClock(v.leave)),
    v.events.length?v.events.map(event=>{
      const locNow=active?view.custody[event.batch]:null;
      const relayWaiting=active&&event.kind==='relay_pickup'&&locNow?.kind!=='relay';
      const operation=event.done?(event.late?'Готово с задержкой':'Готово'):fleetNames[event.kind];
      const hint=relayWaiting&&!event.done?' · ждёт передачи':'';
      const orderIds=view.batches[event.batch].orders?.map(o=>o.id).join(', ');
      const product=view.batches[event.batch].orders?.[0]?.title;
      return '<div class="fleet-task"><span>'+esc(event.batch)+' · '+num(event.qty)+' шт. · '+esc(operation+hint)+
        (product?'<br><small>'+esc(product)+'</small>':'')+
        (orderIds?'<br><small>'+esc(orderIds)+'</small>':'')+'</span>'+
        (v===activeStop&&!event.done?button('fleet-scan','Отметить','scan',false,'data-id="'+esc(event.batch)+'" data-kind="'+esc(event.kind)+'" '+(relayWaiting?'disabled':'')):'')+'</div>';
    }).join(''):'—',
    num(v.liters_after??0)+' л · '+num(v.kg_after??0)+' кг']);
  const ctl=active&&role==='dispatcher'?(truck.status==='PLANNED'?button('fleet-start','Начать рейс','play',true):
    activeStop?button('fleet-next','Завершить остановку','route',true,' '+(activeStop.events.every(e=>e.done)?'':'disabled')):''):'';
  const relay=active?Object.entries(view.custody).filter(([,item])=>item.kind==='relay').map(([id,item])=>[esc(id),esc(loc(item.owner)),num(view.batches[id].qty)]):[];
  return '<section class="panel spaced"><div class="panel-head"><h2>Парк машин</h2><div class="section-actions">'+choices+'</div></div>'+
    '<div class="map-wrap">'+networkMap('A','B','SHARED_TRIP',plan)+zoomTools+'</div>'+
    '<div class="panel-body"><div class="section-actions">'+ctl+'</div>'+
    (activeStop?'<p class="notice">Текущая остановка · '+esc(loc(activeStop.point))+'</p>':'')+
    table(['ПВЗ','Время, мск','Партии и операции','Загрузка по плану'],stops)+
    (relay.length?'<h3>Буфер передачи</h3>'+table(['Партия','ПВЗ','Посылки'],relay):'')+
    (active&&view.journal.length?'<details><summary>Журнал фактических операций</summary>'+table(['Время','Машина','ПВЗ','Партия','Операция'],view.journal.map(e=>[
      esc(fleetClock(e.at)),esc(e.truck),esc(loc(e.point)),esc(e.batch),esc(fleetNames[e.kind])]))+'</details>':'')+'</div></section>';
}

const fleetTruckName=v=>v.index?'№ '+v.index+' · '+v.id:v.id;
const fleetChannel=channel=>channel==='fleet'?'Парк':'Хаб';
const fleetRange=(minimum,maximum)=>maximum==null||maximum<minimum?'Нет диапазона':money(minimum)+'–'+money(maximum);

function fleetWorkday(view){
  const active=view===fleetDay;
  const planned=view.trucks.filter(v=>v.used);
  const dispatched=planned.filter(v=>v.status==='RUNNING'||v.status==='DONE');
  const cost=v=>Object.values(v.costs).reduce((sum,part)=>sum+part,0);
  const delivered=Object.entries(view.custody||{}).reduce((sum,[id,custody])=>
    sum+(custody.kind==='delivered'?view.batches[id].qty:0),0);
  const visits=planned.flatMap(v=>v.stops.filter(stop=>stop.events.length).map(stop=>({...stop,vehicle:v})))
    .sort((a,b)=>(a.service_from??a.arrive)-(b.service_from??b.arrive));
  const points=[...new Set(visits.map(visit=>visit.point))].sort((a,b)=>loc(a).localeCompare(loc(b),'ru'));
  const rows=visits.filter(visit=>!fleetPoint||visit.point===fleetPoint).map(visit=>[
    esc(loc(visit.point)),esc(fleetTruckName(visit.vehicle)),visit.bay??'—',
    fleetTime(visit.service_from??visit.arrive)+'–'+fleetTime(visit.leave),
    visit.events.map(e=>'<div>'+esc(fleetNames[e.kind])+' · '+esc(e.batch)+' · '+num(e.qty)+' шт.'+
      (e.done?' ✓ '+fleetTime(e.actual):'')+'</div>').join('')
  ]);
  return panel('Рабочий день парка',pad('<div class="stack">'+
    stats([['truck',active?'Выехали / запланировано':'Машин в плане',active?dispatched.length+' / '+planned.length:num(planned.length)],
      ['box',active?'Доставлено / в плане':'Заказов через парк',active?delivered+' / '+view.economics.units:num(view.economics.units)],
      ['hub','Заказов через хаб',num(view.economics.total_units-view.economics.units)],
      ['receipt',active?'Смета выехавших машин':'Смета машин в плане',money((active?dispatched:planned).reduce((sum,v)=>sum+cost(v),0))]])+
    '<details><summary>Смета и заказы по машинам</summary>'+table(['Машина','Маршрут','Заказов на борту за рейс','Пробег','Смета рейса'],
      view.trucks.map(v=>[esc(fleetTruckName(v)),esc(loc(v.start)+' → '+loc(v.end)),
        num(v.stops.reduce((sum,stop)=>sum+stop.events.filter(e=>e.kind==='pickup'||e.kind==='relay_pickup')
          .reduce((units,e)=>units+e.qty,0),0)),v.used?num(v.km)+' км':'—',v.used?money(cost(v)):'—']))+'</details>'+
    '</div>'))+
    panel('Расписание погрузки и выгрузки',pad('<div class="stack">'+
      (points.length?selectField('ПВЗ','fleet_point',[['','Все ПВЗ'],...points.map(point=>[point,loc(point)])],fleetPoint):'')+
      table(['ПВЗ','Машина','Место','Работа, мск','Операции по порядку'],rows,'Для выбранных условий погрузок и выгрузок нет.')+'</div>'));
}

function fleetFinances(view){
  const f=view.financials;
  if(!f)return '';
  const live=view.live_results;
  const allOrders=f.orders.map(o=>[
    view.scenario==='live'?linkButton('order-detail',o.id,o.id):esc(o.id),
    esc(o.title+' · '+o.sku),esc(o.seller),esc(loc(o.from)+' → '+loc(o.to)),num(o.liters)+' л · '+num(o.kg)+' кг',
    fleetTime(o.due),o.route.length?o.route.map(leg=>'<div>'+esc('№ '+leg.index+' '+leg.truck+' · '+loc(leg.point)+' · ') +
      fleetTime(leg.at)+' · '+esc(fleetNames[leg.operation])+'</div>').join(''):'Хаб · время не рассчитано'
  ]);
  return panel('Прогноз прибыли за день',pad('<div class="stack">'+stats([
    ['trend','Вклад RWB',signed(f.rwb_profit)],['box','Маржа ПВЗ за работу парка',signed(f.pvz_profit)],
    ['person','Вклад продавцов',signed(f.seller_profit)],['receipt','Расходы RWB',money(f.rwb_cost)]
  ])+'<p class="sub">'+esc(prof(f.profile))+' · Модель при продаже всех заказов потока, до налогов и общих затрат.</p>'+
  '<details><summary>Разбивка по продавцам</summary>'+table(['Продавец','Заказы','Через парк','Продажи','Себестоимость товара','Комиссия','Логистика','Вклад'],
    f.by_seller.map(o=>[esc(o.id),num(o.orders),num(o.direct),money(o.revenue),money(o.goods),money(o.commission),money(o.logistics),signed(o.profit)]))+'</details>'+
  '<details><summary>Распределение заказов · '+num(f.orders.length)+'</summary>'+table(
    ['Заказ','Товар','Продавец','ПВЗ отправления и выдачи','Объём и масса','Срок, мск','Маршрут и операции'],allOrders)+'</details></div>'),
    button('fleet-export','Экспорт плана JSON','receipt'))+
  (live?panel('Начисления за день по отправленным заказам',pad(stats([
    ['trend','Вклад RWB',signed(live.rwb_profit)],['box','Маржа ПВЗ',signed(live.pvz_profit)],
    ['person','Вклад продавцов',signed(live.seller_profit)],['receipt','Расходы RWB · '+num(live.orders)+' зак.',money(live.rwb_cost)]
  ])+'<p class="sub">Данные журнала за дату плана. Выручка от продажи и комиссия появляются после выдачи покупателю.</p>')):'')+
  panel('Рекомендации для договора',pad('<div class="stack"><p class="sub">Целевой вклад за заказ · RWB '+money(f.targets.rwb_per_order)+
    ' · Продавец '+money(f.targets.seller_per_order)+' · Целевая маржа ПВЗ за день '+money(f.targets.pvz_per_day)+'</p>'+
    '<details><summary>Логистика продавца · ₽ за заказ</summary>'+table(
      ['Продавец','ПВЗ выдачи','Канал','Заказы','Сейчас','Допустимый диапазон','Рекомендуемая ставка'],
      f.seller_rates.map(r=>[esc(r.seller),esc(loc(r.point)),fleetChannel(r.channel),num(r.orders),money(r.current),
        fleetRange(r.minimum,r.maximum),r.recommended==null?'Пересмотреть условия':money(r.recommended)]))+'</details>'+
    '<details><summary>Оплата работы ПВЗ · ₽ в час</summary><p class="sub">Диапазоны рассчитаны при текущих тарифах продавцов и доплатах за буфер.</p>'+
      table(['ПВЗ','Работа, мин','Сейчас','Допустимый диапазон','Рекомендуемая ставка','Маржа ПВЗ за день'],
        f.pvz_rates.map(r=>[esc(loc(r.point)),num(r.minutes),money(r.current),fleetRange(r.minimum,r.maximum),
          r.recommended==null?'Пересмотреть условия':money(r.recommended),signed(r.profit)]),
        'Парк не выполняет операций в ПВЗ.')+'</details></div>'));
}

function exportFleet(){
  const view=fleetDraft||fleetDay;
  if(!view?.financials)return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(view,null,2)],{type:'application/json'}));
  const link=document.createElement('a');
  link.href=url;
  link.download='fleet-'+view.date+'.json';
  link.click();
  setTimeout(()=>URL.revokeObjectURL(url),200);
}

function fleetPage(){
  const view=fleetDraft||fleetDay;
  const canPlan=role==='dispatcher';
  if(!fleetSettings)return title('Парк машин')+empty('Загружаем параметры парка…');
  return title('Парк машин',view?view.date+' · '+(fleetSettings.scenarios[view.scenario]?.title||'Собранные заказы смены')+
    ' · '+(fleetDraft?'Расчёт рабочего дня':fleetDay.status==='DONE'?'Рабочий день завершён':'Подтверждённый план'):
    'Маршруты с погрузкой, выгрузкой и передачей между машинами',
    (canPlan?button('fleet-form','Рассчитать парк','truck',true):'')+
    (fleetDraft&&canPlan?button('fleet-confirm','Подтвердить план','scan',false,
      fleetDraft.economics.units&&fleetDay?.status!=='ACTIVE'?'':'disabled'):'')+
    (fleetDraft&&fleetDay?button('fleet-current','Активный план','route'):'')+button('fleet-refresh','Обновить','refresh'))+
    (view?fleetWorkday(view)+fleetTrips(view)+fleetFinances(view)+fleetEconomics(view):
      empty(canPlan?'Выберите тип рабочего дня и укажите машины.':'Диспетчер ещё не подтвердил план парка.'));
}
