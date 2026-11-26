'use strict';
let demand='neutral',orderSearch='',ledgerPageNo=0,ledgerParty='',ledgerDay='',ledgerLot='',stockTab='lots';
const parties={RWB:'RWB',CARRIER:'Перевозчик',BUYER:'Покупатель',LABOR:'Труд ПВЗ',SPACE:'Площадь ПВЗ',COGS:'Себестоимость',PACKAGING:'Упаковка','seller-1':'Продавец'};
const services={RECEIVE:'Приёмка',RECEIVE_LABOR:'Труд на приёмку',REPLENISH:'Пополнение',STORAGE:'Хранение',STORAGE_SELLER:'Хранение продавца',STORAGE_SPACE:'Занятая площадь',ASSEMBLY:'Сборка',ASSEMBLY_LABOR:'Труд на сборку',CARRIAGE:'Перевозка',PACKAGING:'Упаковка',SELLER_LOGISTICS:'Исходящая логистика',PICKUP:'Выдача',PICKUP_LABOR:'Труд на выдачу',SALE:'Продажа',COST_OF_GOODS:'Себестоимость товара',COMMISSION:'Комиссия',BUYER_DELIVERY:'Доставка покупателю',RETURN_HANDLING:'Обработка возврата',RETURN_LABOR:'Труд на возврат',SELLER_RETURN:'Возврат продавцу',RETURN_CARRIAGE:'Обратный рейс',RECOVERY:'Восстановительная доставка',WITHDRAW:'Вывоз остатка',SELLER_STORAGE:'Складской тариф продавцу',SPACE_COST:'Стоимость площади',STORAGE_RENT:'Занятая площадь'};
Object.assign(states,{INSPECTION:'На проверке',RESTOCKED:'Возвращён на полку',QUARANTINE:'Карантин',READY:'Готов к выдаче',WITHDRAW_RESERVED:'Ожидает вывоза',WITHDRAW_IN_TRANSIT:'На пути в хаб',PLACEMENT_RESERVED:'Зарезервирован для перемещения',PLACEMENT_IN_TRANSIT:'Перемещается'});
const party=p=>stations[p]?loc(p):parties[p]||p;
const service=k=>k?.startsWith('REVERSE_')?'Сторно · '+(services[k.slice(8)]||k.slice(8)):services[k]||k||'—';
function place(k){
  if(!k)return 'Вне сети';const [site,st]=k.split(':');
  if(site==='RELAY')return loc(st)+' · Буфер передачи';
  return st?loc(site)+' · '+(states[st]||st):states[k]||loc(k);
}
const stateBadge=k=>chip(states[k]||k,['ISSUED','READY_FOR_PICKUP','RESTOCKED'].includes(k)?'good':k==='IN_TRANSIT'?'accent':'');
const eventsFor=o=>({RESERVED:['ASSEMBLED'],ASSIGNED:['HANDED_OVER'],IN_TRANSIT:s.incidents?.some(i=>i.order_id===o.id&&i.status==='OPEN')?['RECOVERED']:['ARRIVED','INCIDENT'],READY_FOR_PICKUP:['ISSUED'],ISSUED:['RETURNED'],INSPECTION:['RETURN_SENT','QUARANTINED'],RETURN_IN_TRANSIT:['RETURN_RECEIVED']})[o.status]||[];
function orderRows(list){
  return table(['Заказ','Партия','Направление','Статус','Обещано, мск','Готовность'],list.map(o=>[linkButton('order-detail',o.id,o.id),esc(o.lot_id),esc(loc(o.source)+' → '+loc(o.destination)),stateBadge(o.status),esc(tm(o.promised_at)),o.ready_at?(o.late_hours?chip('Опоздание '+num(o.late_hours)+' ч','warn'):chip('В срок','good')):(+new Date(o.promised_at)<+new Date(s.now)?chip('Просрочен','warn'):chip('Открыт'))]),'Заказы появятся после резервирования принятой партии.');
}
function ordersPage(){
  const filtered=s.orders.filter(o=>[o.id,o.lot_id,states[o.status],loc(o.source),loc(o.destination)].some(x=>String(x).toLowerCase().includes(orderSearch.toLowerCase())));
  return title('Заказы','Обещание покупателю и фактическое движение каждой посылки',role==='dispatcher'?button('new-order','Создать заказ','plus',true):'')+
    panel('Реестр заказов',orderRows(filtered),'<form id="order-search" class="filterline"><input name="search" aria-label="Найти заказ" placeholder="Заказ, партия, статус или ПВЗ" value="'+esc(orderSearch)+'"><button class="btn sm">Найти</button></form>');
}
function stockPage(){
  const lots=s.lots,qty=k=>lots.reduce((n,l)=>n+(l[k]||0),0);
  const placement=stockTab==='placement'&&role==='dispatcher';
  const tabs='<div class="section-actions">'+button('stock-lots','Партии','box',stockTab==='lots')+
    button('stock-moves','Движения','route',stockTab==='moves')+
    (role==='dispatcher'?button('stock-placement','Размещение остатка','trend',placement):'')+'</div>';
  const action=role==='pvz'?button('receipt','Принять партию','scan',true):role==='dispatcher'?button('new-order','Создать заказ','plus',true):'';
  const head=title(role==='seller'?'Мой запас':'Склад и смена',role==='seller'?'Партии продавца, условия хранения и возвраты':'Физические остатки и подтверждение операций',action);
  const tableStock=table(['Партия / SKU','ПВЗ приёмки','Доступно','Резерв','В пути','Готово','Возраст'],lots.map(l=>{
    const available=orderStockPoints(l).map(([point,count])=>loc(point)+' · '+num(count)).join(', ');
    return [linkButton('lot-detail',l.id,l.id)+'<div class="micro">'+esc(l.sku_id)+'</div>',esc(loc(l.pvz_id)),
      num(l.available)+(available?'<div class="micro">'+esc(available)+'</div>':''),num(l.reserved),num(l.in_transit),num(l.ready),
      num(l.age_days??Math.max(0,Math.floor((new Date(s.now)-new Date(l.accepted_at))/86400000)))+' сут.'];
  }),'Партии пока не приняты. Сотрудник ПВЗ может добавить первую приёмку.');
  const movements=()=>table(['Время, мск','Партия','Единица','Откуда','Куда'],[...(s.movements||[])].reverse()
    .map(m=>[tm(m.at),esc(m.lot_id),esc(m.unit_id),esc(place(m.from)),esc(place(m.to))]),'Движений пока нет.');
  const occupancy=table(['ПВЗ','Вместимость, л','Занято, л','Свободно, л'],s.points.map(p=>[
    linkButton('point-stock',p.id,pointName(p.id)),num(p.capacity_l),num(p.occupied_l),num(p.free_l)]));
  return head+stats([['box','Доступно на полке',num(qty('available'))],['layers','В резерве',num(qty('reserved'))],['truck','В пути',num(qty('in_transit'))],['scan','Готово к выдаче',num(qty('ready'))]])+
    panel(placement?'Размещение остатка':stockTab==='moves'?'Журнал движений':'Партии на хранении',
      placement?stockPlacementBody():stockTab==='moves'?movements():tableStock,tabs)+
    (s.points.length?panel('Вместимость ПВЗ',occupancy):'')+
    (role==='pvz'?panel('Посылки смены',orderRows(s.orders.filter(o=>eventsFor(o).length))):'')+
    ((s.alerts||[]).length?panel('Оповещения о хранении',table(['Партия','Дата'],s.alerts.map(a=>[esc(a.lot_id),tm(a.at)]))):'');
}
function ledgerPage(){
  const t=s.totals,pointIds=s.points.map(p=>p.id);
  const partyOpts=[...new Set(s.ledger.flatMap(e=>[e.from_party,e.to_party]))].filter(id=>!pointIds.includes(id)).sort();
  const opts=(list,current,label=party)=>list.map(k=>'<option value="'+esc(k)+'" '+(k===current?'selected':'')+'>'+esc(label(k))+'</option>').join('');
  const options=(label,ids)=>ids.length?'<optgroup label="'+label+'">'+opts(ids,ledgerParty)+'</optgroup>':'';
  const issuance={};
  for(const e of s.ledger){
    if(e.service==='PICKUP')issuance[e.to_party]=(issuance[e.to_party]||0)+e.amount;
    if(e.service==='PICKUP_LABOR')issuance[e.from_party]=(issuance[e.from_party]||0)-e.amount;
  }
  const entries=[...s.ledger].reverse().filter(e=>(!ledgerParty||[e.from_party,e.to_party].includes(ledgerParty))&&(!ledgerDay||isoField(e.at).slice(0,10)===ledgerDay)&&(!ledgerLot||e.lot_id===ledgerLot));
  const pages=Math.max(1,Math.ceil(entries.length/30));ledgerPageNo=Math.min(ledgerPageNo,pages-1);
  const controls='<div class="filterline"><select id="ledger-party" aria-label="Участник"><option value="">Все участники</option>'+
    options('Пункты выдачи',pointIds)+options('Участники начислений',partyOpts)+
    '</select><select id="ledger-lot" aria-label="Партия"><option value="">Все партии</option>'+opts(s.lots.map(l=>l.id),ledgerLot,id=>id)+
    '</select><input type="date" id="ledger-day" aria-label="Дата проводки" value="'+esc(ledgerDay)+'"></div>';
  const book=table(['Дата, мск','Услуга','Откуда → кому','Заказ / партия','Сумма','Версия'],entries.slice(ledgerPageNo*30,ledgerPageNo*30+30).map(e=>[tm(e.at),esc(service(e.service))+(e.reversal_of?'<div class="micro">Сторно '+esc(e.reversal_of)+'</div>':''),esc(party(e.from_party)+' → '+party(e.to_party)),esc(e.order_id||e.lot_id),money(e.amount),esc(e.rate_version)]),'Проводок по этому фильтру нет.');
  const paging='<div class="panel-head"><span class="micro">'+num(entries.length)+' записей · Страница '+(ledgerPageNo+1)+' из '+pages+'</span><div class="section-actions">'+button('ledger-prev','Назад','',false,ledgerPageNo===0?'disabled':'')+button('ledger-next','Далее','',false,ledgerPageNo+1>=pages?'disabled':'')+'</div></div>';
  const shift=unifiedRun?.title||scenarios[s.scenario]?.[0]||'Текущая смена';
  return title('Начисления',shift+' · '+prof(s.profile)+' · Журнал фактически оказанных услуг','<a class="btn" href="/economics.md" download="economics.md">Формулы расчёта</a>')+
    (role==='seller'?panel('Результат продавца',pad(dl([['Прибыль с учётом затрат',money(t.seller_profit)]]))):stats([['wallet','Расходы RWB',money(t.rwb_cost)],['receipt','Доход RWB',money(t.rwb_revenue)],['trend','Вклад RWB',money(t.rwb_contribution)],['box','Прибыль продавца',money(t.seller_profit)]]))+
    (role!=='seller'?panel('Доход пунктов выдачи',table(['ПВЗ','Начислено','Труд и площадь','Прибыль','В т. ч. обычная выдача¹'],
      pointIds.map(p=>[esc(loc(p)),money(t.pvz_revenue?.[p]??0),money(t.pvz_cost?.[p]??0),money(t.pvz_profit?.[p]??0),money(issuance[p]||0)]))+
      '<div class="map-legend">¹ Маржа фактических выдач по базовой операции.</div>'):'')+
    panel('Проводки',book+paging,controls);
}
function demandPage(){
  const report=demandReport;
  const head=title('Индекс спроса',report?'Горизонт пополнения · '+report.forecast_days+' дней':'',
    button('stock-placement','Размещение остатка','box')+button('demand-recalculate','Пересчитать','refresh',true));
  if(!report)return head+panel('Оценки',empty('Загружаем сохранённые оценки.'));
  const confidence={low:'Низкая',medium:'Средняя',high:'Высокая'};
  const rows=report.rows.map(({sku,region,zone_name,locality_name,unique_orders,demand_index,forecast_units,confidence:level,recommendation:r})=>{
    const quantity=r.units==null?'':r.units?('Пополнить на '+num(r.units)+' шт.'):'0 шт.';
    const inputs=zone_name&&r.shelf_units!=null
      ? '<div class="micro">'+esc('Запас '+num(r.on_hand)+' шт. · Свободно '+num(r.free_liters)+' л · Попутно до '+num(r.transport_units)+' шт.')+'</div>':'';
    return [esc(sku),esc(region),esc(zone_name||'Вся область')+(locality_name?'<div class="micro">'+esc(locality_name)+'</div>':''),num(unique_orders),
      demand_index==null?'Нет оценки':num(demand_index),forecast_units==null?'Нет оценки':num(forecast_units),
      chip(confidence[level],level==='high'?'good':level==='low'?'warn':''),
      (quantity?'<b>'+esc(quantity)+'</b><br>':'')+esc(r.reason)+inputs];
  });
  const meta=pad(dl([['Период наблюдения, мск',tm(report.observed_from)+' — '+tm(report.observed_to)],
    ['Последний пересчёт, мск',new Date(report.recalculated_at).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'})],
    ['Откуда пополнять',loc(report.source)]]));
  const history=report.demo_enabled?panel('Демоистория · Университет',pad(
    '<div class="stack"><p class="sub">Сравните спрос на SKU S и SMARTPHONE на тех же условиях склада и перевозки.</p><div class="section-actions">'+
    button('demand-baseline','Исходная история')+button('demand-surge','Добавить по 28 выдач')+'</div></div>')):'';
  return head+meta+history+panel('Спрос по областям и зонам ПВЗ',
    table(['SKU','Регион','Локальная зона','Заказы','Индекс / 100','Прогноз, шт.','Уверенность','Пополнение и причина'],rows,
      'Примите партию и пересчитайте спрос, чтобы увидеть оценку для SKU.')+
    '<p class="map-legend">75 баллов — 75% опорного уровня после поправки на объём и регулярность истории. При полной истории это около 1,5 взвешенного заказа в сутки.</p>');
}

function shiftEconomy(){
  const summary=unifiedRun?.summary;
  if(!summary)return '';
  const plan=summary.plan;
  const t=s.totals;
  return panel('Текущая смена · '+unifiedRun.title,pad('<div class="stack">'+
    stats([['box','Заказы в смене',num(summary.orders)],['receipt','Проводки',num(summary.ledger_entries)],
      ['wallet','Фактические расходы RWB',money(t.rwb_cost)],['trend','Фактический вклад RWB',money(t.rwb_contribution)]])+
    (plan?dl([['План · все заказы через хаб',money(plan.all_hub)],['План · парк и остаток через хаб',money(plan.total)],
      ['Плановый эффект RWB',signed(plan.savings)],['Заказы парком / через хаб',num(plan.fleet_orders)+' / '+num(plan.hub_orders)],
      ['Факт · результат продавца',money(t.seller_profit)]])
      :'<p class="sub">Сравнение с хабом появится после расчёта парка. Проводки отражают операции, выполненные на текущем шаге.</p>')+
    '<p class="micro">План сравнивает доставку одного набора заказов. Факт берётся из журнала смены и включает проведённые складские операции.</p>'+
    button('unified-open','Открыть начисления','receipt',false,'data-id="ledger"')+'</div>'));
}

function portfolioPage(){
  const p=portfolio||s.portfolio||{},share=p.orders?p.direct/p.orders*100:0;
  const controls='<div class="filterline"><label>Спрос <select id="demand">'+[['low','Низкий'],['neutral','Нейтральный'],['high','Высокий']].map(([v,l])=>'<option value="'+v+'" '+(demand===v?'selected':'')+'>'+l+'</option>').join('')+'</select></label><label>Согласие на позднее окно <select id="consent">'+[0,5,15,30].map(v=>'<option '+(consent===v?'selected':'')+' value="'+v+'">'+v+'%</option>').join('')+'</select></label></div>';
  return title('Экономика','Рабочий день и портфель на 28 дней',
    button('fleet-scenario','Расчёт по девяти ПВЗ','truck',true,'data-id="network"')+button('profile',prof(s.profile),'contract')+
    '<a class="btn" href="/economics.md" download="economics.md">Формулы расчёта</a>')+
    shiftEconomy()+
    panel('Прогноз на 28 дней',pad('<div class="stack">'+controls+
      stats([['box','Заказов в потоке',num(p.orders)],['truck','Прямых отправлений',num(p.direct)],['hub','Через хаб',num(p.hub)],['trend','Эффект RWB за цикл',signed(p.rwb_delta)]])+'</div>'))+
    '<div class="two-col spaced">'+panel('Результат RWB',pad(dl([['Экономия на операциях',signed(p.operating_savings)],['Изменение тарифной выручки',signed(p.tariff_delta)],['Координация',money(p.coordination)],['Результат за цикл',signed(p.rwb_delta)],['Разовый запуск',money(p.startup)],['После запуска',signed(p.after_startup)]])))+
    panel('Результат участников',pad(dl([['Прирост прибыли ПВЗ',signed(p.pvz_delta)],['Прирост прибыли продавцов',signed(p.seller_delta)],['Доля прямых заказов',num(share)+'% ('+num(p.direct)+' / '+num(p.orders)+')'],['Обходов хаба',num(p.direct)],['Исключено кг·км',num(p.avoided_kg_km)],['Средняя готовность',num(p.mean_ready_hours)+' ч']])) )+'</div>'+
    panel('Добровольное позднее окно',pad(dl([['Выбрали перенос для доставки',num(p.shifted)+' из '+num(p.orders)],['Дополнительный эффект',signed(p.extra_effect)],['Исходное обещание выполнено',num(p.on_time_original==null?null:p.on_time_original*100)+'%'],['Выбранное обещание выполнено',num(p.on_time_current==null?null:p.on_time_current*100)+'%']])))+
    panel('Прогноз пополнения',pad(button('demand-page','Открыть индекс спроса','trend')));
}
function unifiedPanel(){
  const u=unifiedRun;
  const links=[['stock','Склад','box'],['orders','Заказы','route'],['map','Карта','map'],['fleet','Парк машин','truck'],
    ['ledger','Начисления','receipt'],['portfolio','Экономика','chart'],['demand','Индекс спроса','trend']];
  const description='Один набор заказов от приёмки до выдачи, передачи между машинами и начислений.';
  return panel('Рабочий день сети',pad('<div class="stack">'+
    (u?('<div class="section-actions">'+chip('Шаг '+u.stage+' из '+u.steps.length,u.finished?'good':'accent')+'</div>'+
      '<ol class="step-list">'+u.steps.map(({label},i)=>'<li class="'+(i<u.stage?'done':i===u.stage?'next':'')+'">'+esc(label)+(i<u.stage?' ✓':'')+'</li>').join('')+'</ol>'+
      '<div class="section-actions">'+(u.finished?chip('Смена пройдена','good'):button('unified-next',u.next_label,'arrow',true))+
      button('unified-start','Начать заново','refresh')+'</div>'+
      '<div class="section-actions">'+links.map(([id,label,iconName])=>button('unified-open',label,iconName,false,'data-id="'+id+'"')).join('')+'</div>')
      :'<p class="sub">'+description+'</p><div class="section-actions">'+button('unified-start','Начать рабочий день','play',true)+'</div>')+'</div>'));
}

function demoPage(){
  const idx=s.step??0,count=s.steps.length,done=idx>=count;
  const workdays=Object.entries(fleetSettings?.scenarios||{}).filter(([,item])=>item.description)
    .map(([id,item])=>'<div class="scenario-row"><div class="grow"><h3>'+esc(item.title)+'</h3><p>'+esc(item.description)+
      '</p></div>'+button('fleet-scenario','Настроить и рассчитать','truck',false,'data-id="'+esc(id)+'"')+'</div>');
  return title('Демо-сценарии','Сквозные проверки операций, остатков и начислений',button('map-page','Карта рейсов','map'))+
    unifiedPanel()+
    (!unifiedRun?panel(scenarios[s.scenario]?.[0]||'Активная смена',pad('<div class="stack"><div class="section-actions">'+chip(prof(s.profile),'accent')+chip(s.fixture_version||'golden-v1')+chip(count?'Шаг '+idx+' из '+count:'Свободная смена')+'</div>'+(count?'<ol class="step-list">'+s.steps.map((x,i)=>'<li class="'+(i<idx?'done':i===idx?'next':'')+'">'+esc(x.label)+(i<idx?' ✓':'')+'</li>').join('')+'</ol><div class="section-actions">'+button('demo-step','Следующий шаг','arrow',true,done?'disabled':'')+button('demo-run','Пройти до конца','play',false,done?'disabled':'')+'</div>':'')+
    (s.replay_check?'<div class="notice">Повторены два скана. Новых движений, начислений и инцидентов: '+[s.replay_check.movements,s.replay_check.ledger,s.replay_check.incidents].join(' / ')+'. Изменение количества: HTTP '+s.replay_check.changed_body_status+'.</div>':'')+dl([['Физический остаток в сети',num(s.totals.network_units)+' шт.'],['Фактические расходы RWB',money(s.totals.rwb_cost)],['Готовы к исходному сроку',num(s.totals.on_time)+' из '+num(s.totals.ready_count)]])+'</div>')):'')+
    panel('Рабочие дни парка',workdays.length?workdays.join(''):empty('Загружаем рабочие дни…'))+
    panel('Выбрать сценарий',Object.entries(scenarios).map(([id,[n,desc]],i)=>'<div class="scenario-row '+(s.scenario===id?'active':'')+'"><span class="scenario-id">'+(i<5?'0'+(i+1):icon(i===5?'map':'box',17))+'</span><div class="grow"><h3>'+esc(n)+'</h3><p>'+esc(desc)+'</p></div>'+button('reset','Начать','',false,'data-id="'+id+'"')+'</div>').join(''));
}
function metricsPage(){
  const m=s.metrics;
  return title('Диагностика','Текущая смена · '+(s.fixture_version||'golden-v1'),button('refresh','Обновить','refresh'))+
  stats([['truck','Незакрытых перевозок',num(m.unconfirmed)],['box','Расхождений остатков',num(m.stock_errors)],['receipt','Ошибок начислений',num(m.ledger_errors)],['clock','Расчёт p95, мс',num(m.quote_p95_ms)]])+
  '<div class="two-col">'+panel('Статусы заказов',table(['Состояние','Количество'],Object.entries(m.statuses||{}).map(([k,v])=>[stateBadge(k),num(v)])))+
  panel('Фактическое распределение',table(['Маршрут','Заказы','Доля потока'],Object.entries(m.route_counts||{}).map(([k,v])=>[esc(modes[k]||k),num(v),num(100*v/(s.orders.length||1))+'%'])))+'</div>'+
  panel('Инциденты',table(['Заказ','Причина','Статус','Следующая попытка','Факт затрат'],(s.incidents||[]).map(i=>[linkButton('order-detail',i.order_id,i.order_id),esc(i.reason),esc(i.status==='OPEN'?'Открыт':'Закрыт'),tm(i.next_attempt_at),money(i.actual_cost)]),'Открытых или завершённых инцидентов нет.'))+
  panel('Манифесты',table(['Манифест','Тип рейса','Подтверждённые заказы','Счёт перевозчика'],(s.dispatches||[]).map(d=>[esc(d.id),esc(modes[d.mode]),esc(d.order_ids?.join(', ')),money(d.carrier_cost)])))+
  panel('Журнал решений и исключений',table(['Расчёт','Время, мск','Решение','Версия тарифа','Эффект'],(s.decisions||[]).map(q=>[linkButton('decision',q.quote_id,q.quote_id),esc(tm(q.fixed_at)),esc(modes[q.selected]),esc(q.tariff_version),signed(q.savings)])));
}
