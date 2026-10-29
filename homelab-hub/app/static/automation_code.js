/* Small, data-only automation language. It never evaluates JavaScript. */
const CODE_STATE=/^(when|if|and)\s+("(?:\\.|[^"\\])*")\.([A-Za-z_][\w]*)\s*(==|!=|<=|>=|=|<|>)\s*(.+)$/i;
const CODE_ACTION=/^do\s+("(?:\\.|[^"\\])*")\.([A-Za-z_][\w]*)\s*=\s*(.+)$/i;
const CODE_WINDOW=/^during\s+([01]\d|2[0-3]):([0-5]\d)\s*\.\.\s*([01]\d|2[0-3]):([0-5]\d)$/i;
const CODE_TIME=/^(at|after|before)\s+((?:[01]\d|2[0-3]):[0-5]\d|sunrise|sunset)(?:\s*([+-])\s*(\d{1,3})m)?$/i;
const CODE_OPERATORS={'==':'eq','=':'eq','!=':'ne','<':'lt','<=':'lte','>':'gt','>=':'gte'};
const CODE_SYMBOLS={eq:'==',ne:'!=',lt:'<',lte:'<=',gt:'>',gte:'>='};
function graphCodeMessage(message,error=false) {
  $('graphCodeFeedback').textContent=message;
  $('graphCodeFeedback').dataset.error=String(error);
}
function graphCodeDevice(token,line) {
  let name;
  try { name=JSON.parse(token); } catch(_) { throw Error(`Line ${line}: quote the device name.`); }
  const matches=graphObjects.filter(device=>device.id===name || device.name===name);
  if (!matches.length) throw Error(`Line ${line}: device ${token} was not found. Check Devices in the guide.`);
  if (matches.length>1) throw Error(`Line ${line}: ${token} is ambiguous. Use the device ID.`);
  return matches[0];
}
function graphCodeValue(raw,cap,line) {
  const token=raw.trim();
  if (cap.type==='boolean') {
    if (/^(true|on|1)$/i.test(token)) return true;
    if (/^(false|off|0)$/i.test(token)) return false;
    throw Error(`Line ${line}: use true/false, on/off, or 1/0.`);
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
      try { value=JSON.parse(token); } catch(_) { throw Error(`Line ${line}: invalid quoted value.`); }
    }
    if (!(cap.options || []).includes(value)) throw Error(`Line ${line}: choose one of ${(cap.options || []).join(', ')}.`);
    return value;
  }
  throw Error(`Line ${line}: this property cannot be used in an automation.`);
}
function graphCodeTime(match,line) {
  const [,verb,raw,sign,minutes]=match;
  const boundary=/^\d/.test(raw) ? 'clock' : raw.toLowerCase();
  const offset=minutes ? Number(minutes)*(sign==='-' ? -1 : 1) : 0;
  if (Math.abs(offset)>180 || (boundary==='clock' && minutes))
    throw Error(`Line ${line}: solar offsets can be at most 180m; clock times cannot use offsets.`);
  return {verb:verb.toLowerCase(),condition:{boundary,time:boundary==='clock' ? raw : '18:00',after:verb.toLowerCase()!=='before',offset_minutes:offset}};
}
function graphCodeParse(code) {
  if (code.length>20000) throw Error('Rule is too long.');
  const nodes=[],edges=[];
  let last='',context='',source='',started=false,actions=0,path=0,depth=0;
  const add=(kind,values={})=>{
    if (nodes.length>=50) throw Error('An automation can contain at most 50 steps.');
    const id='n'+(nodes.length+1);
    const node={id,kind,item:'',target_item:'',property:'',operator:'eq',value:null,action:'',seconds:0,
      time_condition:null,start:'18:00',end:'00:00',x:Math.min(2200,50+(depth%8)*270),
      y:Math.min(1480,70+path*280+Math.floor(depth/8)*140),...values};
    if (last) edges.push({source:last,target:id});
    nodes.push(node); last=id; depth++; return node;
  };
  const nextPath=line=>{
    if (started && !actions) throw Error(`Line ${line}: the previous path needs a do action.`);
    if (started) path++;
    last=''; context=''; source=''; depth=0; actions=0; started=true;
  };
  for(const [index,raw] of code.split(/\r?\n/).entries()) {
    const line=index+1,text=raw.trim();
    if (!text || text.startsWith('#')) continue;
    const state=text.match(CODE_STATE),action=text.match(CODE_ACTION),time=text.match(CODE_TIME);
    if (state) {
      const [,verb,deviceToken,property,symbol,valueToken]=state;
      const device=graphCodeDevice(deviceToken,line),cap=device.capabilities?.[property];
      if (!cap || !['boolean','enum','number'].includes(cap.type))
        throw Error(`Line ${line}: ${device.name} does not report ${property}.`);
      const operator=CODE_OPERATORS[symbol],value=graphCodeValue(valueToken,cap,line);
      if (!['eq','ne'].includes(operator) && cap.type!=='number')
        throw Error(`Line ${line}: order comparisons need a number.`);
      if (!started || verb.toLowerCase()==='when') {
        nextPath(line);
        add('item',{item:device.id}); add('trigger',{property,operator,value});
        context=device.id; source=device.id;
      } else {
        if (context!==device.id) add('item',{item:device.id});
        add('condition',{property,operator,value}); context=device.id;
      }
      continue;
    }
    if (time) {
      const parsed=graphCodeTime(time,line);
      if (parsed.verb==='at') {
        nextPath(line); add('clock_trigger',{time_condition:parsed.condition});
      } else {
        if (!started) throw Error(`Line ${line}: start with when or at.`);
        add('time',{time_condition:parsed.condition});
      }
      continue;
    }
    if (!started) throw Error(`Line ${line}: start with when or at.`);
    if (/^during\b/i.test(text)) {
      const match=text.match(CODE_WINDOW);
      if (!match) throw Error(`Line ${line}: use during 18:00..05:30.`);
      const start=`${match[1]}:${match[2]}`,end=`${match[3]}:${match[4]}`;
      if (start===end) throw Error(`Line ${line}: the time window needs different start and end times.`);
      add('window',{start,end}); continue;
    }
    if (action) {
      const [,deviceToken,property,valueToken]=action,device=graphCodeDevice(deviceToken,line);
      const actionName=property.startsWith('set_') ? property : 'set_'+property;
      const cap=device.capabilities?.[actionName.replace(/^set_/,'')];
      if (!device.actions?.includes(actionName) || !cap)
        throw Error(`Line ${line}: ${device.name} cannot set ${property}.`);
      if (device.id===source) throw Error(`Line ${line}: an action cannot target its trigger device.`);
      const value=graphCodeValue(valueToken,cap,line);
      if (!context && last && nodes.find(node=>node.id===last)?.kind==='clock_trigger')
        add('item',{item:device.id});
      add('action',{target_item:device.id,action:actionName,value}); actions++; continue;
    }
    if (/^wait\b/i.test(text)) {
      const match=text.match(/^wait\s+([1-9]\d*)(s|m|h)$/i);
      const seconds=match ? Number(match[1])*({s:1,m:60,h:3600})[match[2].toLowerCase()] : 0;
      if (!seconds || seconds>86400) throw Error(`Line ${line}: use wait 5s, wait 2m, or wait 1h (up to 24h).`);
      add('delay',{seconds}); continue;
    }
    throw Error(`Line ${line}: unknown instruction. Open the Automation guide for syntax.`);
  }
  if (!started) throw Error('Start with a when or at instruction.');
  if (!actions) throw Error('The last path needs a do action.');
  return {nodes,edges};
}
function graphCodeCheck() {
  try {
    const graph=graphCodeParse($('graphCode').value);
    const count=graph.nodes.filter(node=>['trigger','clock_trigger'].includes(node.kind)).length;
    graphCodeMessage(`Rule is valid · ${count} ${count===1?'path':'paths'}`);
    return true;
  } catch(error) { graphCodeMessage(error.message,true); return false; }
}
function graphCodeFormat(value) {
  return typeof value==='string' ? JSON.stringify(value) : String(value);
}
function graphCodeBoundary(condition) {
  if (!condition) return null;
  const boundary=condition.boundary==='clock' ? condition.time : condition.boundary;
  const offset=condition.offset_minutes || 0;
  return boundary+(offset ? (offset>0?'+':'')+offset+'m' : '');
}
function graphCodeSerialize(graph) {
  const nodes=graph.nodes || [],edges=graph.edges || [];
  const byId=new Map(nodes.map(node=>[node.id,node]));
  const incoming=new Map(nodes.map(node=>[node.id,[]]));
  const outgoing=new Map(nodes.map(node=>[node.id,[]]));
  for(const edge of edges) {
    if (!byId.has(edge.source) || !byId.has(edge.target)) return {error:'The old flow has an invalid connection.'};
    incoming.get(edge.target).push(edge.source); outgoing.get(edge.source).push(edge.target);
  }
  if ([...incoming.values(),...outgoing.values()].some(list=>list.length>1))
    return {error:'This older flow contains shared or forked paths.'};
  const roots=nodes.filter(node=>!incoming.get(node.id).length),seen=new Set(),blocks=[];
  for(const root of roots) {
    const ordered=[];
    for(let node=root;node;node=byId.get(outgoing.get(node.id)[0])) {
      if (seen.has(node.id)) return {error:'This older flow has a loop.'};
      seen.add(node.id); ordered.push(node);
    }
    const lines=[]; let context='';
    for(let i=0;i<ordered.length;i++) {
      const node=ordered[i];
      if (node.kind==='item') {
        context=node.item;
        if (i===0 && ordered[i+1]?.kind==='trigger') {
          const next=ordered[++i],device=graphItem(context);
          if (!device) return {error:'A device in this older flow is unavailable.'};
          lines.push(`when ${JSON.stringify(device.name)}.${next.property} ${CODE_SYMBOLS[next.operator]} ${graphCodeFormat(next.value)}`);
        }
      } else if (node.kind==='clock_trigger' && i===0) {
        lines.push('at '+graphCodeBoundary(node.time_condition));
      } else if (node.kind==='condition') {
        const device=graphItem(context);
        if (!device) return {error:'A device in this older flow is unavailable.'};
        lines.push(`if ${JSON.stringify(device.name)}.${node.property} ${CODE_SYMBOLS[node.operator]} ${graphCodeFormat(node.value)}`);
      } else if (node.kind==='time') {
        lines.push((node.time_condition?.after ? 'after ' : 'before ')+graphCodeBoundary(node.time_condition));
      } else if (node.kind==='window') {
        lines.push(`during ${node.start}..${node.end}`);
      } else if (node.kind==='delay') {
        lines.push(`wait ${node.seconds}s`);
      } else if (node.kind==='action') {
        const device=graphItem(node.target_item || context);
        if (!device) return {error:'An action target in this older flow is unavailable.'};
        lines.push(`do ${JSON.stringify(device.name)}.${node.action.replace(/^set_/,'')} = ${graphCodeFormat(node.value)}`);
      } else return {error:'This older flow has a step the text editor cannot express.'};
    }
    blocks.push(lines.join('\n'));
  }
  if (seen.size!==nodes.length) return {error:'This older flow has disconnected steps.'};
  const code=blocks.join('\n\n');
  try { graphCodeParse(code); } catch(_) { return {error:'This older flow needs a new text rule before editing.'}; }
  return {code};
}
function graphCodeExample() {
  const source=graphObjects.find(obj=>obj.capabilities?.occupancy?.type==='boolean');
  const target=graphObjects.find(obj=>obj.id!==source?.id && obj.actions?.includes('set_power'));
  const sensor=JSON.stringify(source?.name || 'Motion sensor'),light=JSON.stringify(target?.name || 'Hall light');
  return `when ${sensor}.occupancy == true\nduring 18:00..05:30\ndo ${light}.power = on\n\nwhen ${sensor}.occupancy == false\nduring 18:00..05:30\nwait 5s\nif ${sensor}.occupancy == false\ndo ${light}.power = off`;
}
