/* Code-only Zigbee automation editor. Graph nodes are an internal runtime format. */
let graphObjects=[], graphSaved=[], graphLegacy=[], graphEditing=null, graphOpener=null, graphLoading=false;
let graphListSignature='';
const graphItem=id=>graphObjects.find(device=>device.id===id);

function graphOpen(saved=null) {
  graphOpener=document.activeElement;
  graphEditing=saved?.id || null;
  $('graphEditor').hidden=false;
  $('graphEditorHeading').textContent=saved ? 'Edit automation' : 'New automation';
  $('graphName').value=saved?.name || '';
  $('graphEnabled').checked=saved?.enabled ?? true;
  const result=saved?.code ? {code:saved.code} : saved ? graphCodeSerialize(saved) : {code:''};
  $('graphCode').value=result.code || '';
  $('graphLegacyData').hidden=!result.error;
  $('graphLegacyJson').textContent=result.error ? JSON.stringify({nodes:saved.nodes,edges:saved.edges},null,2) : '';
  graphCodeMessage(result.error ? 'This older flow cannot be converted automatically. Enter a new rule to replace it; the original stays active until you save.' : '',Boolean(result.error));
  $('graphEditor').scrollIntoView({behavior:'smooth',block:'start'});
  (saved ? $('graphCode') : $('graphName')).focus({preventScroll:true});
}
function graphClose() {
  $('graphEditor').hidden=true;
  graphEditing=null;
  (graphOpener?.isConnected ? graphOpener : $('graphNew')).focus({preventScroll:true});
  graphOpener=null;
}
$('graphNew').onclick=()=>graphOpen();
$('graphCancel').onclick=graphClose;
$('graphExample').onclick=()=>{
  $('graphCode').value=graphCodeExample();
  graphCodeCheck();
  $('graphCode').focus({preventScroll:true});
};
$('graphValidate').onclick=graphCodeCheck;
let graphCheckTimer;
$('graphCode').addEventListener('input',()=>{
  clearTimeout(graphCheckTimer);
  graphCheckTimer=setTimeout(graphCodeCheck,180);
});
$('graphSave').onclick=async()=>{
  const name=$('graphName').value.trim();
  if (!name) { graphCodeMessage('Give the automation a name.',true); $('graphName').focus(); return; }
  let graph;
  try { graph=graphCodeParse($('graphCode').value); }
  catch(error) { graphCodeMessage(error.message,true); $('graphCode').focus(); return; }
  const button=$('graphSave'); button.disabled=true;
  try {
    await api('/api/zigbee/automations/graphs'+(graphEditing ? '/'+graphEditing : ''),{
      method:graphEditing ? 'PUT' : 'POST',
      body:JSON.stringify({name,enabled:$('graphEnabled').checked,code:$('graphCode').value.trim(),...graph})
    });
    graphClose(); await loadGraphAutomations();
  } catch(error) { graphCodeMessage(error.message,true); }
  finally { button.disabled=false; }
};

