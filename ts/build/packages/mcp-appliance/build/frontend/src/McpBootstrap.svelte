<script>
 import {onMount} from 'svelte';
 import {api,json} from './lib/api.js';
 export let onNavigate=()=>{};
 let policy=null,error='',message='',busy=false;
 async function load(){policy=await api('/api/mcp/bootstrap-policy')}
 onMount(()=>load().catch(e=>error=e.message));
 async function save(){busy=true;error='';try{await json('/api/mcp/bootstrap-policy','POST',policy.effective);message='MCP bootstrap policy saved.';await load()}catch(e){error=e.message}finally{busy=false}}
 async function boot(){if(!confirm('Apply the MCP bootstrap policy now? This may change the selected MCP runtime.'))return;busy=true;error='';try{const r=await json('/api/mcp/bootstrap-now','POST',{});message=r.message||'Bootstrap complete.'}catch(e){error=e.message}finally{busy=false}}
</script>
<div class="page"><div class="page-title"><div><h1>MCP update policy</h1><p>Runtime bootstrap and distribution-channel configuration.</p></div><button class="btn" on:click={()=>onNavigate('mcp')}>Back to MCP</button></div>
{#if error}<div class="notice warn" role="alert">{error}</div>{/if}{#if message}<div class="notice" role="status">{message}</div>{/if}
<section class="panel"><div class="panel-head"><h2>Bootstrap and updates</h2></div><div class="panel-body stack">{#if policy}
<label class="field"><span>Bootstrap mode</span><select bind:value={policy.effective.mode}><option value="auto">Automatic</option><option value="channel">Distribution channel only</option><option value="recovery">Seed from recovery</option><option value="off">Off</option></select></label>
<label class="field"><span>Bootstrap generation</span><input bind:value={policy.effective.generation}/></label><label class="field"><span>Distribution channel URL</span><input bind:value={policy.effective.channel_url}/></label><div class="actions"><button class="btn primary" disabled={busy} on:click={save}>Save policy</button><button class="btn" disabled={busy} on:click={boot}>Bootstrap now</button></div><p class="muted">Persistent local policy overrides build-time defaults.</p>
{:else}<div class="muted">Loading policy...</div>{/if}</div></section></div>
