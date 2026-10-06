<script>
 import Certificates from './Certificates.svelte';
 import { api, json } from './lib/api.js';
 let tab='general';
 let policy=null, issue='', result='';
 async function load(){try{policy=await api('/api/mcp/bootstrap-policy'); issue=(await api('/api/config/issue')).value||''}catch(e){result=e.message}}
 async function savePolicy(){try{await json('/api/mcp/bootstrap-policy','POST',policy.effective);result='Bootstrap policy saved.';await load()}catch(e){result=e.message}}
 async function saveIssue(){try{await api('/api/config/issue',{method:'PUT',headers:{'Content-Type':'text/plain'},body:issue});result='Login notice saved.'}catch(e){result=e.message}}
 async function boot(){try{result='Bootstrapping…';let r=await json('/api/mcp/bootstrap-now','POST',{});result=r.message||'Bootstrap complete.'}catch(e){result=e.message}}
 $: if(!policy) load();
</script>
<div class="page"><div class="page-title"><div><h1>Settings</h1><p>Appliance-wide configuration</p></div></div>
 <div class="tabs" style="margin-bottom:1rem;padding-left:0"><button class="tab" class:active={tab==='general'} on:click={()=>tab='general'}>General</button><button class="tab" class:active={tab==='certificates'} on:click={()=>tab='certificates'}>Certificates</button></div>
 {#if tab==='certificates'}<Certificates/>{:else}
 <div class="two-col">
  <section class="panel"><div class="panel-head"><h2>MCP bootstrap & updates</h2></div><div class="panel-body stack">
   {#if policy}
    <label class="field"><span>Bootstrap mode</span><select bind:value={policy.effective.mode}><option value="auto">Automatic</option><option value="channel">Distribution channel only</option><option value="recovery">Seed from recovery</option><option value="off">Off</option></select></label>
    <label class="field"><span>Bootstrap generation</span><input bind:value={policy.effective.generation}/></label>
    <label class="field"><span>Distribution channel URL</span><input bind:value={policy.effective.channel_url}/></label>
    <div class="actions"><button class="btn primary" on:click={savePolicy}>Save policy</button><button class="btn" on:click={boot}>Bootstrap now</button></div>
    <div class="muted">Build-time defaults are overridden by persistent site-local policy.</div>
   {/if}
  </div></section>
  <section class="panel"><div class="panel-head"><h2>Login notice</h2></div><div class="panel-body stack">
   <div class="muted">Shown on the console and web login/registration page.</div>
   <textarea bind:value={issue} maxlength="4096"></textarea><button class="btn primary" on:click={saveIssue}>Save notice</button>
  </div></section>
 </div>
 {#if result}<div class="notice" style="margin-top:1rem">{result}</div>{/if}
 {/if}
</div>
