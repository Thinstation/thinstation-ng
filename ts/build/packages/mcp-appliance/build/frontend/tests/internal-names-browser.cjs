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
  const combo=n=>page.getByRole('combobox',{name:n,exact:true});
  const box=n=>page.getByRole('textbox',{name:new RegExp('^'+n)});
  const observed=async()=>await(await fetch(base+'/__fixture')).json();
  async function save(){await page.getByRole('button',{name:'Save configuration',exact:true}).click();await page.getByText('Certificate settings saved. No certificate was requested.',{exact:true}).waitFor();await page.waitForFunction(()=>!Array.from(document.querySelectorAll('.pill')).some(e=>e.textContent==='Unsaved changes'));}
  await page.goto(base+'/#/system/certificates');
  await page.waitForFunction(()=>Array.from(document.querySelectorAll('input')).some(e=>e.value==='fixture.example.test'));
  assert.equal(await box('Primary DNS name').inputValue(),'fixture.example.test');
  assert.equal((await observed()).saved,null);
  await box('Primary DNS name').fill('my-appliance.example.test');
  await page.waitForTimeout(5500);assert.equal(await box('Primary DNS name').inputValue(),'my-appliance.example.test');
  await combo('Certificate authority').selectOption('internal');
  await box('CA directory address').fill('ca.example.test/directory');
  await box('Account email').fill('admin@example.test');
  await combo('Domain validation').selectOption('http-01');
  await box('Primary DNS name').fill('fixture');
  await box('Alternative DNS names').fill('fixture.example.test alias');
  await save();assert.equal((await observed()).saved.primary_domain,'fixture');assert.equal((await observed()).saved.internal_ca,true);
  await page.reload();await combo('Certificate authority').waitFor();assert.equal(await combo('Certificate authority').inputValue(),'internal');assert.equal(await box('Primary DNS name').inputValue(),'fixture');
  for(const method of ['tls-alpn-01','dns-01']){
   await combo('Domain validation').selectOption(method);
   if(method==='dns-01'){await combo('AD DNS server').selectOption('ad');await combo('Vault credential').selectOption('fixture-ad');}
   await save();assert.equal((await observed()).saved.primary_domain,'fixture');assert.equal((await observed()).saved.challenge,method);
  }
  await combo('Certificate authority').selectOption('production');await page.getByRole('button',{name:'Save configuration',exact:true}).click();await page.getByRole('alert').waitFor();
  assert.equal((await observed()).saved.internal_ca,true);assert(await page.getByRole('alert').innerText().then(t=>t.includes('internal CA')));
  await combo('Certificate authority').selectOption('internal');await box('CA directory address').fill('ca.example.test/directory');
  await box('Primary DNS name').fill('');await save();await page.reload();await combo('Domain validation').waitFor();assert.equal(await box('Primary DNS name').inputValue(),'');
  await page.getByRole('button',{name:'Use appliance FQDN',exact:true}).click();assert.equal(await box('Primary DNS name').inputValue(),'fixture.example.test');await save();
  for(const [width,height] of [[1440,1000],[390,844],[844,390]]){
   await page.setViewportSize({width,height});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overflow '+width);
   await page.screenshot({path:path.join(__dirname,'internal-names-'+width+'.png'),fullPage:true});
  }
  assert.equal((await observed()).counters.actions,0);assert.deepEqual(errors,[]);
  console.log(JSON.stringify({fqdn_seeded:true,no_automatic_save:true,edits_survive_poll:true,short_names_saved_all_methods:true,saved_short_not_overwritten:true,explicit_empty_preserved:true,restore_fqdn_button:true,public_short_rejected:true,responsive_widths:[1440,390,844],certificate_requests:0,page_errors:errors}));
 }finally{await browser.close();worker.kill('SIGTERM');}
})().catch(e=>{console.error(e);worker.kill('SIGTERM');process.exitCode=1});
