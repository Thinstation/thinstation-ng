<script>
 import Network from './Network.svelte';
 import Certificates from './Certificates.svelte';
 import StoragePage from './Storage.svelte';
 import SystemNotice from './SystemNotice.svelte';
 import {systemTopics} from './lib/navigation.js';
 export let topic='network',health=null,onRefresh=()=>{},onNavigate=()=>{};
 $: label=systemTopics.find(t=>t[0]===topic)?.[1]||'Network';
</script>
<div class="system-page">
 <nav class="breadcrumb" aria-label="Breadcrumb"><button on:click={()=>onNavigate('system/network')}>System</button><span aria-hidden="true">/</span><span>{label}</span></nav>
 {#if topic==='network'}<Network {health}/>
 {:else if topic==='certificates'}<div class="page"><div class="page-title"><div><h1>Certificates</h1><p>Management identity and automated certificate renewal.</p></div></div><Certificates/></div>
 {:else if topic==='storage'}<StoragePage {onRefresh}/>
 {:else if topic==='notice'}<SystemNotice/>
 {:else if topic==='services'}
 <div class="page"><div class="page-title"><div><h1>Services</h1><p>Local appliance service health.</p></div><button class="btn" on:click={onRefresh}>Refresh</button></div>
 {#if !health}<div class="notice">Service health is unavailable.</div>{:else}<div class="two-col">
 <section class="panel"><div class="panel-head"><h2>Failed units</h2></div><div class="panel-body">{#if health.system?.failed_units?.length}{#each health.system.failed_units as unit}<div class="bad">{unit}</div>{/each}{:else}<div class="good">No failed units reported.</div>{/if}</div></section>
 <section class="panel"><div class="panel-head"><h2>Service state</h2></div><div class="panel-body stack">{#each Object.entries(health.services||{}) as [name,value]}<div class="service-row"><span>{name.replaceAll('_',' ')}</span><strong>{value}</strong></div>{/each}</div></section>
 <section class="panel"><div class="panel-head"><h2>Configuration status</h2></div><div class="panel-body stack"><div>ACME: {health.config?.acme?.enabled?'enabled':'disabled'}</div><div>Mail: {health.config?.mail?.enabled?'configured':'not configured'}</div><div>Content: {health.config?.content?.provider||'unknown'}</div></div></section>
 </div>{/if}</div>
 {:else if topic==='logs'}
 <div class="page"><div class="page-title"><div><h1>Logs</h1><p>Recent appliance events. Detailed service journals remain on the host.</p></div><button class="btn" on:click={onRefresh}>Refresh</button></div><section class="panel"><div class="panel-head"><h2>Recent state</h2></div><div class="panel-body"><pre class="code">{health?(health.recent||[]).map(x=>x.source+': '+x.message).join('\n')||'No recent events.':'Status unavailable.'}</pre></div></section></div>
 {/if}
</div>
<style>.breadcrumb{display:flex;align-items:center;gap:.55rem;margin:0 auto 1rem;max-width:1450px;color:var(--muted);font-size:.82rem}.breadcrumb button{border:0;padding:0;background:none;color:var(--accent)}.system-page{min-width:0}.service-row{display:flex;gap:1rem;justify-content:space-between;overflow-wrap:anywhere}</style>
