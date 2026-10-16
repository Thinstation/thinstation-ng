import test from 'node:test';
import assert from 'node:assert/strict';
import {confirmationState} from '../src/lib/environment-confirmation.js';
const one={action:'delete',rows:[{name:'.stage-00000000000000000000000000001bbd'}]};
const two={action:'delete',rows:[{name:'media-1'},{name:'photo-1'}]};
test('single delete requires only the review acknowledgment',()=>{
 assert.equal(confirmationState(one,false).ready,false);
 assert.equal(confirmationState(one,true).ready,true);
});
test('bulk delete has the same single acknowledgment',()=>{
 assert.equal(confirmationState(two,false).ready,false);
 assert.equal(confirmationState(two,true).ready,true);
});
test('malformed operations cannot be confirmed',()=>{
 for(const value of [null,{}, {action:'delete',rows:[]},{action:'delete',rows:null},{action:'install',rows:one.rows},{action:'delete',rows:[{}]},{action:'delete',rows:[{name:''}]},{action:'delete',rows:[{name:1}]}])
  assert.equal(confirmationState(value,true).ready,false);
});
test('unchecking disables an acknowledged deletion',()=>{
 assert.equal(confirmationState(one,true).ready,true);
 assert.equal(confirmationState(one,false).ready,false);
});
test('feedback explains only the outstanding requirement',()=>{
 assert.match(confirmationState(one,false).message,/review box/);
 assert.match(confirmationState(one,true).message,/now enabled/);
 assert.doesNotMatch(confirmationState(one,false).message,/type|phrase|paste/i);
});
test('in-flight or stale inventory still blocks confirmation',()=>{
 assert.equal(confirmationState(one,true,true).ready,false);
 assert.match(confirmationState(one,true,true).message,/inventory/);
});
test('update and redeploy retain their existing acknowledgment',()=>{
 for(const action of ['update','rebuild']){
  const value={action,rows:one.rows};assert.equal(confirmationState(value,false).ready,false);
  assert.equal(confirmationState(value,true).ready,true);assert.equal(confirmationState(value,true,true).ready,false);
 }
});
test('acknowledgment must be an explicit boolean',()=>{
 for(const value of [null,undefined,0,1,'true',{}])assert.equal(confirmationState(one,value).ready,false);
});
