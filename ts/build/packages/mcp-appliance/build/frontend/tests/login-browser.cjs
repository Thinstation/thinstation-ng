/* Local fixture-only UI checks; never uses real credentials or remote services. */
const {chromium}=require('playwright');const http=require('http'),fs=require('fs'),path=require('path'),assert=require('assert');
const web=path.resolve(__dirname,'../../../usr/share/mcp-appliance/web');
const inventory={hosts:{web:{address:'192.0.2.10',platform:'linux'}},groups:{servers:{hosts:['web']}}};let calls=[],credentials=[];
const health=()=>({vault:{credentials,locked:true},summary:{problems:[]},system:{memory:{},load:[]},mcp:{},network:{},storage:{},certificate:{},services:{}});
const server=http.createServer(async(req,res)=>{
 if(req.url.startsWith('/api/')){let raw='';for await(const c of req)raw+=c;let d={};
 if(req.url==='/api/registration')d={registered:true};else if(req.url==='/api/session')d={user:{username:'qa',role:'admin'},csrf:'fixture'};
 else if(req.url==='/api/health')d=health();else if(req.url==='/api/config/hosts')d={value:JSON.stringify(inventory)};
 else if(req.url==='/api/vault/credential-requests')d={requests:[]};
 else if(req.method==='POST'){const b=JSON.parse(raw);calls.push({path:req.url,body:b});
 if(req.url==='/api/vault/generate-ssh-key')credentials=[{name:b.name,type:'ssh-key',username:b.username,scopes:b.scopes,allowed_hosts:[b.target]}];
 if(req.url==='/api/vault/login')credentials[0].username=b.username;d={ok:true};}
 res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(d));return;}
 const f=path.join(web,req.url==='/'?'index.html':req.url.split('?')[0]);
 try{res.writeHead(200,{'Content-Type':f.endsWith('.js')?'application/javascript':f.endsWith('.css')?'text/css':'text/html'});res.end(fs.readFileSync(f));}catch{res.writeHead(404);res.end();}
});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({headless:true});
try{const p=await browser.newPage({viewport:{width:1440,height:1000}});let errors=[];p.on('pageerror',e=>errors.push(e.message));const button=n=>p.getByRole('button',{name:n,exact:true});const label=n=>p.getByLabel(n,{exact:true});
await p.goto('http://127.0.0.1:'+server.address().port);await button('Inventory').click();await button('Add host').click();assert.equal(await label('Username').count(),0);
await button('Credentials').click();await button('Add credential').click();await p.getByRole('combobox',{name:'Credential type',exact:true}).selectOption('ssh-generate');await label('Credential name').fill('ssh-automation');await button('Next').click();await label('Allowed scopes / capabilities').fill('ssh');await p.getByRole('checkbox',{name:/Group: servers/}).check();await button('Next').click();
await button('Next').click();assert.equal(await button('Save credential').count(),0);await label('Login username').fill('svc-automation');await button('Next').click();await button('Save credential').click();await p.getByRole('row').filter({hasText:'ssh-automation'}).getByRole('button',{name:'Open'}).waitFor();
assert.equal(calls[0].body.username,'svc-automation');assert.equal(calls[0].body.target,'group:servers');
await p.getByRole('row').filter({hasText:'ssh-automation'}).getByRole('button',{name:'Open'}).click();await label('Login username').fill('svc-new');await button('Update login username').click();await p.waitForFunction(()=>document.body.innerText.includes('Credential updated.'));assert.equal(calls.at(-1).body.username,'svc-new');
await button('Add credential').click();await p.getByRole('combobox',{name:'Credential type',exact:true}).selectOption('password');await label('Credential name').fill('password-login');await button('Next').click();await button('Next').click();await label('Login username').fill('operator');await label('Password').fill('fixture-only');assert.equal(await label('Password').getAttribute('type'),'password');await button('Next').click();await button('Save credential').click();await p.waitForTimeout(100);const secret=JSON.parse(calls.at(-1).body.secret);assert.equal(secret.username,'operator');assert.equal(secret.password,'fixture-only');
await button('Add credential').click();await p.getByRole('combobox',{name:'Credential type',exact:true}).selectOption('active-directory');await label('Credential name').fill('ad-login');await button('Next').click();await button('Next').click();await label('AD domain / realm').fill('example.test');await label('Username').fill('domain-operator');await label('Password').fill('fixture-only');
for(const [width,height] of [[1440,1000],[390,844],[844,390]]){await p.setViewportSize({width,height});assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
await button('Next').click();await button('Save credential').click();await p.waitForTimeout(100);assert.equal(JSON.parse(calls.at(-1).body.secret).username,'domain-operator');assert.deepEqual(errors,[]);console.log(JSON.stringify({host_username_absent:true,credential_username_required:true,ssh_group_assignment:true,ssh_username_edit:true,password_login:true,ad_login:true,viewports:[1440,390,844],page_errors:errors}));
}finally{await browser.close();server.close();}})().catch(e=>{console.error(e);server.close();process.exitCode=1});
