<script>
  import { onMount, onDestroy } from 'svelte';
  import { api, json } from './lib/api.js';
  export let openSetup=false;
  let state=null, error='', notice='', busy='', editing=false, loading=false, timer;
  let name='ChatGPT', tunnelId='', organizationId='', apiKey='', dedicated=false, consent=false, localProbe=null;
  $: connection=state?.connection;
  $: running=['active','activating','deactivating'].includes(state?.service);
  const stamp=value=>{if(!value)return 'Not yet observed';const date=new Date(value);return Number.isNaN(date.valueOf())?'Unknown':date.toLocaleString()};
  async function refresh(){
    if(loading)return;loading=true;
    try{state=await api('/api/operator/openai')}catch(e){error=e.message}finally{loading=false}
  }
  function edit(){
    name=state?.profile?.name||'ChatGPT';tunnelId=state?.profile?.tunnel_id||'';organizationId=state?.profile?.organization_id||'';
    apiKey='';dedicated=false;consent=false;error='';notice='';editing=true;
  }
  function cancel(){apiKey='';editing=false;error=''}
  async function save(){
    if(busy)return;busy='save';error='';notice='';
    const body={name:name.trim(),tunnel_id:tunnelId.trim(),organization_id:organizationId.trim(),api_key:apiKey.trim(),confirm_dedicated_tunnel:dedicated,confirm_full_access:consent};apiKey='';
    try{const result=await json('/api/operator/openai/save','POST',body);state=result.status;editing=false;notice='Connection saved. Select Connect below when ready.'}
    catch(e){error=e.message}finally{body.api_key='';busy=''}
  }
  async function act(action){
    if(busy)return;
    if(action==='disconnect'&&!confirm('Disconnect this appliance from OpenAI? Requests through this tunnel will fail until you reconnect. The local MCP and other connections will keep running.'))return;
    busy=action;error='';notice='';
    try{
      if(action!=='disconnect'&&!state?.runtime_installed){busy='install';await json('/api/operator/openai/install','POST',{});busy=action}
      const result=await json('/api/operator/openai/action','POST',{action});state=result.status;
      notice=action==='disconnect'?'Appliance tunnel disconnected.': 'Tunnel service started. Waiting for verified OpenAI connectivity.';
    }catch(e){error=e.message;await refresh()}finally{busy=''}
  }
  async function check(){busy='probe';error='';try{localProbe=await json('/api/operator/probe','POST',{});await refresh()}catch(e){error=e.message}finally{busy=''}}
  async function copyTunnel(){try{await navigator.clipboard.writeText(state.profile.tunnel_id);notice='Tunnel ID copied.'}catch{error='Select and copy the tunnel ID manually.'}}
  onMount(async()=>{await refresh();if(openSetup)edit();timer=setInterval(refresh,5000)});
  onDestroy(()=>{clearInterval(timer);apiKey=''});
</script>

