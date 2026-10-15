import test from 'node:test';
import assert from 'node:assert/strict';
import {runtimeView,updateView} from '../frontend/src/lib/operator-state.js';
const selected={kind:'bundled',generation:'iso-thinstation-mcp-build-309',bundled_generation:'thinstation-mcp-build-309',build_number:309};
const snapshot={service:'active',timestamp:100,selected,probe:{checked_at:100,responding:true}};
test('bundled full MCP is distinct from minimal rescue',()=>{const v=runtimeView(snapshot,'',false,100);assert.match(v.label,/Bundled MCP.*309/);assert.equal(v.tone,'good');assert.equal(v.stop,true)});
test('bundled default does not demand installation',()=>{const v=updateView({available:true,mcps:[]},snapshot);assert.equal(v.label,'Bundled baseline active');assert.match(v.detail,/optional/)});
test('newer persistent releases remain available',()=>{const v=updateView({available:true,mcps:[{generation:'thinstation-mcp-build-310'}]},snapshot);assert.equal(v.label,'Update available');assert.equal(v.target.generation,'thinstation-mcp-build-310')});
