/* Small, data-only automation language. It never evaluates JavaScript. */
let graphCodeApplying=false, graphCodeDraftDirty=false, graphCodeTimer=null;
const GRAPH_CODE_STATE=/^(when|if)\s+("(?:\\.|[^"\\])*")\.([A-Za-z_][\w]*)\s*(==|!=|<=|>=|=|<|>)\s*(.+)$/i;
const GRAPH_CODE_ACTION=/^do\s+("(?:\\.|[^"\\])*")\.([A-Za-z_][\w]*)\s*=\s*(.+)$/i;
const GRAPH_CODE_ITEM=/^item\s+("(?:\\.|[^"\\])*")$/i;
const GRAPH_CODE_OPERATORS={'==':'eq','=':'eq','!=':'ne','<':'lt','<=':'lte','>':'gt','>=':'gte'};
const GRAPH_CODE_SYMBOLS={eq:'==',ne:'!=',lt:'<',lte:'<=',gt:'>',gte:'>='};

function graphCodeMessage(message,error=false) {
  const status=$('graphCodeFeedback'); status.textContent=message;
  status.dataset.error=String(error);
}
function graphCodeDevice(token,line) {
  let name;
  try { name=JSON.parse(token); } catch (_) { throw Error(`Line ${line}: use a quoted device name.`); }
  const matches=graphObjects.filter(obj=>obj.id===name || obj.name===name);
  if (!matches.length) throw Error(`Line ${line}: device ${token} was not found. Use a name from Add cards.`);
  if (matches.length>1) throw Error(`Line ${line}: ${token} is ambiguous. Use the device ID instead.`);
  return matches[0];
}
function graphCodeValue(raw,cap,line) {
  const token=raw.trim();
  if (cap.type==='boolean') {
    if (/^(true|on)$/i.test(token)) return true;
    if (/^(false|off)$/i.test(token)) return false;
    throw Error(`Line ${line}: use true/false or on/off for ${cap.label || 'this value'}.`);
  }
  if (cap.type==='number') {
    if (!/^-?(?:\d+\.?\d*|\.\d+)$/.test(token)) throw Error(`Line ${line}: enter a number.`);
    const value=Number(token);
    if (!Number.isFinite(value) || (cap.minimum!=null && value<cap.minimum) || (cap.maximum!=null && value>cap.maximum))
      throw Error(`Line ${line}: value is outside the device's range.`);
    return value;
  }
  if (cap.type==='enum') {
    let value=token;
    if (token.startsWith('"')) {
      try { value=JSON.parse(token); } catch (_) { throw Error(`Line ${line}: invalid quoted value.`); }
    }
    if (!(cap.options || []).includes(value)) throw Error(`Line ${line}: choose one of ${(cap.options || []).join(', ')}.`);
    return value;
  }
  throw Error(`Line ${line}: this property is not supported in programming mode.`);
}
function graphCodeParse(code) {
  const nodes=[],edges=[];
  let context='',triggerSource='',started=false;
  const add=(kind,values={}) => {
    if (nodes.length>=50) throw Error('A flow can contain at most 50 cards.');
    const index=nodes.length,id='n'+(index+1);
    const node={id,kind,item:'',target_item:'',property:'',operator:'eq',value:null,action:'',seconds:0,
      time_condition:null,start:'18:00',end:'00:00',x:graphPosition(46+(index%8)*230,2200),y:graphPosition(69+Math.floor(index/8)*138,1480),...values};
    if (index) edges.push({source:nodes[index-1].id,target:id});
    nodes.push(node); return node;
  };
  for (const [index,raw] of code.split(/\r?\n/).entries()) {
    const line=index+1,text=raw.trim();
    if (!text || text.startsWith('#')) continue;
    const state=text.match(GRAPH_CODE_STATE),action=text.match(GRAPH_CODE_ACTION),item=text.match(GRAPH_CODE_ITEM);
    if (state) {
      const [,verb,deviceToken,property,symbol,valueToken]=state;
      const device=graphCodeDevice(deviceToken,line),cap=device.capabilities?.[property];
      if (!cap || !['boolean','enum','number'].includes(cap.type)) throw Error(`Line ${line}: ${device.name} does not report ${property}.`);
      const operator=GRAPH_CODE_OPERATORS[symbol],value=graphCodeValue(valueToken,cap,line);
      if (!['eq','ne'].includes(operator) && cap.type!=='number') throw Error(`Line ${line}: order comparisons need a number.`);
      if (!started) {
        add('item',{item:device.id}); add('trigger',{property,operator,value});
        started=true; context=device.id; triggerSource=device.id;
      } else {
        if (verb.toLowerCase()==='when') throw Error(`Line ${line}: use if for a condition after the trigger.`);
        if (context!==device.id) add('item',{item:device.id});
        add('condition',{property,operator,value}); context=device.id;
      }
      continue;
    }
    if (/^at\s+/i.test(text)) {
      const match=text.match(/^at\s+([01]\d|2[0-3]):([0-5]\d)$/i);
      if (!match) throw Error(`Line ${line}: use a 24-hour time such as at 18:00.`);
      if (started) throw Error(`Line ${line}: a clock trigger must be the first instruction.`);
      add('clock_trigger',{time_condition:{boundary:'clock',time:`${match[1]}:${match[2]}`,after:true,offset_minutes:0}});
      started=true; continue;
    }
    if (!started) throw Error(`Line ${line}: start with when, if, or at.`);
    if (action) {
      const [,deviceToken,property,valueToken]=action,device=graphCodeDevice(deviceToken,line);
      const actionName=property.startsWith('set_') ? property : 'set_'+property;
      const cap=device.capabilities?.[actionName.replace(/^set_/,'')];
      if (!device.actions?.includes(actionName) || !cap) throw Error(`Line ${line}: ${device.name} cannot perform ${property}.`);
      if (device.id===triggerSource) throw Error(`Line ${line}: an action cannot target its own trigger device.`);
      const value=graphCodeValue(valueToken,cap,line);
      if (nodes.length===1 && nodes[0].kind==='clock_trigger') { add('item',{item:device.id}); context=device.id; }
      add('action',{target_item:device.id,action:actionName,value}); continue;
    }
    if (item) {
      const device=graphCodeDevice(item[1],line);
      add('item',{item:device.id}); context=device.id; continue;
    }
    if (/^wait\s+/i.test(text)) {
      const match=text.match(/^wait\s+([1-9]\d*)s?$/i),seconds=Number(match?.[1]);
      if (!match || seconds>86400) throw Error(`Line ${line}: wait must be 1–86400 seconds, such as wait 5s.`);
      add('delay',{seconds}); continue;
    }
    throw Error(`Line ${line}: expected if, do, wait, or item. Open Syntax for examples.`);
  }
  if (!nodes.length) throw Error('Add a when, if, or at line to start the automation.');
  return {nodes,edges};
}
function graphCodeSerialize() {
  const nodes=graphCurrent?.nodes || [],edges=graphCurrent?.edges || [];
  if (!nodes.length) return {code:''};
  if (edges.length!==nodes.length-1) return {error:'Connect every card in a single path before editing it as code.'};
  const incoming=new Map(nodes.map(node=>[node.id,[]])),outgoing=new Map(nodes.map(node=>[node.id,[]]));
  for (const edge of edges) {
    if (!incoming.has(edge.target) || !outgoing.has(edge.source)) return {error:'This flow has an invalid connection.'};
    incoming.get(edge.target).push(edge.source); outgoing.get(edge.source).push(edge.target);
  }
  if ([...incoming.values(),...outgoing.values()].some(list=>list.length>1)) return {error:'Branched flows remain editable on the canvas.'};
  const roots=nodes.filter(node=>!incoming.get(node.id).length);
  if (roots.length!==1) return {error:'This flow cannot be represented as one code path.'};
  const ordered=[],seen=new Set();
  for (let node=roots[0];node;node=graphById(outgoing.get(node.id)[0])) {
    if (seen.has(node.id)) return {error:'A loop cannot be represented as code.'};
    seen.add(node.id); ordered.push(node);
  }
  if (ordered.length!==nodes.length) return {error:'This flow has disconnected cards.'};
  const lines=[];
  let context='';
  for (let i=0;i<ordered.length;i++) {
    const node=ordered[i],next=ordered[i+1];
    if (node.kind==='item') {
      const device=graphItem(node.item);
      if (!device) return {error:'A device in this flow is no longer available.'};
      context=node.item;
      if (i===0 && next?.kind==='trigger') {
        lines.push(`when ${JSON.stringify(device.name)}.${next.property} ${GRAPH_CODE_SYMBOLS[next.operator]} ${graphCodeFormatValue(next.value)}`);
        i++; continue;
      }
      lines.push(`item ${JSON.stringify(device.name)}`); continue;
    }
    if (node.kind==='clock_trigger' && i===0 && node.time_condition?.boundary==='clock' && node.time_condition.after && !node.time_condition.offset_minutes) {
      lines.push(`at ${node.time_condition.time}`); continue;
    }
    if (node.kind==='condition' && context) {
      const device=graphItem(context);
      lines.push(`if ${JSON.stringify(device.name)}.${node.property} ${GRAPH_CODE_SYMBOLS[node.operator]} ${graphCodeFormatValue(node.value)}`); continue;
    }
    if (node.kind==='action') {
      const device=graphItem(node.target_item || context);
      if (!device || !node.action) return {error:'Choose an action and target device on the canvas first.'};
      lines.push(`do ${JSON.stringify(device.name)}.${node.action.replace(/^set_/,'')} = ${graphCodeFormatValue(node.value)}`); continue;
    }
    if (node.kind==='delay') { lines.push(`wait ${node.seconds}s`); continue; }
    return {error:'This card type is available on the canvas but not in programming mode.'};
  }
  const code=lines.join('\n');
  try { graphCodeParse(code); }
  catch (_) { return {error:'Complete the card settings before editing this flow as code.'}; }
  return {code};
}
function graphCodeFormatValue(value) {
  if (typeof value==='string') return JSON.stringify(value);
  return String(value);
}
function graphCodeUpdateExample() {
  const source=graphObjects.find(obj=>obj.capabilities?.occupancy?.type==='boolean') ||
    graphObjects.find(obj=>Object.values(obj.capabilities || {}).some(cap=>cap.type==='boolean'));
  const target=graphObjects.find(obj=>(obj.actions || []).some(action=>obj.capabilities?.[action.replace(/^set_/,'')]?.type==='boolean'));
  const property=source?.capabilities?.occupancy?.type==='boolean' ? 'occupancy' :
    Object.keys(source?.capabilities || {}).find(key=>source.capabilities[key].type==='boolean') || 'occupancy';
  const action=(target?.actions || []).find(name=>target.capabilities?.[name.replace(/^set_/,'')]?.type==='boolean')?.replace(/^set_/,'') || 'power';
  const example=`when ${JSON.stringify(source?.name || 'Motion sensor')}.${property} == true\ndo ${JSON.stringify(target?.name || 'Hall light')}.${action} = on\nwait 5s\ndo ${JSON.stringify(target?.name || 'Hall light')}.${action} = off`;
  $('graphCodeExample').textContent=example;
  $('graphCode').placeholder=example;
}
function graphCodeSyncFromCanvas() {
  if (!graphCurrent || !$('graphCodePanel').open || graphCodeApplying) return;
  graphCodeUpdateExample();
  if (graphCodeDraftDirty) return;
  const result=graphCodeSerialize(),editor=$('graphCode');
  editor.disabled=Boolean(result.error);
  editor.value=result.code || '';
  $('graphCodeStart').hidden=!result.error;
  graphCodeMessage(result.error || 'Code and canvas are in sync.',Boolean(result.error));
}
function graphCodeResetForGraph() {
  clearTimeout(graphCodeTimer); graphCodeDraftDirty=false; graphCodeApplying=false;
  $('graphCode').value=''; $('graphCode').disabled=false; $('graphCodeStart').hidden=true; graphCodeMessage('');
}
function graphCodeHasError() { return $('graphCodePanel').open && graphCodeDraftDirty; }

