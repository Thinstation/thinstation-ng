const {chromium}=require('playwright');
const {spawn}=require('child_process');
const path=require('path'),assert=require('assert'),readline=require('readline');
const web=path.resolve(__dirname,'../../../usr/share/mcp-appliance/web');
const worker=spawn('python3',[path.join(__dirname,'acme-save-fixture.py'),web],{stdio:['ignore','pipe','pipe']});
let stderr='';worker.stderr.on('data',d=>stderr+=d);
const first=new Promise((resolve,reject)=>{const rl=readline.createInterface({input:worker.stdout});rl.once('line',line=>resolve(JSON.parse(line)));worker.once('error',reject);worker.once('exit',code=>{if(code)reject(new Error(stderr))});});
(async()=>{
 const {port}=await first,base='http://127.0.0.1:'+port;
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const combo=name=>page.getByRole('combobox',{name,exact:true});
  const box=name=>page.getByRole('textbox',{name:new RegExp('^'+name)});
  const save=()=>page.getByRole('button',{name:'Save configuration',exact:true}).click();
  const observed=async()=>await (await fetch(base+'/__fixture')).json();
  const mode=async data=>await fetch(base+'/__fixture',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const waitSaved=async()=>{await page.getByText('Certificate settings saved. No certificate was requested.',{exact:true}).waitFor();await page.waitForFunction(()=>!Array.from(document.querySelectorAll('.pill')).some(e=>e.textContent==='Unsaved changes'));};
  await page.goto(base+'/#/system/certificates');
  await combo('Domain validation').selectOption('http-01');
  await box('Primary DNS name').fill('mcp');
  await save();await page.getByRole('alert').waitFor();
  assert((await page.getByRole('alert').innerText()).includes('Primary DNS name'));
  let bounds=await page.getByRole('alert').boundingBox();assert(bounds.y>=0&&bounds.y<900);
  await page.waitForTimeout(5500);assert.equal(await page.getByRole('alert').count(),1);assert.equal((await observed()).saved,null);
  assert.equal(await box('Primary DNS name').inputValue(),'mcp');
  await box('Primary DNS name').fill('mcp.example.test');
  await combo('Certificate authority').selectOption('custom');await box('CA directory address').fill('ca.example.test/directory');
  await box('Account email').fill('not-an-email');let attempts=(await observed()).counters.save_attempts;
  await save();assert((await page.getByRole('alert').innerText()).includes('Account email'));assert.equal((await observed()).counters.save_attempts,attempts);
  await box('Account email').fill('operator@example.test');
  await box('Allowed CA validation sources').fill('192.0.2.10');await page.getByLabel('I authorize temporary port-80 access').check();
  await save();await waitSaved();let stored=(await observed()).saved;
  assert.equal(stored.directory_url,'https://ca.example.test/directory');assert.deepEqual(stored.http_source_networks,['192.0.2.10/32']);assert.equal(stored.primary_domain,'mcp.example.test');
  await page.reload();await box('Primary DNS name').waitFor();assert.equal(await box('Primary DNS name').inputValue(),'mcp.example.test');assert.equal(await page.getByText('Unsaved changes',{exact:true}).count(),0);
  await combo('Domain validation').selectOption('tls-alpn-01');await box('Allowed CA validation sources').fill('192.0.2.10');await page.getByLabel('I authorize temporary port-443 access').check();await save();await waitSaved();
  assert.equal((await observed()).saved.challenge,'tls-alpn-01');assert.equal((await observed()).saved.credential,'');
  await combo('Domain validation').selectOption('dns-01');await combo('AD DNS server').selectOption('ad');await combo('Vault credential').selectOption('fixture-ad');await save();await waitSaved();
  stored=(await observed()).saved;assert.equal(stored.ad_server,'dc.example.test');assert.equal(stored.credential,'fixture-ad');assert.equal(stored.ad_realm,'EXAMPLE.TEST');
  await mode({reject_save:true});await box('Primary DNS name').fill('new.example.test');await save();await page.getByRole('alert').waitFor();assert((await page.getByRole('alert').innerText()).includes('read-only'));assert.equal((await observed()).saved.primary_domain,'mcp.example.test');
  await page.waitForTimeout(5500);assert.equal(await page.getByRole('alert').count(),1);assert.equal(await box('Primary DNS name').inputValue(),'new.example.test');
  await mode({reject_save:false});await save();await waitSaved();assert.equal((await observed()).saved.primary_domain,'new.example.test');
  await mode({fail_status:true});await box('Primary DNS name').fill('saved-without-status.example.test');await save();await waitSaved();assert.equal((await observed()).saved.primary_domain,'saved-without-status.example.test');assert.equal(await page.getByRole('alert').count(),0);
  await mode({fail_status:false,malformed_ack:true});await box('Primary DNS name').fill('unconfirmed.example.test');await save();await page.getByRole('alert').waitFor();assert((await page.getByRole('alert').innerText()).includes('valid saved configuration'));assert.equal(await page.getByText('Unsaved changes',{exact:true}).count(),1);
  await mode({malformed_ack:false});await save();await waitSaved();assert.equal((await observed()).saved.primary_domain,'unconfirmed.example.test');
  await box('Primary DNS name').fill('shortname');await save();await page.getByRole('alert').waitFor();
  for(const [width,height] of [[1440,900],[390,844],[844,390]]){
   await page.setViewportSize({width,height});await save();await page.getByRole('alert').waitFor();
   bounds=await page.getByRole('alert').boundingBox();assert(bounds.y>=0&&bounds.y<height,'visible error at '+width);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overflow '+width);
   await page.screenshot({path:path.join(__dirname,'save-feedback-'+width+'.png'),fullPage:false});
  }
  assert.deepEqual(errors,[]);assert.equal((await observed()).counters.actions,0);
  console.log(JSON.stringify({real_backend_persistence:['http-01','tls-alpn-01','dns-01'],normalized_values_clean:true,reload_persistence:true,server_error_survives_poll:true,native_validation_feedback:true,rejected_save_retains_entries:true,retry_succeeds:true,status_failure_does_not_hide_saved_config:true,malformed_ack_not_treated_as_saved:true,errors_visible_at_widths:[1440,390,844],certificate_requests:0,page_errors:errors}));
 }finally{await browser.close();worker.kill('SIGTERM')}
})().catch(e=>{console.error(e);if(stderr)console.error(stderr);worker.kill('SIGTERM');process.exitCode=1});
