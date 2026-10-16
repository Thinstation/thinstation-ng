/* Browser fixtures only. Never connects to a live appliance or executes a tool. */
const {chromium}=require('playwright');
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const web=path.resolve(__dirname,'../../../usr/share/mcp-appliance/web');
const output=process.env.ENV_QA_OUTPUT||path.resolve(__dirname,'environment-qa');
const longName='custom-environment-'+ 'x'.repeat(42),stageName='.stage-'+ '0'.repeat(128);
const normal={package_manager:'dnf',os:'Fedora Linux 44',update_status:'Not checked',key_packages:['python3'],rebuild_available:true};
const fixtures={root:'/var/prstnt/mcp-appliance/chroots',sources:{fedora_url:'',updates_url:'',source:'build defaults'},
 installed:[{...normal,name:'media-f44',title:'Video & Audio',description:'Video processing and encoding',last_checked:'2026-10-15T12:00:00Z',updates_available:true},
 { ...normal,name:'browser-f44',title:'Browser Automation',description:'Managed browser tools'},
 {...normal,name:longName,title:longName,description:'A custom definition with a very long name'},
 {...normal,name:'missing-f44',title:'Missing package manager',package_manager:'none',rebuild_available:false},
 {...normal,name:'busy-f44',title:'Active environment',operation_state:'running'},
 {name:stageName,package_manager:'apt',os:'Ubuntu 24.04 LTS',description:'This must not appear as installed'}],
 staging:[{name:stageName,kind:'stage',state:'failed',environment:'test-ubuntu',modified_at:'2026-10-15T10:00:00Z',latest_job:'f'.repeat(32)},
 {name:'.previous-'+ 'a'.repeat(32),kind:'previous',modified_at:'2026-10-14T10:00:00Z'}],
 catalog:[{id:'media',title:'Video & Audio',description:'Video processing',key_packages:['ffmpeg','ffprobe','mediainfo'],supported_bases:['fedora','ubuntu'],installed:true},
 {id:'photo',title:'Photography',description:'Image processing and metadata',key_packages:['imagemagick','exiftool'],supported_bases:['fedora','ubuntu'],installed:false}],
 jobs:[{id:'f'.repeat(32),name:'test-ubuntu',action:'rebuild',state:'failed',created_at:'2026-10-15T10:00:00Z'}]};
