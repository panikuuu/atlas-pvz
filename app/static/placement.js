'use strict';

let stockPlacementReport=null;
const placementAction={keep:'Оставить на месте',hub:'Вернуть в хаб',relocate:'Перевезти в ПВЗ'};
const placementStatus={RESERVED:'Ожидает передачи',IN_TRANSIT:'В пути',RECEIVED:'Принято',CANCELLED:'Отменено'};
const placementEvent={confirm:'Резерв остатка',send:'Передача перевозчику',receive:'Приёмка на месте',cancel:'Отмена перемещения'};
const placementJournalEvent={PLACEMENT_RESERVED:placementEvent.confirm,PLACEMENT_SENT:placementEvent.send,
  PLACEMENT_RECEIVED:placementEvent.receive,PLACEMENT_CANCELLED:placementEvent.cancel};
const placementCosts={storage:'Хранение',space:'Занятое место',capital:'Стоимость капитала',obsolescence:'Риск неликвида',transport:'Перевозка'};
const placementPoint=id=>id==='HUB'?'Распределительный хаб':loc(id);
const placementTitle=(action,point)=>placementAction[action]+(action==='relocate'?' · '+placementPoint(point):'');
const placementAttributes=({lot_id,source})=>'data-id="'+esc(lot_id)+'" data-kind="'+esc(source)+'"';

async function loadStockPlacement(){
  const seq=loadSequence;
  /** @type {import('./api').StockPlacementReport} */
  const report=await api('stock-placement');
  if(seq===loadSequence&&activePage==='stock'&&stockTab==='placement'&&role==='dispatcher'){
    stockPlacementReport=report;
    render();
  }
}

async function openStockPlacement(){
  stockTab='placement';
  stockPlacementReport=null;
  if(activePage==='stock'){
    render();
    await loadStockPlacement();
  }else go('stock');
}

function stockPlacementBody(){
  const report=stockPlacementReport;
  if(!report)return empty('Загружаем расчёт размещения остатка.');
  const {rows,transfers}=report;
  const recommendations=rows.map(row=>{
    const {lot_id,sku,source,available,recommendation}=row;
    return [esc(lot_id)+'<div class="micro">'+esc(sku)+'</div>',esc(placementPoint(source)),num(available),
      '<b>'+esc(placementTitle(recommendation.action,recommendation.point))+'</b><div class="micro">'+esc(recommendation.reason)+'</div>',
      button('placement-details','Сравнить варианты','layers',false,placementAttributes(row))];
  });
  const operations=transfers.map(transfer=>{
    const {id,lot_id,sku,source,destination,status}=transfer;
    const attrs='data-id="'+esc(id)+'"';
    const actions=[button('placement-journal','Журнал','receipt',false,attrs)];
    if(status==='RESERVED'){
      actions.push(button('placement-operation','Передача','truck',true,attrs+' data-kind="send"'),
        button('placement-operation','Отмена','',false,attrs+' data-kind="cancel"'));
    }
    if(status==='IN_TRANSIT')actions.push(button('placement-operation','Приёмка','scan',true,attrs+' data-kind="receive"'));
    return [esc(lot_id)+'<div class="micro">'+esc(sku)+'</div>',esc(placementPoint(source)+' → '+placementPoint(destination)),
      chip(placementStatus[status]||status,status==='RECEIVED'?'good':status==='IN_TRANSIT'?'accent':''),
      '<div class="section-actions">'+actions.join('')+'</div>'];
  });
  const forecastDays=rows[0]?.options[0]?.forecast_days;
  const scope=forecastDays?'Оценка одной свободной единицы на '+num(forecastDays)+' дн.':'Оценка одной свободной единицы';
  return '<p class="map-legend">'+esc(scope)+'</p>'+table(['Партия / SKU','Фактический остаток','Свободно, шт.','Рекомендация',''],recommendations,
    'Свободных единиц для пересмотра размещения пока нет.')+
    '<div class="panel-head"><h3>Перемещения и журнал</h3></div>'+table(['Партия / SKU','Направление','Статус','Операции'],operations,
      'Подтверждённых перемещений пока нет.');
}

