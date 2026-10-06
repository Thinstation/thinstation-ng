const {chromium}=require('playwright');
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('assert');
const web=path.resolve(__dirname,'../../../usr/share/mcp-appliance/web');
const production='https://acme-v02.api.letsencrypt.org/directory',staging='https://acme-staging-v02.api.letsencrypt.org/directory';
let actions=0,saves=0,lastBody=null;let providerTests=0;
let state={provider_ready:true,config:{ad_host:'',dns_provider:'active-directory',ad_server:'dc01.example.test',ad_zone:'example.test',ad_realm:'EXAMPLE.TEST',ad_ttl:60,ad_propagation_timeout:60,enabled:false,automatic:false,directory_url:production,email:'admin@example.test',primary_domain:'mcp.example.test',alternative_names:[],challenge:'dns-01',dns_hook:'example-hook',credential:'example-dns',key_algorithm:'prime256v1',renew_days:30,accept_terms:false,http_ready:false,test_only:false},certificate:{present:true,valid_now:true,self_issued:true,subject:'CN=mcp.example.test',issuer:'CN=mcp.example.test',not_after:'Nov 1 2026',days_remaining:29,sans:['mcp.example.test'],trust_note:'Fixture certificate for UI tests.'},job:{state:'idle',message:'No certificate request has been run.'},readiness:{ready:true,issues:[],warnings:[]},dns_hooks:['example-hook'],credentials:[{name:'example-dns',type:'secret'},{name:'example-ad',type:'active-directory',scopes:['acme'],allowed_hosts:['group:windows'],domain:'example.test'},{name:'wrong-group',type:'active-directory',scopes:['acme'],allowed_hosts:['group:unrelated']}],vault_locked:false,timer_active:false,schedule:'Every 12 hours',http_webroot:'/var/prstnt/mcp-appliance/acme/http-01',dns_hook_directory:'/var/prstnt/mcp-appliance/config/acme-hooks.d'};

state.ad_inventory_hosts=[{alias:'ad',hostname:'dc01.example.test',address:'192.0.2.10',groups:['windows']}];
state.challenge_types=[{value:'dns-01',label:'DNS-01',enabled:true},{value:'http-01',label:'HTTP-01',enabled:true},{value:'tls-alpn-01',label:'TLS-ALPN-01',enabled:true}];
state.config={http_mode:'standalone',http_public_access:false,http_source_networks:[],...state.config};
const defaults=JSON.parse(JSON.stringify(state.config));

