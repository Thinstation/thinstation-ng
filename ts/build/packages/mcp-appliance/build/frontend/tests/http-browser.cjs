const {chromium}=require('playwright');
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('assert');
const web=path.resolve(__dirname,'../../../usr/share/mcp-appliance/web');
const production='https://acme-v02.api.letsencrypt.org/directory',staging='https://acme-staging-v02.api.letsencrypt.org/directory';
let actions=0,saves=0;let providerTests=0;
let state={provider_ready:true,config:{dns_provider:'custom',ad_server:'dc01.example.test',ad_zone:'example.test',ad_realm:'EXAMPLE.TEST',ad_ttl:60,ad_propagation_timeout:60,enabled:false,automatic:false,directory_url:production,email:'admin@example.test',primary_domain:'mcp.example.test',alternative_names:[],challenge:'dns-01',dns_hook:'example-hook',credential:'example-dns',key_algorithm:'prime256v1',renew_days:30,accept_terms:false,http_ready:false,test_only:false},certificate:{present:true,valid_now:true,self_issued:true,subject:'CN=mcp.example.test',issuer:'CN=mcp.example.test',not_after:'Nov 1 2026',days_remaining:29,sans:['mcp.example.test'],trust_note:'Fixture certificate for UI tests.'},job:{state:'idle',message:'No certificate request has been run.'},readiness:{ready:true,issues:[],warnings:[]},dns_hooks:['example-hook'],credentials:[{name:'example-dns',type:'secret'},{name:'example-ad',type:'active-directory'}],vault_locked:false,timer_active:false,schedule:'Every 12 hours',http_webroot:'/var/prstnt/mcp-appliance/acme/http-01',dns_hook_directory:'/var/prstnt/mcp-appliance/config/acme-hooks.d'};
const server=http.createServer(async(req,res)=>{
 if(req.url.startsWith('/api/')){let body='';for await(const c of req)body+=c;let data={};
  if(req.url==='/api/registration')data={registered:true};
  else if(req.url==='/api/session')data={user:{username:'qa',role:'admin'},csrf:'test-only'};
  else if(req.url==='/api/health')data=null;
  else if(req.url==='/api/mcp/bootstrap-policy')data={effective:{mode:'off',generation:'test',channel_url:''}};
  else if(req.url==='/api/config/issue')data={value:''};
  else if(req.url==='/api/operator/certificates')data=state;
  else if(req.url.endsWith('/certificates/save')){saves++;state.config=JSON.parse(body);data={ok:true,status:state,message:'Certificate settings saved. No certificate was requested.'};}
  else if(req.url.endsWith('/certificates/action')){const action=JSON.parse(body);if(action.action==='test-provider'){providerTests++;}else{actions++;assert.equal(action.confirm_force,true);}data={message:'Fixture request accepted'};}
  else if(req.url.endsWith('/certificates/validate'))data=state.readiness;
  res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(data));return;
 }
 const file=path.join(web,req.url==='/'?'index.html':req.url.split('?')[0]);
 try{const type=file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.svg')?'image/svg+xml':'text/html';res.writeHead(200,{'Content-Type':type});res.end(fs.readFileSync(file));}catch{res.writeHead(404);res.end();}
});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({headless:true});
try{const page=await browser.newPage({viewport:{width:1440,height:1000}});let errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto('http://127.0.0.1:'+server.address().port);await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'System',exact:true}).click();await page.getByRole('button',{name:'Certificates',exact:true}).click();
const combo=name=>page.getByRole('combobox',{name,exact:true});
await combo('Domain validation').selectOption('http-01');
assert.equal(await combo('HTTP responder').inputValue(),'standalone');
assert.equal(await page.getByRole('combobox',{name:/Vault credential/}).count(),0);
await page.getByRole('textbox',{name:/Allowed CA validation sources/}).fill('192.0.2.10\n2001:db8::10');
await page.getByLabel('Enable ACME').check();await page.getByLabel('I have reviewed and accept').check();
await page.getByLabel('I authorize temporary port-80 access').check();
await page.getByRole('button',{name:'Save configuration',exact:true}).click();
assert.equal(saves,1);assert.equal(actions,0);assert.equal(state.config.http_mode,'standalone');assert.deepEqual(state.config.http_source_networks,['192.0.2.10','2001:db8::10']);assert(!('credential' in state.config));
await combo('HTTP responder').selectOption('external');assert(await page.getByLabel('I have configured and verified').isVisible());assert.equal(await page.getByRole('textbox',{name:/Allowed CA validation sources/}).count(),0);
await combo('HTTP responder').selectOption('standalone');
await page.getByLabel('Allow public CA validation').check();assert.equal(await page.getByRole('textbox',{name:/Allowed CA validation sources/}).count(),0);assert.equal(await page.getByLabel('I authorize temporary port-80 access').isChecked(),false);
await page.getByLabel('Allow public CA validation').uncheck();await page.getByLabel('I authorize temporary port-80 access').check();
await combo('Key algorithm').selectOption('rsa');await page.getByRole('button',{name:'Save configuration',exact:true}).click();assert.equal(actions,0);
for(const [width,height] of [[1440,1000],[390,844],[844,390]]){await page.setViewportSize({width,height});await page.screenshot({path:path.join(__dirname,'http-certificates-'+width+'.png'),fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'horizontal overflow at '+width);}
assert.deepEqual(errors,[]);console.log(JSON.stringify({http_builtin:true,restricted_sources:true,external_webroot:true,explicit_public_access:true,no_vault_credential:true,save_without_issue:true,responsive_widths:[1440,390,844],page_errors:errors}));
}finally{await browser.close();server.close();}})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
