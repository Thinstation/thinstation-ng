<script>
  import { onMount, onDestroy } from 'svelte';
  import { api, json } from './lib/api.js';
  import { runtimeView, updateView, buildInfo, timeLabel } from './lib/operator-state.js';
  import './operator.css';
  export let health=null;
  export let onRefresh=()=>{};
  export let onNavigate=()=>{};
  let snapshot=null,catalog=null,error='',notice='',busy='',tab='capabilities',search='',timer,stale=false,now=Date.now()/1000;
  let loading=false;
  $: state=runtimeView(snapshot,busy,stale,now);
  $: updates=updateView(catalog,snapshot);
  $: selected=snapshot?.selected||{};
  $: runtimeGeneration=selected.bundled_generation||selected.generation||snapshot?.active;
  $: activeMeta=selected.kind==='bundled'?selected:(snapshot?.versions||[]).find(v=>v.generation===runtimeGeneration)||{};
  $: version=buildInfo(runtimeGeneration,activeMeta).label;
  $: sourceLabel=selected.kind==='bundled'?'Bundled ISO':selected.kind==='recovery'?'Minimal rescue':selected.slot==='previous'?'Previous upgrade':'Active upgrade';
  $: serviceName=snapshot?.probe?.server_name||(catalog?.mcps||[]).find(r=>r.generation===runtimeGeneration)?.name||'MCP service';
  $: tools=snapshot?.probe?.tools||[];
  $: filtered=tools.filter(t=>(t.name+' '+t.description).toLowerCase().includes(search.toLowerCase()));
  $: recovery=selected.kind==='recovery';
  async function refreshRuntime(){
    if(loading)return;loading=true;
    try{snapshot=await api('/api/operator/runtime');stale=false;now=Date.now()/1000}catch(e){stale=true;error=e.message}finally{loading=false}
  }
  async function loadCatalog(){
    try{catalog=await api('/api/mcp/catalog')}catch(e){catalog={available:false,error:e.message}}
  }
  async function check(){
    if(busy)return;busy='probe';error='';
    try{await json('/api/operator/probe','POST',{});await refreshRuntime()}catch(e){error=e.message}finally{busy=''}
  }
  async function control(action){
    if(busy)return;
    if(action==='stop'&&!confirm('Stop this MCP? AI applications will not be able to use its tools until it is started again.'))return;
    busy='runtime:'+action;error='';notice='';
    try{await json('/api/mcp/'+action,'POST',{});notice=action==='stop'?'MCP stopped.':action==='start'?'Start requested.':'Restart requested.';await refreshRuntime();await onRefresh()}catch(e){error=e.message}finally{busy=''}
  }
  async function install(row,start=false){
    if(busy)return;busy='install:'+row.generation;error='';notice='';
    try{
      await json('/api/mcp/catalog/install','POST',{generation:row.generation});
      notice=buildInfo(row.generation,row).label+' downloaded and installed.';
      if(start){await json('/api/mcp-generation/activate','POST',{generation:row.generation});notice+=' Selected and start requested.'}
      await refreshRuntime();await onRefresh();
    }catch(e){error=e.message;await refreshRuntime()}finally{busy=''}
  }
  async function useVersion(gen){
    if(busy)return;
    if(!confirm('Use '+buildInfo(gen).label+'? The MCP will restart and active calls may be interrupted.'))return;
    busy='activate:'+gen;error='';notice='';
    try{await json('/api/mcp-generation/activate','POST',{generation:gen});notice=buildInfo(gen).label+' selected. Check the runtime before resuming work.';await refreshRuntime();await onRefresh()}catch(e){error=e.message}finally{busy=''}
  }
  async function rollback(){
    if(busy||!confirm('Roll back to the previous version and restart the MCP?'))return;
    busy='rollback';error='';
    try{await json('/api/mcp-generation/rollback','POST',{});notice='Previous version selected.';await refreshRuntime();await onRefresh()}catch(e){error=e.message}finally{busy=''}
  }
  onMount(()=>{refreshRuntime();loadCatalog();timer=setInterval(()=>{now=Date.now()/1000;refreshRuntime()},15000)});
  onDestroy(()=>clearInterval(timer));
</script>

