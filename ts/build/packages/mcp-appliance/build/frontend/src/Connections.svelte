<script>
  import { onMount, onDestroy } from 'svelte';
  import { api, json } from './lib/api.js';
  import { connectionView, timeLabel } from './lib/operator-state.js';
  import ChatgptConnection from './ChatgptConnection.svelte';
  import './operator.css';
  export let health=null;
  export let onNavigate=()=>{};
  let data=null, error='', notice='', busy='', wizard=false, name='', application='vscode', method='direct';
  let acknowledge=false, issued=null, reveal=false, sharedToken='', selected=null, timer;
  let probe=null, showRevoked=false, loading=false;
  const applications=[['vscode','VS Code'],['cursor','Cursor'],['local-agent','Local or self-hosted agent'],['generic','Other MCP client'],['chatgpt','ChatGPT'],['cloud','Other hosted AI application']];
  const appLabel=value=>applications.find(a=>a[0]===value)?.[1]||value;
  $: remote=application==='chatgpt'||application==='cloud'||method!=='direct';
  $: rows=(data?.clients||[]).filter(c=>showRevoked||!c.revoked_at);
  $: current=(data?.clients||[]).find(c=>c.id===selected);
  $: endpoint=data?.url||'';
  $: configuration=JSON.stringify({inputs:[{id:'mcp-token',type:'promptString',description:'ThinStation MCP access token',password:true}],servers:{thinstation:{type:'http',url:endpoint,headers:{Authorization:'Bearer ${input:mcp-token}'}}}},null,2);
  async function load(){if(loading)return;loading=true;try{data=await api('/api/operator/connections')}catch(e){error=e.message}finally{loading=false}}
  function begin(){wizard=true;issued=null;reveal=false;acknowledge=false;name='';application='vscode';method='direct';error='';notice=''}
  function close(){if(issued&&!confirm('Have you saved the new token? It cannot be displayed again.'))return;wizard=false;issued=null;reveal=false}
  async function copy(value,label){try{await navigator.clipboard.writeText(value);notice=label+' copied.'}catch{error='Clipboard access was denied. Select and copy the field manually.'}}
  async function create(){
    if(busy||remote)return;busy='create';error='';
    try{issued=await json('/api/operator/connections/create','POST',{name:name.trim(),application,method:'direct',confirm_full_access:acknowledge});selected=issued.connection.id;await load()}
    catch(e){error=e.message}finally{busy=''}
  }
  async function revoke(row){
    if(!confirm('Revoke access for '+row.name+'? New requests will be blocked; an in-flight request may finish.'))return;
    busy='revoke';error='';try{await json('/api/operator/connections/revoke','POST',{id:row.id});notice='Access revoked for '+row.name+'.';await load()}catch(e){error=e.message}finally{busy=''}
  }
  async function check(){busy='check';error='';try{probe=await json('/api/operator/probe','POST',{})}catch(e){error=e.message}finally{busy=''}}
  async function revealShared(){busy='shared';error='';try{sharedToken=(await json('/api/operator/shared-token','POST',{})).token||''}catch(e){error=e.message}finally{busy=''}}
  async function rotateShared(){
    if(!confirm('Replace the shared appliance token? Every client using that shared token must be reconfigured. Named client tokens are unaffected.'))return;
    busy='rotate';error='';try{await api('/api/connections/token/rotate',{method:'POST'});sharedToken='';notice='Shared token replaced. Update clients that used it.';await load()}catch(e){error=e.message}finally{busy=''}
  }
  onMount(()=>{load();timer=setInterval(load,15000)});
  onDestroy(()=>{clearInterval(timer);issued=null;sharedToken=''});
</script>

