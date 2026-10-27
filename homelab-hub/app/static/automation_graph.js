/* Item-based flow editor. Cards are selectable, draggable and connected by ports. */
let graphObjects = [], graphSaved = [], graphLegacy = [], graphCurrent = null;
let graphEditing = null, graphSelected = null, graphConnecting = null;
let graphLoading = false, graphSerial = 0, graphListSignature = '', graphPaletteSignature = '';
let graphOpener = null;
const GRAPH_GRID = 23;
const graphCamera = {x:24,y:24,scale:1};
let graphWirePreview = null, graphSuppressPortClick = false;
const graphPosition = (value, maximum) => Math.max(0,Math.min(Math.floor(maximum / GRAPH_GRID)*GRAPH_GRID,Math.round(value / GRAPH_GRID) * GRAPH_GRID));
const GRAPH_KINDS = [
  ['trigger','When item reports','◆'], ['clock_trigger','When time is reached','◷'],
  ['condition','While item equals','=', 'eq'], ['condition','While item differs','≠', 'ne'],
  ['condition','While less than','<', 'lt'], ['condition','While at most','≤', 'lte'],
  ['condition','While greater than','>', 'gt'], ['condition','While at least','≥', 'gte'],
  ['time','While time matches','◷'], ['window','While inside time window','◴'],
  ['action','Do action','⚡'], ['delay','Wait','⏱'],
];
const GRAPH_OPERATORS = [['eq','equals'],['ne','does not equal'],['gt','greater than'],['gte','at least'],['lt','less than'],['lte','at most']];
const graphById = id => graphCurrent?.nodes.find(node => node.id === id);
const graphItem = id => graphObjects.find(obj => obj.id === id);
const graphText = value => escapeHtml(String(value ?? ''));
const graphKindLabel = node => node.kind === 'item' ? 'Item' : GRAPH_KINDS.find(row => row[0] === node.kind && (!row[3] || row[3] === node.operator))?.[1] || node.kind;
function graphRevealCard(card) {
  const frame=$('graphViewport'), margin=28, scale=graphCamera.scale;
  const left=graphCamera.x+card.offsetLeft*scale, right=left+card.offsetWidth*scale;
  const top=graphCamera.y+card.offsetTop*scale, bottom=top+card.offsetHeight*scale;
  if (left < margin) graphCamera.x+=margin-left;
  else if (right > frame.clientWidth-margin) graphCamera.x-=right-frame.clientWidth+margin;
  if (top < margin) graphCamera.y+=margin-top;
  else if (bottom > frame.clientHeight-margin) graphCamera.y-=bottom-frame.clientHeight+margin;
  graphApplyCamera();
}
function graphApplyCamera() {
  $('graphCanvas').style.transform=`translate(${graphCamera.x}px, ${graphCamera.y}px) scale(${graphCamera.scale})`;
  $('graphZoomValue').textContent=Math.round(graphCamera.scale*100)+'%';
}
function graphCanvasPoint(clientX,clientY) {
  const rect=$('graphViewport').getBoundingClientRect();
  return {x:(clientX-rect.left-graphCamera.x)/graphCamera.scale,y:(clientY-rect.top-graphCamera.y)/graphCamera.scale};
}
function graphZoomTo(scale,clientX,clientY) {
  const frame=$('graphViewport'),rect=frame.getBoundingClientRect();
  const anchorX=(clientX ?? rect.left+rect.width/2)-rect.left;
  const anchorY=(clientY ?? rect.top+rect.height/2)-rect.top;
  const next=Math.max(.35,Math.min(2,Math.round(scale*100)/100));
  graphCamera.x=anchorX-(anchorX-graphCamera.x)*next/graphCamera.scale;
  graphCamera.y=anchorY-(anchorY-graphCamera.y)*next/graphCamera.scale;
  graphCamera.scale=next; graphApplyCamera();
}
function graphFit() {
  const frame=$('graphViewport'),nodes=graphCurrent?.nodes || [];
  if (!nodes.length) { Object.assign(graphCamera,{x:24,y:24,scale:1}); graphApplyCamera(); return; }
  const left=Math.min(...nodes.map(node=>node.x))-42,top=Math.min(...nodes.map(node=>node.y))-42;
  const right=Math.max(...nodes.map(node=>node.x+188))+42,bottom=Math.max(...nodes.map(node=>node.y+110))+42;
  const scale=Math.max(.35,Math.min(1.4,frame.clientWidth/(right-left),frame.clientHeight/(bottom-top)));
  graphCamera.scale=scale;
  graphCamera.x=(frame.clientWidth-(right-left)*scale)/2-left*scale;
  graphCamera.y=(frame.clientHeight-(bottom-top)*scale)/2-top*scale;
  graphApplyCamera();
}

