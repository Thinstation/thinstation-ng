// View models shared by all Environment tabs. No mutation or network access.
export const activeStates = new Set(['queued', 'running']);
export const terminalStates = new Set(['completed', 'succeeded', 'failed', 'canceled', 'cancelled']);
export const actionLabels = {check:'Check updates', update:'Update', rebuild:'Redeploy', delete:'Delete', install:'Create'};
export const validName = name => /^[a-z][a-z0-9-]{0,62}$/.test(name || '');

export function splitInventory(data) {
  const rows=Array.isArray(data?.installed)?data.installed:[];
  const staging=new Map((Array.isArray(data?.staging)?data.staging:[]).map(row=>[row.name,row]));
  for(const row of rows) if(String(row.name).startsWith('.')) staging.set(row.name,{...row,kind:row.name.startsWith('.previous-')?'previous':'stage',...staging.get(row.name)});
  return {installed:rows.filter(row=>!String(row.name).startsWith('.')), staging:[...staging.values()]};
}
export function actionState(row, action) {
  const internal=/^\.(stage|previous|deleting)-[a-f0-9]{32}$/.test(row?.name||'');
  if(!validName(row?.name)&&!(action==='delete'&&internal)) return {enabled:false,reason:'This is not a managed environment name.'};
  if(activeStates.has(row.operation_state||row.update_status||row.state))return {enabled:false,reason:'An operation is already active.'};
  if(action==='delete')return {enabled:row.delete_available===true&&!!row.delete_token,reason:row.delete_reason||'Deletion is not available on this backend.'};
  if(action==='rebuild')return {enabled:row.rebuild_available===true,reason:row.rebuild_available?'Recreate from the stored definition.':'A stored definition is required.'};
  if(!['apt','dnf'].includes(row.package_manager))return {enabled:false,reason:'No supported package manager was detected.'};
  return {enabled:['check','update'].includes(action),reason:''};
}
export function updateState(row) {
  const state=row.operation_state||row.update_status;
  if(activeStates.has(state))return {label:state==='queued'?'Queued':({check:'Checking',update:'Updating',install:'Installing',rebuild:'Redeploying',delete:'Deleting'}[row.operation_action]||'Running'),tone:'neutral'};
  if(row.check_state==='failed'||(state==='failed'&&row.operation_action==='check'))return {label:'Check failed',tone:'bad'};
  if(state==='failed')return {label:'Last operation failed',tone:'bad'};
  if(!['apt','dnf'].includes(row.package_manager))return {label:'Manager unavailable',tone:'warn'};
  if(row.updates_available===true){
    const count=Number.isInteger(row.update_count)&&row.update_count>0?row.update_count:null;
    return {label:count?`${count} update${count===1?'':'s'} available`:row.held_count>0?'Held packages remain':'Updates available',tone:'warn'};
  }
  if(row.updates_available===false&&row.last_checked)return {label:'Up to date',tone:'good'};
  if(row.last_checked)return {label:'Check complete; see log',tone:'neutral'};
  if(['completed','succeeded'].includes(state)&&row.operation_action==='update')return {label:'Updated; check required',tone:'neutral'};
  return {label:'Not checked',tone:'neutral'};
}
export function filterRows(rows, query, fields=['name','title','description','os']) {
  const needle=String(query||'').trim().toLocaleLowerCase();
  return needle?rows.filter(row=>fields.map(field=>String(row[field]||'')).join(' ').toLocaleLowerCase().includes(needle)):rows;
}
export function chooseTargets(rows, names, action) {
  const selected=new Set(names);
  return rows.filter(row=>selected.has(row.name)&&actionState(row,action).enabled);
}
export function toggleVisible(selected, visible, checked) {
  const next=new Set(selected);
  for(const row of visible) checked?next.add(row.name):next.delete(row.name);
  return [...next];
}
export function timeLabel(value) {
  if(!value) return 'Not recorded';
  const date=new Date(value);
  return Number.isNaN(date.getTime())?'Not recorded':date.toLocaleString();
}
export function stageLabel(row) {
  if(row.kind==='previous'||row.name?.startsWith('.previous-')) return 'Retained previous';
  if(activeStates.has(row.state)) return 'Deployment in progress';
  if(row.state==='failed') return 'Failed deployment';
  return 'Staging / untracked';
}
