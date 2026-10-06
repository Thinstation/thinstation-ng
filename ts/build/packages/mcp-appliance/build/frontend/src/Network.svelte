<script>
  import { api, json } from './lib/api.js';
  export let health=null;
  let config=null, selected='', result='', busy=false;
  let hostname='', autoconnect=true;
  let v4={method:'auto',addresses:'',gateway:'',dns:'',search:'',routes:''};
  let v6={method:'auto',addresses:'',gateway:'',dns:'',search:'',routes:''};
  const lines=v=>String(v||'').split(/[\n,;]+/).map(x=>x.trim()).filter(Boolean);
  async function load(){
    try{
      config=await api('/api/network/config'); hostname=config.hostname||'';
      if(!selected||!config.connections.some(c=>c.uuid===selected)) selected=config.connections.find(c=>c.active)?.uuid||config.connections[0]?.uuid||'';
      choose();
    }catch(e){result=e.message}
  }
  function choose(){
    const c=config?.connections?.find(x=>x.uuid===selected); if(!c)return;
    autoconnect=!!c.autoconnect;
    for(const [target,src] of [[v4,c.ipv4||{}],[v6,c.ipv6||{}]]){
      target.method=src.method||'auto'; target.addresses=(src.addresses||[]).join('\n'); target.gateway=src.gateway||''; target.dns=(src.dns||[]).join(', '); target.search=(src.dns_search||[]).join(', '); target.routes=(src.routes||[]).join('\n');
    }
    v4={...v4};v6={...v6};
  }
  async function save(apply){
    const c=config?.connections?.find(x=>x.uuid===selected); if(!c)return; busy=true;result='';
    const body={uuid:c.uuid,hostname:hostname.trim(),autoconnect,
      ipv4:{method:v4.method,addresses:lines(v4.addresses),gateway:v4.gateway.trim(),dns:lines(v4.dns),dns_search:lines(v4.search),routes:lines(v4.routes)},
      ipv6:{method:v6.method,addresses:lines(v6.addresses),gateway:v6.gateway.trim(),dns:lines(v6.dns),dns_search:lines(v6.search),routes:lines(v6.routes)}};
    let checkpoint=null;
    try{
      if(apply){ result='Creating 90-second rollback checkpoint…'; checkpoint=await json('/api/network/checkpoint','POST',{uuid:c.uuid,seconds:90}); }
      result='Saving configuration…'; await json('/api/network/config','POST',body);
      if(!apply){ result='Configuration saved. Changes are not active yet.'; await load(); return; }
      result='Applying connection. Automatic rollback is armed…'; await json('/api/network/activate','POST',{uuid:c.uuid});
      let ok=false; for(let i=0;i<12;i++){ await new Promise(r=>setTimeout(r,1500)); try{await api('/api/session');ok=true;break}catch{} }
      if(!ok) throw new Error('Management connection was not confirmed. Previous network profile will be restored automatically.');
      await json('/api/network/confirm','POST',{token:checkpoint.token}); result='Connection applied and confirmed. Rollback checkpoint removed.'; await load();
    }catch(e){result=e.message} finally{busy=false}
  }
  $: if(!config) load();
</script>
<div class="page">
  <div class="page-title"><div><h1>Network</h1><p>Interfaces, addressing, DNS and routes</p></div><button class="btn" on:click={load}>Refresh</button></div>
  {#if health}
    <div class="notice" style="margin-bottom:1rem"><strong>Live state:</strong> {health.network.default_route?health.network.default_route.dev+' via '+(health.network.default_route.gateway||'direct'):'no default route'} · {(health.network.interfaces||[]).flatMap(x=>x.addresses||[]).join(', ')||'no addresses'} · DNS {(health.network.dns||[]).join(', ')||'none'}</div>
  {/if}
  <section class="panel">
    <div class="panel-head"><h2>Connection profile</h2><span class="spacer"></span>{#if config}<select style="max-width:420px" bind:value={selected} on:change={choose}>{#each config.connections as c}<option value={c.uuid}>{c.name}{c.device?' · '+c.device:''}{c.active?' · active':''}</option>{/each}</select>{/if}</div>
    <div class="panel-body stack">
      <div class="form-grid">
        <label class="field"><span>Hostname</span><input bind:value={hostname}/></label>
        <label style="align-self:end;padding:.55rem 0"><input type="checkbox" bind:checked={autoconnect}/> Connect automatically</label>
      </div>
      <div class="two-col">
        {#each [[4,v4],[6,v6]] as pair}
          <div class="panel" style="box-shadow:none">
            <div class="panel-head"><h3>IPv{pair[0]}</h3></div><div class="panel-body stack">
              <label class="field"><span>Method</span><select bind:value={pair[1].method}><option value="auto">Automatic</option><option value="manual">Manual</option><option value="disabled">Disabled</option></select></label>
              <label class="field"><span>Addresses / prefix</span><textarea bind:value={pair[1].addresses} disabled={pair[1].method!=='manual'} placeholder={pair[0]===4?'192.0.2.10/24':'2001:db8::10/64'}></textarea></label>
              <label class="field"><span>Gateway</span><input bind:value={pair[1].gateway} disabled={pair[1].method!=='manual'}/></label>
              <label class="field"><span>DNS servers</span><input bind:value={pair[1].dns}/></label>
              <label class="field"><span>Search domains</span><input bind:value={pair[1].search}/></label>
              <label class="field"><span>Routes</span><textarea bind:value={pair[1].routes}></textarea></label>
            </div>
          </div>
        {/each}
      </div>
      <div class="actions"><button class="btn" disabled={busy} on:click={()=>save(false)}>Save configuration</button><button class="btn primary" disabled={busy} on:click={()=>save(true)}>Save & apply now</button><span class="muted">Apply uses a timed rollback checkpoint to prevent remote lockout.</span></div>
      {#if result}<div class="notice" class:warn={result.toLowerCase().includes('rollback')||result.toLowerCase().includes('error')}>{result}</div>{/if}
    </div>
  </section>
</div>
