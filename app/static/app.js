'use strict';
if(new URLSearchParams(location.search).get('desktop')==='1'){
  document.title='Атлас доставки · Atlas-PVZ ['+location.port+']';
}
const $=s=>document.querySelector(s);
const main=$('#main'), dialog=$('#dialog');
const moneyFormat=new Intl.NumberFormat('ru-RU',{style:'currency',currency:'RUB',maximumFractionDigits:2,minimumFractionDigits:0});
const nf=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2});
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>v==null?'—':moneyFormat.format(v/100);
const num=v=>v==null?'—':nf.format(v);
const signed=v=>v==null?'—':(v>0?'+':'')+money(v);
const tm=v=>v?new Date(v).toLocaleString('ru-RU',{timeZone:'Europe/Moscow',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}):'—';
const isoField=v=>new Date(+new Date(v)+10800000).toISOString().slice(0,16);
const prof=p=>p==='pilot'?'Пилотный договор':'Исходный договор';
const loc=id=>stations[id]?.title||id||'—';
const modes={SHARED_TRIP:'Попутный рейс',DEDICATED_TRIP:'Отдельный рейс',HUB:'Через хаб',COMBINED:'Смешанный план',MANUAL_EXCEPTION:'Исключение'};
const reasons={DIRECT_SAVES_COST:'Прямая доставка экономит средства',PAID_ROUNDTRIP_TOO_COSTLY:'Дорогой оплачиваемый круг',NO_CAPACITY:'Нет свободного места',DEADLINE_MISSED:'Пропущено окно готовности',PVZ_PEAK:'Не хватает времени смены',HUB_CHEAPER:'Через хаб выгоднее',DATA_MISSING:'Не хватает исходных данных',MANUAL_EXCEPTION:'Нужен разбор диспетчера',ELIGIBLE:'Доступен',OK:'Доступен'};
const states={RESERVED:'В резерве',ASSEMBLED:'Собран',ASSIGNED:'В манифесте',IN_TRANSIT:'В пути',READY_FOR_PICKUP:'Готов к выдаче',ISSUED:'Выдан',RETURN_INSPECTION:'На проверке',RETURN_IN_TRANSIT:'В обратном рейсе',RETURNED:'Возвращён',QUARANTINED:'В карантине',AVAILABLE:'Доступен',AT_HUB:'На хабе'};
const processes={ASSEMBLED:'Собрать',HANDED_OVER:'Передать перевозчику',ARRIVED:'Принять в ПВЗ',ISSUED:'Выдать покупателю',RETURNED:'Принять возврат',RETURN_SENT:'Передать возврат',RETURN_RECEIVED:'Вернуть на полку',QUARANTINED:'В карантин',INCIDENT:'Открыть инцидент',RECOVERED:'Подтвердить восстановление',WITHDRAW_REQUESTED:'Заказать вывоз',WITHDRAW_SENT:'Передать на хаб',WITHDRAW_RECEIVED:'Подтвердить приёмку хабом'};
const scenarios={case1:['Городская доставка','10 посылок из Центра в Университет одним попутным рейсом.'],case2:['Единичный заказ','Сравнение хаба с отдельным кругом при закрытом попутном окне.'],case3:['Возврат товара','Возврат одной выданной посылки на исходную полку.'],case4:['Частичный сбой','Приёмка девяти посылок, поиск десятой и повтор сообщения.'],case5:['Долгое хранение','30 суток хранения и вывоз непроданного остатка.'],rural:['Сельское плечо','Две посылки из Райцентра в Озёрное при обещании 48 часов.'],sandbox:['Свободная смена','Приёмка и обработка собственных тестовых заказов.']};
const pages={map:['map','Карта рейсов'],fleet:['truck','Парк машин'],orders:['route','Заказы'],stock:['box','Склад и смена'],ledger:['receipt','Начисления'],portfolio:['chart','Экономика'],demo:['play','Сценарии'],metrics:['activity','Диагностика'],truck:['truck','Текущий рейс']};
const allowedPages={dispatcher:Object.keys(pages).filter(p=>p!=='truck'),pvz:['stock','orders','ledger','truck','fleet'],seller:['stock','orders','ledger']};
let role=localStorage.getItem('atlas-role')||'dispatcher';if(!allowedPages[role])role='dispatcher';
let activePage=location.hash.slice(1);if(!allowedPages[role].includes(activePage))activePage=allowedPages[role][0];
let s={},loadSequence=0,consent=0,portfolio=null,busy=false,toastTimer,sortOrders='id';
const button=(action,label,symbol='',primary=false,extra='')=>'<button type="button" class="btn '+(primary?'primary':'')+'" data-action="'+esc(action)+'" '+extra+'>'+(symbol?icon(symbol,15):'')+esc(label)+'</button>';
const chip=(v,c='')=>'<span class="chip '+c+'">'+esc(v)+'</span>';
const title=(h,sub,actions='')=>'<div class="head"><div><h1>'+esc(h)+'</h1>'+(sub?'<p class="sub">'+esc(sub)+'</p>':'')+'</div><div class="section-actions">'+actions+'</div></div>';
const panel=(h,body,actions='')=>'<section class="panel"><div class="panel-head"><h2>'+esc(h)+'</h2>'+actions+'</div>'+body+'</section>';
const pad=html=>'<div class="panel-body">'+html+'</div>';
const empty=msg=>'<p class="empty">'+esc(msg)+'</p>';
const dl=rows=>'<dl class="data-list">'+rows.map(([k,v])=>'<div><dt>'+esc(k)+'</dt><dd>'+esc(v??'—')+'</dd></div>').join('')+'</dl>';
const table=(cols,rows,none='Пока нет записей.')=>rows.length?'<div class="table-wrap"><table><thead><tr>'+cols.map(c=>'<th scope="col">'+esc(c)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>':empty(none);
const stat=(symbol,label,value)=>'<div class="stat"><span class="stat-symbol">'+icon(symbol)+'</span><div><strong>'+esc(value)+'</strong><small>'+esc(label)+'</small></div></div>';
const stats=cards=>'<div class="stats">'+cards.map(a=>stat(...a)).join('')+'</div>';
const linkButton=(act,id,v)=>'<button type="button" class="table-link" data-action="'+esc(act)+'" data-id="'+esc(id)+'">'+esc(v)+'</button>';
const pointName=id=>stations[id]?stations[id].letter+' · '+stations[id].title:id||'—';
const pickupOptions=()=>s.points.map(({id})=>[id,pointName(id)]);
function toast(v){clearTimeout(toastTimer);$('#toast').textContent=v;toastTimer=setTimeout(()=>$('#toast').textContent='',5000)}
function dialogBox(label,body){
  $('#dialog-body').innerHTML='<div class="panel-head"><h2 id="dialog-title">'+esc(label)+'</h2><button class="plain" data-action="dismiss" aria-label="Закрыть">'+icon('close')+'</button></div><div class="panel-body">'+body+'</div>';
  if(!dialog.open)dialog.showModal();
}
async function api(path,body){
  const headers={'X-Role':role};let options={headers,cache:'no-store'};
  if(body!==undefined){options.method='POST';headers['Content-Type']='application/json';headers['Idempotency-Key']=crypto.randomUUID?crypto.randomUUID():Date.now()+'-'+Math.random();options.body=JSON.stringify(body);}
  const r=await fetch('/api/'+path,options);let data;
  try{data=await r.json()}catch{throw new Error('Сервис вернул ответ в неизвестном формате ('+r.status+').');}
  if(!r.ok){const d=data.detail||data.message||data.error;const detail=typeof d==='object'?(d.message||d.detail||JSON.stringify(d)):d;throw new Error((r.status===409?'Конфликт версии или остатка. ':'')+(reasons[detail]||detail||r.statusText)+' ('+r.status+')');}
  return data;
}
function go(page){if(!allowedPages[role].includes(page))page=allowedPages[role][0];activePage=page;location.hash=page;render();if(page==='portfolio')loadPortfolio().catch(showError);if(page==='fleet'||(page==='demo'&&!fleetSettings))loadFleet().catch(showError)}
function showError(err){
  const msg=err.message||String(err);if(dialog.open){
    $('#dialog-body .notice.error')?.remove();
    const e=document.createElement('p');e.className='notice error';e.textContent=msg;$('#dialog-body .panel-body').prepend(e);
  }else toast(msg);
}
async function refresh(){
  const seq=++loadSequence;
  try{
    /** @type {import('./api').State} */
    const [,state,truck]=await Promise.all([ensureRoads(),api('state'),role==='seller'?null:api('truck')]);
    if(seq!==loadSequence)return;
    activeTruck=truck?.run||null;
    if(activeTruck&&['CONFIRMED','IN_PROGRESS'].includes(activeTruck.status)&&truckViewInitialized!==activeTruck.id){
      showTruck=true;
      truckViewInitialized=activeTruck.id;
    }
    s=state;s.orders??=[];s.lots??=[];s.ledger??=[];s.settings??={};s.points??=[];s.totals??={};s.metrics??={};s.steps??=[];
    $('#connection').textContent='Стенд на связи';$('#connection-dot').classList.add('live');
    render();if(activePage==='portfolio')await loadPortfolio();if(activePage==='fleet'||(activePage==='demo'&&!fleetSettings))await loadFleet();
  }catch(e){if(seq!==loadSequence)return;
    $('#connection').textContent='Нет связи со стендом';$('#connection-dot').classList.remove('live');main.innerHTML=panel('Смена временно недоступна',pad('<div class="stack"><p>'+esc(e.message)+'</p>'+button('refresh','Повторить подключение','refresh')+'</div>'));main.setAttribute('aria-busy','false');}
}
async function loadPortfolio(){
  const chosen=consent,selectedDemand=demand,p=await api('portfolio?consent='+chosen+'&demand='+selectedDemand);if(activePage==='portfolio'&&chosen===consent&&selectedDemand===demand){portfolio=p;render();}
}
async function change(path,data,message){
  await api(path,data);if(dialog.open)dialog.close();portfolio=null;await refresh();if(message)toast(message);
}
function render(){
  $('#role').value=role;$('.avatar').innerHTML=icon('person',15);
  $('#nav').innerHTML=allowedPages[role].map((p,i)=>((i===4||i===5)?'<div class="nav-sep"></div>':'')+'<button class="nav-item '+(p===activePage?'current':'')+'" data-page="'+p+'" title="'+pages[p][1]+'" aria-label="'+pages[p][1]+'" '+(p===activePage?'aria-current="page"':'')+'>'+icon(pages[p][0],19)+'<span>'+pages[p][1]+'</span></button>').join('');
  $('#crumb').innerHTML='Рабочее место <b> / '+esc(pages[activePage][1])+'</b>';
  $('#clock-control').innerHTML=icon('clock',15)+'<span>'+esc(tm(s.now))+'</span><span class="clock-long">мск</span>';
  main.innerHTML=({map:mapPage,fleet:fleetPage,orders:ordersPage,stock:stockPage,ledger:ledgerPage,portfolio:portfolioPage,demo:demoPage,metrics:metricsPage,truck:()=>title('Текущий рейс')+executionView(activeTruck)})[activePage]();
  if(activePage==='map'||activePage==='fleet')bindMapControls(document.getElementById('city-map'));
  main.setAttribute('aria-busy','false');
}
function routeState(){return {src:s.settings.source||'A',dest:s.settings.destination||'B',q:s.quote||null}}
function mapPage(){
  const {src,dest,q}=routeState(),{totals:t}=s,selected=q?.selected,candidates=q?.candidates||[];
  const plan=currentTruckPlan();
  const run=showTruck?activeTruck:null;
  const itinerary=run?executionView(run):(plan?truckItinerary(plan):null);
  const mapPlan=run?activeMapPlan(run):plan?.included.length?{...plan,focus:focusedTruckStop}:null;
  const eligibleOrders=s.orders.filter(o=>o.source===src&&o.destination===dest&&['RESERVED','ASSEMBLED'].includes(o.status));
  const candidate=q?.candidates?.find(c=>c.mode===selected);
  const ready=eligibleOrders.length,savings=q?.savings??candidate?.savings;
  const hasManifest=s.dispatches?.some(d=>d.quote_id===q?.quote_id);
  let routeInfo='<div class="panel-body"><div class="route-header">'+icon('route',16)+'Выбранное направление</div><h2 class="route-title">'+esc(loc(src))+' → '+esc(loc(dest))+'</h2><p class="sub">'+(q?esc(q.orders_count??ready)+' зак. в расчёте · '+esc(prof(q.profile||s.profile)):'Подготовьте заказы и рассчитайте рейс')+'</p></div>';
  routeInfo+='<div class="route-actions">'+(q?button('compare','Сравнить варианты','layers',true):button('quote','Рассчитать рейс','route',true,!ready?'disabled':''))+(q?button('dispatch',hasManifest?'Закреплён':'Закрепить','',false,hasManifest||!eligibleOrders.some(o=>o.status==='ASSEMBLED')||selected==='MANUAL_EXCEPTION'?'disabled':''):'')+'</div>';
  routeInfo+='<div class="route-list">'+candidates.map(c=>'<div class="route-option '+(c.mode===selected?'chosen':'')+'"><div><b>'+esc(modes[c.mode]||c.mode)+'</b><small>'+esc(!c.eligible?(reasons[c.reason]||c.reason||'Недоступен'):c.mode===selected?'Выбран системой':'Альтернатива')+'</small></div><div class="amount"><b>'+money(c.route_cost)+'</b><small>'+(!c.eligible?'недоступно':num(c.ready_hours)+' ч')+'</small></div></div>').join('')+'</div>';
  if(!q)routeInfo+=empty('Для расчёта требуется принятый товар и резерв заказов.');
  if (candidate?.eligible && candidate.lost_tariff_revenue > 0) {
    routeInfo += '<p class="tariff-note">В экономии партии уже учтено снижение выручки RWB на ' +
      money(candidate.lost_tariff_revenue) + ' из-за скидки продавцу.</p>';
  }
  const mapHeader='<div class="panel-head"><div class="section-title">'+icon('map',19)+'<h2>Схема сети</h2></div><div class="section-actions">'+
    (s.scenario==='sandbox'?button('direction','Направление','route'):'')+
    button('network-plan','План сети','layers')+button('settings','Условия рейса','filter')+
    (activeTruck&&!run?button('truck-open','Текущий рейс','truck'):'')+
    button('truck-form','Спланировать рейс','truck',true)+'</div></div>';
  const legend=mapPlan?[['truck','Маршрут'],['stop','Номер остановки'],...(mapPlan.focus>0?[['focus-segment','Выбранный участок']]:[])]:
    [['','Прямой рейс'],['dashed','Через хаб'],['gray','Вне выбранного рейса']];
  const directions=new Map();
  for(const order of s.orders){
    if(!['RESERVED','ASSEMBLED'].includes(order.status)||(order.source===src&&order.destination===dest))continue;
    const lane=order.source+'-'+order.destination;
    directions.set(lane,(directions.get(lane)||0)+1);
  }
  const otherLanes=[...directions.keys()].map(lane=>lane.split('-'));
  const mapVisual='<div class="map-wrap">'+networkMap(src,dest,selected,mapPlan,otherLanes)+
    '<div class="map-tools">'+[['minus','Уменьшить'],['plus','Увеличить'],['fit','Вся сеть']].map(([a,v])=>'<button data-action="zoom-'+a+'" title="'+v+'" aria-label="'+v+'">'+icon(a,15)+'</button>').join('')+
    '</div></div><div class="map-legend">'+legend.map(([a,v])=>'<span class="legend-item"><i class="legend-stroke '+a+'"></i>'+v+'</span>').join('')+'</div>';
  const dir=pointName(src)+' → '+pointName(dest);
  const otherRows=[...directions].sort(([a],[b])=>a.localeCompare(b)).map(([lane,count])=>{
    const [source,destination]=lane.split('-');
    const name=pointName(source)+' → '+pointName(destination);
    return [s.scenario==='sandbox'?linkButton('open-direction',lane,name):esc(name),num(count)+' шт.','—','Ожидает расчёта','—'];
  });
  const map='<section class="panel">'+mapHeader+mapVisual+'</section>';
  return title('Карта рейсов','Учебная агломерация · '+tm(s.now).split(',')[0]+' · Московское время',
    button('fleet-page','Парк машин','truck',true)+button('demo-page','Сценарии','play')+button('profile',prof(s.profile),'contract'))+
    (itinerary?'':stats([['box','Заказов в направлении',num(s.orders.filter(o=>o.source===src&&o.destination===dest).length)],['truck','Свободных попутных мест',num(s.settings.shared_slots)],['target','Индекс рейса, из 100',num(q?.index??candidate?.index)],['trend','Экономия по расчёту',signed(savings)]]))+
    (itinerary?'<div class="map-grid has-itinerary">'+map+itinerary+'</div>':
      '<div class="map-grid map-overview"><section class="panel route-panel">'+routeInfo+'</section>'+map+'</div>')+
    (itinerary?'':(
    panel('Направления смены',table(['Направление','Заказы к окну','Попутный остаток','Решение','Экономия'],[[linkButton(q?'compare':'settings',src+'-'+dest,dir),esc(ready)+' шт.',esc(num(s.settings.shared_slots))+' мест',chip(modes[selected]||'Ожидает расчёта',q?'accent':''),signed(savings)],...otherRows]),button('demo-page','Демо-сценарии','play'))+
    panel('Результат по факту',pad(dl([['Вклад RWB',money(t.rwb_contribution)],['Эффект программы против централизованной схемы',signed(t.program_delta)],['Готовы к исходному сроку',num(t.on_time)+' из '+num(t.ready_count)]])))));
}
window.addEventListener('hashchange',()=>{const p=location.hash.slice(1);if(p!==activePage&&allowedPages[role].includes(p))go(p)});
