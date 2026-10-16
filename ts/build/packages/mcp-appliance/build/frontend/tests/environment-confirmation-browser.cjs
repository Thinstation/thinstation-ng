/* LOCAL FIXTURE ONLY. Deletion requests are captured in memory; no live API is used. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),http=require('http'),fs=require('fs'),path=require('path');
const web=path.resolve(__dirname,'../../../usr/share/mcp-appliance/web');
const out=process.env.ENV_QA_OUTPUT||'/tmp/environment-confirmation-qa';
const stage='.stage-00000000000000000000000000001bbd';
const extra='.stage-00000000000000000000000000001bbe';
const token='a'.repeat(64),actions=[],jobs={};let inventoryError=false;
const data={root:'/var/prstnt/mcp-appliance/chroots',sources:{},capabilities:{check:true,update:true,rebuild:true,delete:true,install:true},
 installed:[{name:'media-1',title:'Video & Audio',package_manager:'dnf',os:'Fixture OS',delete_available:true,delete_token:token,rebuild_available:true}],
 staging:[{name:stage,kind:'stage',delete_available:true,delete_token:token},{name:extra,kind:'stage',delete_available:true,delete_token:token}],catalog:[],jobs:[]};
const server=http.createServer(async(req,res)=>{
 try{
 if(req.url.startsWith('/api/')){
  let raw='';for await(const c of req)raw+=c;let result={},status=200;
  if(req.url==='/api/registration')result={registered:true};
  else if(req.url==='/api/issue')result={text:''};
  else if(req.url==='/api/session')result={user:{username:'fixture',role:'admin'},csrf:'fixture'};
  else if(req.url==='/api/health')result={summary:{problems:[]}};
  else if(req.url==='/api/operator/environments'){result=inventoryError?{error:'Fixture inventory unavailable'}:data;status=inventoryError?503:200;}
  else if(req.url==='/api/operator/environments/start'){
   assert.equal(req.method,'POST');assert.equal(req.headers['x-csrf-token'],'fixture');
   const body=JSON.parse(raw);assert.equal(body.action,'delete');assert.equal(body.confirmation,'DELETE '+body.name);assert.equal(body.delete_token,token);
   actions.push(body);const id=actions.length.toString(16).padStart(32,'0');result={...body,id,state:'queued'};jobs[id]=result;
  }else if(req.url.startsWith('/api/operator/environments/jobs/')){
   const old=jobs[req.url.split('/').at(-1)];assert(old);result={...old,state:'completed'};
  }else{status=404;result={error:'No fixture handler'};}
  res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(result));return;
 }
 const target=path.resolve(web,req.url==='/'?'index.html':'.'+decodeURIComponent(req.url.split('?')[0]));
 if(!target.startsWith(web+path.sep)){res.writeHead(403);res.end();return;}
 const body=fs.readFileSync(target);res.writeHead(200,{'Content-Type':target.endsWith('.js')?'application/javascript':target.endsWith('.css')?'text/css':target.endsWith('.png')?'image/png':'text/html'});res.end(body);
 }catch(e){res.writeHead(500);res.end(String(e));}
});
(async()=>{
 fs.mkdirSync(out,{recursive:true});await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const url='http://127.0.0.1:'+server.address().port+'/#/environments';
 await page.goto(url);await page.getByRole('table',{name:'Installed environments',exact:true}).waitFor();
 await page.getByRole('tab',{name:/^Staging/}).click();
 const table=page.getByRole('table',{name:'Staging and recovery entries'});
 const row=table.locator('tbody tr').filter({hasText:stage});
 await row.getByRole('button',{name:'Delete',exact:true}).click();
 const modal=page.getByRole('dialog'),button=modal.getByRole('button',{name:'Confirm delete',exact:true});
 const field=modal.getByRole('textbox',{name:'Deletion confirmation',exact:true});
 const ack=modal.getByRole('checkbox',{name:/I have reviewed/});
 const feedback=modal.locator('#env-confirm-status');
 assert.deepEqual(await modal.getByRole('list',{name:'Selected targets'}).locator('li').allTextContents(),[stage]);
 assert.equal(await modal.getByTestId('delete-confirmation-phrase').textContent(),'DELETE '+stage);
 assert(await button.isDisabled());assert.match(await feedback.textContent(),/review box/);
 await field.fill('DELETE '+stage);assert(await button.isDisabled());assert.match(await feedback.textContent(),/review box/);
 // A programmatic click still must not bypass confirmation.
 await button.evaluate(node=>node.dispatchEvent(new MouseEvent('click',{bubbles:true})));assert.equal(actions.length,0);
 await ack.check();assert(await button.isEnabled());
 await field.fill('DELETE '+stage+'x');assert(await button.isDisabled());assert.equal(await field.getAttribute('aria-invalid'),'true');
 assert.match(await feedback.textContent(),/does not match/);
 await field.fill('  delete   '+stage+'  ');assert(await button.isEnabled());assert.equal(await field.getAttribute('aria-invalid'),'false');
 assert.match(await feedback.textContent(),/now enabled/);
 await ack.uncheck();assert(await button.isDisabled());await ack.check();assert(await button.isEnabled());
 for(const [width,height] of [[1440,1000],[844,390],[390,844]]){
  await page.setViewportSize({width,height});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await button.scrollIntoViewIfNeeded();assert(await button.isVisible());assert(await button.isEnabled());
  await page.screenshot({path:path.join(out,'confirmation-ready-'+width+'.png'),fullPage:true});
 }
 await page.setViewportSize({width:1440,height:1000});await button.click();
 await page.getByText('Finished 1 of 1 environment operations.',{exact:true}).waitFor({timeout:12000});
 assert.equal(actions.length,1);assert.equal(actions[0].confirmation,'DELETE '+stage);
 // Bulk state uses the displayed item count and emits exact per-target confirmations.
 await page.getByRole('checkbox',{name:'Select staging '+stage,exact:true}).check();
 await page.getByRole('checkbox',{name:'Select staging '+extra,exact:true}).check();
 await page.getByRole('button',{name:'Delete selected staging (2)',exact:true}).click();
 assert.equal(await modal.getByTestId('delete-confirmation-phrase').textContent(),'DELETE 2 ITEMS');assert.equal(await field.inputValue(),'');
 assert(!(await ack.isChecked()));await ack.check();await field.fill('DELETE 3 ITEMS');assert(await button.isDisabled());
 await field.fill(' delete  2  items ');assert(await button.isEnabled());await button.click();
 await page.getByText('Finished 2 of 2 environment operations.',{exact:true}).waitFor({timeout:15000});assert.equal(actions.length,3);
 assert.deepEqual(actions.slice(1).map(x=>x.confirmation),['DELETE '+stage,'DELETE '+extra]);
 // While an inventory refresh fails, a completed challenge remains blocked with an explanation.
 await row.getByRole('button',{name:'Delete',exact:true}).click();await ack.check();await field.fill('DELETE '+stage);assert(await button.isEnabled());
 inventoryError=true;
 await page.getByRole('button',{name:'Refresh',exact:true}).evaluate(node=>node.click());
 await page.getByRole('alert').filter({hasText:'Showing the last inventory'}).waitFor();
 assert(await button.isDisabled());assert.match(await feedback.textContent(),/inventory/);assert.equal(actions.length,3);
 await modal.getByRole('button',{name:'Cancel',exact:true}).click();inventoryError=false;await page.getByRole('button',{name:'Refresh',exact:true}).click();
 await page.getByRole('tab',{name:/^Installed/}).click();await page.getByRole('checkbox',{name:'Select media-1',exact:true}).check();
 await page.getByRole('button',{name:'Update selected (1)',exact:true}).click();
 const update=modal.getByRole('button',{name:'Confirm update',exact:true});assert(await update.isDisabled());
 await ack.check();assert(await update.isEnabled());await modal.getByRole('button',{name:'Cancel',exact:true}).click();
 assert.equal(actions.length,3);assert.deepEqual(errors,[]);
 const report={fixture_only:true,no_live_deletions:true,acknowledgment_required:true,exact_target_required:true,spacing_and_action_case:true,bulk_count_exact:true,visible_feedback:true,programmatic_click_guard:true,stale_inventory_guard:true,update_unchanged:true,viewports:[1440,844,390],page_errors:errors};
 fs.writeFileSync(path.join(out,'confirmation-browser-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
