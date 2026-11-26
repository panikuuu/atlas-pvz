'use strict';

function truckLeg(from,to){
  const edges=roadRoute(from,to);
  const km=edges.reduce((total,edge)=>total+edge.length,0)*roadNetwork.scaleKm;
  return {from,to,edges,km,minutes:km/roadNetwork.speedKmh*60};
}

function simulateTruck(visits,config){
  const stops=[],legs=[];
  let time=config.departure,km=0,serviceMinutes=0,liters=0,grams=0,peakLiters=0,peakGrams=0,peakOrders=0;
  const onboard=new Set();
  for(let i=0;i<visits.length;i++){
    const stop=visits[i];
    if(i){
      let leg;
      try{leg=truckLeg(visits[i-1].id,stop.id);}catch{return null;}
      legs.push(leg);
      km+=leg.km;
      time+=leg.minutes*60000;
    }
    const arrive=time;
    const handling=stop.drop.length+stop.pickup.length;
    if(handling){
      time+=4*60000;
      serviceMinutes+=4+handling;
    }
    for(const order of [...stop.drop].sort((a,b)=>a.due-b.due)){
      time+=60000;
      if(!onboard.delete(order.id)||time>order.due)return null;
      liters-=order.liters;
      grams-=order.grams;
    }
    for(const order of stop.pickup){
      time+=60000;
      onboard.add(order.id);
      liters+=order.liters;
      grams+=order.grams;
    }
    if(liters>config.liters+1e-8||grams>config.grams)return null;
    peakLiters=Math.max(peakLiters,liters);
    peakGrams=Math.max(peakGrams,grams);
    peakOrders=Math.max(peakOrders,onboard.size);
    stops.push({...stop,arrive,leave:time,liters:Math.max(0,liters),grams,orders:onboard.size});
  }
  if(onboard.size)return null;
  return {stops,legs,km,serviceMinutes,peakLiters,peakGrams,peakOrders,finish:time};
}

function* addTruckEvent(visits,point,operation,order,firstIndex){
  const timesAtPoint=visits.filter(stop=>stop.id===point).length;
  for(let i=firstIndex;i<visits.length;i++){
    const stop=visits[i];
    if(stop.id===point){
      const updated=visits.slice();
      updated[i]={...stop,[operation]:[...stop[operation],order]};
      yield [updated,i];
    }
    if(i===0||timesAtPoint>=2||stop.id===point||visits[i-1]?.id===point)continue;
    const next={id:point,pickup:[],drop:[],[operation]:[order]};
    yield [[...visits.slice(0,i),next,...visits.slice(i)],i];
  }
}

function insertTruckOrder(visits,order,config){
  let best=null;
  for(const [withPickup,index] of addTruckEvent(visits,order.from,'pickup',order,0)){
    for(const [candidate] of addTruckEvent(withPickup,order.to,'drop',order,index+1)){
      const result=simulateTruck(candidate,config);
      if(result&&(!best||result.finish<best.result.finish-1||
          (Math.abs(result.finish-best.result.finish)<1&&candidate.length<best.visits.length))){
        best={visits:candidate,result};
      }
    }
  }
  return best;
}

function shortenTruckPlan(visits,result,config){
  // Try merging repeated visits when all previously accepted orders still fit.
  for(let i=1;i<visits.length;i++){
    const previous=visits.findIndex(stop=>stop.id===visits[i].id);
    if(previous===i)continue;
    for(const [keep,remove] of [[previous,i],[i,previous]]){
      if(remove===0||remove===visits.length-1)continue;
      const first=visits[keep],second=visits[remove];
      const merged={id:first.id,pickup:[...first.pickup,...second.pickup],drop:[...first.drop,...second.drop]};
      const candidate=visits.map((stop,k)=>k===keep?merged:stop).filter((_,k)=>k!==remove);
      const simulated=simulateTruck(candidate,config);
      if(simulated&&simulated.finish<=result.finish){
        return shortenTruckPlan(candidate,simulated,config);
      }
    }
  }
  return {visits,result};
}

function planTruck(orders,config){
  if(!stations[config.start]||!stations[config.end]||!Number.isFinite(config.departure)||
    !Number.isFinite(config.liters)||!Number.isFinite(config.grams)||config.liters<=0||config.grams<=0){
    throw Error('Укажите точки, время выезда и положительную вместимость машины.');
  }
  const blank=id=>({id,pickup:[],drop:[]});
  const initial=[blank(config.start),blank(config.end)];
  const rejected=[],eligible=[];
  for(const order of orders){
    let reason;
    if(!stations[order.from]||!stations[order.to]||order.from===order.to||
      !Number.isFinite(order.due)||!(order.liters>0)||!(order.grams>0))reason='Недостаточно данных';
    else if(order.directBlock)reason=reasons[order.directBlock]||'Недостаточно данных для прямого рейса';
    else if(order.liters>config.liters||order.grams>config.grams)reason='Не помещается в машину';
    else if(order.due<=config.departure)reason='Срок истекает до выезда';
    if(reason)rejected.push({...order,reason});
    else eligible.push(order);
  }
  eligible.sort((a,b)=>a.due-b.due||a.id.localeCompare(b.id));
  let visits=initial,result=simulateTruck(initial,config);
  if(!result)throw Error('Между начальной и конечной точками нет пути по дорожному графу.');
  for(const order of eligible){
    const added=insertTruckOrder(visits,order,config);
    if(added)({visits,result}=added);
    else rejected.push({...order,reason:'Не удалось включить при заданных сроках и загрузке'});
  }
  ({visits,result}=shortenTruckPlan(visits,result,config));
  const included=visits.flatMap(v=>v.pickup);
  const baseKm=truckLeg(config.start,config.end).km;
  const truckRates=roadNetwork.rates;
  const discount=sellerDiscount(config.profile)*included.length;
  const extraKm=Math.max(0,result.km-baseKm);
  const extraCost=Math.round(extraKm*truckRates.km)+result.serviceMinutes*truckRates.stopMinute+
    discount;
  const hubCost=included.reduce((total,order)=>total+
    ([order.from,order.to].some(p=>['Село','Деревня','Посёлок'].includes(stations[p].area))?
      truckRates.ruralHub:truckRates.cityHub),0);
  const lanes=new Map(included.map(order=>[order.from+order.to,[order.from,order.to]]));
  const separateCost=[...lanes.values()].reduce((total,[from,to])=>total+truckRates.dedicatedFixed+
    Math.round(2*truckLeg(from,to).km*truckRates.km),0)+(8*lanes.size+2*included.length)*truckRates.stopMinute+discount;
  return {...result,config,rejected,included,extraKm,extraCost,hubCost,separateCost};
}

function sellerDiscount(profile){
  return profile==='original'?1000:roadNetwork.rates.sellerDiscount;
}

function truckSample(departure){
  const pairs=[['F','A'],['F','B'],['A','E'],['E','G'],['B','C'],['B','J'],['G','D'],['C','D'],['C','K'],['J','K'],['D','K']];
  return pairs.map(([from,to],i)=>({id:'Т-'+String(i+1).padStart(2,'0'),from,to,liters:2+i%3,
    grams:600+200*(i%3),due:departure+(i<3?240:360)*60000}));
}
