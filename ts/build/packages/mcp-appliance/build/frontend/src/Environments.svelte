<script>
 import {onMount} from 'svelte';
 import {api,json} from './lib/api.js';
 let data=null,loading=true,error='',job=null,busy='',tab='installed',saving=false,notice='';
 let fedoraUrl='',updatesUrl='';
 async function start(name,action){busy=name;try{job=await json('/api/operator/environments/start','POST',{name,action});await refresh()}catch(e){error=e.message}finally{busy=''}}
 async function log(id){try{job=await api('/api/operator/environments/jobs/'+id)}catch(e){error=e.message}}

 async function refresh(){loading=true;error='';try{data=await api('/api/operator/environments');fedoraUrl=data.sources?.fedora_url||'';updatesUrl=data.sources?.updates_url||''}catch(e){error=e.message}finally{loading=false}}
 async function saveSources(){saving=true;error='';notice='';try{const v=await json('/api/operator/environments/sources/save','POST',{fedora_url:fedoraUrl,updates_url:updatesUrl,fallback:false});notice='Package source settings saved';data.sources=v}catch(e){error=e.message}finally{saving=false}}
 onMount(()=>{refresh();const timer=setInterval(()=>{if(job?.id&&['queued','running'].includes(job.state))log(job.id)},3000);return ()=>clearInterval(timer)});
</script>
<div class="page-header"><div><h1>Environments</h1><p>Persistent execution environments, independent of the immutable appliance OS.</p></div><button class="btn" on:click={refresh} disabled={loading}>Refresh</button></div>
{#if error}<p role="alert" class="notice warn">{error}</p>{/if}
{#if data}
 <div class="env-tabs"><button class:active={tab==='installed'} on:click={()=>tab='installed'}>Installed</button><button class:active={tab==='catalog'} on:click={()=>tab='catalog'}>Catalog</button><button class:active={tab==='settings'} on:click={()=>tab='settings'}>Settings</button></div>
 {#if tab==='installed'}<section class="panel"><h2>Installed chroots ({data.installed.length})</h2>
 {#if !data.installed.length}<p>No environments are installed.</p>{/if}
 <div class="env-list">{#each data.installed as env}
 <article class="env-card"><div><h3>{env.title} <small>{env.name}</small></h3><p>{env.description}</p><p class="meta">{env.os} · Package manager: {env.dnf_available?'DNF available':'DNF missing'} · Updates: {env.update_status}</p><p><button class="btn small" disabled={busy===env.name||!env.dnf_available} on:click={()=>start(env.name,'check')}>Check updates</button> <button class="btn small" disabled={true} title="Requires verified snapshot and rollback support" on:click={()=>start(env.name,'upgrade')}>Upgrade</button></p></div>
 </article>{/each}</div></section>
 {/if}{#if tab==='catalog'}<section class="panel"><h2>Optional environments</h2><p>Available profiles for a first-time installation. Installation actions require a validated provisioning worker.</p><div class="env-list">{#each data.catalog as item}<article class="env-card"><div><h3>{item.title}</h3><p>{item.description}</p></div><span class="meta">{item.installed?'Installed':'Available profile'}</span></article>{/each}</div></section>
 {/if}{#if tab==='settings'}<section class="panel"><h2>Package Sources</h2><p>Preferred Fedora mirror for existing execution environments. Empty fields use upstream Fedora.</p><label for="fedora-source">Fedora base repository URL</label><input id="fedora-source" class="source-input" bind:value={fedoraUrl} placeholder="https://foreman.example/pulp/content/.../fedora/$releasever/$basearch/"/><label for="updates-source">Fedora updates repository URL</label><input id="updates-source" class="source-input" bind:value={updatesUrl} placeholder="https://foreman.example/pulp/content/.../updates/"/><p class="meta">Only HTTPS URLs without embedded credentials are accepted. Automatic upstream fallback after a mirror failure is not yet available.</p><button class="btn" disabled={saving} on:click={saveSources}>Save package sources</button>{#if notice}<p role="status">{notice}</p>{/if}</section>{/if}
 {#if job}<section class="panel"><h2>{job.name}: {job.action}</h2><p>{job.state} · {job.package_source||'Source pending'}</p><button class="btn small" on:click={()=>log(job.id)}>Refresh log</button><pre style="white-space:pre-wrap;max-height:280px;overflow:auto">{job.log_tail||'No log yet'}</pre></section>{/if}<p class="meta">{data.note}</p>
{:else if loading}<p>Scanning persistent environments…</p>{/if}
<style>
 .env-tabs{display:flex;gap:.4rem;margin:1rem 0}.env-tabs button{padding:.6rem 1rem;border-radius:8px;cursor:pointer}.env-tabs button.active{font-weight:700;border-bottom:2px solid currentColor}.source-input{display:block;width:100%;padding:.65rem;margin:.4rem 0 1rem;box-sizing:border-box}
 .page-header{display:flex;justify-content:space-between;align-items:center;gap:1rem;margin-bottom:1rem;flex-wrap:wrap}
 .page-header h1{margin:0}.page-header p{margin:.3rem 0 0;opacity:.78}
 .panel{background:var(--panel,#172231);border:1px solid var(--border,#344255);border-radius:12px;padding:1rem;margin:1rem 0}
 .env-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:.8rem}
 .env-card{border:1px solid var(--border,#344255);border-radius:9px;padding:.85rem;display:flex;justify-content:space-between;gap:.5rem}
 .env-card h3{margin:0 0 .4rem}.env-card small{font-size:.72rem;font-weight:400;opacity:.7}
 .env-card p{margin:.3rem 0}.meta{font-size:.82rem;opacity:.73}
</style>
