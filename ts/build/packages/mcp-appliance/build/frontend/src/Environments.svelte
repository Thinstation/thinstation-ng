<script>
 import {onMount} from 'svelte';
 import {api} from './lib/api.js';
 let data=null,loading=true,error='';
 async function refresh(){loading=true;error='';try{data=await api('/api/operator/environments')}catch(e){error=e.message}finally{loading=false}}
 onMount(refresh);
</script>
<div class="page-header"><div><h1>Environments</h1><p>Persistent execution environments, independent of the immutable appliance OS.</p></div><button class="btn" on:click={refresh} disabled={loading}>Refresh</button></div>
{#if error}<p role="alert" class="notice warn">{error}</p>{/if}
{#if data}
 <section class="panel"><h2>Installed chroots ({data.installed.length})</h2>
 {#if !data.installed.length}<p>No environments are installed.</p>{/if}
 <div class="env-list">{#each data.installed as env}
 <article class="env-card"><div><h3>{env.title} <small>{env.name}</small></h3><p>{env.description}</p><p class="meta">{env.os} · Package manager: {env.dnf_available?'DNF available':'DNF missing'} · Updates: {env.update_status}</p></div>
 </article>{/each}</div></section>
 <section class="panel"><h2>Optional environments</h2><p>Available profiles for a first-time installation. Installation actions require a validated provisioning worker.</p><div class="env-list">{#each data.catalog as item}<article class="env-card"><div><h3>{item.title}</h3><p>{item.description}</p></div><span class="meta">{item.installed?'Installed':'Available profile'}</span></article>{/each}</div></section>
 <p class="meta">{data.note}</p>
{:else if loading}<p>Scanning persistent environments…</p>{/if}
<style>
 .page-header{display:flex;justify-content:space-between;align-items:center;gap:1rem;margin-bottom:1rem;flex-wrap:wrap}
 .page-header h1{margin:0}.page-header p{margin:.3rem 0 0;opacity:.78}
 .panel{background:var(--panel,#172231);border:1px solid var(--border,#344255);border-radius:12px;padding:1rem;margin:1rem 0}
 .env-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:.8rem}
 .env-card{border:1px solid var(--border,#344255);border-radius:9px;padding:.85rem;display:flex;justify-content:space-between;gap:.5rem}
 .env-card h3{margin:0 0 .4rem}.env-card small{font-size:.72rem;font-weight:400;opacity:.7}
 .env-card p{margin:.3rem 0}.meta{font-size:.82rem;opacity:.73}
</style>
