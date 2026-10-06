import test from 'node:test';
import assert from 'node:assert/strict';
import {route,title,topPages,systemTopics} from '../src/lib/navigation.js';
import {allocationBytes,bytes,usedPercent} from '../src/lib/storage.js';
test('application resources are top-level',()=>assert.deepEqual(topPages.map(p=>p[0]),['overview','connections','mcp','inventory','credentials','system']));
test('legacy resource routes leave System',()=>{
 for(const [old,next] of [['overview','overview'],['hosts','inventory'],['credentials','credentials'],['system/overview','overview'],['system/inventory','inventory'],['system/credentials','credentials']])assert.equal(route(old),next)
});
test('local appliance routes remain under System',()=>{for(const [old,next] of [['network','network'],['settings','certificates'],['storage','storage']])assert.equal(route(old),'system/'+next)});
test('every System topic has a deep link',()=>{for(const [topic,label] of systemTopics){assert.equal(route('#/system/'+topic),'system/'+topic);assert.equal(title('system/'+topic),'System / '+label)}});
test('System lands on Network',()=>assert.equal(route('system'),'system/network'));
test('unknown routes fall back safely',()=>{for(const value of ['__proto__','constructor','http://example.test','system/nope',''])assert.equal(route(value),'overview')});
test('MCP policy remains with MCP',()=>assert.equal(route('#/mcp/settings'),'mcp/settings'));
test('GiB converted to exact safe bytes',()=>{assert.equal(allocationBytes('2'),2147483648);assert.equal(allocationBytes('0.5'),536870912)});
test('invalid allocation sizes rejected',()=>{for(const value of ['0','-1','1e2','Infinity','anything','1.1234567','99999999999'])assert.throws(()=>allocationBytes(value))});
test('unavailable capacity is not zero',()=>{assert.equal(bytes(null),'Unavailable');assert.equal(bytes(0),'0 B')});
test('capacity bar is bounded',()=>{assert.equal(usedPercent({total_bytes:10,used_bytes:20}),100);assert.equal(usedPercent({}),0)});