let starts=[],saves=[],running=null,jobResults={},inventoryError=false;
const server=http.createServer(async(req,res)=>{
 if(req.url.startsWith('/api/')){
  let raw='';for await(const c of req)raw+=c;
  let result={},status=200;
  if(req.method==='POST')assert.equal(req.headers['x-csrf-token'],'fixture');
  if(req.url==='/api/registration')result={registered:true};
  else if(req.url==='/api/issue')result={text:''};
  else if(req.url==='/api/session')result={user:{username:'qa',role:'admin'},csrf:'fixture'};
  else if(req.url==='/api/health')result={summary:{problems:[]}};
  else if(req.url==='/api/operator/environments'){
   if(inventoryError){status=503;result={error:'Fixture inventory unavailable'};}else result=fixtures;
  }else if(req.url==='/api/operator/environments/start'){
   assert.equal(running,null,'overlapping fixture jobs');
   const body=JSON.parse(raw);assert(!body.name.startsWith('.'));assert(['check','update','rebuild'].includes(body.action));
   const id=(starts.length+1).toString(16).padStart(32,'0');
   result={...body,id,state:'queued',created_at:new Date().toISOString()};
   running=id;jobResults[id]=result;starts.push(body);fixtures.jobs.unshift(result);
  }else if(req.url.startsWith('/api/operator/environments/jobs/')){
   const id=req.url.split('/').at(-1);result=jobResults[id]||{...fixtures.jobs.find(row=>row.id===id),log_tail:'Fixture worker output',error:'Fixture failure'};
  }else if(req.url==='/api/operator/environments/sources/save'){
   const body=JSON.parse(raw);saves.push(body);fixtures.sources={...body,source:'persistent'};result=fixtures.sources;
  }else {status=404;result={error:'Unknown fixture endpoint'};}
  res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(result));return;
 }
 const pathname=decodeURIComponent(req.url.split('?')[0]);
 const file=path.join(web,pathname==='/'?'index.html':pathname);
 if(!file.startsWith(web+path.sep)){res.writeHead(403);res.end();return;}
 try{res.writeHead(200,{'Content-Type':file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.png')?'image/png':'text/html'});res.end(fs.readFileSync(file));}
 catch{res.writeHead(404);res.end();}
});
async function waitFor(predicate,message){const end=Date.now()+12000;while(Date.now()<end){if(predicate())return;await new Promise(r=>setTimeout(r,60));}throw new Error('Timed out: '+message);}
function finish(state='completed'){
 assert(running);jobResults[running]={...jobResults[running],state,progress:100,log_tail:'Fixture '+state,error:state==='failed'?'Simulated failure':undefined};
 const index=fixtures.jobs.findIndex(row=>row.id===running);fixtures.jobs[index]=jobResults[running];running=null;
}
(async()=>{
 fs.mkdirSync(output,{recursive:true});await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  const base='http://127.0.0.1:'+server.address().port;
  await page.goto(base+'/#/environments');await page.getByRole('table',{name:'Installed environments',exact:true}).waitFor();
  const table=page.getByRole('table',{name:'Installed environments',exact:true});
  assert.equal(await table.locator('tbody>tr').count(),5);
  assert.equal(await table.getByText(stageName,{exact:true}).count(),0);
  assert(await page.getByRole('button',{name:'Update selected',exact:true}).isDisabled());
  await page.getByRole('checkbox',{name:'Select media-f44',exact:true}).check();
  await page.getByRole('searchbox',{name:'Find an environment'}).fill('browser');
  await page.getByRole('checkbox',{name:'Select all visible eligible environments'}).check();
  await page.getByRole('searchbox',{name:'Find an environment'}).fill('');
  assert(await page.getByRole('checkbox',{name:'Select media-f44',exact:true}).isChecked());
  assert(await page.getByRole('checkbox',{name:'Select browser-f44',exact:true}).isChecked());
  const selectAll=page.getByRole('checkbox',{name:'Select all visible eligible environments'});
  assert(await selectAll.evaluate(node=>node.indeterminate));
  await page.getByRole('button',{name:'Actions for media-f44',exact:true}).click();
  assert(await page.getByRole('button',{name:'Delete',exact:true}).isDisabled());
  await page.keyboard.press('Escape');assert.equal(await page.locator('.env-menu').count(),0);
  await page.getByRole('tab',{name:/^Installed/}).focus();
  await page.keyboard.press('ArrowRight');assert.equal(await page.getByRole('tab',{name:/^Catalog/}).getAttribute('aria-selected'),'true');
  await page.keyboard.press('Home');assert.equal(await page.getByRole('tab',{name:/^Installed/}).getAttribute('aria-selected'),'true');
  const before=starts.length;
  await page.getByRole('button',{name:'Update selected (2)',exact:true}).click();
  const modal=page.getByRole('dialog');assert(await modal.isVisible());
  await page.keyboard.press('Shift+Tab');assert(await modal.getByRole('button',{name:'Cancel',exact:true}).evaluate(node=>node===document.activeElement));
  await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:path.join(output,'confirmation-390.png'),fullPage:true});await page.setViewportSize({width:1440,height:1000});
  assert(await modal.getByRole('button',{name:'Confirm update',exact:true}).isDisabled());assert.equal(starts.length,before);
  await modal.getByRole('button',{name:'Cancel',exact:true}).click();assert.equal(starts.length,before);
  // Consistent layout and overflow guards for every tab at desktop and mobile sizes.
  const tabs=[['Installed','installed'],['Catalog','catalog'],['Staging & recovery','staging'],['Operations','operations'],['Settings','settings']];
  for(const [label,id] of tabs){
   await page.getByRole('tab',{name:new RegExp('^'+label.replace('&','&'))}).click();
   if(id==='catalog')await page.getByRole('button',{name:'Video & Audio',exact:true}).click();
   for(const [width,height] of [[1440,1000],[844,390],[390,844]]){
    await page.setViewportSize({width,height});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'horizontal page overflow '+id+' '+width);
    const overlap=await page.locator('.env-table td').evaluateAll(cells=>cells.some(cell=>cell.getBoundingClientRect().width>0&&cell.scrollWidth>cell.clientWidth+2));
    assert(!overlap,'cell overflow '+id+' '+width);
    await page.screenshot({path:path.join(output,id+'-'+width+'.png'),fullPage:true});
   }
   await page.setViewportSize({width:1440,height:1000});
  }
  // Settings drafts must survive refresh and tab switching.
  const input=page.getByRole('textbox',{name:'Fedora base repository URL'});
  await input.fill('https://mirror.example/'+ 'a'.repeat(160)+'/$releasever/$basearch/');
  const draft=await input.inputValue();await page.getByRole('button',{name:'Refresh',exact:true}).click();
  assert.equal(await input.inputValue(),draft);await page.getByRole('button',{name:'Reset changes',exact:true}).click();assert.equal(await input.inputValue(),'');
  await input.fill('https://mirror.example/fedora/$releasever/$basearch/');
  await page.getByRole('button',{name:'Save changes',exact:true}).click();await waitFor(()=>saves.length===1,'sources save');
  assert.equal(starts.length,0);
  await page.getByRole('tab',{name:/^Installed/}).click();
  await page.getByRole('button',{name:'Clear selection',exact:true}).click();
  // Check all is serialized, and never includes hidden stages, busy or unsupported roots.
  await page.getByRole('button',{name:'Check all updates',exact:true}).click();
  for(let i=0;i<3;i++){await waitFor(()=>starts.length===i+1,'check job '+i);assert.equal(starts[i].action,'check');finish();}
  await page.getByText('Finished 3 of 3 environment operations.',{exact:true}).waitFor({timeout:12000});
  assert.deepEqual(starts.map(row=>row.name),['media-f44','browser-f44',longName]);
  // Updates require confirmation, and a failure stops all remaining submissions.
  await page.getByRole('checkbox',{name:'Select media-f44',exact:true}).check();
  await page.getByRole('checkbox',{name:'Select browser-f44',exact:true}).check();
  await page.getByRole('button',{name:'Update selected (2)',exact:true}).click();
  await modal.getByRole('checkbox').check();await modal.getByRole('button',{name:'Confirm update',exact:true}).click();
  await waitFor(()=>starts.length===4,'first update');finish('failed');
  await page.getByRole('alert').filter({hasText:'Remaining operations were not submitted'}).waitFor({timeout:12000});assert.equal(starts.length,4);
  // A stale inventory remains visible, but cannot be used for mutations.
  inventoryError=true;await page.getByRole('button',{name:'Refresh',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'Showing the last inventory'}).waitFor();
  assert(await page.getByRole('button',{name:'Check all updates',exact:true}).isDisabled());
  assert.equal(await table.locator('tbody>tr').count(),5);
  assert.deepEqual(errors,[]);
  const report={tabs:tabs.map(row=>row[1]),viewports:[1440,844,390],staging_separated:true,long_names_contained:true,
   draft_preserved:true,confirmed_mutations_only:true,serialized_jobs:true,failure_stops_queue:true,stale_inventory_guard:true,page_errors:errors};
  fs.writeFileSync(path.join(output,'browser-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
