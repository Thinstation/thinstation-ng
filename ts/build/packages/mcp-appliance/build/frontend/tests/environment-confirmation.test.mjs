import test from 'node:test';
import assert from 'node:assert/strict';
import {deletionPhrase,matchesDeletionPhrase,confirmationState} from '../src/lib/environment-confirmation.js';
const name='.stage-00000000000000000000000000001bbd';
const one={action:'delete',rows:[{name}]};
const two={action:'delete',rows:[{name:'media-1'},{name:'photo-1'}]};
const phrase='DELETE '+name;
test('single and bulk phrases name their exact target set',()=>{
 assert.equal(deletionPhrase(one.rows),phrase);assert.equal(deletionPhrase(two.rows),'DELETE 2 ITEMS');
 for(const value of [[],null,[{}],[{name:''}],[{name:1}]])assert.equal(deletionPhrase(value),'');
});
test('no selected operation cannot be confirmed',()=>{
 for(const value of [null,{action:'delete',rows:[]},{action:'install',rows:one.rows}])assert.equal(confirmationState(value,true,phrase).ready,false);
});
test('acknowledgment and full phrase are both required',()=>{
 assert.equal(confirmationState(one,false,'').ready,false);
 assert.equal(confirmationState(one,false,phrase).ready,false);
 assert.equal(confirmationState(one,true,'').ready,false);
 assert.equal(confirmationState(one,true,phrase).ready,true);
});
test('action word and outer whitespace do not cause silent mismatch',()=>{
 for(const value of [phrase,'delete '+name,'  DELETE '+name+'  ','Delete    '+name,'\nDELETE '+name+'\n'])assert.equal(matchesDeletionPhrase(value,phrase),true,value);
});
test('target names are exact and are not lowercased',()=>{
 for(const value of [name,'DELETE '+name.toUpperCase(),'DELETE '+name+'x','DELETE '+name+' '+name,'DELETE '+name.slice(1),'DELETE\u200b '+name])assert.equal(matchesDeletionPhrase(value,phrase),false,value);
});
test('bulk action words normalize but count remains exact',()=>{
 for(const value of ['DELETE 2 ITEMS',' delete 2 items ','Delete   2   Items'])assert.equal(matchesDeletionPhrase(value,'DELETE 2 ITEMS'),true);
 for(const value of ['DELETE 3 ITEMS','DELETE 02 ITEMS','2 ITEMS','DELETE 2','DELETE 2 ITEM','DELETE 2 ITEMS extra'])assert.equal(matchesDeletionPhrase(value,'DELETE 2 ITEMS'),false);
});
test('unchecking review disables a previously ready delete',()=>{
 assert.equal(confirmationState(one,true,phrase).ready,true);
 assert.equal(confirmationState(one,false,phrase).ready,false);
 assert.match(confirmationState(one,false,phrase).message,/review box/);
});
test('feedback explains a missing or mismatched phrase',()=>{
 assert.match(confirmationState(one,true,'').message,/Enter the full/);
 assert.match(confirmationState(one,true,'wrong').message,/does not match/);
 assert.match(confirmationState(one,true,phrase).message,/now enabled/);
});
test('in-flight or stale inventory blocks otherwise ready confirmation',()=>{
 assert.equal(confirmationState(one,true,phrase,true).ready,false);
 assert.match(confirmationState(one,true,phrase,true).message,/inventory/);
});
test('update and redeploy retain acknowledgment without a delete phrase',()=>{
 for(const action of ['update','rebuild']){
  const value={action,rows:one.rows};assert.equal(confirmationState(value,false,'').ready,false);
  assert.equal(confirmationState(value,true,'').ready,true);assert.equal(confirmationState(value,true,'',true).ready,false);
 }
});
