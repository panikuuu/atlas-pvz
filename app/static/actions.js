'use strict';
let lastOrderInfo=null;
const receiptPackages={
  S:{label:'S · компактная упаковка',dimensions:[250,160,50],mass:600},
  M:{label:'M · средняя упаковка',dimensions:[300,200,100],mass:1800},
  SMARTPHONE:{label:'SMARTPHONE · смартфон',dimensions:[180,95,55],mass:380,sale:70000,cost:50000},
};
function field(label,name,type,value,attrs=''){
  return '<label>'+esc(label)+'<input name="'+esc(name)+'" type="'+esc(type)+'" value="'+esc(value)+'" '+attrs+'></label>';
}
function selectField(label,name,opts,current){
  return '<label>'+esc(label)+'<select name="'+esc(name)+'" required>'+opts.map(([k,v])=>'<option value="'+esc(k)+'" '+(k===current?'selected':'')+'>'+esc(v)+'</option>').join('')+'</select></label>';
}
function form(id,html,submit='Подтвердить'){
  return '<form id="'+id+'">'+html+'<div class="dialog-actions">'+button('dismiss','Отмена')+'<button class="btn primary">'+esc(submit)+'</button></div></form>';
}
function restrictDestination(form,source){
  const select=form.elements.destination||form.elements.pvz_id;
  for(const option of select.options)option.disabled=option.value===source;
  if(select.selectedOptions[0]?.disabled)select.value=[...select.options].find(o=>!o.disabled)?.value||'';
}
function directionForm(){
  const points=pickupOptions();
  dialogBox('Рабочее направление',form('direction-form','<div class="fields">'+
    selectField('ПВЗ отправления','source',points,s.settings.source)+
    selectField('ПВЗ выдачи','destination',points,s.settings.destination)+'</div>','Открыть окно'));
  restrictDestination($('#direction-form'),s.settings.source);
}
function compare(){
  const q=s.quote;if(!q){toast('Сначала рассчитайте предложение для открытых заказов.');return;}
  const references=[['Момент фиксации',tm(q.fixed_at)],['Исходные данные',q.scenario_version],['Версия тарифа',q.tariff_version],['База через хаб для всей партии',money(q.hub_reference_cost)],['Экономия относительно хаба из локального запаса',signed(q.savings)],['Индекс экономии',q.index==null?'Нет оценки':num(q.index)+' из 100']];
  const cards=q.candidates.map(c=>'<details '+(q.selected===c.mode?'open':'')+'><summary>'+esc(modes[c.mode])+' · '+money(c.route_cost)+' · '+esc(c.eligible?(c.mode===q.selected?'выбран':'доступен'):reasons[c.reason]||c.reason)+'</summary>'+dl([['Обслужено рейсом',num(c.fits_count??c.order_count)+' / '+num(q.orders_count)],['Перевозка',money(c.carrier_cost)],['Постоянная часть',money(c.fixed_carrier_cost)],['Переменная часть на единицу',money(c.carrier_per_unit)],['Упаковка партии',money(c.packaging_cost)],['Ожидаемые возвраты и сбои',money(c.risk_cost)],['Потеря тарифной выручки',money(c.lost_tariff_revenue)],['Расходы маршрута на заказ',money(c.per_order_cost)],['Эффект маршрута',signed(c.savings)],['Готовность от момента заказа',num(c.ready_hours)+' ч'],['Индекс',c.eligible?num(c.index):'Недоступно'],['Обоснование',reasons[c.reason]||c.reason],['Прогноз опоздания',c.late_hours==null?'Нет оценки':num(c.late_hours)+' ч'],...(c.mode==='SHARED_TRIP'?[['Предел затрат на остановку',money(c.maximum_stop_cost)],['Крюк',num(q.settings?.detour_km)+' км / '+num(q.settings?.detour_minutes)+' мин']]:[])] )+'</details>').join('');
  const plans=table(['План','По манифестам','Эффект'],q.plans.map(p=>[esc(modes[p.mode]||p.mode),Object.entries(p.allocations||{}).filter(([,v])=>v.length).map(([k,v])=>esc((modes[k]||k)+' · '+v.join(', '))).join('<br>')||esc(reasons[p.reason]||p.reason),p.eligible?signed(p.savings):'Недоступно']));
  dialogBox('Расчёт рейса', '<div class="stack"><div class="notice">'+esc(modes[q.selected])+' · '+esc(reasons[q.reason]||q.reason)+'</div>'+dl(references)+'<p class="notes">Индекс показывает долю положительной экономии в расходах хаба. Потеря тарифной выручки уменьшает экономию. Общая сборка и выдача учитываются в результате программы.</p><div>'+cards+'</div><details><summary>Распределение партии по четырём планам</summary>'+plans+'</details>'+button('settings','Изменить условия рейса','filter')+'</div>');
}
function pointDetails(id){
  const point=s.points.find(p=>p.id===id),rd=s.quote?.readiness?.[id===s.settings.source?'source':id===s.settings.destination?'destination':'other'];
  const stock=s.lots.filter(l=>l.pvz_id===id),ready=s.orders.filter(o=>o.destination===id&&o.status==='READY_FOR_PICKUP');
  if(!point && id!=='HUB'){dialogBox(pointName(id),dl([['Местность',stations[id].area],['Расписание','Рейсы в текущей смене отсутствуют']]));return;}
  if(!point){dialogBox('Распределительный хаб',dl([['Товар на хабе',num(s.lots.reduce((n,l)=>n+l.at_hub,0))+' ед.'],['Схема доставки','Через централизованную обработку']]));return;}
  dialogBox('ПВЗ '+pointName(id),'<div class="stack">'+dl([['Вместимость',num(point.capacity_l)+' л'],['Занято / свободно',num(point.occupied_l)+' / '+num(point.free_l)+' л'],['Доступно в рабочем окне',num(point.minutes)+' мин'],['Готовы к выдаче',num(ready.length)+' шт.'],['SKU в принятых партиях',[...new Set(stock.map(l=>l.sku_id))].join(', ')||'—'],...(rd?[['Готовность ПВЗ к партии',num(rd.index)+' из 100'],['Требуется дополнительно',num(rd.required_liters)+' л и '+num(rd.required_minutes)+' мин']]:[])])+table(['Партия','На полке','Резерв'],stock.map(l=>[linkButton('lot-detail',l.id,l.id),num(l.available),num(l.reserved)]),'На этой точке нет принятых партий.')+'</div>');
}
function settingsForm(){
  const cfg=s.settings,{q,src,dest}=routeState();
  const orders=s.orders.filter(o=>['ASSEMBLED','RESERVED'].includes(o.status)&&o.source===src&&o.destination===dest);
  const count=q?.order_ids?.length??orders.length;
  dialogBox('Условия рейса',form('conditions','<div class="stack"><div class="notice">'+esc(loc(src)+' → '+loc(dest))+' · '+esc(s.window_id)+'</div><div class="fields">'+field('Заказов в расчёте','count','number',Math.min(count,orders.length),'required step="1" min="'+(orders.length?1:0)+'" max="'+orders.length+'"')+field('Попутные места','shared_slots','number',cfg.shared_slots,'min="0" step="1"')+field('Попутный объём, л','shared_liters','number',cfg.shared_liters,'min="0" step="any"')+field('Попутный груз, г','shared_grams','number',cfg.shared_grams,'min="0" step="1"')+
  field('Готовность попутным рейсом, ч','shared_ready_hours','number',cfg.shared_ready_hours,'min="0" step="any"')+field('Готовность отдельным рейсом, ч','dedicated_ready_hours','number',cfg.dedicated_ready_hours,'min="0" step="any"')+field('Готовность через хаб, ч','hub_ready_hours','number',cfg.hub_ready_hours,'min="0" step="any"')+field('Доступно на сборку, мин','origin_minutes','number',cfg.origin_minutes,'min="0" step="any"')+field('Доступно в точке выдачи, мин','destination_minutes','number',cfg.destination_minutes,'min="0" step="any"')+field('Свободно в точке выдачи, л','destination_liters','number',cfg.destination_liters,'min="0" step="any"')+'</div><details><summary>Расписание и часы работы</summary><div class="fields">'+
  field('Дополнительный пробег попутного рейса, км','detour_km','number',cfg.detour_km,'min="0" step="any"')+
  field('Дополнительное время попутного рейса, мин','detour_minutes','number',cfg.detour_minutes,'min="0" step="any"')+
  ['shared','dedicated','hub'].map((k,i)=>[['departure_at','Выезд'],['handoff_at','Сдать до']].map(([suffix,label])=>field(label+' · '+['попутный','отдельный','хаб'][i]+', мск',k+'_'+suffix,'datetime-local',cfg[k+'_'+suffix]?isoField(cfg[k+'_'+suffix]):'')).join('')).join('')+field('Закрытие ПВЗ выдачи, мск','destination_close_at','datetime-local',cfg.destination_close_at?isoField(cfg.destination_close_at):'')+'</div><p class="micro">Для фиксированного рейса задайте выезд и время передачи. Время готовности включает ожидание этого выезда.</p></details><p class="micro">Ноль мест закрывает попутный рейс. Пустое поле означает отсутствие данных. Первыми распределяются заказы с ближайшим обещанным сроком.</p></div>','Пересчитать'));
}
function profileForm(){
  const body='<div class="stack">'+table(['Договор','Сборка ПВЗ','Прямой тариф продавцу','Через хаб'],[['Пилотный','12 ₽','85 ₽','92 ₽'],['Исходный','16 ₽','82 ₽','92 ₽']])+
  selectField('Активный договор','profile',[['pilot','Пилотный договор'],['original','Исходный договор']],s.profile)+'<p class="notes">Новые предложения рассчитываются по выбранным ставкам. В начислениях хранится версия тарифа на момент операции.</p></div>';
  dialogBox('Тарифный профиль',form('profile-form',body,'Применить профиль'));
}
function receiptForm(){
  const promptId='LOT-'+String(s.lots.length+1).padStart(3,'0');
  dialogBox('Приёмка партии',form('receipt-form','<div class="fields">'+field('Номер партии','lot_id','text',promptId,'required maxlength="100"')+field('Штрихкод','barcode','text','S','required')+
    selectField('ПВЗ приёмки','pvz_id',pickupOptions(),s.settings.source)+selectField('SKU','sku_id',Object.entries(receiptPackages).map(([id,item])=>[id,item.label]),'S')+
    field('Количество','quantity','number',1,'min="1" step="1" required')+field('Масса единицы, г','mass_g','number',600,'min="1" required')+
    ['Длина','Ширина','Высота'].map((name,i)=>field(name+' единицы, мм','dim'+i,'number',receiptPackages.S.dimensions[i],'min="1" required')).join('')+
    field('Разрешённое хранение, сут.','storage_days','number',30,'min="1" required')+
    field('Цена продажи, ₽','sale_price','number','','min="0" step="0.01"')+field('Себестоимость, ₽','cost_price','number','','min="0" step="0.01"')+
    '</div><p id="receipt-preview" class="notes spaced"></p>','Подтвердить приёмку'));
  receiptPreview();
}
function receiptPreview(){
  const f=$('#receipt-form');if(!f)return;const data=new FormData(f),n=Number(data.get('quantity')),ls=[0,1,2].reduce((x,i)=>x*Number(data.get('dim'+i)),n)/1e6,p=s.points.find(p=>p.id===data.get('pvz_id'));
  $('#receipt-preview').textContent='Партия займёт '+num(ls)+' л. После приёмки в ПВЗ останется '+num(p?p.free_l-ls:null)+' л. Хранение продавцу — 0,50 ₽ за литр в сутки. Обработка возврата — 30 ₽.';
}
function orderStockPoints(lot){
  if(lot.available_by_pvz)return Object.entries(lot.available_by_pvz).filter(([id,count])=>id!=='HUB'&&count>0);
  if(!lot.positions)return lot.available&&lot.pvz_id?[[lot.pvz_id,lot.available]]:[];
  return Object.entries(lot.positions).flatMap(([position,count])=>{
    const [point,status]=position.split(':');
    return status==='AVAILABLE'&&point!=='HUB'&&count>0?[[point,count]]:[];
  });
}
function newOrder(){
  const lots=s.lots.filter(l=>orderStockPoints(l).length);
  if(!lots.length){dialogBox('Создание заказа',empty('Свободных единиц нет. Примите партию в разделе «Склад и смена» под ролью сотрудника ПВЗ.'));return;}
  const points=pickupOptions();
  const shippingPoints=[['original','ПВЗ первичной приёмки'],...points,['unknown','Нет данных']];
  dialogBox('Тестовый заказ',form('order-form','<div class="fields">'+selectField('Партия','lot_id',lots.map(l=>[l.id,l.id+' · '+l.sku_id+' · '+l.available+' шт.']),lots[0].id)+
    selectField('Точка отгрузки продавца','seller_ship_from_pvz_id',shippingPoints,'original')+
    selectField('Фактический старт груза','stock_source_pvz_id',[],'')+
    selectField('ПВЗ выдачи','pvz_id',points,s.settings.destination)+field('Исходный срок, мск','promised_at','datetime-local','','required')+
    '<label>Цена доставки покупателю<input value="0 ₽" readonly></label><label class="checkbox wide"><input type="checkbox" name="consent">Покупатель выбрал дополнительное окно</label><label class="wide" id="chosen-label" hidden>Выбранный срок, мск<input type="datetime-local" name="selected_promised_at" disabled></label></div><p class="notes spaced">Будет зарезервирована одна единица из выбранной партии.</p>','Зарезервировать единицу'));
  updateOrderStockPoints($('#order-form'));
}
function updateOrderStockPoints(form){
  const fields=form.elements,lot=s.lots.find(l=>l.id===fields.lot_id.value);
  const sources=orderStockPoints(lot),select=fields.stock_source_pvz_id;
  select.replaceChildren(...sources.map(([id,count])=>new Option(pointName(id)+' · '+num(count)+' шт.',id)));
  select.value=sources.some(([id])=>id===lot.pvz_id)?lot.pvz_id:sources[0][0];
  fields.seller_ship_from_pvz_id.options[0].textContent='ПВЗ первичной приёмки · '+loc(lot.pvz_id);
  setOrderDestination(form);
}
function setOrderDestination(form){
  const fields=form.elements;
  const source=fields.stock_source_pvz_id.value;
  const rural=[source,fields.pvz_id.value].some(id=>stations[id]?.area!=='Город');
  const ready=Date.parse(s.now)+(rural?48:24)*3600000;
  for(const [field,value] of [[fields.promised_at,isoField(ready)],[fields.selected_promised_at,isoField(ready+86400000)]]){
    const keep=field.value!==field.defaultValue;
    field.defaultValue=value;
    if(!keep)field.value=value;
  }
}
function lotDetails(id){
  const l=s.lots.find(l=>l.id===id);if(!l)return;
  const positions=Object.entries(l.positions||{}),withdraw=positions.filter(([k,n])=>k.endsWith('WITHDRAW_RESERVED')&&n).length>0,inTransit=positions.some(([k,n])=>k==='WITHDRAW_IN_TRANSIT'&&n);
  const actions=[];if(role==='seller'&&l.available)actions.push('WITHDRAW_REQUESTED');if(role==='pvz'||role==='dispatcher'){if(withdraw)actions.push('WITHDRAW_SENT');if(inTransit)actions.push('WITHDRAW_RECEIVED');}
  const age=Math.max(0,Math.floor((new Date(s.now)-new Date(l.accepted_at))/86400000));
  const next=+new Date(l.accepted_at)+(age+1)*86400000;
  dialogBox('Партия '+l.id,'<div class="stack">'+dl([['SKU и штрихкод',l.sku_id+' · '+l.barcode],['Место и время приёмки',loc(l.pvz_id)+' · '+tm(l.accepted_at)],['Упаковка',l.dimensions_mm?.join(' × ')+' мм · '+num(l.volume_l)+' л · '+num(l.mass_g)+' г'],['Возраст / срок хранения',age+' / '+num(l.storage_limit_days)+' сут.'],['Следующие полные сутки на исходной полке',l.occupied_l?tm(next):'—'],['Хранение продавцу',money(50*l.volume_l)+' / ед. в сутки'],['Цена / себестоимость',money(l.sale_price)+' / '+money(l.cost_price)],['Комиссия с продажи',money(Math.round(l.sale_price*.15))],['Исходящая логистика',money(s.profile==='pilot'?8500:8200)+' напрямую / 92 ₽ через хаб'],['Прогноз прибыли при прямой продаже после суток',money(l.sale_price-l.cost_price-Math.round(l.sale_price*.15)-(s.profile==='pilot'?8500:8200)-50*l.volume_l)],['Обработка годного возврата','30 ₽; сторно продажи и комиссии']])+table(['Местонахождение','Остаток'],positions.map(([k,n])=>[esc(place(k)),num(n)]))+'<div class="section-actions">'+actions.map(k=>button('lot-event',processes[k],'truck',true,'data-id="'+esc(id)+'" data-kind="'+k+'"')).join('')+'</div></div>');
}
async function orderDetails(id){
  const info=await api('orders/'+encodeURIComponent(id));const o=info.order||info;lastOrderInfo=info;
  const fin=o.financials||{},q=info.decision;
  const ordering=role==='pvz'||role==='dispatcher';
  const rows=[['Партия',o.lot_id],['Исходное обещание',tm(o.original_promised_at)+' · '+money(o.delivery_price)],['Выбранное обещание',tm(o.promised_at)+' · '+money(o.delivery_price)],['Согласие на перенос',o.consent?'Да':'Нет'],['Готовность по факту',tm(o.ready_at)],['Опоздание к исходному сроку',o.ready_at?num(o.late_hours)+' ч':'—'],['Манифест',o.dispatch_id||'Ещё не закреплён'],['Схема',modes[o.mode]||'Ожидает решения'],['Расходы RWB',money(fin.rwb_cost)],['Результат продавца',money(fin.seller_profit)],['Вклад RWB',money(fin.rwb_contribution)],['Вклад при централизованной доставке',money(fin.central_contribution)],['Эффект программы',signed(fin.program_delta)]];
  if(q)rows.push(['Снимок решения',q.tariff_version+' · '+tm(q.fixed_at)],['Экономия маршрута на всю партию',signed(q.savings)]);
  const moves=(info.movements?.length?info.movements:(s.movements||[]).filter(m=>m.unit_id===o.unit_id));
  dialogBox('Заказ '+o.id,'<div class="stack"><div>'+stateBadge(o.status)+'</div>'+orderGeography(o)+dl(role==='seller'?rows.filter(([k])=>!k.includes('RWB')&&!k.includes('централизованной')&&!k.includes('программы')):rows)+
    (ordering?'<div class="section-actions">'+eventsFor(o).map(k=>button('order-event',processes[k],'scan',k!=='INCIDENT','data-kind="'+k+'" data-id="'+esc(o.id)+'"')).join('')+'</div>':'')+
    '<details><summary>История движения</summary>'+table(['Время','Откуда','Куда'],moves.map(m=>[tm(m.at),esc(place(m.from)),esc(place(m.to))]))+'</details>'+button('download','Экспортировать объяснение','download')+'</div>');
}
function orderGeography(order){
  const g=order.geography;
  if(!g)return dl([['Маршрут',loc(order.source)+' → '+loc(order.destination)]]);
  const types={city:'город',town:'посёлок',village:'село',hamlet:'деревня'};
  const describe=({point_id,locality})=>{
    if(!point_id)return 'Точка не указана';
    const place=locality?types[locality.type]+' '+locality.name+' · '+locality.region_name:'Населённый пункт не определён';
    return loc(point_id)+' · '+place;
  };
  const comparisons={same_locality:g.seller_ship_from.locality?.type==='city'?'Один город':'Один населённый пункт',
    different_localities:'Разные населённые пункты',unknown:'Недостаточно данных'};
  const scopes={local:'Локальное направление',intercity:'Межгород',rural:'Сельское плечо',unknown:'Недостаточно данных'};
  const rows=[
    ['Продавец и покупатель',comparisons[g.relation]],
    ['Точка отгрузки продавца',describe(g.seller_ship_from)],
    ['ПВЗ выдачи',describe(g.buyer_pickup)],
    ['Основание',g.reason],
    ['Фактический старт груза',describe(g.stock_start)],
    ['Плечо доставки',scopes[g.route_scope]],
  ];
  if(g.road_km!=null)rows.push(['Расстояние по дорогам',num(g.road_km)+' км']);
  if(g.direct_block)rows.push(['Проверка прямого рейса',reasons[g.direct_block]]);
  return '<section class="stack"><h3>География заказа</h3>'+dl(rows)+'</section>';
}
function previewEvent(id,kind,isLot){
  const obj=(isLot?s.lots:s.orders).find(o=>o.id===id);if(!obj)return;
  const next={ASSEMBLED:'Собран на исходной полке',HANDED_OVER:'В пути у перевозчика',ARRIVED:'Готов к выдаче',ISSUED:'Выдан покупателю',RETURNED:'На проверке в ПВЗ выдачи',RETURN_SENT:'В обратном рейсе',RETURN_RECEIVED:'Доступен на исходной полке',QUARANTINED:'На карантине',INCIDENT:'Остаётся в пути',RECOVERED:'Готов к выдаче',WITHDRAW_REQUESTED:'Ожидает вывоза на полке',WITHDRAW_SENT:'На пути в хаб',WITHDRAW_RECEIVED:'Принят на хабе'};
  let fields=dl([['Объект',id],['После подтверждения',next[kind]],['Виртуальное время',tm(s.now)]]);
  if(!isLot){const point=['ASSEMBLED','HANDED_OVER','RETURN_RECEIVED'].includes(kind)?obj.source:obj.destination,delta=['ARRIVED','RETURN_RECEIVED','RETURNED','RECOVERED'].includes(kind)?-1:['ISSUED','HANDED_OVER','RETURN_SENT'].includes(kind)?1:0,free=s.points.find(p=>p.id===point)?.free_l;if(free!=null)fields+=dl([['После скана свободно в ПВЗ '+loc(point),num(free+delta*obj.volume_l)+' л']]);}
  if(isLot)fields+=field('Количество единиц','quantity','number',1,'min="1" max="'+esc(obj.quantity)+'" required');
  if(kind==='INCIDENT')fields+=field('Причина инцидента','reason','text','Задержка перевозчика','required maxlength="250"');
  dialogBox(processes[kind],form('event-form','<div class="stack">'+fields+'<input type="hidden" name="obj" value="'+esc(id)+'"><input type="hidden" name="kind" value="'+esc(kind)+'"><input type="hidden" name="target" value="'+(isLot?'lot':'order')+'"><input type="hidden" name="version" value="'+esc(obj.version)+'"></div>'));
}
function batchOrders(){
  const {src,dest}=routeState();
  return s.orders.filter(o=>['RESERVED','ASSEMBLED'].includes(o.status)&&o.source===src&&o.destination===dest)
    .sort((a,b)=>new Date(a.promised_at)-new Date(b.promised_at)||a.id.localeCompare(b.id));
}
async function requestQuote(orders){
  return api('routing/quotes',{order_ids:orders.map(o=>o.id),window_id:s.window_id,scenario_version:s.fixture_version});
}
function selectReset(id){
  if(!scenarios[id])return;
  dialogBox('Начать сценарий',form('reset-form','<p class="notes">Откроется чистый набор «'+esc(scenarios[id][0])+'» с начальными часами. Текущая демонстрационная смена будет заменена. Контрольные примеры используют исходный договор.</p><input type="hidden" name="scenario" value="'+esc(id)+'">','Начать сценарий'));
}
function download(){
  const order=lastOrderInfo?.order||lastOrderInfo;if(!order)return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(lastOrderInfo,null,2)],{type:'application/json;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download='Решение-'+String(order.id).replace(/[^\p{L}\p{N}_-]/gu,'_')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),200);
}
async function act(a,el){
  const id=el.dataset.id,kind=el.dataset.kind;
  if(a==='zoom-fit'){moveMap(0,0,1);return;}
  if(a==='zoom-plus'||a==='zoom-minus'){zoomMap(a==='zoom-plus'?1.35:1/1.35);return;}
  const handlers={
    'fleet-page':()=>go('fleet'),'fleet-form':()=>fleetForm(),'fleet-refresh':loadFleet,'fleet-add':()=>changeFleetVehicles(),
    'fleet-scenario':async()=>{if(!fleetSettings)await loadFleet();go('fleet');fleetForm(id);},'fleet-export':exportFleet,
    'fleet-remove':()=>changeFleetVehicles(Number(id)),
    'fleet-current':()=>{fleetDraft=null;fleetSelected=null;fleetFocus=null;render();},
    'fleet-truck':()=>{fleetSelected=id;fleetFocus=null;moveMap(0,0,1);render();},
    'fleet-stop':()=>{fleetFocus=Number(id);render();document.getElementById('city-map')?.scrollIntoView({block:'nearest'});},
    'fleet-confirm':()=>dialogBox('Подтвердить план парка',form('fleet-confirm-form',
      '<p>Подтверждение сохраняет маршруты и закрепляет заказы рабочей смены за машинами.</p>','Подтвердить план')),
    'fleet-start':()=>fleetCommand('start'),'fleet-next':()=>fleetCommand('next'),
    'fleet-scan':()=>fleetCommand('scan',{batch:id,operation:kind}),
    direction:directionForm,
    'open-direction':()=>{const [source,destination]=id.split('-');return change('direction',{source,destination},'Выбрано окно направления.');},
    'network-plan':openPlan,'portfolio-plan':openPortfolioPlan,'plan-edge':()=>planEdge(id),
    'truck-form':truckForm,'truck-export':exportTruck,'truck-confirm':confirmTruck,
    'truck-start':()=>truckCommand('start'),
    'truck-cancel':()=>dialogBox('Отменить рейс',form('truck-cancel-form',
      '<p>Закреплённые заказы вернутся в список собранных.</p>','Освободить заказы')),
    'truck-open':()=>{showTruck=true;truckPlan=null;moveMap(0,0,1);render();},
    'truck-clear':()=>{showTruck=false;truckPlan=null;focusedTruckStop=null;moveMap(0,0,1);render();},
    'truck-scan':()=>truckCommand('scan',{order_id:id,kind}),
    'truck-review-stop':reviewTruckStop,
    'truck-delay':()=>dialogBox('Задержка рейса',form('truck-delay-form',
      field('Длительность, мин','minutes','number',30,'required min="1" max="1440" step="1"'),'Пересчитать время')),
    'truck-stop':()=>{
      focusedTruckStop=Number(id);
      const stop=(showTruck?activeTruck:truckPlan)?.stops[focusedTruckStop],point=stations[stop?.id];
      if(!point)return;
      const scale=Math.max(2.2,mapCamera.scale);
      moveMap(point.x-mapWidth/scale/2,point.y-mapHeight/scale/2,scale);
      render();
      document.querySelector('#city-map')?.scrollIntoView({block:'nearest'});
    },
    'decision':async()=>{
      const q=await api('routing/quotes/'+encodeURIComponent(id));
      dialogBox('Решение '+q.quote_id,'<div class="stack">'+dl([['Дата расчёта',tm(q.fixed_at)],['Договор',q.tariff_version],['Окно',q.window_id],['Версия',q.version],['Заказы',q.order_ids.join(', ')],['Решение',modes[q.selected]],['Причина',reasons[q.reason]],['Экономия',signed(q.savings)]])+table(['Вариант','Ограничение или причина','Готовность','Опоздание'],q.candidates.map(c=>[modes[c.mode],esc(reasons[c.reason]||c.reason),num(c.ready_hours)+' ч',c.late_hours==null?'Нет оценки':num(c.late_hours)+' ч']))+'</div>');
    },
    dismiss:()=>dialog.close(),refresh,compare,settings:settingsForm,profile:profileForm,receipt:receiptForm,'new-order':newOrder,
    'stock-lots':()=>{stockTab='lots';render()},'stock-moves':()=>{stockTab='moves';render()},'stock-placement':openStockPlacement,
    'placement-details':()=>placementDetails(id,kind),'placement-confirm':()=>placementConfirm(id,kind),
    'placement-operation':()=>placementOperation(id,kind),'placement-journal':()=>placementJournal(id),
    'point-stock':()=>pointDetails(id),
    'ledger-prev':()=>{ledgerPageNo--;render()},'ledger-next':()=>{ledgerPageNo++;render()},
    'demo-page':()=>go('demo'),'map-page':()=>go('map'),'lot-detail':()=>lotDetails(id),'order-detail':()=>orderDetails(id),
    'demand-page':()=>go('demand'),
    'demand-recalculate':()=>change('demand',{action:'recalculate'},'Индекс спроса пересчитан.'),
    'demand-baseline':()=>change('demand',{action:'baseline'},'Восстановлена исходная демоистория.'),
    'demand-surge':()=>change('demand',{action:'surge'},'Пересчитан спрос по расширенной демоистории.'),
    'order-event':()=>previewEvent(id,kind,false),'lot-event':()=>previewEvent(id,kind,true),reset:()=>selectReset(id),download,
    quote:async()=>{await requestQuote(batchOrders());await refresh();compare()},
    dispatch:async()=>{const q=s.quote;if(!q)return;await change('dispatches',{quote_id:q.quote_id,expected_version:q.version,selected:q.selected},'Партия закреплена за манифестом.')},
    clock:()=>dialogBox('Виртуальные часы',role==='dispatcher'?form('clock-form','<div class="stack">'+field('Дата и время, мск','now','datetime-local',isoField(s.now),'required min="'+isoField(s.now)+'"')+'<p class="notes">Перевод часов вперёд начисляет хранение за полные сутки.</p></div>','Перевести часы'):dl([['Текущее время смены',tm(s.now)+' мск']])),
    'demo-step':()=>change('demo/step',{},'Шаг выполнен.'),'demo-run':()=>change('demo/run',{},'Сценарий пройден.')
  };
  if(handlers[a])await handlers[a]();
}
async function locked(fn,el){
  if(busy)return;busy=true;const button=el?.matches('button')?el:null;
  if(button)button.disabled=true;
  try{await fn()}catch(e){showError(e)}finally{if(button?.isConnected)button.disabled=false;busy=false;}
}
document.addEventListener('click',e=>{
  if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();return;}
  const el=e.target.closest('[data-page],[data-point],[data-action]');if(!el||el.disabled)return;
  if(el.dataset.page){if(!busy)go(el.dataset.page);return;}
  if(el.dataset.point){pointDetails(el.dataset.point);return;}
  locked(()=>act(el.dataset.action,el),el);
});
document.addEventListener('keydown',e=>{
  const g=e.target.closest('svg g[role="button"]');if(g&&['Enter',' '].includes(e.key)){e.preventDefault();g.dispatchEvent(new MouseEvent('click',{bubbles:true}));}
});
document.addEventListener('change',async e=>{
 const el=e.target;
 if(el.form?.id==='direction-form'&&el.name==='source'){restrictDestination(el.form,el.value);return;}
 if(el.form?.id==='order-form'&&el.name==='lot_id'){updateOrderStockPoints(el.form);return;}
 if(el.form?.id==='order-form'&&['stock_source_pvz_id','pvz_id'].includes(el.name)){setOrderDestination(el.form);return;}
 if(el.name==='fleet_scenario'){fleetForm(el.value);return;}
 if(el.name==='fleet_point'){fleetPoint=el.value;render();document.querySelector('[name="fleet_point"]')?.focus({preventScroll:true});return;}
 if(el.name==='fleet_contract'){el.form.elements.price_rebate.value=fleetSettings.contracts[el.value].rebate;return;}
 if(el.id==='truck-cargo-only'){cargoOnly=el.checked;render();return;}
 if(el.id==='role'){
    if(busy){el.value=role;return;}role=el.value;localStorage.setItem('atlas-role',role);portfolio=null;fleetSettings=null;fleetDraft=null;fleetDay=null;fleetFormState=null;fleetPoint='';fleetSelected=null;ledgerParty='';ledgerLot='';ledgerDay='';ledgerPageNo=0;orderSearch='';activePage=allowedPages[role][0];location.hash=activePage;await refresh();return;
 }
 if(el.id==='demand'||el.id==='consent'){
    if(el.id==='demand')demand=el.value;else consent=Number(el.value);
    try{await loadPortfolio()}catch(error){showError(error)}return;
 }
 if(el.id?.startsWith('ledger-')){
    if(el.id==='ledger-party')ledgerParty=el.value;if(el.id==='ledger-lot')ledgerLot=el.value;if(el.id==='ledger-day')ledgerDay=el.value;ledgerPageNo=0;render();return;
 }
 if(el.name==='consent'&&el.form?.id==='order-form'){
    const chosen=el.form.elements.selected_promised_at;chosen.disabled=!el.checked;chosen.required=el.checked;$('#chosen-label').hidden=!el.checked;
 }
 if(el.name==='sku_id'&&el.form?.id==='receipt-form'){
    const item=receiptPackages[el.value],fields=el.form.elements;
    ['dim0','dim1','dim2'].forEach((key,i)=>fields[key].value=item.dimensions[i]);
    fields.mass_g.value=item.mass;fields.barcode.value=el.value;
    fields.sale_price.value=item.sale??'';fields.cost_price.value=item.cost??'';
    receiptPreview();
 }
});
document.addEventListener('input',e=>{if(e.target.form?.id==='receipt-form')receiptPreview()});
document.addEventListener('submit',e=>{
  e.preventDefault();const f=e.target,d=Object.fromEntries(new FormData(f));
  locked(async()=>{
    switch(f.id){
      case 'direction-form':await change('direction',{source:d.source,destination:d.destination},'Выбрано окно направления.');break;
      case 'plan-filter':slice=d;await openPortfolioPlan();break;
      case 'truck-form':calculateTruck(d);break;
      case 'fleet-plan-form':await calculateFleet();break;
      case 'fleet-confirm-form':await fleetCommand('confirm');break;
      case 'truck-confirm-form':{
        const plan=currentTruckPlan();
        if(!plan)throw Error('Смена изменилась. Сначала пересчитайте маршрут.');
        await truckCommand('confirm',{config:plan.config,stops:plan.stops.map(stop=>({id:stop.id,
          pickup:stop.pickup.map(o=>o.id),drop:stop.drop.map(o=>o.id)}))});break;
      }
      case 'truck-delay-form':await truckCommand('delay',{minutes:Number(d.minutes)});break;
      case 'truck-scan-form':await scanTruckInput(d.order_id);break;
      case 'truck-next-form':await truckCommand(d.action,{acknowledge:true});break;
      case 'truck-cancel-form':await truckCommand('cancel');break;
      case 'order-search':orderSearch=d.search.trim();render();break;
      case 'reset-form':truckPlan=null;showTruck=false;focusedTruckStop=null;fleetDraft=null;fleetDay=null;fleetSelected=null;moveMap(0,0,1);await change('demo/reset',{scenario:d.scenario},'Открыта чистая смена.');break;
      case 'clock-form':await change('clock',{now:d.now+':00+03:00'},'Часы переведены.');break;
      case 'profile-form':await change('profile',{profile:d.profile},'Активный договор обновлён.');break;
      case 'conditions':{
        const batch=batchOrders().slice(0,Number(d.count));delete d.count;
        const settings=Object.fromEntries(Object.entries(d).map(([k,v])=>[k,v===''?null:k.endsWith('_at')?v+':00+03:00':Number(v)]));
        await api('settings',{settings});if(batch.length&&batch.length<batchOrders().length)await requestQuote(batch);
        dialog.close();await refresh();toast('Условия рейса сохранены.');break;
      }
      case 'receipt-form':{
        const fields={lot_id:d.lot_id.trim(),barcode:d.barcode.trim(),pvz_id:d.pvz_id,sku_id:d.sku_id,quantity:Number(d.quantity),mass_g:Number(d.mass_g),storage_days:Number(d.storage_days),dimensions_mm:[d.dim0,d.dim1,d.dim2].map(Number)};
        for(const key of ['sale_price','cost_price'])if(d[key]!=='')fields[key]=Math.round(Number(d[key])*100);
        await change('receipts',fields,'Партия принята на полку.');break;
      }
      case 'order-form':{
        const lot=s.lots.find(l=>l.id===d.lot_id);const initial=d.promised_at+':00+03:00',chosen=d.consent?d.selected_promised_at+':00+03:00':initial;
        const shipment=d.seller_ship_from_pvz_id;
        const order={lot_id:lot.id,pvz_id:d.pvz_id,stock_source_pvz_id:d.stock_source_pvz_id,quantity:1,expected_version:lot.version,delivery_price:0,promised_at:initial,original_promised_at:initial,selected_promised_at:chosen,consent:Boolean(d.consent)};
        if(shipment!=='original')order.seller_ship_from_pvz_id=shipment==='unknown'?null:shipment;
        await change('orders',order,'Заказ создан, единица зарезервирована.');break;
      }
      case 'placement-confirm-form':
        await change('stock-placement',{action:'confirm',lot_id:d.lot_id,source:d.source,fingerprint:d.fingerprint},'Единица зарезервирована к перемещению.');break;
      case 'placement-operation-form':
        await change('stock-placement',{action:d.action,transfer_id:d.transfer_id},'Операция записана в журнал.');break;
      case 'event-form':{
        const body={event_type:d.kind,expected_version:Number(d.version),quantity:Number(d.quantity||1),[d.target+'_id']:d.obj};if(d.reason)body.reason=d.reason;
        await change('events',body,'Операция подтверждена.');break;
      }
    }
  },e.submitter);
});
Object.assign(reasons,{WINDOW_MISSED:'Прошло время передачи',UNKNOWN_GEOGRAPHY:'Недостаточно данных о географии',NO_ROAD_ROUTE:'Нет пути по дорожному графу'});
Object.assign(states,{RESTOCKED:'Возвращён в запас',INSPECTION:'На проверке'});
refresh();
