import test from 'node:test';
import assert from 'node:assert/strict';
import {payload,directoryAddress,addressText,cleanName,eligibleCredential,methods} from '../src/lib/certificate-form.js';
const config={enabled:false,automatic:false,email:'admin@example.test',primary_domain:'mcp.example.test',challenge:'dns-01',key_algorithm:'rsa',renew_days:30,accept_terms:false,test_only:false,dns_provider:'active-directory',ad_host:'ad',ad_server:'dc.example.test',ad_zone:'example.test',ad_realm:'EXAMPLE.TEST',ad_ttl:60,ad_propagation_timeout:60,credential:'acme-ad',http_mode:'standalone',http_ready:true,http_public_access:false};
const host={alias:'ad',hostname:'dc.example.test',address:'192.0.2.10',groups:['windows']};
const credential={type:'active-directory',scopes:['acme'],allowed_hosts:['group:windows']};
test('CA prefix added and displayed separately',()=>{assert.equal(directoryAddress('ca.example.test/directory'),'https://ca.example.test/directory');assert.equal(addressText('https://ca.example.test/directory'),'ca.example.test/directory');});
test('hostname input needs no scheme',()=>assert.equal(cleanName('https://mcp.example.test/'),'mcp.example.test'));
test('AD request refers to inventory and never posts an arbitrary server',()=>{const p=payload(config,'','','custom','ca.example.test/directory');assert.equal(p.ad_host,'ad');assert(!('ad_server' in p));assert(!('http_ready' in p));});
test('HTTP request excludes all credential and AD fields',()=>{const p=payload({...config,challenge:'http-01'},'','192.0.2.10','custom','ca.example.test/directory');assert(!('credential' in p));assert(!('ad_host' in p));assert(!('dns_provider' in p));assert.deepEqual(p.http_source_networks,['192.0.2.10']);});
test('external HTTP excludes appliance firewall fields',()=>{const p=payload({...config,challenge:'http-01',http_mode:'external'},'','bad','production','');assert(!('http_public_access' in p));assert(!('http_source_networks' in p));});
test('AD credential matches inventory group not arbitrary hosts',()=>{assert(eligibleCredential(credential,host));assert(!eligibleCredential({...credential,allowed_hosts:['group:other']},host));assert(!eligibleCredential({...credential,type:'api-token'},host));});
test('credential scope and selected server are required',()=>{assert(!eligibleCredential({...credential,scopes:[]},host));assert(!eligibleCredential(credential,null));});
test('ALPN managed capability is enabled',()=>assert.equal(methods.find(x=>x.value==='tls-alpn-01').enabled,true));

test('ALPN payload excludes DNS credentials and HTTP settings',()=>{const c={challenge:'tls-alpn-01',primary_domain:'mcp.example.test',alpn_ready:true,alpn_public_access:false,credential:'ignored',http_ready:true};const r=payload(c,'','ignored','custom','ca.example.test/directory','192.0.2.10');assert.equal(r.directory_url,'https://ca.example.test/directory');assert.deepEqual(r.alpn_source_networks,['192.0.2.10']);assert.equal(r.alpn_ready,true);assert.equal('credential' in r,false);assert.equal('http_ready' in r,false)});

test('internal CA explicitly sets short-name policy',()=>{const p=payload({challenge:'http-01',primary_domain:'mcp'},'','','internal','ca.example.test/directory');assert.equal(p.internal_ca,true);assert.equal(p.primary_domain,'mcp')});
test('custom public CA does not enable internal names',()=>{const p=payload({challenge:'http-01',primary_domain:'mcp.example.test'},'','','custom','ca.example.test/directory');assert.equal(p.internal_ca,false)});