<div class="page operator-page">
  <div class="page-title"><div><h1>AI Connector</h1><p>Choose which applications may use this MCP.</p></div><div class="actions"><button class="btn" disabled={!!busy} on:click={()=>{error='';load()}}>Refresh</button><button class="btn primary" disabled={!data||!!busy||wizard} on:click={begin}>Connect an AI application</button></div></div>
  {#if error}<div class="notice warn" role="alert">{error}</div>{/if}
  {#if notice}<div class="notice" role="status">{notice}</div>{/if}
  {#if !(wizard&&application==='chatgpt')}<ChatgptConnection/>{/if}
  {#if wizard}
    <section class="panel operator-setup">
      <div class="panel-head"><h2>{issued?'Finish application setup':'Connect an AI application'}</h2><span class="spacer"></span><button class="btn small" disabled={!!busy} on:click={close}>Close</button></div>
      <div class="panel-body stack">
        {#if !issued}
          <label class="field"><span>AI application</span><select bind:value={application}>{#each applications as app}<option value={app[0]}>{app[1]}</option>{/each}</select></label>
          {#if application==='chatgpt'}
            <ChatgptConnection openSetup={true}/>
          {:else}
            <div class="form-grid"><label class="field"><span>Connection name</span><input bind:value={name} maxlength="100" placeholder="Development workstation"/></label><label class="field wide"><span>Where will the MCP client connect from?</span><select bind:value={method}><option value="direct">A device or agent that can reach this appliance</option><option value="remote">A hosted service outside this network</option></select></label></div>
            {#if remote}
              <div class="notice warn"><strong>A remote access path is required.</strong><p>This hosted application needs its own supported private relay or suitable public HTTPS endpoint. The ChatGPT integration is available separately; it does not configure other vendors.</p><p>No tunnel, public listener, or client token will be created by this selection.</p></div>
            {:else}
              <div class="operator-callout"><strong>Direct network access</strong><p>The calling application must reach this address and trust the appliance certificate. A local browser opening this page does not prove that another application can connect.</p><div class="mono operator-wrap">{endpoint}</div></div>
              <div class="operator-callout"><strong>Access granted</strong><p>All tools exposed by the active MCP. Target-system credentials and vault restrictions still apply. Per-connection host filters, read-only permissions, and approval policies are not enforced by this gateway yet.</p><button class="btn small" on:click={()=>onNavigate('mcp')}>Review MCP capabilities</button></div>
              <label class="operator-check"><input type="checkbox" bind:checked={acknowledge}/><span>I trust this application with the access described above.</span></label>
              <div class="actions"><button class="btn primary" disabled={!!busy||!name.trim()||!acknowledge} on:click={create}>{busy==='create'?'Creating access…':'Create client access'}</button></div>
            {/if}
          {/if}
        {:else}
          <div class="operator-callout"><strong>{issued.connection.name}: access created</strong><p>Copy this token now. It is shown once, stored only as a hash, and can be revoked without affecting other named clients.</p></div>
          <div class="field"><label for="operator-endpoint">MCP URL</label><div class="copy-row"><input id="operator-endpoint" class="mono" value={endpoint} readonly/><button class="btn" on:click={()=>copy(endpoint,'MCP URL')}>Copy</button></div></div>
          <div class="field"><label for="operator-token">Client access token</label><div class="copy-row"><input id="operator-token" class="mono" type={reveal?'text':'password'} value={issued.token} readonly autocomplete="off"/><button class="btn" on:click={()=>copy(issued.token,'Client token')}>Copy token</button></div></div>
          <button class="btn small" on:click={()=>reveal=!reveal}>{reveal?'Hide token':'Show token'}</button>
          {#if application==='vscode'}<details open><summary>VS Code configuration</summary><p>Use this in your MCP configuration. The token is requested as a secret input rather than saved in the configuration.</p><pre class="code operator-code">{configuration}</pre><button class="btn" on:click={()=>copy(configuration,'Configuration')}>Copy configuration</button></details>
          {:else}<div class="operator-callout"><strong>Configure your application</strong><p>Choose Streamable HTTP, use the MCP URL above, and configure HTTP bearer authentication with the client access token. Do not put the token in the URL.</p></div>{/if}
          <div class="notice"><strong>{connectionView(current||issued.connection).label}</strong><p>{connectionView(current||issued.connection).detail}</p><p>Connect from the application, then refresh this page. A local MCP check does not prove client reachability.</p></div>
          <div class="actions"><button class="btn" on:click={load}>Check for client request</button><button class="btn primary" on:click={close}>Done</button></div>
        {/if}
      </div>
    </section>
  {/if}
  <section class="panel">
    <div class="panel-head"><h2>Applications with direct access</h2><span class="spacer"></span><label class="operator-check compact"><input type="checkbox" bind:checked={showRevoked}/><span>Show revoked</span></label></div>
    {#if !data}<div class="empty">{error?'Connection state is unavailable.':'Loading application access…'}</div>
    {:else if !rows.length}<div class="empty operator-empty"><strong>No named direct-client access yet</strong><p>Create separate access for each direct application so it can be identified and revoked independently. ChatGPT tunnel access above and existing shared-token clients are managed separately.</p></div>
    {:else}<div class="operator-connections">{#each rows as row (row.id)}{@const state=connectionView(row)}<article class="operator-connection"><div><h3>{row.name}</h3><p class="muted">{appLabel(row.application)} · Direct network</p><span class="pill" class:good={state.tone==='good'} class:warn={state.tone==='warn'}>{state.label}</span><p class="operator-caption">Last gateway request: {timeLabel(row.last_request_at)}</p></div><div class="actions"><button class="btn" on:click={()=>selected=selected===row.id?null:row.id}>{selected===row.id?'Close details':'Details'}</button>{#if !row.revoked_at}<button class="btn danger" disabled={!!busy} on:click={()=>revoke(row)}>Revoke access</button>{/if}</div>{#if selected===row.id}<div class="operator-connection-detail"><p>{state.detail}</p><p><strong>Access:</strong> {data.permissions}</p><div class="copy-row"><input class="mono" value={endpoint} readonly aria-label="MCP URL"/><button class="btn" on:click={()=>copy(endpoint,'MCP URL')}>Copy URL</button></div><p class="operator-caption">Created {timeLabel(row.created)}. Tokens cannot be displayed again. Revoke and create new access to replace a lost token.</p></div>{/if}</article>{/each}</div>{/if}
  </section>
  <div class="operator-secondary-grid">
    <section class="panel"><div class="panel-head"><h2>Local service check</h2></div><div class="panel-body stack"><p>Check that the appliance's MCP answers a protocol handshake. This does not call any tools.</p><button class="btn" disabled={!!busy||!data} on:click={check}>{busy==='check'?'Checking…':'Test local MCP'}</button>{#if probe}<div class="notice" class:warn={!probe.responding}><strong>{probe.responding?'MCP responds locally':'Local MCP check failed'}</strong><p>{probe.error||probe.message}</p><div class="operator-caption">{probe.scope} Checked {timeLabel(probe.checked_at)}.</div></div>{/if}</div></section>
    <section class="panel"><div class="panel-head"><h2>Existing shared access</h2></div><div class="panel-body stack"><p>Legacy clients may use the shared appliance token. They cannot be distinguished or revoked individually.</p><details><summary>Shared access settings</summary><div class="stack operator-inset"><p>Replacing this token affects every legacy client using it. Named client tokens and the ChatGPT tunnel are independent.</p>{#if sharedToken}<label class="field"><span>Shared token</span><input type="password" value={sharedToken} readonly autocomplete="off"/></label><div class="actions"><button class="btn" on:click={()=>copy(sharedToken,'Shared token')}>Copy token</button><button class="btn" on:click={()=>sharedToken=''}>Hide</button></div>{:else}<button class="btn" disabled={!!busy||!data} on:click={revealShared}>Access shared token</button>{/if}<button class="btn danger" disabled={!!busy||!data} on:click={rotateShared}>Replace shared token</button></div></details></div></section>
  </div>
  <section class="panel"><div class="panel-head"><h2>Recent access activity</h2></div><div class="panel-body">{#if data?.events?.length}<div class="operator-events">{#each data.events as event}<div><time>{timeLabel(event.time)}</time><strong>{event.name}</strong><span>{event.detail}</span></div>{/each}</div>{:else}<p class="muted">No access activity has been recorded. This view does not contain tool arguments, results, or credential material.</p>{/if}</div></section>
</div>
