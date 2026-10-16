/* LOCAL HTTP FIXTURE ONLY: no real package, creation or deletion request is sent. */
const {chromium}=require('playwright');
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const web=path.resolve(__dirname,'../../../usr/share/mcp-appliance/web');
const output=process.env.ENV_QA_OUTPUT||'/tmp/environment-lifecycle-browser';
const token='a'.repeat(64),stage='.stage-'+'b'.repeat(32),busyStage='.stage-'+'c'.repeat(32);
const normal={package_manager:'apt',os:'Ubuntu 24.04 LTS',update_status:'Not checked',rebuild_available:true,delete_available:true,delete_token:token,key_packages:[]};
const data={root:'/var/prstnt/mcp-appliance/chroots',sources:{},capabilities:{check:true,update:true,rebuild:true,delete:true,install:true},
 installed:[{...normal,name:'bad-check',title:'bad-check',operation_state:'failed',operation_action:'check',check_state:'failed',last_check_attempt:'2026-10-16T00:00:00Z'},
 {...normal,name:'media-1',title:'Video & Audio',operation_state:'completed',operation_action:'update'},
 {...normal,name:'empty-tools',title:'empty-tools',package_manager:'none',rebuild_available:false}],
 staging:[{name:stage,kind:'stage',state:'failed',delete_available:true,delete_token:token},
 {name:busyStage,kind:'stage',state:'running',delete_available:false,delete_reason:'Active mounts'}],
 catalog:[{id:'media',title:'Video & Audio',description:'Fixture profile',key_packages:['ffmpeg'],supported_bases:['ubuntu'],installed:true,install_available:true,install_note:'Fixture package recipe',bases:[{id:'ubuntu',releases:['22.04','24.04'],packages:['bash','ffmpeg']}]}],jobs:[]};