<section class="panel operator-chatgpt" aria-label="ChatGPT connection">
  <div class="panel-head"><h2>{state?.profile?.name||'ChatGPT'}</h2><span class="spacer"></span><span class="pill" class:good={connection?.tone==='good'} class:warn={connection?.tone==='warn'}>{!state?'Checking':!state.configured?'Not set up':connection?.label||'Status unavailable'}</span></div>
  <div class="panel-body stack">
    {#if error}<div class="notice warn" role="alert">{error}</div>{/if}
    {#if notice}<div class="notice" role="status">{notice}</div>{/if}
    {#if !state}
      <p class="muted">{error?'ChatGPT connection settings are unavailable.':'Loading ChatGPT connection settings…'}</p><button class="btn" disabled={loading} on:click={refresh}>Refresh</button>
    {:else if editing}
      <div class="operator-callout"><strong>1. Create a dedicated tunnel in OpenAI</strong><p>In OpenAI Platform tunnel settings, create a tunnel for this appliance, associate the intended ChatGPT workspace, and obtain a runtime API key with tunnel Use permission. Your ChatGPT workspace must allow developer-mode apps.</p><p><a href="https://developers.openai.com/api/docs/guides/secure-mcp-tunnels" target="_blank" rel="noopener noreferrer">Open official tunnel setup instructions</a></p><p>Do not reuse the tunnel currently serving another MCP. Two clients polling the same tunnel could receive each other's requests.</p></div>
      <strong>2. Paste the connection details</strong>
      <div class="form-grid">
        <label class="field"><span>Connection name</span><input bind:value={name} maxlength="100" autocomplete="off" placeholder="ChatGPT workspace"/></label>
        <label class="field wide"><span>OpenAI tunnel ID or tunnel URL</span><input class="mono" bind:value={tunnelId} maxlength="512" autocomplete="off" placeholder="tunnel_…"/><small>A URL is accepted only when it contains a tunnel ID. An OAuth callback URL is not a tunnel identifier.</small></label>
        <label class="field wide"><span>Runtime API key</span><input type="password" bind:value={apiKey} maxlength="1024" autocomplete="new-password" placeholder={state.credential_saved?'Leave blank to keep the saved key':'Paste the runtime API key'}/><small>Write-only. Encrypted with this appliance's TPM and supplied to the tunnel through systemd credentials. Not stored in browser configuration.</small></label>
      </div>
      <details><summary>Organization setting</summary><label class="field operator-inset"><span>OpenAI organization ID (optional)</span><input class="mono" bind:value={organizationId} placeholder="org-…" autocomplete="off"/><small>Use when OpenAI requires an explicit organization for the runtime key.</small></label></details>
      <div class="operator-callout"><strong>Access and data flow</strong><p>ChatGPT will be able to request all tools exposed by this MCP. Existing target credentials and vault restrictions still apply; there are no separate tool or host restrictions for this tunnel yet.</p><p>The local MCP target is filled in automatically. No public inbound port is opened. Tool requests and results pass through OpenAI; a private tunnel does not keep returned data inside your LAN.</p></div>
      {#if !state.tpm_available}<div class="notice warn">This connection requires a TPM 2.0 device to protect its runtime key. Attach one before saving a new key.</div>{/if}
      {#if state.enabled||running}<div class="notice warn">Disconnect this appliance tunnel before editing its settings.</div>{/if}
      <label class="operator-check"><input type="checkbox" bind:checked={dedicated}/><span>This tunnel is dedicated to this appliance, not the existing ThinStation CLI connection.</span></label>
      <label class="operator-check"><input type="checkbox" bind:checked={consent}/><span>I authorize the intended OpenAI workspace to use the MCP access described above.</span></label>
      <div class="actions"><button class="btn primary" disabled={!!busy||running||state.enabled||!name.trim()||!tunnelId.trim()||!dedicated||!consent||(!state.credential_saved&&!apiKey.trim())||(!state.tpm_available&&!!apiKey)} on:click={save}>{busy==='save'?'Protecting and saving…':'Save connection'}</button><button class="btn" disabled={!!busy} on:click={cancel}>Cancel</button></div>
    {:else if !state.configured}
      <p>Connect this appliance to ChatGPT with an outbound private tunnel. Supply the tunnel ID and runtime API key; the appliance manages the local target and connection service.</p>
      <div class="actions"><button class="btn primary" disabled={!!busy} on:click={edit}>Set up ChatGPT</button></div>
    {:else}
      <p>{connection?.detail}</p>
      <div class="detail-grid">
        <div class="detail-item"><div class="k">OpenAI tunnel</div><div class="v mono operator-wrap">{state.profile.tunnel_id}</div></div>
        <div class="detail-item"><div class="k">Last authenticated OpenAI poll</div><div class="v">{stamp(connection?.last_poll_success)}</div></div>
        <div class="detail-item"><div class="k">Last request received through tunnel</div><div class="v">{stamp(connection?.last_request)}</div></div>
        <div class="detail-item"><div class="k">Last response accepted by OpenAI</div><div class="v">{stamp(connection?.last_response_accepted)}</div></div>
      </div>
      <div class="actions">
        <button class="btn primary" disabled={!!busy||running||state.enabled} on:click={()=>act('connect')}>{busy==='install'?'Installing connection component…':busy==='connect'?'Connecting…':state.runtime_installed?'Connect':'Install component and connect'}</button>
        <button class="btn" disabled={!!busy||(!running&&!state.enabled)} on:click={()=>act('reconnect')}>{busy==='reconnect'?'Reconnecting…':'Reconnect'}</button>
        <button class="btn" disabled={!!busy||(!running&&!state.enabled)} on:click={()=>act('disconnect')}>{busy==='disconnect'?'Disconnecting…':'Disconnect'}</button>
        <button class="btn" disabled={!!busy||running||state.enabled} on:click={edit}>Edit settings</button>
      </div>
      <div class="operator-callout"><strong>3. Finish in ChatGPT</strong><p>Create a developer-mode app in ChatGPT, choose the Tunnel connection, and select or paste this tunnel ID. If it is missing, check the workspace association and tunnel Use permission in OpenAI.</p><div class="actions"><button class="btn small" on:click={copyTunnel}>Copy tunnel ID</button><button class="btn small" disabled={!!busy} on:click={refresh}>Check for request</button></div><p class="operator-caption">A successful poll confirms the OpenAI connection, not that the intended ChatGPT app has made a tool call. Request evidence can come from any OpenAI context permitted to use this tunnel.</p></div>
      <details><summary>Connection details and checks</summary><div class="stack operator-inset"><p><strong>Local MCP:</strong> <span class="mono">{state.local_mcp}</span></p><p><strong>Key protection:</strong> {state.credential_protection}. TPM reset or replacement requires re-entering the key. This service credential stays available to the tunnel while connected; it is not controlled by the target-credential vault unlock timer.</p><p><strong>Component:</strong> OpenAI tunnel runtime {state.runtime_version}, {state.runtime_installed?'installed':'not installed'}. First connect downloads the reviewed, checksum-verified runtime and its licenses.</p><p>Disconnect stops this appliance's tunnel and prevents its automatic restart. It does not delete the OpenAI tunnel or revoke the API key at OpenAI.</p><button class="btn" disabled={!!busy} on:click={check}>{busy==='probe'?'Checking…':'Test local MCP and refresh tunnel'}</button>{#if localProbe}<div class="notice" class:warn={!localProbe.responding}><strong>{localProbe.responding?'Local MCP responds':'Local MCP check failed'}</strong><p>{localProbe.error||localProbe.message}</p><p class="operator-caption">This check does not execute tools or verify a request from your ChatGPT app.</p></div>{/if}</div></details>
    {/if}
  </div>
</section>