function graphRenderList() {
  const signature=JSON.stringify([graphSaved,graphLegacy,graphObjects.map(obj=>[obj.id,obj.name])]);
  if (signature===graphListSignature) return;
  graphListSignature=signature;
  const host=$('automationAllCards'),active=document.activeElement;
  const focusKey=active?.closest?.('[data-automation-key]')?.dataset.automationKey;
  const focusAction=['edit','toggle','delete'].find(key=>active?.hasAttribute?.('data-'+key));
  host.replaceChildren();
  for(const graph of graphSaved) {
    const card=document.createElement('article');
    card.className='panel automation-card graph-list-card';
    card.dataset.automationKey='graph:'+graph.id;
    card.innerHTML='<div><h3></h3><p class="muted"></p><span class="graph-card-status"></span></div><div class="automation-pair"><button class="btn" data-edit>Edit</button><button class="btn" data-toggle></button><button class="btn" data-delete>Delete</button></div>';
    card.querySelector('h3').textContent=graph.name;
    const paths=graph.nodes.filter(node=>['trigger','clock_trigger'].includes(node.kind)).length;
    card.querySelector('p').textContent=`${paths} ${paths===1?'path':'paths'} · ${graph.enabled?'Enabled':'Disabled'}`;
    card.querySelector('.graph-card-status').textContent=graph.status || '';
    card.querySelector('[data-edit]').onclick=()=>graphOpen(graph);
    card.querySelector('[data-toggle]').textContent=graph.enabled?'Disable':'Enable';
    card.querySelector('[data-toggle]').onclick=async()=>{
      try {
        const {id,status,...body}=graph;
        await api('/api/zigbee/automations/graphs/'+id,{method:'PUT',body:JSON.stringify({...body,enabled:!graph.enabled})});
        graphListSignature=''; await loadGraphAutomations();
      } catch(error) { $('automationStatus').textContent=error.message; }
    };
    card.querySelector('[data-delete]').onclick=async()=>{
      if (!confirm('Delete this automation? Already scheduled actions may still finish.')) return;
      try { await api('/api/zigbee/automations/graphs/'+graph.id,{method:'DELETE'}); graphListSignature=''; await loadGraphAutomations(); }
      catch(error) { $('automationStatus').textContent=error.message; }
    };
    host.append(card);
  }
  for(const rule of graphLegacy) {
    const card=document.createElement('article');
    card.className='panel automation-card graph-list-card';
    card.dataset.automationKey='rule:'+rule.id;
    card.innerHTML='<div><h3></h3><p class="muted"></p><span class="graph-card-status"></span></div><div class="automation-pair"><button class="btn" data-toggle></button><button class="btn" data-delete>Delete</button></div>';
    card.querySelector('h3').textContent=rule.name;
    card.querySelector('p').textContent=`Earlier rule · ${graphItem(rule.source)?.name || rule.source} → ${graphItem(rule.target)?.name || rule.target} · ${rule.enabled?'Enabled':'Disabled'}`;
    card.querySelector('.graph-card-status').textContent=rule.status || '';
    card.querySelector('[data-toggle]').textContent=rule.enabled?'Disable':'Enable';
    card.querySelector('[data-toggle]').onclick=async()=>{
      const {id,status,off_at,...body}=rule;
      try { await api('/api/zigbee/automations/'+id,{method:'PUT',body:JSON.stringify({...body,enabled:!rule.enabled})}); graphListSignature=''; await loadGraphAutomations(); }
      catch(error) { $('automationStatus').textContent=error.message; }
    };
    card.querySelector('[data-delete]').onclick=async()=>{
      if (!confirm('Delete this rule? Already scheduled actions may still finish.')) return;
      try { await api('/api/zigbee/automations/'+rule.id,{method:'DELETE'}); graphListSignature=''; await loadGraphAutomations(); }
      catch(error) { $('automationStatus').textContent=error.message; }
    };
    host.append(card);
  }
  if (!host.children.length) host.textContent='No automations yet.';
  if (focusKey && focusAction) host.querySelector(`[data-automation-key="${CSS.escape(focusKey)}"] [data-${focusAction}]`)?.focus({preventScroll:true});
}
function graphRenderDeviceReference() {
  const host=$('automationDeviceReference'); host.replaceChildren();
  if (!graphObjects.length) { host.textContent='No Zigbee devices discovered yet.'; return; }
  for(const device of graphObjects) {
    const section=document.createElement('section'); section.className='automation-device';
    const title=document.createElement('h4'); title.textContent=device.name;
    const id=document.createElement('code'); id.textContent=device.id;
    const list=document.createElement('ul');
    for(const [key,cap] of Object.entries(device.capabilities || {})) {
      if (!['boolean','number','enum'].includes(cap.type)) continue;
      const row=document.createElement('li');
      const writable=(device.actions || []).includes('set_'+key);
      const detail=cap.type==='enum' ? ': '+cap.options.join(', ') : cap.type==='number' ? ': '+(cap.minimum ?? '−∞')+'–'+(cap.maximum ?? '∞')+(cap.unit || '') : '';
      row.textContent=`${key} (${cap.type}${detail})${writable?' · action available':''}`;
      list.append(row);
    }
    section.append(title,id,list); host.append(section);
  }
}
async function loadGraphAutomations() {
  if (graphLoading) return;
  graphLoading=true;
  try {
    const [data,devices]=await Promise.all([api('/api/zigbee/automations'),api('/api/v1/objects?module=zigbee')]);
    graphSaved=data.graphs || []; graphLegacy=data.rules || [];
    const nextObjects=devices.objects || [];
    const changed=JSON.stringify(nextObjects)!==JSON.stringify(graphObjects);
    graphObjects=nextObjects;
    graphRenderList();
    if (changed) graphRenderDeviceReference();
  } catch(error) { $('automationStatus').textContent=error.message; }
  finally { graphLoading=false; }
}
$('automationRefresh').onclick=loadGraphAutomations;
setInterval(()=>{ if ($('automationsView').classList.contains('active') && !document.hidden) loadGraphAutomations(); },10000);
