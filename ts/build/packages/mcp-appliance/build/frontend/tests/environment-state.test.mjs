import test from 'node:test';
import assert from 'node:assert/strict';
import {splitInventory,actionState,updateState,filterRows,chooseTargets,toggleVisible,stageLabel} from '../src/lib/environment-state.js';
const row={name:'media-f44',package_manager:'dnf',title:'Video & Audio'};
test('internal directories are separated even with an older backend',()=>{
 const value=splitInventory({installed:[row,{name:'.stage-'+ '0'.repeat(32)},{name:'.previous-abc'}]});
 assert.deepEqual(value.installed,[row]);assert.equal(value.staging.length,2);
});
test('new staging metadata wins without duplicate records',()=>{
 const name='.stage-abc',value=splitInventory({installed:[{name}],staging:[{name,state:'failed'}]});
 assert.equal(value.staging.length,1);assert.equal(value.staging[0].state,'failed');
});
test('completed job does not masquerade as current packages',()=>assert.equal(updateState({...row,update_status:'completed'}).label,'Not checked'));
test('check result is distinct from worker status',()=>{
 assert.equal(updateState({...row,last_checked:'2026-10-15T12:00:00Z',updates_available:false}).label,'Up to date');
 assert.equal(updateState({...row,last_checked:'2026-10-15T12:00:00Z'}).label,'Check complete; see log');
 assert.equal(updateState({...row,updates_available:true}).label,'Updates available');
});
test('missing package manager disables checks and updates',()=>{
 for(const action of ['check','update'])assert.equal(actionState({...row,package_manager:'none'},action).enabled,false);
});
test('redeploy is enabled only with explicit definition metadata',()=>{
 assert.equal(actionState(row,'rebuild').enabled,false);assert.equal(actionState({...row,rebuild_available:true},'rebuild').enabled,true);
});
test('busy and internal rows cannot be operated on',()=>{
 assert.equal(actionState({...row,operation_state:'running',rebuild_available:true},'rebuild').enabled,false);
 assert.equal(actionState({...row,name:'.stage-abc'},'update').enabled,false);
});
test('unsupported deletion is never sent by the interface',()=>assert.equal(actionState({...row,delete_available:true},'delete').enabled,false));
test('bulk actions contain eligible selected rows only',()=>{
 const rows=[row,{...row,name:'missing',package_manager:'none'},{...row,name:'running',operation_state:'running'}];
 assert.deepEqual(chooseTargets(rows,['media-f44','missing','running'],'update'),[row]);
});
test('select visible does not clear selections hidden by the filter',()=>{
 assert.deepEqual(toggleVisible(['other'],[row],true),['other','media-f44']);
 assert.deepEqual(toggleVisible(['other','media-f44'],[row],false),['other']);
});
test('search is case insensitive and supports long names',()=>{
 assert.deepEqual(filterRows([row], 'VIDEO'),[row]);assert.equal(filterRows([row],'not present').length,0);
});
test('untracked stage is not falsely reported as failed',()=>{
 assert.equal(stageLabel({name:'.stage-abc'}),'Staging / untracked');
 assert.equal(stageLabel({name:'.previous-abc'}),'Retained previous');
});