let actions=[],plans=[],jobs={},errors=[];
const server=http.createServer(async(req,res)=>{
 if(req.url.startsWith('/api/')){
  let raw='';for await(const part of req)raw+=part;let result={},code=200;
  if(req.method==='POST')assert.equal(req.headers['x-csrf-token'],'fixture');
  if(req.url==='/api/registration')result={registered:true};
  else if(req.url==='/api/issue')result={text:''};
  else if(req.url==='/api/session')result={user:{username:'qa',role:'admin'},csrf:'fixture'};
  else if(req.url==='/api/health')result={summary:{problems:[]}};
  else if(req.url==='/api/operator/environments')result=data;
  else if(req.url==='/api/operator/environments/plan'){
   const body=JSON.parse(raw);plans.push(body);
   result={name:body.name,manifest:{profile:body.profile,base:body.base,release:body.release,source:'ubuntu',packages:['bash','ffmpeg']},plan_token:token,confirmation:'CREATE '+body.name,note:'Fixture package recipe',warning:'Creates a new named root; existing roots are never replaced.'};
  }else if(req.url==='/api/operator/environments/start'){
   const body=JSON.parse(raw);actions.push(body);const id=actions.length.toString(16).padStart(32,'0');
   if(body.action==='delete'){assert.equal(body.delete_token,token);assert.equal(body.confirmation,'DELETE '+body.name);assert.notEqual(body.name,busyStage);}
   if(body.action==='install'){assert.equal(body.plan_token,token);assert.equal(body.confirmation,'CREATE '+body.name);}
   result={...body,id,state:'queued'};jobs[id]=result;data.jobs.unshift(result);
  }else if(req.url.startsWith('/api/operator/environments/jobs/')){
   const id=req.url.split('/').at(-1),job=jobs[id];assert(job);const failed=job.action==='check'&&job.name==='bad-check';
   result={...job,state:failed?'failed':'completed',progress:100,error:failed?'Fixture repository failure':undefined};jobs[id]=result;
   data.jobs=data.jobs.map(row=>row.id===id?result:row);
   if(job.action==='delete'){data.installed=data.installed.filter(row=>row.name!==job.name);data.staging=data.staging.filter(row=>row.name!==job.name);}
   if(job.action==='install'&&!data.installed.some(row=>row.name===job.name))data.installed.push({...normal,name:job.name,title:job.name});
   if(job.action==='check'){
    const row=data.installed.find(row=>row.name===job.name);
    Object.assign(row,{operation_state:result.state,operation_action:'check',check_state:failed?'failed':'succeeded',last_check_attempt:'2026-10-16T01:00:00Z',last_checked:failed?null:'2026-10-16T01:00:00Z',updates_available:failed?null:false,update_count:failed?null:0});
   }
  }else {code=404;result={error:'Unknown fixture request'};}
  res.writeHead(code,{'Content-Type':'application/json'});res.end(JSON.stringify(result));return;
 }
 const target=path.join(web,req.url==='/'?'index.html':req.url.split('?')[0]);
 try{res.writeHead(200,{'Content-Type':target.endsWith('.js')?'application/javascript':target.endsWith('.css')?'text/css':target.endsWith('.png')?'image/png':'text/html'});res.end(fs.readFileSync(target));}catch{res.writeHead(404);res.end();}
});
(async()=>{
 fs.mkdirSync(output,{recursive:true});await new Promise(done=>server.listen(0,'127.0.0.1',done));
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+server.address().port+'/#/environments');
  const table=page.getByRole('table',{name:'Installed environments',exact:true});await table.waitFor();
  await table.getByText('Check failed',{exact:true}).waitFor();await table.getByText('Updated; check required',{exact:true}).waitFor();
  // The missing package-manager environment still has deletion available.
  await page.getByRole('button',{name:'Actions for empty-tools',exact:true}).click();
  assert(await page.getByRole('button',{name:'Delete',exact:true}).isEnabled());await page.keyboard.press('Escape');
  await page.getByRole('tab',{name:/^Staging/}).click();
  assert(await page.getByRole('checkbox',{name:'Select staging '+busyStage,exact:true}).isDisabled());
  await page.getByRole('checkbox',{name:'Select staging '+stage,exact:true}).check();
  await page.getByRole('button',{name:'Delete selected staging (1)',exact:true}).click();
  let dialog=page.getByRole('dialog');assert(await dialog.isVisible());
  await dialog.getByRole('checkbox').check();assert(await dialog.getByRole('button',{name:'Confirm delete',exact:true}).isDisabled());
  await dialog.getByRole('textbox').fill('wrong');assert(await dialog.getByRole('button',{name:'Confirm delete',exact:true}).isDisabled());
  await dialog.getByRole('textbox').fill('DELETE '+stage);assert(await dialog.getByRole('button',{name:'Confirm delete',exact:true}).isEnabled());
  assert.equal(actions.length,0);
  await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(output,'delete-review-mobile.png'),fullPage:true});await page.setViewportSize({width:1440,height:1000});
  await dialog.getByRole('button',{name:'Confirm delete',exact:true}).click();
  await page.getByText('Finished 1 of 1 environment operations.',{exact:true}).waitFor({timeout:15000});assert.equal(actions[0].action,'delete');assert.equal(data.staging.length,1);
  // Creation wizard: duplicate/invalid names blocked, review performs no creation.
  await page.getByRole('tab',{name:/^Catalog/}).click();await page.getByRole('button',{name:'Create',exact:true}).click();dialog=page.getByRole('dialog');
  await dialog.getByRole('textbox',{name:'Environment name',exact:true}).fill('media-1');assert(await dialog.getByRole('button',{name:'Review configuration',exact:true}).isDisabled());
  await dialog.getByRole('textbox',{name:'Environment name',exact:true}).fill('../bad');assert(await dialog.getByRole('button',{name:'Review configuration',exact:true}).isDisabled());
  await dialog.getByRole('textbox',{name:'Environment name',exact:true}).fill('media-editing');
  await dialog.getByRole('combobox',{name:'Release',exact:true}).selectOption('24.04');
  await dialog.getByRole('button',{name:'Review configuration',exact:true}).click();await dialog.getByText('ffmpeg',{exact:true}).waitFor();
  assert.equal(plans.length,1);assert.equal(actions.length,1);assert(await dialog.getByRole('button',{name:'Create environment',exact:true}).isDisabled());
  for(const [width,height] of [[1440,1000],[844,390],[390,844]]){
   await page.setViewportSize({width,height});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(output,'create-review-'+width+'.png'),fullPage:true});
  }
  await page.setViewportSize({width:1440,height:1000});await dialog.getByRole('checkbox').check();await dialog.getByRole('button',{name:'Create environment',exact:true}).click();
  await page.getByText('Creation queued for media-editing. Track it in Operations.',{exact:true}).waitFor();
  await page.getByRole('tab',{name:/^Installed/}).click();await table.getByText('media-editing',{exact:true}).waitFor({timeout:15000});
  // A failed check must not abandon the other environments; results persist on reload.
  await page.getByRole('button',{name:'Check all updates',exact:true}).click();
  await page.getByText('Finished 3 of 3 environment operations. 1 failed; see Operations.',{exact:true}).waitFor({timeout:20000});
  assert.equal(actions.filter(row=>row.action==='check').length,3);
  await page.reload();await table.waitFor();assert.equal(await table.getByText('Up to date',{exact:true}).count(),2);assert.equal(await table.getByText('Check failed',{exact:true}).count(),1);
  await page.screenshot({path:path.join(output,'verified-statuses.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  const result={fixture_only:true,typed_delete:true,staging_cleanup:true,busy_stage_blocked:true,missing_manager_deletable:true,naming_wizard:true,creation_review:true,checks_continue_after_failure:true,status_persists_after_reload:true,page_errors:errors};
  fs.writeFileSync(path.join(output,'lifecycle-browser-report.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
