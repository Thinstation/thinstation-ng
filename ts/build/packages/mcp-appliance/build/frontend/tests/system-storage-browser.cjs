/* Local fixtures only. No real storage operation is performed. */
const {chromium}=require('playwright');
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('assert');
const web=path.resolve(__dirname,'../../../usr/share/mcp-appliance/web'),G=1024**3;
let plans=0,applies=0,request=null;
const storage={checked_at:1791090000,devices:[{path:'/dev/vdb',type:'disk',size:20*G,fstype:'LVM2_member'}],mounts:[{target:'/data',device:'/dev/mapper/vg-data',device_bytes:4*G,fstype:'ext4',fs_bytes:4*G,total_bytes:4*G,used_bytes:G,available_bytes:3*G,grow:{available:false,reason:'No larger device capacity.'},allocation:{available:true,vg:'vg',free_bytes:12*G}}],lvm:{available:true,vgs:[{vg_name:'vg',vg_size:16*G,vg_free:12*G}],pvs:[],lvs:[{vg_name:'vg',lv_path:'/dev/vg/data',lv_size:4*G,segtype:'linear'}]},warnings:[],tools:{},pv_actions:[],job:{state:'idle',message:'No changes requested.'}};
const server=http.createServer(async(req,res)=>{
 if(req.url.startsWith('/api/')){let body='';for await(const c of req)body+=c;let data={};
  if(req.url==='/api/registration')data={registered:true};
  else if(req.url==='/api/session')data={user:{username:'qa',role:'admin'},csrf:'fixture'};
  else if(req.url==='/api/health')data=null;
  else if(req.url==='/api/config/hosts')data={name:'hosts',value:'{"hosts":{},"groups":{}}'};
  else if(req.url==='/api/config/issue')data={value:'Fixture notice'};
  else if(req.url==='/api/mcp/bootstrap-policy')data={effective:{mode:'off',generation:'',channel_url:''}};
  else if(req.url==='/api/operator/storage')data=storage;
  else if(req.url==='/api/operator/storage/job')data=storage.job;
  else if(req.url==='/api/storage')data={mounted:true,candidates:[]};
  else if(req.url==='/api/operator/storage/plan'){
   assert.equal(req.headers['x-csrf-token'],'fixture');request=JSON.parse(body);plans++;
   data={message:'Preview only. No disk has changed.',plan:{id:'a'.repeat(32),request,confirmation:'ALLOCATE /data',warning:'No automatic rollback.',details:{current_bytes:4*G,target_bytes:6*G,added_bytes:2*G,vg_remaining_bytes:10*G},steps:[{tool:'vgcfgbackup',args:['vg'],description:'Save metadata'},{tool:'lvextend',args:['--extents','1536','/dev/vg/data'],description:'Allocate free extents'},{tool:'resize2fs',args:['/dev/mapper/vg-data'],description:'Grow filesystem'}]}};
  }else if(req.url==='/api/operator/storage/apply'){
   assert.equal(req.headers['x-csrf-token'],'fixture');assert.deepEqual(JSON.parse(body),{plan_id:'a'.repeat(32),confirmation:'ALLOCATE /data'});applies++;storage.job={state:'queued',message:'Fixture operation queued.'};data={ok:true,job:storage.job};
  }
  res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(data));return;
 }
 const file=path.join(web,req.url==='/'?'index.html':req.url.split('?')[0]);
 try{res.writeHead(200,{'Content-Type':file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.svg')?'image/svg+xml':'text/html'});res.end(fs.readFileSync(file));}catch{res.writeHead(404);res.end();}
});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({headless:true});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const base='http://127.0.0.1:'+server.address().port;await page.goto(base+'/#/system/storage');
 await page.getByRole('heading',{name:'Storage',exact:true}).waitFor();
 const nav=page.getByRole('navigation',{name:'Main navigation'});
 assert.equal(await nav.locator(':scope > button').count(),3);
 assert.deepEqual(await nav.locator(':scope > button').allTextContents(),['AI Connector','MCP','System']);
 assert.equal(await nav.getByRole('button',{name:'Settings',exact:true}).count(),0);
 await page.getByRole('combobox',{name:'Capacity operation'}).selectOption('allocate');
 await page.getByRole('textbox',{name:/Additional space/}).fill('2');
 await page.getByRole('button',{name:'Preview capacity change'}).click();
 await page.getByRole('heading',{name:'Review before applying'}).waitFor();
 assert.equal(plans,1);assert.equal(applies,0);assert.equal(request.add_bytes,2*G);
 const apply=page.getByRole('button',{name:'Apply confirmed change'});assert(await apply.isDisabled());
 await page.getByRole('checkbox',{name:/current backup/}).check();assert(await apply.isDisabled());
 await page.getByRole('textbox',{name:/Type ALLOCATE/}).fill('wrong');assert(await apply.isDisabled());
 await page.getByRole('textbox',{name:/Type ALLOCATE/}).fill('ALLOCATE /data');assert(await apply.isEnabled());
 for(const [width,height] of [[1440,1000],[390,844],[844,390]]){
  await page.setViewportSize({width,height});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overflow at '+width);
  await page.screenshot({path:path.join(__dirname,'storage-'+width+'.png'),fullPage:true});
 }
 await page.setViewportSize({width:1440,height:1000});await apply.click();await page.getByText('Fixture operation queued.',{exact:true}).waitFor();assert.equal(applies,1);
 storage.job={state:'succeeded',message:'Fixture growth complete.'};await page.getByText('Fixture growth complete.',{exact:true}).waitFor();
 await nav.getByRole('button',{name:'Login notice',exact:true}).click();await page.getByRole('heading',{name:'Login notice',exact:true}).waitFor();assert(page.url().endsWith('#/system/notice'));
 await page.reload();await page.waitForFunction(()=>document.querySelector('textarea')?.value==='Fixture notice');assert.equal(await page.getByRole('textbox',{name:'Notice text'}).inputValue(),'Fixture notice');
 await page.goto(base+'/#network');await page.getByRole('heading',{name:'Network',exact:true}).waitFor();assert.equal(await nav.getByRole('button',{name:'Network',exact:true}).getAttribute('aria-current'),'page');
 await page.goto(base+'/#/mcp/settings');await page.getByRole('heading',{name:'MCP update policy',exact:true}).waitFor();
 assert.deepEqual(errors,[]);console.log(JSON.stringify({main_navigation:3,deep_links:true,legacy_routes:true,preview_without_mutation:true,typed_confirmation:true,simulated_job_progress:true,mcp_policy_separate:true,viewports:[1440,390,844],page_errors:errors}));
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1});
