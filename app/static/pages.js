'use strict';
let demand='neutral',orderSearch='',ledgerPageNo=0,ledgerParty='',ledgerDay='',ledgerLot='',stockTab='lots';
const parties={RWB:'RWB',CARRIER:'Перевозчик',BUYER:'Покупатель',LABOR:'Труд ПВЗ',SPACE:'Площадь ПВЗ',COGS:'Себестоимость',PACKAGING:'Упаковка','seller-1':'Продавец'};
const services={RECEIVE:'Приёмка',RECEIVE_LABOR:'Труд на приёмку',REPLENISH:'Пополнение',STORAGE:'Хранение',STORAGE_SELLER:'Хранение продавца',STORAGE_SPACE:'Занятая площадь',ASSEMBLY:'Сборка',ASSEMBLY_LABOR:'Труд на сборку',CARRIAGE:'Перевозка',PACKAGING:'Упаковка',SELLER_LOGISTICS:'Исходящая логистика',PICKUP:'Выдача',PICKUP_LABOR:'Труд на выдачу',SALE:'Продажа',COST_OF_GOODS:'Себестоимость товара',COMMISSION:'Комиссия',BUYER_DELIVERY:'Доставка покупателю',RETURN_HANDLING:'Обработка возврата',RETURN_LABOR:'Труд на возврат',SELLER_RETURN:'Возврат продавцу',RETURN_CARRIAGE:'Обратный рейс',RECOVERY:'Восстановительная доставка',WITHDRAW:'Вывоз остатка',SELLER_STORAGE:'Складской тариф продавцу',SPACE_COST:'Стоимость площади',STORAGE_RENT:'Занятая площадь'};
Object.assign(states,{INSPECTION:'На проверке',RESTOCKED:'Возвращён на полку',QUARANTINE:'Карантин',READY:'Готов к выдаче',WITHDRAW_RESERVED:'Ожидает вывоза',WITHDRAW_IN_TRANSIT:'На пути в хаб'});
const party=p=>stations[p]?loc(p):parties[p]||p;
const service=k=>k?.startsWith('REVERSE_')?'Сторно · '+(services[k.slice(8)]||k.slice(8)):services[k]||k||'—';
function place(k){
  if(!k)return 'Вне сети';const [site,st]=k.split(':');return st?loc(site)+' · '+(states[st]||st):states[k]||loc(k);
}
const stateBadge=k=>chip(states[k]||k,['ISSUED','READY_FOR_PICKUP','RESTOCKED'].includes(k)?'good':k==='IN_TRANSIT'?'accent':'');
const eventsFor=o=>({RESERVED:['ASSEMBLED'],ASSIGNED:['HANDED_OVER'],IN_TRANSIT:s.incidents?.some(i=>i.order_id===o.id&&i.status==='OPEN')?['RECOVERED']:['ARRIVED','INCIDENT'],READY_FOR_PICKUP:['ISSUED'],ISSUED:['RETURNED'],INSPECTION:['RETURN_SENT','QUARANTINED'],RETURN_IN_TRANSIT:['RETURN_RECEIVED']})[o.status]||[];
function orderRows(list){
  return table(['Заказ','Партия','Направление','Статус','Обещано, мск','Готовность'],list.map(o=>[linkButton('order-detail',o.id,o.id),esc(o.lot_id),esc(loc(o.source)+' → '+loc(o.destination)),stateBadge(o.status),esc(tm(o.promised_at)),o.ready_at?(o.late_hours?chip('Опоздание '+num(o.late_hours)+' ч','warn'):chip('В срок','good')):(+new Date(o.promised_at)<+new Date(s.now)?chip('Просрочен','warn'):chip('Открыт'))]),'Заказы появятся после резервирования принятой партии.');
}
function ordersPage(){
  const filtered=s.orders.filter(o=>[o.id,o.lot_id,states[o.status]].some(x=>String(x).toLowerCase().includes(orderSearch.toLowerCase())));
  return title('Заказы','Обещание покупателю и фактическое движение каждой посылки',role==='dispatcher'?button('new-order','Создать заказ','plus',true):'')+
    panel('Реестр заказов',orderRows(filtered),'<form id="order-search" class="filterline"><input name="search" aria-label="Найти заказ" placeholder="Заказ, партия или статус" value="'+esc(orderSearch)+'"><button class="btn sm">Найти</button></form>');
}
function stockPage(){
  const lots=s.lots,qty=k=>lots.reduce((n,l)=>n+(l[k]||0),0);
  const action=role==='pvz'?button('receipt','Принять партию','scan',true):role==='dispatcher'?button('new-order','Создать заказ','plus',true):'';
  const head=title(role==='seller'?'Мой запас':'Склад и смена',role==='seller'?'Партии продавца, условия хранения и возвраты':'Физические остатки и подтверждение операций',action);
  const tableStock=table(['Партия / SKU','ПВЗ','Доступно','Резерв','В пути','Готово','Возраст'],lots.map(l=>[linkButton('lot-detail',l.id,l.id)+'<div class="micro">'+esc(l.sku_id)+'</div>',esc(loc(l.pvz_id)),num(l.available),num(l.reserved),num(l.in_transit),num(l.ready),num(l.age_days??Math.max(0,Math.floor((new Date(s.now)-new Date(l.accepted_at))/86400000)))+' сут.']),'Партии пока не приняты. Сотрудник ПВЗ может добавить первую приёмку.');
  const movements=()=>table(['Время, мск','Партия','Единица','Откуда','Куда'],[...(s.movements||[])].reverse().map(m=>[tm(m.at),esc(m.lot_id),esc(m.unit_id),esc(place(m.from)),esc(place(m.to))]),'Движений пока нет.');
  return head+stats([['box','Доступно на полке',num(qty('available'))],['layers','В резерве',num(qty('reserved'))],['truck','В пути',num(qty('in_transit'))],['scan','Готово к выдаче',num(qty('ready'))]])+
    panel(stockTab==='lots'?'Партии на хранении':'Журнал движений',stockTab==='lots'?tableStock:movements(),'<div class="section-actions">'+button('stock-lots','Партии','box',stockTab==='lots')+button('stock-moves','Движения','route',stockTab==='moves')+'</div>')+
    (role==='pvz'?panel('Посылки смены',orderRows(s.orders.filter(o=>eventsFor(o).length))):'')+
    ((s.alerts||[]).length?panel('Оповещения о хранении',table(['Партия','Дата'],s.alerts.map(a=>[esc(a.lot_id),tm(a.at)]))):'');
}
function ledgerPage(){
  const t=s.totals,partyOpts=[...new Set(s.ledger.flatMap(e=>[e.from_party,e.to_party]))].sort();
  const opts=(list,current,caption)=>'<option value="">'+caption+'</option>'+list.map(k=>'<option value="'+esc(k)+'" '+(k===current?'selected':'')+'>'+esc(party(k))+'</option>').join('');
  const entries=[...s.ledger].reverse().filter(e=>(!ledgerParty||[e.from_party,e.to_party].includes(ledgerParty))&&(!ledgerDay||isoField(e.at).slice(0,10)===ledgerDay)&&(!ledgerLot||e.lot_id===ledgerLot));
  const pages=Math.max(1,Math.ceil(entries.length/30));ledgerPageNo=Math.min(ledgerPageNo,pages-1);
  const controls='<div class="filterline"><select id="ledger-party" aria-label="Участник">'+opts(partyOpts,ledgerParty,'Все участники')+'</select><select id="ledger-lot" aria-label="Партия">'+opts(s.lots.map(l=>l.id),ledgerLot,'Все партии')+'</select><input type="date" id="ledger-day" aria-label="Дата проводки" value="'+esc(ledgerDay)+'"></div>';
  const book=table(['Дата, мск','Услуга','Откуда → кому','Заказ / партия','Сумма','Версия'],entries.slice(ledgerPageNo*30,ledgerPageNo*30+30).map(e=>[tm(e.at),esc(service(e.service))+(e.reversal_of?'<div class="micro">Сторно '+esc(e.reversal_of)+'</div>':''),esc(party(e.from_party)+' → '+party(e.to_party)),esc(e.order_id||e.lot_id),money(e.amount),esc(e.rate_version)]),'Проводок по этому фильтру нет.');
  const paging='<div class="panel-head"><span class="micro">'+num(entries.length)+' записей · Страница '+(ledgerPageNo+1)+' из '+pages+'</span><div class="section-actions">'+button('ledger-prev','Назад','',false,ledgerPageNo===0?'disabled':'')+button('ledger-next','Далее','',false,ledgerPageNo+1>=pages?'disabled':'')+'</div></div>';
  return title('Начисления',prof(s.profile)+' · Журнал фактически оказанных услуг','<a class="btn" href="/economics.md" download="economics.md">Формулы расчёта</a>')+
    (role==='seller'?panel('Результат продавца',pad(dl([['Прибыль с учётом затрат',money(t.seller_profit)]]))):stats([['wallet','Расходы RWB',money(t.rwb_cost)],['receipt','Доход RWB',money(t.rwb_revenue)],['trend','Вклад RWB',money(t.rwb_contribution)],['box','Прибыль продавца',money(t.seller_profit)]]))+
    (role!=='seller'?panel('Доход пунктов выдачи',table(['ПВЗ','Начислено','Труд и площадь','Прибыль','В т. ч. обычная выдача¹'],Object.keys(t.pvz_revenue||{}).map(p=>[esc(loc(p)),money(t.pvz_revenue[p]),money(t.pvz_cost[p]),money(t.pvz_profit[p]),money(s.ledger.filter(e=>e.to_party===p&&e.service==='PICKUP').reduce((x,e)=>x+e.amount,0)-s.ledger.filter(e=>e.from_party===p&&e.service==='PICKUP_LABOR').reduce((x,e)=>x+e.amount,0))]))+'<div class="map-legend">¹ Маржа фактических выдач по базовой операции.</div>'):'')+
    panel('Проводки',book+paging,controls);
}
function portfolioPage(){
  const p=portfolio||s.portfolio||{},share=p.orders?p.direct/p.orders*100:0;
  const controls='<div class="filterline"><label>Спрос <select id="demand">'+[['low','Низкий'],['neutral','Нейтральный'],['high','Высокий']].map(([v,l])=>'<option value="'+v+'" '+(demand===v?'selected':'')+'>'+l+'</option>').join('')+'</select></label><label>Согласие на позднее окно <select id="consent">'+[0,5,15,30].map(v=>'<option '+(consent===v?'selected':'')+' value="'+v+'">'+v+'%</option>').join('')+'</select></label></div>';
  const f=s.forecast;
  return title('Экономика программы','Портфель на 28 дней · Синтетический поток',
    button('fleet-page','Расчёт рабочего дня','truck')+button('profile',prof(s.profile),'contract')+
    '<a class="btn" href="/economics.md" download="economics.md">Формулы расчёта</a>')+
    stats([['box','Заказов в потоке',num(p.orders)],['truck','Прямых отправлений',num(p.direct)],['hub','Через хаб',num(p.hub)],['trend','Эффект RWB за цикл',signed(p.rwb_delta)]])+
    panel('Параметры портфеля',pad(controls))+
    '<div class="two-col spaced">'+panel('Результат RWB',pad(dl([['Экономия на операциях',signed(p.operating_savings)],['Изменение тарифной выручки',signed(p.tariff_delta)],['Координация',money(p.coordination)],['Результат за цикл',signed(p.rwb_delta)],['Разовый запуск',money(p.startup)],['После запуска',signed(p.after_startup)]])))+
    panel('Результат участников',pad(dl([['Прирост прибыли ПВЗ',signed(p.pvz_delta)],['Прирост прибыли продавцов',signed(p.seller_delta)],['Доля прямых заказов',num(share)+'% ('+num(p.direct)+' / '+num(p.orders)+')'],['Обходов хаба',num(p.direct)],['Исключено кг·км',num(p.avoided_kg_km)],['Средняя готовность',num(p.mean_ready_hours)+' ч']])) )+'</div>'+
    panel('Добровольное позднее окно',pad(dl([['Выбрали перенос для доставки',num(p.shifted)+' из '+num(p.orders)],['Дополнительный эффект',signed(p.extra_effect)],['Исходное обещание выполнено',num(p.on_time_original==null?null:p.on_time_original*100)+'%'],['Выбранное обещание выполнено',num(p.on_time_current==null?null:p.on_time_current*100)+'%']])))+
    (f?panel('Прогноз пополнения',pad(dl([['Ожидаемый спрос',num(f.expected_daily)+' ед./сут.'],['Предельное пополнение',num(f.max_replenishment)+' ед.'],['Уверенность',f.confidence==='weak'?'Низкая':'По истории SKU'],['Источник',f.source==='category_district'?'Категория и район':'Сопоставимый день недели'],['Тип истории','Синтетическая'],['Момент прогноза',tm(f.generated_at)]]))):'');
}
function demoPage(){
  const idx=s.step??0,count=s.steps.length,done=idx>=count;
  return title('Демо-сценарии','Сквозные проверки операций, остатков и начислений',button('map-page','Карта рейсов','map'))+
    panel(scenarios[s.scenario]?.[0]||'Активная смена',pad('<div class="stack"><div class="section-actions">'+chip(prof(s.profile),'accent')+chip(s.fixture_version||'golden-v1')+chip(count?'Шаг '+idx+' из '+count:'Свободная смена')+'</div>'+(count?'<ol class="step-list">'+s.steps.map((x,i)=>'<li class="'+(i<idx?'done':i===idx?'next':'')+'">'+esc(x.label)+(i<idx?' ✓':'')+'</li>').join('')+'</ol><div class="section-actions">'+button('demo-step','Следующий шаг','arrow',true,done?'disabled':'')+button('demo-run','Пройти до конца','play',false,done?'disabled':'')+'</div>':'')+
    (s.replay_check?'<div class="notice">Повторены два скана. Новых движений, начислений и инцидентов: '+[s.replay_check.movements,s.replay_check.ledger,s.replay_check.incidents].join(' / ')+'. Изменение количества: HTTP '+s.replay_check.changed_body_status+'.</div>':'')+dl([['Физический остаток в сети',num(s.totals.network_units)+' шт.'],['Фактические расходы RWB',money(s.totals.rwb_cost)],['Готовы к исходному сроку',num(s.totals.on_time)+' из '+num(s.totals.ready_count)]])+'</div>'))+
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