const server=http.createServer(async(req,res)=>{
 if(req.url.startsWith('/api/')){let body='';for await(const c of req)body+=c;let data={};
  if(req.url==='/api/registration')data={registered:true};
  else if(req.url==='/api/session')data={user:{username:'qa',role:'admin'},csrf:'test-only'};
  else if(req.url==='/api/health')data=null;
  else if(req.url==='/api/mcp/bootstrap-policy')data={effective:{mode:'off',generation:'test',channel_url:''}};
  else if(req.url==='/api/config/issue')data={value:''};
  else if(req.url==='/api/operator/certificates')data=state;
  else if(req.url.endsWith('/certificates/save')){saves++;lastBody=JSON.parse(body);state.config={...defaults,...lastBody};if(lastBody.ad_host==='ad')state.config.ad_server='dc01.example.test';data={ok:true,status:state,message:'Certificate settings saved. No certificate was requested.'};}
  else if(req.url.endsWith('/certificates/action')){const action=JSON.parse(body);if(action.action==='test-provider'){providerTests++;}else{actions++;assert.equal(action.confirm_force,true);}data={message:'Fixture request accepted'};}
  else if(req.url.endsWith('/certificates/validate'))data=state.readiness;
  res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(data));return;
 }
 const file=path.join(web,req.url==='/'?'index.html':req.url.split('?')[0]);
 try{const type=file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.svg')?'image/svg+xml':'text/html';res.writeHead(200,{'Content-Type':type});res.end(fs.readFileSync(file));}catch{res.writeHead(404);res.end();}
});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const combo=name=>page.getByRole('combobox',{name,exact:true});
 await page.goto('http://127.0.0.1:'+server.address().port);
 await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'System',exact:true}).click();await page.getByRole('button',{name:'Certificates',exact:true}).click();
 await combo('Domain validation').waitFor();
 assert.equal(await page.getByRole('textbox',{name:/AD DNS server/}).count(),0);
 assert.equal(await page.getByRole('textbox',{name:'CA directory address',exact:true}).count(),0);
 assert.equal(await combo('Domain validation').locator('option[value="tls-alpn-01"]').evaluate(e=>e.disabled),false);
 await combo('AD DNS server').selectOption('ad');
 const credentials=page.getByRole('combobox',{name:/Vault credential/});
 assert.equal(await credentials.locator('option[value="wrong-group"]').count(),0);
 await credentials.selectOption('example-ad');
 assert.equal(await page.getByRole('textbox',{name:/Kerberos realm/}).inputValue(),'EXAMPLE.TEST');
 await combo('Certificate authority').selectOption('custom');
 await page.getByRole('textbox',{name:'CA directory address',exact:true}).fill('ca.example.test/directory');
 await page.getByRole('button',{name:'Save configuration',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('button[type="submit"]').disabled);
 assert.equal(lastBody.ad_host,'ad');assert.equal(lastBody.directory_url,'https://ca.example.test/directory');assert(!('ad_server' in lastBody));assert(!('http_mode' in lastBody));assert.equal(actions,0);
 await combo('Domain validation').selectOption('http-01');
 assert.equal(await combo('AD DNS server').count(),0);assert.equal(await credentials.count(),0);assert.equal(await page.getByRole('textbox',{name:/Kerberos realm/}).count(),0);
 await page.getByRole('textbox',{name:/Allowed CA validation sources/}).fill('192.0.2.10');
 await page.getByLabel('I authorize temporary port-80 access').check();
 await page.getByRole('button',{name:'Save configuration',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('button[type="submit"]').disabled);
 assert(!('credential' in lastBody));assert(!('ad_host' in lastBody));assert.equal(lastBody.directory_url,'https://ca.example.test/directory');
 await combo('HTTP responder').selectOption('external');assert.equal(await page.getByRole('textbox',{name:/Allowed CA validation sources/}).count(),0);
 await page.getByLabel('I have configured and verified').check();await page.getByRole('button',{name:'Save configuration',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('button[type="submit"]').disabled);
 assert(!('http_source_networks' in lastBody));assert(!('http_public_access' in lastBody));
 await combo('Domain validation').selectOption('dns-01');await combo('DNS provider').selectOption('custom');
 assert.equal(await combo('AD DNS server').count(),0);assert(await combo('Installed DNS hook').isVisible());
 await combo('Certificate authority').selectOption('production');assert.equal(await page.getByRole('textbox',{name:'CA directory address',exact:true}).count(),0);
 await combo('Domain validation').selectOption('tls-alpn-01');
 assert.equal(await combo('HTTP responder').count(),0);assert.equal(await combo('DNS provider').count(),0);assert.equal(await credentials.count(),0);
 await page.getByRole('textbox',{name:/Allowed CA validation sources/}).fill('192.0.2.10');
 await page.getByLabel('I authorize temporary port-443 access').check();
 await page.getByRole('button',{name:'Save configuration',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('button[type="submit"]').disabled);
 assert.equal(lastBody.challenge,'tls-alpn-01');assert.equal(lastBody.alpn_ready,true);assert.deepEqual(lastBody.alpn_source_networks,['192.0.2.10']);
 assert(!('credential' in lastBody));assert(!('http_mode' in lastBody));assert(!('ad_host' in lastBody));
 await page.getByLabel('Allow public CA validation').check();assert.equal(await page.getByLabel('I authorize temporary port-443 access').isChecked(),false);
 assert.equal(await page.getByRole('textbox',{name:/Allowed CA validation sources/}).count(),0);
 await page.getByLabel('Allow public CA validation').uncheck();
 for(const [width,height] of [[1440,1000],[390,844],[844,390]]){
  await page.setViewportSize({width,height});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overflow at '+width);
  await page.screenshot({path:path.join(__dirname,'context-'+width+'.png'),fullPage:true});
 }
 assert.deepEqual(errors,[]);assert.equal(actions,0);
 console.log(JSON.stringify({inventory_selector:true,group_credential_filter:true,automatic_https:true,challenge_specific_fields:true,active_fields_only:true,alpn_enabled:true,alpn_save:true,alpn_field_isolation:true,save_without_issuance:true,viewports:[1440,390,844],page_errors:errors}));
}finally{await browser.close();server.close();}})().catch(e=>{console.error(e);server.close();process.exitCode=1});