function graphContext(id, seen = new Set()) {
  if (seen.has(id)) return '';
  seen.add(id);
  const node = graphById(id);
  if (!node) return '';
  if (node.kind === 'item') return node.item;
  const input = graphCurrent.edges.find(edge => edge.target === id);
  return input ? graphContext(input.source, seen) : '';
}
function graphNodeLabel(node) {
  if (node.kind === 'item') return graphItem(node.item)?.name || 'Choose item';
  if (node.kind === 'delay') return `Wait ${node.seconds || 5}s`;
  if (node.kind === 'clock_trigger') return `At ${node.time_condition?.boundary === 'clock' ? node.time_condition?.time : node.time_condition?.boundary || 'time'}`;
  if (node.kind === 'time') return `${node.time_condition?.after ? 'After' : 'Before'} ${node.time_condition?.boundary === 'clock' ? node.time_condition?.time : node.time_condition?.boundary || 'time'}`;
  if (node.kind === 'window') return `${node.start} until ${node.end}`;
  if (node.kind === 'action') return `${node.action?.replace(/^set_/, '') || 'Choose action'} = ${node.value ?? '—'}`;
  return `${node.property || 'Choose property'} ${node.operator || 'eq'} ${node.value ?? '—'}`;
}
function graphMakeNode(kind, item = '', x = 60, y = 80, operator = 'eq') {
  const node = {id:'n'+(++graphSerial),kind,item,property:'',operator,value:null,action:'',seconds:kind === 'delay' ? 5 : 0,
    time_condition:['time','clock_trigger'].includes(kind) ? {boundary:'clock',time:'18:00',after:true,offset_minutes:0} : null,
    start:'18:00',end:'00:00',
    x:graphPosition(x,2200),y:graphPosition(y,1480)};
  graphCurrent.nodes.push(node);
  graphSelected = node.id;
  graphDraw();
  const card=$('graphNodes').querySelector(`[data-node="${node.id}"]`);
  card.querySelector('.graph-node-head').focus({preventScroll:true}); graphRevealCard(card);
  return node;
}
function graphLink(source, target) {
  const from=graphById(source),to=graphById(target);
  if (!from || !to) return false;
  let reason='';
  if (source === target) reason='A card cannot connect to itself.';
  else if (to.kind === 'clock_trigger') reason='A clock trigger starts a flow and cannot have an incoming connection.';
  else if (graphCurrent.edges.some(edge => edge.source === source && edge.target === target)) reason='These cards are already connected.';
  else if (to.kind === 'trigger' && from.kind !== 'item') reason='Connect an item directly before a device trigger.';
  else if (to.kind === 'trigger' && graphCurrent.edges.some(edge => edge.target === target)) reason='A device trigger can have only one source item.';
  else {
    const seen=new Set(),pending=[target];
    while (pending.length) {
      const current=pending.pop();
      if (current === source) { reason='This connection would make a loop.'; break; }
      if (seen.has(current)) continue;
      seen.add(current);
      pending.push(...graphCurrent.edges.filter(edge => edge.source === current).map(edge => edge.target));
    }
  }
  if (reason) { $('graphFeedback').textContent=reason; return false; }
  graphCurrent.edges.push({source,target});
  $('graphFeedback').textContent='';
  graphDraw();
  $('graphNodes').querySelector(`[data-node="${target}"] [data-port="in"]`)?.focus({preventScroll:true});
  return true;
}
function graphRoundedPath(points) {
  let result=`M${points[0][0]} ${points[0][1]}`;
  for (let i=1;i<points.length-1;i++) {
    const [x,y]=points[i],prev=points[i-1],next=points[i+1];
    const before=Math.hypot(x-prev[0],y-prev[1]),after=Math.hypot(next[0]-x,next[1]-y);
    const radius=Math.min(12,before/2,after/2);
    if (!radius) { result+=` L${x} ${y}`; continue; }
    const a=[x+(prev[0]-x)*radius/before,y+(prev[1]-y)*radius/before];
    const b=[x+(next[0]-x)*radius/after,y+(next[1]-y)*radius/after];
    result+=` L${a[0]} ${a[1]} Q${x} ${y} ${b[0]} ${b[1]}`;
  }
  return result+` L${points.at(-1)[0]} ${points.at(-1)[1]}`;
}
function graphWirePath(x1,y1,x2,y2,source,target) {
  const middle=(x1+x2)/2;
  const forward=x2-x1>70;
  const corridor=graphCurrent.nodes.some(node => node.id!==source && node.id!==target &&
    node.x < Math.max(x1,x2)+14 && node.x+188 > Math.min(x1,x2)-14 &&
    node.y < Math.max(y1,y2)+18 && node.y+105 > Math.min(y1,y2)-18);
  if (forward && !corridor)
    return graphRoundedPath([[x1,y1],[middle,y1],[middle,y2],[x2,y2]]);
  const nearby=graphCurrent.nodes.filter(node => node.x < Math.max(x1,x2)+70 && node.x+188 > Math.min(x1,x2)-70);
  const above=Math.min(y1,y2,...nearby.map(node=>node.y))-44;
  const below=Math.max(y1,y2,...nearby.map(node=>node.y+105))+44;
  const lane=Math.abs(above-y1)+Math.abs(above-y2) < Math.abs(below-y1)+Math.abs(below-y2) ? above : below;
  const out=x1+36,into=x2-36;
  return graphRoundedPath([[x1,y1],[out,y1],[out,lane],[into,lane],[into,y2],[x2,y2]]);
}
function graphDrawWires() {
  const svg = $('graphWires'); svg.replaceChildren();
  for (const edge of graphCurrent.edges) {
    const a = graphById(edge.source), b = graphById(edge.target);
    if (!a || !b) continue;
    const path = document.createElementNS('http://www.w3.org/2000/svg','path');
    const route=graphWirePath(a.x+188,a.y+47,b.x,b.y+47,a.id,b.id);
    path.setAttribute('d',route);
    path.setAttribute('class','graph-wire'); path.setAttribute('aria-hidden','true');
    const hit=document.createElementNS('http://www.w3.org/2000/svg','path');
    hit.setAttribute('d',route); hit.setAttribute('class','graph-wire-hit');
    hit.setAttribute('tabindex','0'); hit.setAttribute('role','button');
    hit.setAttribute('aria-label',`Remove connection from ${graphNodeLabel(a)} to ${graphNodeLabel(b)}`);
    const remove=() => { graphCurrent.edges=graphCurrent.edges.filter(row => row !== edge); graphDraw(); $('graphSave').focus({preventScroll:true}); };
    hit.onclick=remove;
    hit.onkeydown=event => { if (['Enter',' ','Delete','Backspace'].includes(event.key)) { event.preventDefault(); event.stopPropagation(); remove(); } };
    svg.append(path,hit);
  }
  if (graphWirePreview) {
    const source=graphById(graphWirePreview.source),target=graphById(graphWirePreview.target);
    if (source) {
      const path=document.createElementNS('http://www.w3.org/2000/svg','path');
      path.setAttribute('d',graphWirePath(source.x+188,source.y+47,target ? target.x : graphWirePreview.x,target ? target.y+47 : graphWirePreview.y,source.id,target?.id));
      path.setAttribute('class','graph-wire graph-wire-preview'); path.setAttribute('aria-hidden','true'); svg.append(path);
    }
  }
}
function graphDraw() {
  if (!graphCurrent) return;
  const host=$('graphNodes'); host.replaceChildren();
  for (const node of graphCurrent.nodes) {
    const card=document.createElement('article');
    card.className=`graph-node graph-${node.kind}${graphSelected === node.id ? ' selected' : ''}`;
    card.dataset.node=node.id;
    card.style.left=node.x+'px'; card.style.top=node.y+'px';
    const kind = graphKindLabel(node);
    card.innerHTML=`<button class="graph-port input" type="button" aria-label="Connect into ${graphText(kind)}" data-port="in"></button>
      <button class="graph-node-head" type="button"><span>${graphText(kind)}</span><b>⠿</b></button>
      <div class="graph-node-body"></div><button class="graph-port output" type="button" aria-label="Connect from ${graphText(kind)}" data-port="out"></button>`;
    card.querySelector('.graph-node-body').textContent=graphNodeLabel(node);
    const head=card.querySelector('.graph-node-head');
    head.title='Drag to move; arrow keys also move this card';
    head.onclick = () => graphSelect(node.id);
    card.onclick=() => {
      if (graphConnecting && graphConnecting!==node.id) {
        const source=graphConnecting; graphConnecting=null;
        $('graphViewport').classList.remove('graph-connecting'); graphLink(source,node.id);
      } else graphSelect(node.id);
    };
    card.ondblclick=event => {
      if (event.target.closest('.graph-port')) return;
      graphSelect(node.id);
      $('graphInspector').querySelector('input,select')?.focus({preventScroll:true});
    };
    head.onpointerdown = event => graphBeginDrag(event,node,card);
    head.onkeydown = event => {
      const direction={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[event.key];
      if (!direction) return;
      event.preventDefault(); graphSelect(node.id);
      graphMove(node,direction[0]*(event.shiftKey ? 5 : 1),direction[1]*(event.shiftKey ? 5 : 1));
    };
    card.querySelector('[data-port="out"]').onpointerdown = event => graphBeginWire(event,node.id);
    card.querySelector('[data-port="out"]').onclick = event => {
      event.stopPropagation();
      if (graphSuppressPortClick) { graphSuppressPortClick=false; return; }
      graphConnecting=node.id; $('graphViewport').classList.add('graph-connecting');
      $('graphFeedback').textContent='Choose a target card to connect.';
    };
    card.querySelector('[data-port="in"]').onclick = event => {
      event.stopPropagation(); if (!graphConnecting) return;
      const source=graphConnecting; graphConnecting=null;
      $('graphViewport').classList.remove('graph-connecting'); graphLink(source,node.id);
    };
    host.append(card);
  }
  graphDrawWires(); graphInspector();
  host.querySelectorAll('[data-node]').forEach(card => {
    const node=graphById(card.dataset.node);
    card.querySelector('.graph-node-body').textContent=graphNodeLabel(node);
  });
}
function graphMove(node,stepX,stepY) {
  node.x=graphPosition(node.x+stepX*GRAPH_GRID,2200);
  node.y=graphPosition(node.y+stepY*GRAPH_GRID,1480);
  const card=$('graphNodes').querySelector(`[data-node="${node.id}"]`);
  card.style.left=node.x+'px'; card.style.top=node.y+'px';
  graphDrawWires(); graphRevealCard(card);
}
function graphBeginDrag(event,node,card) {
  if (event.button !== 0) return;
  event.preventDefault();
  graphSelect(node.id);
  const handle=event.currentTarget,x=event.clientX,y=event.clientY,startX=node.x,startY=node.y;
  handle.focus({preventScroll:true});
  handle.setPointerCapture(event.pointerId);
  handle.onpointermove = move => {
    if (!handle.hasPointerCapture(event.pointerId)) return;
    node.x=graphPosition(startX+(move.clientX-x)/graphCamera.scale,2200);
    node.y=graphPosition(startY+(move.clientY-y)/graphCamera.scale,1480);
    card.style.left=node.x+'px'; card.style.top=node.y+'px'; graphDrawWires();
  };
  const finish=() => { handle.onpointermove=null; handle.onpointerup=null; handle.onpointercancel=null; };
  handle.onpointerup=finish; handle.onpointercancel=finish;
}
function graphBeginWire(event,source) {
  if (event.button !== 0) return;
  event.stopPropagation();
  graphSelect(source);
  const port=event.currentTarget,startX=event.clientX,startY=event.clientY;
  let moved=false;
  graphConnecting=source;
  port.setPointerCapture(event.pointerId);
  $('graphViewport').classList.add('graph-connecting');
  const update=(clientX,clientY) => {
    const element=document.elementFromPoint(clientX,clientY);
    const targetCard=element?.closest('[data-node]');
    const target=targetCard?.dataset.node!==source ? targetCard?.dataset.node : null;
    const input=target ? targetCard.querySelector('[data-port="in"]') : null;
    $('graphNodes').querySelectorAll('.graph-port.input').forEach(dot=>dot.classList.toggle('graph-port-target',dot===input));
    $('graphNodes').querySelectorAll('.graph-node').forEach(card=>card.classList.toggle('graph-node-target',card===targetCard && Boolean(target)));
    graphWirePreview={source,...graphCanvasPoint(clientX,clientY),target}; graphDrawWires();
  };
  const finish=() => {
    port.onpointermove=null; port.onpointerup=null; port.onpointercancel=null;
    $('graphViewport').classList.remove('graph-connecting');
    $('graphNodes').querySelectorAll('.graph-port-target').forEach(dot=>dot.classList.remove('graph-port-target'));
    $('graphNodes').querySelectorAll('.graph-node-target').forEach(card=>card.classList.remove('graph-node-target'));
    graphWirePreview=null; graphDrawWires();
  };
  port.onpointermove=move => {
    if (!port.hasPointerCapture(event.pointerId)) return;
    if (Math.hypot(move.clientX-startX,move.clientY-startY)>4) moved=true;
    if (moved) update(move.clientX,move.clientY);
  };
  port.onpointerup = up => {
    const target=document.elementFromPoint(up.clientX,up.clientY)?.closest('[data-node]')?.dataset.node;
    finish();
    if (target && target!==source) { graphSuppressPortClick=true; graphConnecting=null; graphLink(source,target); }
    else if (moved) { graphSuppressPortClick=true; graphConnecting=null; $('graphFeedback').textContent='Drop on another card to connect.'; }
    if (graphSuppressPortClick) setTimeout(()=>{ graphSuppressPortClick=false; },0);
  };
  port.onpointercancel=() => { finish(); graphConnecting=null; };
}
function graphSelect(id) { graphSelected=id; $('graphNodes').querySelectorAll('.graph-node').forEach(card => card.classList.toggle('selected',card.dataset.node===id)); graphInspector(); }
const graphSelectHtml=(name,options,value) => `<label>${graphText(name)}<select data-field="${name}">${options.map(([key,label]) => `<option value="${graphText(key)}"${String(key)===String(value) ? ' selected' : ''}>${graphText(label)}</option>`).join('')}</select></label>`;
function graphValueEditor(node,cap) {
  const value=node.value;
  if (cap?.type === 'boolean') return graphSelectHtml('value',[['true','On / true'],['false','Off / false']],String(value ?? true));
  if (cap?.type === 'enum') return graphSelectHtml('value',(cap.options||[]).map(option => [option,option]),value);
  return `<label>Value<input data-field="value" type="number" step="any" value="${graphText(value ?? 0)}"></label>`;
}
function graphInspector() {
  const host=$('graphInspector'),node=graphById(graphSelected);
  host.closest('.graph-inspector').hidden=!node;
  if (!node) { host.replaceChildren(); return; }
  const item=graphItem(graphContext(node.id));
  if (item && (node.kind === 'trigger' || node.kind === 'condition') && !node.property) {
    node.property=Object.keys(item.capabilities || {}).find(key =>
      ['eq','ne'].includes(node.operator) ? ['boolean','enum','number'].includes(item.capabilities[key].type) : item.capabilities[key].type === 'number') || '';
    const cap=item.capabilities[node.property];
    node.value=cap?.type==='boolean' ? true : cap?.type==='enum' ? cap.options?.[0] ?? null : 0;
  }
  if (item && node.kind === 'action' && !node.action) {
    node.action=(item.actions || []).find(action => ['boolean','enum','number'].includes(item.capabilities?.[action.replace(/^set_/,'')]?.type)) || '';
    const cap=item.capabilities?.[node.action.replace(/^set_/,'')];
    node.value=cap?.type==='boolean' ? true : cap?.type==='enum' ? cap.options?.[0] ?? null : 0;
  }
  let html=`<p class="graph-inspector-type">${graphText(node.kind.toUpperCase())}</p>`;
  if (node.kind === 'item') html+=graphSelectHtml('item',graphObjects.map(obj => [obj.id,obj.name]),node.item);
  if (node.kind === 'trigger' || node.kind === 'condition') {
    const caps=Object.entries(item?.capabilities || {}).filter(([,cap]) => ['boolean','enum','number'].includes(cap.type));
    html+=`<p class="muted tiny">Item: ${graphText(item?.name || 'Connect an item card first')}</p>`;
    html+=graphSelectHtml('property',caps.map(([key,cap]) => [key,cap.label || key]),node.property);
    html+=graphSelectHtml('operator',GRAPH_OPERATORS,node.operator);
    if (!['eq','ne'].includes(node.operator)) html+='<p class="muted tiny">Order comparisons require a numeric property.</p>';
    html+=graphValueEditor(node,item?.capabilities[node.property]);
  }
  if (node.kind === 'action') {
    const actions=(item?.actions || []).filter(action => ['boolean','enum','number'].includes(item.capabilities?.[action.replace(/^set_/, '')]?.type));
    html+=`<p class="muted tiny">Target item: ${graphText(item?.name || 'Connect an item card first')}</p>`;
    html+=graphSelectHtml('action',actions.map(action => [action,action.replace(/^set_/, '').replaceAll('_',' ')]),node.action);
    html+=graphValueEditor(node,item?.capabilities[node.action.replace(/^set_/, '')]);
  }
  if (node.kind === 'delay') html+=`<label>Seconds<input data-field="seconds" type="number" min="1" max="86400" value="${node.seconds}"></label>`;
  if (node.kind === 'time' || node.kind === 'clock_trigger') {
    const tc=node.time_condition;
    html+=graphSelectHtml('boundary',[['clock','Clock'],['sunrise','Sunrise'],['sunset','Sunset']],tc.boundary);
    if (tc.boundary === 'clock') html+=`<label>Local time<input data-field="time" type="time" value="${graphText(tc.time)}"></label>`;
    if (node.kind === 'time') html+=graphSelectHtml('after',[['true','At or after'],['false','Before']],String(tc.after));
    else html+='<p class="muted tiny">Runs once per local day when this time is reached. The Hub must be running then.</p>';
    if (tc.boundary !== 'clock') html+=`<label>Solar offset (minutes)<input data-field="offset_minutes" type="number" min="-180" max="180" value="${tc.offset_minutes}"></label>`;
  }
  if (node.kind === 'window') {
    html+=`<p class="muted tiny">Uses the timezone saved in Settings. Windows that cross midnight work automatically.</p>
      <label>From<input data-field="start" type="time" value="${graphText(node.start)}"></label>
      <label>Until<input data-field="end" type="time" value="${graphText(node.end)}"></label>`;
  }
  host.innerHTML=html;
  host.querySelectorAll('[data-field]').forEach(input => input.onchange = () => {
    const field=input.dataset.field;
    if (node.kind === 'time' || node.kind === 'clock_trigger') node.time_condition[field]=field==='after' ? input.value==='true' : field==='offset_minutes' ? Number(input.value) : input.value;
    else if (field==='start' || field==='end') node[field]=input.value;
    else if (field==='item' || field==='property' || field==='action' || field==='operator') {
      node[field]=input.value;
      if (field==='property' || field==='action') {
        const cap=graphItem(graphContext(node.id))?.capabilities[field==='action' ? input.value.replace(/^set_/,'') : input.value];
        node.value=cap?.type==='boolean' ? true : cap?.type==='enum' ? cap.options?.[0] ?? null : 0;
      }
      if (field==='operator' && !['eq','ne'].includes(node.operator)) {
        const item=graphItem(graphContext(node.id));
        if (item?.capabilities[node.property]?.type !== 'number') {
          node.property=Object.keys(item?.capabilities || {}).find(key => item.capabilities[key].type === 'number') || '';
          node.value=0;
        }
      }
    } else if (field==='seconds') node.seconds=Number(input.value);
    else {
      const cap=graphItem(graphContext(node.id))?.capabilities[node.kind==='action' ? node.action.replace(/^set_/,'') : node.property];
      node.value=cap?.type==='boolean' ? input.value==='true' : cap?.type==='number' ? Number(input.value) : input.value;
    }
    const card=$('graphNodes').querySelector(`[data-node="${node.id}"]`);
    card.querySelector('.graph-node-head span').textContent=graphKindLabel(node);
    card.querySelector('.graph-node-body').textContent=graphNodeLabel(node);
    if (['item','property','action','operator','boundary'].includes(field)) {
      graphInspector(); host.querySelector(`[data-field="${field}"]`)?.focus({preventScroll:true});
    }
  });
}
function graphPalette() {
  const items=$('graphItemPalette'); items.replaceChildren();
  const label=document.createElement('h4'); label.textContent='Items'; items.append(label);
  for (const obj of graphObjects) graphPaletteEntry(items,'item',obj.name,obj.id);
  const logic=$('graphLogicPalette'); logic.replaceChildren();
  for (const [title,kinds] of [['When',['trigger','clock_trigger']],['While / compare',['condition']],
      ['Time conditions',['time','window']],['Then',['action','delay']]]) {
    const heading=document.createElement('h4'); heading.textContent=title; logic.append(heading);
    for (const [kind,name,icon,operator] of GRAPH_KINDS.filter(row => kinds.includes(row[0])))
      graphPaletteEntry(logic,kind,icon+' '+name,'',operator);
  }
}
function graphPaletteEntry(host,kind,label,item,operator='eq') {
  const button=document.createElement('button'); button.type='button'; button.className='graph-palette-card';
  button.dataset.kind=kind;
  button.textContent=label; button.draggable=true;
  button.ondragstart=event => event.dataTransfer.setData('application/x-hub-node',JSON.stringify({kind,item,operator}));
  button.onclick=() => {
    if (!$('graphEditor').hidden) {
      const selected=graphById(graphSelected);
      graphMakeNode(kind,item,selected ? selected.x+225 : 45,selected ? selected.y : 50+graphCurrent.nodes.length*115,operator);
    }
  };
  host.append(button);
}
$('graphViewport').ondragover=event => { if (event.dataTransfer.types.includes('application/x-hub-node')) event.preventDefault(); };
$('graphViewport').ondrop=event => {
  event.preventDefault();
  let data; try { data=JSON.parse(event.dataTransfer.getData('application/x-hub-node')); } catch (_) { return; }
  if (!['item',...GRAPH_KINDS.map(row=>row[0])].includes(data.kind)) return;
  const point=graphCanvasPoint(event.clientX,event.clientY);
  graphMakeNode(data.kind,data.item || '',point.x,point.y,data.operator || 'eq');
};
$('graphZoomIn').onclick=()=>graphZoomTo(graphCamera.scale*1.2);
$('graphZoomOut').onclick=()=>graphZoomTo(graphCamera.scale/1.2);
$('graphFit').onclick=graphFit;
$('graphViewport').addEventListener('wheel',event => {
  if (!event.ctrlKey && !event.metaKey) return;
  event.preventDefault(); graphZoomTo(graphCamera.scale*(event.deltaY<0 ? 1.1 : 1/1.1),event.clientX,event.clientY);
},{passive:false});
$('graphViewport').onpointerdown=event => {
  if (event.button !== 0 || event.target.closest('.graph-node,.graph-wire')) return;
  const frame=event.currentTarget,x=event.clientX,y=event.clientY,startX=graphCamera.x,startY=graphCamera.y;
  frame.setPointerCapture(event.pointerId); frame.classList.add('graph-panning');
  frame.onpointermove=move => {
    if (!frame.hasPointerCapture(event.pointerId)) return;
    graphCamera.x=startX+move.clientX-x; graphCamera.y=startY+move.clientY-y; graphApplyCamera();
  };
  const finish=()=>{ frame.classList.remove('graph-panning'); frame.onpointermove=null; frame.onpointerup=null; frame.onpointercancel=null; };
  frame.onpointerup=finish; frame.onpointercancel=finish;
};
document.addEventListener('keydown',event => {
  if (!graphCurrent || $('graphEditor').hidden) return;
  if (event.key==='Escape' && graphConnecting) {
    graphConnecting=null; graphWirePreview=null; $('graphViewport').classList.remove('graph-connecting');
    graphDrawWires(); $('graphFeedback').textContent='Connection cancelled.';
  }
  if (!['Delete','Backspace'].includes(event.key) || !graphSelected || event.ctrlKey || event.metaKey || event.altKey) return;
  if (!event.target.closest('#graphEditor') || event.target.closest('input,textarea,select,[contenteditable]') || event.target.isContentEditable) return;
  event.preventDefault(); graphDeleteSelected();
});
function graphOpen(saved=null) {
  graphOpener=document.activeElement;
  graphEditing=saved?.id || null;
  graphCurrent=saved ? {name:saved.name,enabled:saved.enabled,nodes:structuredClone(saved.nodes),edges:structuredClone(saved.edges)} : {name:'',enabled:true,nodes:[],edges:[]};
  graphSerial=Math.max(0,...graphCurrent.nodes.map(node=>Number(node.id.replace(/^n/,''))||0));
  graphSelected=null; graphConnecting=null; graphWirePreview=null;
  $('graphEditor').hidden=false; $('graphEditorHeading').textContent=saved ? 'Edit automation' : 'New automation';
  $('graphName').value=graphCurrent.name; $('graphEnabled').checked=graphCurrent.enabled;
  $('graphFeedback').textContent=''; graphPalette(); graphDraw();
  requestAnimationFrame(graphFit);
  $('graphEditor').scrollIntoView({behavior:'smooth',block:'start'});
  $('graphName').focus({preventScroll:true});
}
function graphClose() {
  $('graphEditor').hidden=true; graphCurrent=null; graphSelected=null; graphConnecting=null; graphWirePreview=null;
  (graphOpener?.isConnected ? graphOpener : $('graphNew')).focus({preventScroll:true});
  graphOpener=null;
}
$('graphNew').onclick=() => graphOpen();
$('graphCancel').onclick=graphClose;
function graphDeleteSelected() {
  if (!graphCurrent || !graphSelected) return;
  graphCurrent.nodes=graphCurrent.nodes.filter(node=>node.id!==graphSelected);
  graphCurrent.edges=graphCurrent.edges.filter(edge=>edge.source!==graphSelected&&edge.target!==graphSelected);
  graphSelected=null; graphConnecting=null; graphDraw();
  $('graphViewport').focus({preventScroll:true});
}
$('graphDeleteNode').onclick=graphDeleteSelected;
$('graphViewport').onclick=event => {
  if (!event.target.closest('.graph-node,.graph-wire-hit')) graphSelect(null);
};
$('graphSave').onclick=async () => {
  graphCurrent.name=$('graphName').value.trim(); graphCurrent.enabled=$('graphEnabled').checked;
  if (!graphCurrent.name) { $('graphFeedback').textContent='Give the automation a name.'; return; }
  const button=$('graphSave'); button.disabled=true;
  try {
    await api('/api/zigbee/automations/graphs'+(graphEditing ? '/'+graphEditing : ''),
      {method:graphEditing ? 'PUT' : 'POST',body:JSON.stringify(graphCurrent)});
    graphClose(); await loadGraphAutomations();
  } catch (error) { $('graphFeedback').textContent=error.message; }
  finally { button.disabled=false; }
};
function graphRenderList() {
  const signature=JSON.stringify([graphSaved,graphLegacy,graphObjects.map(obj => [obj.id,obj.name])]);
  if (signature === graphListSignature) return;
  graphListSignature=signature;
  const host=$('automationAllCards'),active=document.activeElement;
  const focusedCard=active?.closest?.('[data-automation-key]');
  const focusKey=focusedCard?.dataset.automationKey;
  const focusAction=['edit','toggle','delete'].find(key => active.hasAttribute?.('data-'+key));
  const focusIndex=focusedCard ? [...host.children].indexOf(focusedCard) : -1;
  host.replaceChildren();
  for (const graph of graphSaved) {
    const card=document.createElement('article'); card.className='panel automation-card graph-list-card';
    card.dataset.automationKey='graph:'+graph.id;
    card.innerHTML='<div><h3></h3><p class="muted"></p><span class="graph-card-status"></span></div><div class="automation-pair"><button class="btn" data-edit>Edit canvas</button><button class="btn" data-delete>Delete</button></div>';
    card.querySelector('h3').textContent=graph.name;
    card.querySelector('p').textContent=`${graph.nodes.length} cards · ${graph.edges.length} connections · ${graph.enabled ? 'Enabled' : 'Disabled'}`;
    card.querySelector('.graph-card-status').textContent=graph.status;
    card.querySelector('[data-edit]').onclick=() => graphOpen(graph);
    card.querySelector('[data-delete]').onclick=async () => {
      if (!confirm('Delete this automation? Already scheduled actions still finish.')) return;
      try { await api('/api/zigbee/automations/graphs/'+graph.id,{method:'DELETE'}); await loadGraphAutomations(); }
      catch (error) { $('automationStatus').textContent=error.message; }
    };
    host.append(card);
  }
  for (const rule of graphLegacy) {
    const card=document.createElement('article'); card.className='panel automation-card graph-list-card';
    card.dataset.automationKey='rule:'+rule.id;
    card.innerHTML='<div><h3></h3><p class="muted"></p><span class="graph-card-status"></span></div><div class="automation-pair"><button class="btn" data-toggle></button><button class="btn" data-delete>Delete</button></div>';
    card.querySelector('h3').textContent=rule.name;
    card.querySelector('p').textContent=`Earlier rule · ${graphItem(rule.source)?.name || rule.source}: ${rule.property} = ${rule.equals} → ${graphItem(rule.target)?.name || rule.target} · ${rule.seconds}s`;
    card.querySelector('.graph-card-status').textContent=rule.status;
    card.querySelector('[data-toggle]').textContent=rule.enabled ? 'Disable' : 'Enable';
    card.querySelector('[data-toggle]').onclick=async () => {
      const {name,source,property,equals,target,seconds,while_occupied,time_condition}=rule;
      try { await api('/api/zigbee/automations/'+rule.id,{method:'PUT',body:JSON.stringify({name,source,property,equals,target,seconds,while_occupied,time_condition,enabled:!rule.enabled})}); await loadGraphAutomations(); }
      catch (error) { $('automationStatus').textContent=error.message; }
    };
    card.querySelector('[data-delete]').onclick=async () => {
      if (!confirm('Delete this rule? Already scheduled actions still finish.')) return;
      try { await api('/api/zigbee/automations/'+rule.id,{method:'DELETE'}); await loadGraphAutomations(); }
      catch (error) { $('automationStatus').textContent=error.message; }
    };
    host.append(card);
  }
  if (!host.children.length) host.textContent='No automations yet. Create a flow from the item and action cards.';
  if (focusKey) {
    const replacement=[...host.children].find(card => card.dataset.automationKey === focusKey);
    (replacement?.querySelector(`[data-${focusAction}]`) || host.children[Math.min(focusIndex,host.children.length-1)]?.querySelector('button') || $('graphNew')).focus({preventScroll:true});
  }
}
async function loadGraphAutomations() {
  if (graphLoading) return;
  graphLoading=true;
  try {
    const [data,devices]=await Promise.all([api('/api/zigbee/automations'),api('/api/v1/objects?module=zigbee')]);
    graphSaved=data.graphs || []; graphLegacy=data.rules || [];
    const nextObjects=devices.objects || [];
    const paletteSignature=JSON.stringify(nextObjects.map(obj => [obj.id,obj.name,obj.capabilities,obj.actions]));
    const paletteChanged=paletteSignature !== graphPaletteSignature;
    graphPaletteSignature=paletteSignature;
    graphObjects=nextObjects;
    graphRenderList();
    if (graphCurrent && paletteChanged) graphPalette();
  } catch (error) { $('automationStatus').textContent=error.message; }
  finally { graphLoading=false; }
}
$('automationRefresh').addEventListener('click',loadGraphAutomations);
setInterval(() => { if ($('automationsView').classList.contains('active') && !document.hidden) loadGraphAutomations(); }, 10000);