function getPlacementRow(id,source){
  return stockPlacementReport?.rows.find(row=>row.lot_id===id&&row.source===source);
}

function placementDetails(id,source){
  const row=getPlacementRow(id,source);
  if(!row)return;
  const {sku,available,recommendation,options}=row;
  const confidence={low:'Низкая',medium:'Средняя',high:'Высокая'};
  const comparison=options.map(option=>{
    const {action,point,eligible,reason,net,costs}=option;
    const chosen=action===recommendation.action&&point===recommendation.point;
    const summary=placementTitle(action,point)+' · '+(eligible?signed(net):'Недоступно');
    const inputs=[['Локальный индекс',option.demand_index==null?'Нет оценки':num(option.demand_index)+' / 100'],
      ['Локальный прогноз',option.forecast_units==null?'Нет оценки':num(option.forecast_units)+' шт.'],
      ['Горизонт',num(option.forecast_days)+' дн.'],
      ['Уверенность',confidence[option.confidence]],['Ожидаемые продажи',option.expected_sales==null?'—':num(option.expected_sales)+' шт.'],
      ['Выгода продажи и доставки',money(option.benefit)],
      ...Object.entries(placementCosts).map(([key,label])=>[label,money(costs?.[key])]),['Ожидаемый результат',signed(net)]];
    return '<details '+(chosen?'open':'')+'><summary>'+esc(summary)+(chosen?' · Рекомендовано':'')+'</summary>'+dl(inputs)+
      (reason?'<p class="notes spaced">'+esc(reason)+'</p>':'')+'</details>';
  });
  const heading=sku+' · '+placementPoint(source)+' · '+num(available)+' свободно';
  const improvement=recommendation.improvement>0?' Эффект к хранению на месте '+signed(recommendation.improvement)+'.':'';
  dialogBox('Размещение партии '+id,'<div class="stack"><p>'+esc(heading)+'</p><p class="notice">'+
    esc(placementTitle(recommendation.action,recommendation.point)+'. '+recommendation.reason+improvement)+'</p>'+comparison.join('')+
    (recommendation.action!=='keep'?'<div class="section-actions">'+
      button('placement-confirm','Подготовить перемещение','truck',true,placementAttributes(row))+'</div>':'')+'</div>');
}

function placementConfirm(id,source){
  const row=getPlacementRow(id,source);
  if(!row||row.recommendation.action==='keep')return;
  const destination=row.recommendation.point;
  dialogBox('Подтвердить перемещение',form('placement-confirm-form','<div class="stack">'+dl([
    ['Партия / SKU',id+' / '+row.sku],['Движение',placementPoint(source)+' → '+placementPoint(destination)],['Количество','1 шт.']])+
    '<p class="notes">Единица будет зарезервирована для перемещения. Передачу и приёмку подтвердите в журнале.</p>'+
    '<input type="hidden" name="lot_id" value="'+esc(id)+'"><input type="hidden" name="source" value="'+esc(source)+'">'+
    '<input type="hidden" name="fingerprint" value="'+esc(row.fingerprint)+'"></div>','Зарезервировать к перемещению'));
}

function placementOperation(id,action){
  const transfer=stockPlacementReport?.transfers.find(transfer=>transfer.id===id);
  if(!transfer||!placementEvent[action])return;
  const title=placementEvent[action];
  dialogBox(title,form('placement-operation-form',dl([
    ['Перемещение',id],['Партия',transfer.lot_id],['Направление',placementPoint(transfer.source)+' → '+placementPoint(transfer.destination)],
    ['Текущий статус',placementStatus[transfer.status]]])+
    '<input type="hidden" name="transfer_id" value="'+esc(id)+'"><input type="hidden" name="action" value="'+esc(action)+'">',
    'Подтвердить'));
}

function placementJournal(id){
  const transfer=stockPlacementReport?.transfers.find(transfer=>transfer.id===id);
  if(!transfer)return;
  dialogBox('Журнал перемещения '+id,table(['Время, мск','Операция','ID записи'],transfer.journal.map(event=>[
    esc(tm(event.at)),esc(placementJournalEvent[event.action]||event.action),esc(event.event_id)]),'Записей пока нет.'));
}
