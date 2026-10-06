// One derived object owns each label, tone, explanation and permitted action.
// Pass reactive inputs explicitly so Svelte can track every dependency.
export function runtimeView(snapshot, busy='', stale=false, now=Date.now()/1000) {
  const state = snapshot?.service;
  const unavailable = stale || !snapshot || !snapshot.timestamp || now - snapshot.timestamp > 45;
  if (unavailable) return {label: snapshot ? 'Status unavailable' : 'Checking', tone:'neutral', detail:'Refresh to check the runtime.', start:false, stop:false, restart:false};
  const transitions = {'runtime:start':'Starting', 'runtime:stop':'Stopping', 'runtime:restart':'Restarting'};
  if (transitions[busy]) return {label:transitions[busy],tone:'neutral',detail:'Waiting for the appliance.',start:false,stop:false,restart:false};
  const base = {start:false,stop:false,restart:false,tone:'neutral'};
  if (state === 'active') {
    const p=snapshot.probe, fresh=p && now-p.checked_at < 60;
    return {...base,label:fresh&&p.responding?'Running · responding':'Running',tone:fresh&&p.responding?'good':'neutral',
      detail:fresh?(p.responding?'Local MCP handshake verified.':p.error||'MCP did not answer the local check.'):'Process is running; protocol response has not been checked recently.',
      stop:!busy,restart:!busy};
  }
  if (state==='inactive'||state==='failed') return {...base,label:state==='failed'?'Failed':'Stopped',tone:state==='failed'?'bad':'neutral',detail:state==='failed'?'Inspect runtime details before restarting.':'The MCP service is not running.',start:!busy};
  if (state==='activating'||state==='deactivating'||state==='reloading') return {...base,label:state==='deactivating'?'Stopping':'Starting',detail:'The runtime is changing state.'};
  return {...base,label:'Status unavailable',detail:'The service did not return a recognized state.'};
}

export function buildInfo(generation, metadata={}) {
  const match=/^(.+)-build-(\d+)$/.exec(generation||'');
  const number=Number.isInteger(metadata.build_number)?metadata.build_number:match?Number(match[2]):null;
  return {number,family:metadata.family||match?.[1]||null,label:number!==null?'Build '+number:metadata.version||generation||'Not selected'};
}

export function updateView(catalog, snapshot) {
  if (!catalog) return {label:'Checking updates',tone:'neutral'};
  if (!catalog.available) return {label:'Update check unavailable',tone:'neutral',detail:'The running MCP is unaffected.'};
  const rows=catalog.mcps||[], active=snapshot?.active;
  if (!active) return {label:rows.length?'Choose an MCP':'No releases listed',tone:'neutral'};
  const meta=snapshot?.versions?.find(v=>v.generation===active)||{};
  const current=buildInfo(active,meta);
  const comparable=rows.filter(r=>{const i=buildInfo(r.generation,r);return current.family && i.family===current.family && i.number!==null;});
  const newer=current.number===null?[]:comparable.filter(r=>buildInfo(r.generation,r).number>current.number).sort((a,b)=>buildInfo(b.generation,b).number-buildInfo(a.generation,a).number);
  if (newer.length) {
    const target=newer[0], installed=(snapshot?.versions||[]).some(v=>v.generation===target.generation);
    return {label:installed?'Update ready to apply':'Update available',tone:'warn',target,installed};
  }
  if(rows.some(r=>r.generation===active)) return {label:'Up to date',tone:'good'};
  if(comparable.length&&current.number!==null) return {label:'No newer build listed',tone:'neutral'};
  return {label:'Version comparison unavailable',tone:'neutral',detail:'No matching release family is listed.'};
}

export function connectionView(row) {
  if(row.revoked_at) return {label:'Access revoked',tone:'neutral',detail:'New requests using this token are blocked.'};
  if(!row.last_request_at) return {label:'Awaiting first request',tone:'neutral',detail:'Access is configured. No authenticated request has been observed.'};
  const code=Number(row.last_http_status);
  if(code>=400) return {label:'Last request failed',tone:'warn',detail:'Gateway returned HTTP '+code+'. Open setup to troubleshoot.'};
  return {label:'Request observed',tone:'good',detail:'Authenticated gateway response: HTTP '+code+'. Individual tool results are not evaluated here.'};
}
export function timeLabel(epoch) { return epoch?new Date(epoch*1000).toLocaleString():'Not observed'; }
