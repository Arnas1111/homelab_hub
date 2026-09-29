/* Capability-driven cards with stable nodes, local drafts and per-device commands. */
let zigbeeLoading = false;
let zigbeeSending = false; // Compatibility for browser diagnostics.
let zigbeeObjects = [];
let zigbeeOrganization = {};
let zigbeeReachable = true;
const zigbeeCards = new Map();
const zigbeePending = new Set();
const zigbeeNotices = new Map();
const zbE = escapeHtml;
const zbLabel = key => key.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
function zbColor(hex) {
  const rgb = hex.match(/[a-f\d]{2}/gi).map(v => { const n = parseInt(v,16)/255; return n > .04045 ? ((n+.055)/1.055)**2.4 : n/12.92; });
  const [r,g,b] = rgb, x = r*.4124+g*.3576+b*.1805, y=r*.2126+g*.7152+b*.0722, z=r*.0193+g*.1192+b*.9505;
  const sum=x+y+z;
  return sum ? {x:x/sum,y:y/sum} : {x:.3127,y:.329};
}
function zbHex(value) {
  if (!value || !value.y) return '#ffffff';
  const x=value.x/value.y, z=(1-value.x-value.y)/value.y;
  let rgb=[3.2406*x-1.5372-.4986*z,-.9689*x+1.8758+.0415*z,.0557*x-.204+1.057*z];
  rgb=rgb.map(v=>v<=.0031308 ? 12.92*v : 1.055*Math.max(0,v)**(1/2.4)-.055);
  const scale=Math.max(1,...rgb);
  return '#'+rgb.map(v=>Math.round(Math.max(0,Math.min(1,v/scale))*255).toString(16).padStart(2,'0')).join('');
}
function zbRange(object,key,label,low,high,unit='',step=1,component='') {
  const value=component ? object.state[key]?.[component] : object.state[key];
  return `<label class="zb-control"><span>${zbE(label)}<output>${value == null ? '—' : zbE(value)} ${zbE(unit)}</output></span><input type="range" min="${low}" max="${high}" step="${step}" value="${value ?? low}" aria-label="${zbE(object.name+' '+label)}" data-zigbee-action="set_${key}" data-component="${component}" data-unit="${zbE(unit)}"></label>`;
}
function renderZigbeeObject(object) {
  const caps=object.capabilities || {}, state=object.state, power=state.power;
  const can=key=>object.actions.includes('set_'+key);
  let controls='';
  if(can('brightness')) controls+=zbRange(object,'brightness','Brightness',0,100,'%');
  if(can('color_temp')) controls+=zbRange(object,'color_temp','White temperature',caps.color_temp.minimum,caps.color_temp.maximum,'mired');
  if(can('color_xy')) controls+=`<label class="zb-color"><span>Color</span><input type="color" aria-label="${zbE(object.name)} color" value="${zbHex(state.color_xy)}" data-zigbee-action="set_color_xy"></label>`;
  else if(can('color_hs')) controls+=zbRange(object,'color_hs','Hue',0,360,'°',1,'hue')+zbRange(object,'color_hs','Saturation',0,100,'%',1,'saturation');
  if(can('effect')) controls+=`<label class="zb-control"><span>Effect</span><select class="select" aria-label="${zbE(object.name)} effect" data-zigbee-action="set_effect"><option value="">Choose effect</option>${(caps.effect?.options || []).map(v=>`<option value="${zbE(v)}">${zbE(v)}</option>`).join('')}</select></label>`;
  const readings=Object.entries(caps).filter(([key])=>!can(key) && !['battery','linkquality'].includes(key)).map(([key,cap])=>{
    const value=state[key];
    if(typeof value==='object' && value!==null) return '';
    return `<div class="zb-reading"><span>${zbE(cap.label || zbLabel(key))}</span><strong>${value == null ? '—' : typeof value==='boolean' ? value ? 'Yes':'No' : zbE(value)} <small>${zbE(cap.unit || '')}</small></strong></div>`;
  }).join('');
  return `<header class="zb-card-head"><span class="zb-device-icon" aria-hidden="true">${object.type==='light'?'☀':object.type==='switch'?'⏻':'◉'}</span><div><h3>${zbE(object.name)}</h3><span class="zb-state ${object.available?'':'offline'}">${object.available ? zbLabel(object.type) : 'Unavailable · last reported state'}</span></div>${can('power')?`<button class="zb-toggle" role="switch" aria-checked="${power===true}" aria-label="${zbE(object.name)} power" data-zigbee-action="set_power" data-value="${power!==true}"><span></span></button>`:''}</header>
    <div class="zb-controls">${controls}${readings}</div>
    <footer class="zb-footer"><span>${state.battery==null?'':`Battery ${zbE(state.battery)} %`}</span><span>${state.linkquality==null?'':`Signal ${zbE(state.linkquality)} LQI`}</span></footer>
    <p class="zb-notice" role="status">${zbE(zigbeeNotices.get(object.id) || '')}</p>
    <details class="zb-details"><summary>Details & grouping</summary><p class="muted tiny">${zbE(object.id)}<br>${object.updated_at ? 'Last report: '+zbE(new Date(object.updated_at).toLocaleString()):'No state report yet'}</p><label>Room / category<input class="zb-group-input" list="zigbeeGroupNames" maxlength="80" value="${zbE(zigbeeOrganization[object.id] || '')}" placeholder="e.g. Living room"></label><button class="btn" data-save-zb-group>Save group</button></details>`;
}
function renderZigbee() {
  const search=$('zigbeeSearch').value.toLowerCase(), type=$('zigbeeType').value, mode=$('zigbeeGrouping').value;
  const visible=zigbeeObjects.filter(o=>(!type || o.type===type) && (o.name+' '+(zigbeeOrganization[o.id]||'')).toLowerCase().includes(search));
  $('zigbeeCount').textContent=`${visible.length} / ${zigbeeObjects.length} devices`;
  const root=$('zigbeeLights'), groups=new Map();
  for(const object of visible) {
    const group=mode==='type'?zbLabel(object.type)+'s':mode==='room'?zigbeeOrganization[object.id]||'Ungrouped':'All devices';
    if(!groups.has(group)) groups.set(group,[]);
    groups.get(group).push(object);
  }
  const activeGroups=new Set();
  for(const [name,objects] of [...groups].sort(([a],[b])=>a.localeCompare(b))) {
    let section=[...root.children].find(n=>n.dataset.group===name);
    if(!section) { section=document.createElement('section'); section.className='zb-group'; section.dataset.group=name; section.innerHTML='<h3 class="zb-group-title"></h3><div class="zigbee-grid"></div>'; root.appendChild(section); }
    activeGroups.add(name);
    section.firstChild.textContent=`${name} · ${objects.length}`;
    const grid=section.lastChild;
    for(const object of objects.sort((a,b)=>a.name.localeCompare(b.name))) {
      let card=zigbeeCards.get(object.id);
      if(!card) { card=document.createElement('article'); card.className='zb-card'; card.dataset.objectId=object.id; zigbeeCards.set(object.id,card); }
      if(card.parentNode!==grid) grid.appendChild(card);
      card.hidden=false;
      const editing=card.contains(document.activeElement) && document.activeElement.matches('input,select');
      if(!editing && !zigbeePending.has(object.id)) patchContent(card,renderZigbeeObject(object));
      for(const control of card.querySelectorAll('[data-zigbee-action]')) control.disabled=!object.available || !zigbeeReachable || zigbeePending.has(object.id);
    }
  }
  const ids=new Set(visible.map(o=>o.id)), known=new Set(zigbeeObjects.map(o=>o.id));
  for(const [id,card] of zigbeeCards) {
    if(!ids.has(id)) card.remove();
    if(!known.has(id)) { zigbeeCards.delete(id); zigbeeNotices.delete(id); }
  }
  for(const section of [...root.children]) if(!activeGroups.has(section.dataset.group)) section.remove();
  if(!visible.length) { const empty=document.createElement('p'); empty.className='board-empty'; empty.textContent=zigbeeObjects.length?'No devices match these filters.':'No supported devices discovered. Pair a device in Zigbee2MQTT.'; root.appendChild(empty); }
  patchContent($('zigbeeGroupNames'),[...new Set(Object.values(zigbeeOrganization))].sort().map(g=>`<option value="${zbE(g)}"></option>`).join(''));
}
async function loadZigbee() {
  if(zigbeeLoading) return;
  zigbeeLoading=true;
  try {
    const [modules,result,organization]=await Promise.all([api('/api/v1/modules'),api('/api/v1/objects?module=zigbee'),api('/api/zigbee/organization')]);
    zigbeeObjects=result.objects; zigbeeOrganization=organization; zigbeeReachable=true;
    const status=modules.modules.find(m=>m.id==='zigbee')?.status;
    $('zigbeeStatus').textContent=status==='online'?'Zigbee2MQTT online':typeof mqttMessages!=='undefined'?mqttMessages[status]||'Zigbee unavailable':status||'Zigbee unavailable';
    renderZigbee();
  } catch(error) { zigbeeReachable=false; $('zigbeeStatus').textContent=`Unable to refresh: ${error.message}. Showing last received values.`; renderZigbee(); }
  finally { zigbeeLoading=false; }
}
async function sendZigbeeAction(control) {
  const card=control.closest('[data-object-id]'), id=card.dataset.objectId;
  if(control.disabled || zigbeePending.has(id)) return;
  const action=control.dataset.zigbeeAction;
  let value=action==='set_power'?control.dataset.value==='true':action==='set_effect'?control.value:action==='set_color_xy'?zbColor(control.value):Number(control.value);
  if(action==='set_effect' && !value) return;
  if(action==='set_color_hs') value=Object.fromEntries([...card.querySelectorAll('[data-zigbee-action="set_color_hs"]')].map(i=>[i.dataset.component,Number(i.value)]));
  zigbeePending.add(id); zigbeeSending=true;
  for(const input of card.querySelectorAll('[data-zigbee-action]')) input.disabled=true;
  try {
    await api(`/api/v1/objects/${encodeURIComponent(id)}/actions`,{method:'POST',body:JSON.stringify({action,value})});
    zigbeeNotices.set(id,'Command sent · awaiting device report');
    const before=zigbeeObjects.find(o=>o.id===id)?.updated_at;
    setTimeout(()=>{if(zigbeeNotices.get(id)==='Command sent · awaiting device report'){zigbeeNotices.set(id,zigbeeObjects.find(o=>o.id===id)?.updated_at!==before?'Device report received':'No new report yet');renderZigbee();}},6000);
  } catch(error) { zigbeeNotices.set(id,`Failed: ${error.message}`); }
  finally { zigbeePending.delete(id); zigbeeSending=zigbeePending.size>0; control.blur(); renderZigbee(); loadZigbee(); }
}
$('zigbeeRefresh').addEventListener('click',loadZigbee);
for(const id of ['zigbeeSearch','zigbeeType','zigbeeGrouping']) $(id).addEventListener(id==='zigbeeSearch'?'input':'change',renderZigbee);
$('zigbeeLights').addEventListener('input',event=>{const input=event.target;if(input.type==='range') input.closest('label').querySelector('output').textContent=`${input.value} ${input.dataset.unit}`;});
$('zigbeeLights').addEventListener('change',event=>{if(event.target.matches('input[data-zigbee-action],select[data-zigbee-action]'))sendZigbeeAction(event.target);});
$('zigbeeLights').addEventListener('click',async event=>{
  const control=event.target.closest('button[data-zigbee-action]'); if(control) return sendZigbeeAction(control);
  const save=event.target.closest('[data-save-zb-group]'); if(!save) return;
  const card=save.closest('[data-object-id]'); save.disabled=true;
  try { zigbeeOrganization=await api(`/api/zigbee/organization/${encodeURIComponent(card.dataset.objectId)}`,{method:'PUT',body:JSON.stringify({group:card.querySelector('.zb-group-input').value})}); $('zigbeeFeedback').textContent='Group saved.'; renderZigbee(); }
  catch(error){$('zigbeeFeedback').textContent=error.message;}finally{save.disabled=false;}
});
setInterval(()=>{if(!document.hidden && $('zigbeeView').classList.contains('active'))loadZigbee();},5000);