<div class="page operator-page">
  <div class="page-title"><div><h1>MCP</h1><p>Capabilities, runtime health, and software updates.</p></div><button class="btn" disabled={!!busy} on:click={()=>{error='';refreshRuntime();loadCatalog()}}>Refresh</button></div>
  {#if error}<div class="notice warn" role="alert">{error}</div>{/if}
  {#if notice}<div class="notice" role="status">{notice}</div>{/if}
  <section class="panel operator-hero">
    <div class="operator-hero-head"><div><div class="operator-eyebrow">MCP service</div><h2>{serviceName}</h2><p>Tools available to your authorized AI applications.</p></div><span class="pill operator-status" class:good={state.tone==='good'} class:bad={state.tone==='bad'}>{state.label}</span></div>
    <p class="operator-caption" aria-live="polite">{state.detail}</p>
    <div class="operator-facts"><div><span>Selected runtime</span><strong>{version} · {sourceLabel}</strong></div><div><span>Updates</span><strong class:warn={updates.tone==='warn'}>{updates.label}</strong></div><div><span>Last local protocol check</span><strong>{timeLabel(snapshot?.probe?.checked_at)}</strong></div></div>
    {#if selected.kind==='bundled'}<div class="notice">The full MCP bundled with this ISO is selected. {snapshot?.active?'Configured upgrade: '+buildInfo(snapshot.active).label+'. Its persistent files are unchanged.':'Persistent upgrades are optional.'}</div>{/if}
    {#if recovery}<div class="notice warn">Minimal rescue is selected, not the full MCP server. Inspect Diagnostics for the unavailable runtimes.</div>{/if}
    <div class="actions"><button class="btn primary" on:click={()=>onNavigate('connections')}>Connect an AI application</button><button class="btn" disabled={!!busy||!snapshot||stale} on:click={check}>{busy==='probe'?'Checking…':'Test MCP response'}</button><button class="btn" disabled={!state.start} on:click={()=>control('start')}>Start</button><button class="btn" disabled={!state.restart} on:click={()=>control('restart')}>Restart</button><button class="btn" disabled={!state.stop} on:click={()=>control('stop')}>Stop</button></div>
  </section>

  <nav class="operator-tabs" aria-label="MCP sections"><button class:active={tab==='capabilities'} aria-pressed={tab==='capabilities'} on:click={()=>tab='capabilities'}>Capabilities</button><button class:active={tab==='updates'} aria-pressed={tab==='updates'} on:click={()=>tab='updates'}>Updates &amp; versions</button><button class:active={tab==='details'} aria-pressed={tab==='details'} on:click={()=>tab='details'}>Diagnostics</button></nav>

  {#if tab==='capabilities'}
    <div class="operator-secondary-grid">
      <section class="panel"><div class="panel-head"><h2>Configured targets</h2></div><div class="panel-body stack"><p>{snapshot?`${snapshot.host_count} hosts in ${snapshot.group_count} groups`:'Checking inventory…'}</p>{#if snapshot?.host_count===0}<p class="muted">No managed hosts are configured. Host-based operations need an inventory target.</p>{/if}<button class="btn" on:click={()=>onNavigate('hosts')}>Open inventory</button></div></section>
      <section class="panel"><div class="panel-head"><h2>Target credentials</h2></div><div class="panel-body stack"><p>{snapshot?`${snapshot.credential_count} stored credentials`:'Checking credentials…'}</p><p class="muted">{!snapshot?.vault_available?'Vault status is unavailable.':snapshot?.vault_locked?'Vault is locked. Operations using protected credentials require appropriate authorization.':'Vault is unlocked. Review the active authorization window in Credentials.'}</p><button class="btn" on:click={()=>onNavigate('credentials')}>Open credentials</button></div></section>
    </div>
    <section class="panel"><div class="panel-head"><h2>Tools advertised by this MCP</h2><span class="spacer"></span>{#if tools.length}<span class="muted">{tools.length}{snapshot?.probe?.tools_truncated?'+':''} tools</span>{/if}</div><div class="panel-body stack">
      <p class="muted">Discovery shows what the service advertises, not what a particular task is authorized or configured to do. No tool is executed by this page.</p>
      {#if snapshot?.probe?.error}<div class="notice warn">{snapshot.probe.error}</div>{/if}
      {#if !snapshot?.probe}<div class="operator-empty"><p>Check the MCP response to discover its current capabilities.</p><button class="btn" disabled={!!busy||!snapshot||stale} on:click={check}>Discover capabilities</button></div>
      {:else if tools.length}<label class="field"><span>Find a tool</span><input type="search" bind:value={search} placeholder="Search tool names and descriptions"/></label><div class="operator-tools">{#each filtered as tool}<details><summary>{tool.name}</summary><p>{tool.description||'No description provided by the MCP.'}</p></details>{/each}</div>{#if !filtered.length}<p>No matching tools.</p>{/if}
      {:else}<p>No tools were returned by the last check.</p>{/if}
    </div></section>
  {:else if tab==='updates'}
    <section class="panel"><div class="panel-head"><h2>Software updates</h2><span class="spacer"></span><button class="btn small" disabled={!!busy} on:click={loadCatalog}>Check for updates</button></div><div class="panel-body stack"><strong>{updates.label}</strong>{#if updates.detail}<p class="muted">{updates.detail}</p>{/if}{#if catalog?.error}<div class="notice warn">{catalog.error}</div>{/if}
      {#if updates.target}<div class="operator-callout"><strong>{buildInfo(updates.target.generation,updates.target).label}</strong><p>{updates.target.description||'A newer build is listed for this MCP.'}</p><button class="btn primary" disabled={!!busy} on:click={()=>updates.installed?useVersion(updates.target.generation):install(updates.target)}>{updates.installed?'Apply update':busy?'Working…':'Download update'}</button></div>{/if}
      <details open={!snapshot?.active}><summary>{snapshot?.active?'Browse available releases':'Choose an MCP upgrade'}</summary><div class="operator-release-list">{#each catalog?.mcps||[] as row}{@const installed=snapshot?.versions?.some(v=>v.generation===row.generation)}<article><div><h3>{row.name}</h3><p>{row.description||'No release description supplied.'}</p><strong>{buildInfo(row.generation,row).label}</strong></div><div class="actions">{#if row.generation===snapshot?.active}<span class="pill">Configured upgrade</span>{:else if installed}<button class="btn" disabled={!!busy} on:click={()=>useVersion(row.generation)}>Use this version</button>{:else}<button class="btn" disabled={!!busy} on:click={()=>install(row,!snapshot?.active)}>{busy==='install:'+row.generation?'Installing…':snapshot?.active?'Download':'Install and start'}</button>{/if}</div></article>{/each}{#if catalog?.available&&!catalog.mcps?.length}<p>No releases are listed.</p>{/if}</div></details>
      <details><summary>Update source</summary><p class="mono operator-wrap">{catalog?.url||'Not configured'}</p><button class="btn" on:click={()=>onNavigate('mcp/settings')}>Update settings</button></details>
    </div></section>
    <section class="panel"><div class="panel-head"><h2>Version history</h2></div><div class="panel-body operator-release-list">{#each snapshot?.versions||[] as v}<article><div><h3>{v.version}</h3><p class="muted">{v.generation===snapshot?.active?'Configured upgrade':v.generation===snapshot?.previous?'Previous version · rollback target':'Installed, not selected'}</p></div>{#if v.generation!==snapshot?.active}<button class="btn" disabled={!!busy} on:click={()=>useVersion(v.generation)}>Use this version</button>{/if}</article>{/each}{#if !snapshot?.versions?.length}<p class="muted">No persistent MCP version is installed.</p>{/if}{#if snapshot?.previous}<button class="btn" disabled={!!busy} on:click={rollback}>Roll back to {buildInfo(snapshot.previous).label}</button>{/if}</div></section>
  {:else}
    <section class="panel"><div class="panel-head"><h2>Runtime evidence</h2></div><div class="panel-body stack"><p>Selected software, service state, and protocol response are checked separately. A successful local handshake does not verify an AI application's network path or an individual tool operation.</p><dl class="operator-details"><dt>Runtime source</dt><dd>{sourceLabel}</dd><dt>Configured upgrade</dt><dd>{snapshot?.active||'None'}</dd><dt>Service state</dt><dd>{snapshot?.service||'Unknown'}</dd><dt>Runtime observation</dt><dd class="mono">{snapshot?.runtime||'No observation'}</dd><dt>Last state refresh</dt><dd>{timeLabel(snapshot?.timestamp)}</dd><dt>Protocol check</dt><dd>{snapshot?.probe?.message||'Not checked'}{snapshot?.probe?.error?' '+snapshot.probe.error:''}</dd><dt>Source commit</dt><dd class="mono">{activeMeta.source_sha||'Not recorded'}</dd></dl>{#if snapshot?.quarantined?.length}<div class="notice warn">Blocked persistent versions: {snapshot.quarantined.join(', ')}</div>{/if}<button class="btn" on:click={()=>onNavigate('connections')}>View AI access activity</button></div></section>
  {/if}
</div>
