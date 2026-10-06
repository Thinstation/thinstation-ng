/* Run after npm run build with Playwright available to Node. Uses only a local
   fixture HTTP server; never connects to or changes a real appliance. */
const {chromium}=require('playwright');
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('assert');
const web=path.resolve(__dirname,'../../../usr/share/mcp-appliance/web');
let inventory={hosts:{},groups:{}},writes=0,revision=0,failSave=false;
const server=http.createServer(async(req,res)=>{
 if(req.url.startsWith('/api/')){
  let raw='';for await(const c of req)raw+=c;let data={},status=200;
  if(req.url==='/api/registration')data={registered:true};
  else if(req.url==='/api/session')data={user:{username:'qa',role:'admin'},csrf:'fixture'};
  else if(req.url==='/api/health')data=null;
  else if(req.url==='/api/config/hosts'){
   if(req.method==='PUT'){
    if(failSave){status=503;data={error:'Fixture save failure'};}
    else {assert.equal(req.headers['x-csrf-token'],'fixture');assert.equal(req.headers['if-match'],String(revision));inventory=JSON.parse(raw);writes++;revision++;data={ok:true,name:'hosts',value:JSON.stringify(inventory),revision:String(revision)};}
   }else data={name:'hosts',value:JSON.stringify(inventory),revision:String(revision)};
  }
  res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(data));return;
 }
 const f=path.join(web,req.url==='/'?'index.html':req.url.split('?')[0]);
 try{res.writeHead(200,{'Content-Type':f.endsWith('.js')?'application/javascript':f.endsWith('.css')?'text/css':f.endsWith('.svg')?'image/svg+xml':'text/html'});res.end(fs.readFileSync(f));}catch{res.writeHead(404);res.end();}
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  async function count(n){await page.waitForFunction(n=>document.querySelectorAll('tbody tr').length===n,n);}
  async function saved(){await page.waitForFunction(()=>!!document.querySelector('[role=status]'));}
  const button=name=>page.getByRole('button',{name,exact:true});
  const input=name=>page.getByLabel(name,{exact:true});
  await page.goto('http://127.0.0.1:'+server.address().port);await button('Inventory').click();
  await button('Add host').click();await input('Alias').fill('qa-host');await input('Address').fill('192.0.2.10');await button('Save').click();await saved();await count(1);
  assert.equal(writes,1);assert.equal(await page.getByText('No hosts are configured yet.').count(),0);
  await button('Add host').click();await input('Alias').fill('qa-host');await input('Address').fill('192.0.2.11');await button('Save').click();await page.getByRole('alert').waitFor();assert.equal(writes,1);await button('Cancel').click();
  await button('Open').click();await input('Address').fill('192.0.2.20');failSave=true;await button('Save').click();await page.getByText('Fixture save failure').waitFor();assert.equal(await input('Address').inputValue(),'192.0.2.20');assert.equal(writes,1);
  failSave=false;await button('Save').click();await saved();await count(1);assert.equal(inventory.hosts['qa-host'].address,'192.0.2.20');assert(await page.getByText('192.0.2.20',{exact:true}).isVisible());
  await page.getByRole('button',{name:/^Groups/}).click();await button('Add group').click();await input('Group name').fill('servers');await page.getByRole('checkbox',{name:/qa-host/}).check();await button('Save').click();await saved();await count(1);assert.deepEqual(inventory.groups.servers.hosts,['qa-host']);
  await page.getByRole('button',{name:/^Hosts/}).click();await count(1);assert(await page.locator('tbody').getByText('servers',{exact:true}).isVisible());
  await button('Open').click();await input('Alias').fill('renamed');await button('Save').click();await saved();assert(!inventory.hosts['qa-host']);assert(inventory.hosts.renamed);assert.deepEqual(inventory.groups.servers.hosts,['renamed']);
  await page.reload();await button('Inventory').click();await count(1);assert(await page.locator('tbody').getByText('renamed',{exact:true}).isVisible());
  inventory.hosts.renamed.hostname='renamed.example.test';revision++;await button('Refresh').click();await page.locator('tbody').getByText('renamed.example.test',{exact:true}).waitFor();
  for(const [width,height] of [[1440,1000],[390,844],[844,390]]){
   await page.setViewportSize({width,height});assert(await button('Open').isVisible(),'Open inaccessible at '+width);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'horizontal overflow at '+width);
  }
  await button('Open').click();await button('Remove').click();await saved();await count(0);assert.deepEqual(inventory.groups.servers.hosts,[]);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({add_immediate:true,duplicate_rejected:true,edit_immediate:true,save_error_retains_form:true,groups_and_rename:true,page_reload:true,refresh:true,remove:true,responsive_widths:[1440,390,844],page_errors:errors,writes}));
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1});
