<script>
  export let health=null;
  export let onNavigate=()=>{};
  const fmtBytes=(n)=>{ if(!Number.isFinite(n)) return '—'; const u=['B','KiB','MiB','GiB','TiB']; let i=0,v=n; while(v>=1024&&i<u.length-1){v/=1024;i++} return v.toFixed(i?1:0)+' '+u[i]; };
  const fmtUptime=(s)=>{s=Number(s||0); const d=Math.floor(s/86400),h=Math.floor((s%86400)/3600),m=Math.floor((s%3600)/60); return [d&&d+'d',h&&h+'h',m+'m'].filter(Boolean).join(' ')};
</script>
<div class="page">
  <div class="page-title"><div><h1>Overview</h1><p>Appliance health and services at a glance</p></div></div>
  {#if !health}<div class="panel"><div class="empty">Loading appliance health…</div></div>
  {:else}
    {#if health.summary?.problems?.length}<div class="notice warn" style="margin-bottom:1rem"><strong>Needs attention:</strong> {health.summary.problems.join(' · ')}</div>{/if}
    <div class="cards">
      <div class="panel metric"><div class="label">Appliance</div><div class="value">{health.system.hostname}</div><div class="detail">{health.system.kernel} · uptime {fmtUptime(health.system.uptime_seconds)}</div></div>
      <div class="panel metric"><div class="label">MCP runtime</div><div class="value" class:warn={health.mcp.selected?.kind==='recovery'}>{health.mcp.selected?.kind==='recovery'?'Recovery MCP':health.mcp.service}</div><div class="detail">active {health.mcp.active||'—'} · previous {health.mcp.previous||'—'}</div></div>
      <div class="panel metric"><div class="label">Network</div><div class="value" class:good={!!health.network.default_route} class:bad={!health.network.default_route}>{health.network.default_route?'Online':'No default route'}</div><div class="detail">{health.network.default_route?.dev||'—'} {health.network.default_route?.gateway?'via '+health.network.default_route.gateway:''}</div></div>
      <div class="panel metric"><div class="label">Vault</div><div class="value" class:warn={!health.vault?.locked}>{health.vault?.available===false?'Unavailable':health.vault?.locked?'Locked':'Unlocked'}</div><div class="detail">{health.vault?.credentials?.length||0} credential{(health.vault?.credentials?.length||0)===1?'':'s'} · {health.vault?.key_mode_effective||'unknown'}</div></div>
      <div class="panel metric"><div class="label">Persistent storage</div><div class="value" class:good={health.storage.persist_mounted} class:bad={!health.storage.persist_mounted}>{health.storage.persist_mounted?'Mounted':'Degraded'}</div><div class="detail">{health.storage.persist?.free?fmtBytes(health.storage.persist.free)+' free':'—'}</div></div>
      <div class="panel metric"><div class="label">Memory</div><div class="value">{fmtBytes(health.system.memory.used)} / {fmtBytes(health.system.memory.total)}</div><div class="detail">load {health.system.load.map(x=>Number(x).toFixed(2)).join(' / ')}</div></div>
      <div class="panel metric"><div class="label">Certificate</div><div class="value" class:good={health.certificate.valid} class:bad={!health.certificate.valid}>{health.certificate.valid?(health.certificate.days_remaining!=null?health.certificate.days_remaining+' days':'Valid'):'Invalid / missing'}</div><div class="detail">{health.certificate.subject||'No subject'}</div></div>
      <div class="panel metric"><div class="label">Services</div><div class="value">{health.services.ssh==='active'&&health.services.qemu_guest_agent==='active'?'Healthy':'Attention'}</div><div class="detail">SSH {health.services.ssh} · QGA {health.services.qemu_guest_agent}</div></div>
    </div>
    <div class="two-col" style="margin-top:1rem">
      <section class="panel"><div class="panel-head"><h2>Provisioning readiness</h2></div><div class="panel-body">
        {#each health.provisioning?.items||[] as item}
          <div style="display:flex;gap:.65rem;align-items:center;padding:.4rem 0;border-bottom:1px solid #edf0f2">
            <span class:good={item.ready} class:warn={!item.ready}>{item.ready?'Ready':'Pending'}</span>
            <div style="flex:1"><strong>{item.item.replaceAll('_',' ')}</strong><div class="muted">{item.detail}</div></div>
            {#if !item.ready && item.item==='persistent_storage'}<button class="btn small" on:click={()=>onNavigate('system/storage')}>Provision</button>{/if}
          </div>
        {/each}
      </div></section>
      <section class="panel"><div class="panel-head"><h2>Recent state</h2></div><div class="panel-body">
        {#if health.recent?.length}{#each health.recent.slice(0,8) as x}<div style="padding:.4rem 0"><strong>{x.source}</strong><div class="muted">{x.message}</div></div>{/each}{:else}<div class="muted">No recent events.</div>{/if}
      </div></section>
    </div>
  {/if}
</div>
