/* Item-based flow editor. Cards are selectable, draggable and connected by ports. */
let graphObjects = [], graphSaved = [], graphLegacy = [], graphCurrent = null;
let graphEditing = null, graphSelected = null, graphConnecting = null, graphDrag = null;
let graphLoading = false, graphSerial = 0;
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
    x:Math.max(0,Math.min(2200,Math.round(x))),y:Math.max(0,Math.min(1480,Math.round(y)))};
  graphCurrent.nodes.push(node);
  if (graphSelected && graphSelected !== node.id) {
    const selected = graphById(graphSelected);
    if (selected && kind !== 'clock_trigger' && (kind !== 'trigger' || selected.kind === 'item'))
      graphLink(selected.id, node.id, false);
  }
  graphSelected = node.id;
  graphDraw();
  return node;
}
function graphLink(source, target, redraw = true) {
  if (!source || !target || source === target || graphCurrent.edges.some(edge => edge.source === source && edge.target === target)) return;
  graphCurrent.edges.push({source,target});
  if (redraw) graphDraw();
}
function graphDrawWires() {
  const svg = $('graphWires'); svg.replaceChildren();
  for (const edge of graphCurrent.edges) {
    const a = graphById(edge.source), b = graphById(edge.target);
    if (!a || !b) continue;
    const x1=a.x+188,y1=a.y+47,x2=b.x,y2=b.y+47;
    const path = document.createElementNS('http://www.w3.org/2000/svg','path');
    const bend=Math.max(48,Math.abs(x2-x1)*.45);
    path.setAttribute('d',`M${x1} ${y1} C${x1+bend} ${y1}, ${x2-bend} ${y2}, ${x2} ${y2}`);
    path.setAttribute('class','graph-wire');
    path.setAttribute('aria-label','Remove connection');
    path.onclick = () => { graphCurrent.edges=graphCurrent.edges.filter(row => row !== edge); graphDraw(); };
    svg.append(path);
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
    const kind = node.kind === 'item' ? 'Item' : GRAPH_KINDS.find(row => row[0] === node.kind && (!row[3] || row[3] === node.operator))?.[1] || node.kind;
    card.innerHTML=`<button class="graph-port input" type="button" aria-label="Connect into ${graphText(kind)}" data-port="in"></button>
      <button class="graph-node-head" type="button"><span>${graphText(kind)}</span><b>⠿</b></button>
      <div class="graph-node-body"></div><button class="graph-port output" type="button" aria-label="Connect from ${graphText(kind)}" data-port="out"></button>`;
    card.querySelector('.graph-node-body').textContent=graphNodeLabel(node);
    card.querySelector('.graph-node-head').onclick = () => graphSelect(node.id);
    card.querySelector('.graph-node-head').onpointerdown = event => graphBeginDrag(event,node,card);
    card.querySelector('[data-port="out"]').onpointerdown = event => graphBeginWire(event,node.id);
    card.querySelector('[data-port="out"]').onclick = event => { event.stopPropagation(); graphConnecting=node.id; $('graphFeedback').textContent='Select an input dot to connect cards.'; };
    card.querySelector('[data-port="in"]').onclick = event => {
      event.stopPropagation(); if (!graphConnecting) return;
      graphLink(graphConnecting,node.id); graphConnecting=null; $('graphFeedback').textContent='';
    };
    host.append(card);
  }
  graphDrawWires(); graphInspector();
  host.querySelectorAll('[data-node]').forEach(card => {
    const node=graphById(card.dataset.node);
    card.querySelector('.graph-node-body').textContent=graphNodeLabel(node);
  });
}
function graphBeginDrag(event,node,card) {
  if (event.button !== 0) return;
  graphSelect(node.id);
  const x=event.clientX,y=event.clientY,startX=node.x,startY=node.y;
  event.currentTarget.setPointerCapture(event.pointerId);
  event.currentTarget.onpointermove = move => {
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
    node.x=Math.max(0,Math.min(2200,Math.round(startX+move.clientX-x)));
    node.y=Math.max(0,Math.min(1480,Math.round(startY+move.clientY-y)));
    card.style.left=node.x+'px'; card.style.top=node.y+'px'; graphDrawWires();
  };
  event.currentTarget.onpointerup = up => { up.currentTarget.onpointermove=null; up.currentTarget.onpointerup=null; };
}
function graphBeginWire(event,source) {
  event.stopPropagation();
  graphConnecting=source;
  const port=event.currentTarget;
  port.setPointerCapture(event.pointerId);
  port.onpointerup = up => {
    const target=document.elementFromPoint(up.clientX,up.clientY)?.closest('[data-port="in"]')?.closest('[data-node]')?.dataset.node;
    if (target) { graphLink(source,target); graphConnecting=null; $('graphFeedback').textContent=''; }
    port.onpointerup=null;
  };
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
  $('graphDeleteNode').hidden=!node;
  if (!node) { host.textContent='Select a card to configure it. Connect output to input dots.'; return; }
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
    html+=`<label>Local time<input data-field="time" type="time" value="${graphText(tc.time)}"></label>`;
    if (node.kind === 'time') html+=graphSelectHtml('after',[['true','At or after'],['false','Before']],String(tc.after));
    else html+='<p class="muted tiny">Runs once per local day when this time is reached. The Hub must be running then.</p>';
    html+=`<label>Solar offset (minutes)<input data-field="offset_minutes" type="number" min="-180" max="180" value="${tc.offset_minutes}"></label>`;
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
    } else if (field==='seconds') node.seconds=Number(input.value);
    else {
      const cap=graphItem(graphContext(node.id))?.capabilities[node.kind==='action' ? node.action.replace(/^set_/,'') : node.property];
      node.value=cap?.type==='boolean' ? input.value==='true' : cap?.type==='number' ? Number(input.value) : input.value;
    }
    graphDraw();
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
$('graphCanvas').ondragover=event => { if (event.dataTransfer.types.includes('application/x-hub-node')) event.preventDefault(); };
$('graphCanvas').ondrop=event => {
  event.preventDefault();
  let data; try { data=JSON.parse(event.dataTransfer.getData('application/x-hub-node')); } catch (_) { return; }
  if (!['item',...GRAPH_KINDS.map(row=>row[0])].includes(data.kind)) return;
  const rect=$('graphCanvas').getBoundingClientRect();
  graphMakeNode(data.kind,data.item || '',event.clientX-rect.left,event.clientY-rect.top,data.operator || 'eq');
};
function graphOpen(saved=null) {
  graphEditing=saved?.id || null;
  graphCurrent=saved ? {name:saved.name,enabled:saved.enabled,nodes:structuredClone(saved.nodes),edges:structuredClone(saved.edges)} : {name:'',enabled:true,nodes:[],edges:[]};
  graphSerial=Math.max(0,...graphCurrent.nodes.map(node=>Number(node.id.replace(/^n/,''))||0));
  graphSelected=null; graphConnecting=null;
  $('graphEditor').hidden=false; $('graphEditorHeading').textContent=saved ? 'Edit automation' : 'New automation';
  $('graphName').value=graphCurrent.name; $('graphEnabled').checked=graphCurrent.enabled;
  $('graphFeedback').textContent=''; graphPalette(); graphDraw();
  $('graphEditor').scrollIntoView({behavior:'smooth',block:'start'});
}
function graphClose() { $('graphEditor').hidden=true; graphCurrent=null; graphSelected=null; }
$('graphNew').onclick=() => graphOpen();
$('graphCancel').onclick=graphClose;
$('graphDeleteNode').onclick=() => {
  graphCurrent.nodes=graphCurrent.nodes.filter(node=>node.id!==graphSelected);
  graphCurrent.edges=graphCurrent.edges.filter(edge=>edge.source!==graphSelected&&edge.target!==graphSelected);
  graphSelected=null; graphDraw();
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
  const host=$('automationAllCards'); host.replaceChildren();
  for (const graph of graphSaved) {
    const card=document.createElement('article'); card.className='panel automation-card graph-list-card';
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
}
async function loadGraphAutomations() {
  if (graphLoading) return;
  graphLoading=true;
  try {
    const [data,devices]=await Promise.all([api('/api/zigbee/automations'),api('/api/v1/objects?module=zigbee')]);
    graphSaved=data.graphs || []; graphLegacy=data.rules || []; graphObjects=devices.objects || [];
    graphRenderList();
    if (graphCurrent) graphPalette();
  } catch (error) { $('automationStatus').textContent=error.message; }
  finally { graphLoading=false; }
}
$('automationRefresh').addEventListener('click',loadGraphAutomations);
setInterval(() => { if ($('automationsView').classList.contains('active') && !document.hidden) loadGraphAutomations(); }, 10000);