$('graphCodePanel').addEventListener('toggle',event => {
  if (event.target!==$('graphCodePanel')) return;
  if (event.target.open) graphCodeSyncFromCanvas();
  else { clearTimeout(graphCodeTimer); graphCodeDraftDirty=false; graphCodeMessage(''); }
});
$('graphCodeRestore').onclick=() => { graphCodeDraftDirty=false; graphCodeSyncFromCanvas(); };
$('graphCodeStart').onclick=() => {
  graphCodeDraftDirty=true; $('graphCode').disabled=false; $('graphCode').value='';
  graphCodeMessage('Canvas stays unchanged until the code is valid.');
  $('graphCode').focus({preventScroll:true});
};
$('graphCode').addEventListener('input',() => {
  clearTimeout(graphCodeTimer); graphCodeDraftDirty=true;
  graphCodeTimer=setTimeout(() => {
    if (!graphCurrent || !$('graphCodePanel').open) return;
    try {
      const draft=graphCodeParse($('graphCode').value);
      graphCodeApplying=true;
      graphCurrent.nodes=draft.nodes; graphCurrent.edges=draft.edges;
      graphSerial=draft.nodes.length; graphSelected=null; graphConnecting=null;
      graphDraw(); graphFit();
      graphCodeApplying=false; graphCodeDraftDirty=false;
      $('graphCodeStart').hidden=true;
      graphCodeMessage('Canvas updated.'); $('graphFeedback').textContent='';
    } catch (error) { graphCodeApplying=false; graphCodeMessage(error.message,true); }
  },250);
});
