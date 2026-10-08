<script>
 import {onDestroy} from 'svelte';
 import {api,setCsrf} from './lib/api.js';
 import {route,title,topPages,systemTopics} from './lib/navigation.js';
 import Auth from './Auth.svelte';
 import Mcp from './Mcp.svelte';
 import Connections from './Connections.svelte';
 import SystemPage from './System.svelte';
 import Overview from './Overview.svelte';
 import Hosts from './Hosts.svelte';
 import Environments from './Environments.svelte';
 import Credentials from './Credentials.svelte';
 import McpBootstrap from './McpBootstrap.svelte';
 let state='loading',registration={registered:false},issue='',user=null,health=null;
 let page=route(window.location.hash),navOpen=false,timer=null,healthError=false;
 function go(value){page=route(value);window.location.hash='/'+page;navOpen=false}
 function hashChanged(){page=route(window.location.hash);navOpen=false}
 window.addEventListener('hashchange',hashChanged);
 async function refresh(){try{health=await api('/api/health');healthError=false}catch{healthError=true}}
 function startTimer(){if(timer)clearInterval(timer);timer=setInterval(refresh,15000)}
 async function init(){
  try{const [reg,iss]=await Promise.all([api('/api/registration'),api('/api/issue')]);registration=reg;issue=(iss.text||'').trim();
   if(reg.registered){try{const ss=await api('/api/session');user=ss.user;setCsrf(ss.csrf);state='app';await refresh();startTimer();return}catch{}}
   state='auth';
  }catch{state='auth'}
 }
 async function authenticated(u,csrf){user=u;setCsrf(csrf);state='app';await refresh();startTimer()}
 async function logout(){try{await api('/api/logout',{method:'POST'})}catch{}if(timer)clearInterval(timer);user=null;health=null;setCsrf('');state='auth'}
 function attentionTarget(){
  const problems=health?.summary?.problems||[];if(problems.length!==1)return 'overview';
  const p=problems[0].toLowerCase();
  if(p.includes('mcp')||p.includes('generation'))return 'mcp';
  if(p.includes('route')||p.includes('network'))return 'system/network';
  if(p.includes('storage')||p.includes('disk')||p.includes('mount'))return 'system/storage';
  if(p.includes('vault')||p.includes('grant')||p.includes('credential'))return 'credentials';
  if(p.includes('certificate'))return 'system/certificates';
  return 'system/services';
 }
 onDestroy(()=>{clearInterval(timer);window.removeEventListener('hashchange',hashChanged)});
 init();
</script>
{#if state==='loading'}
 <div class="login-shell"><div class="login-card">Loading appliance...</div></div>
{:else if state==='auth'}<Auth {issue} {registration} onAuthenticated={authenticated}/>
{:else}
 <div class="shell" class:nav-open={navOpen}>
  {#if navOpen}<button class="drawer-backdrop" aria-label="Close menu" on:click={()=>navOpen=false}></button>{/if}
  <aside class="sidebar">
   <div class="brand"><img class="brandwordmark" src="/watermark.png" alt="ThinStation"/><div class="brandsub">MCP Appliance</div></div>
   <nav class="navgroup" aria-label="Main navigation">
    {#each topPages as item}
     <button class="navbtn" class:active={page===item[0]||page.startsWith(item[0]+'/')} on:click={()=>go(item[0])}>{item[1]}</button>
     {#if item[0]==='system'&&page.startsWith('system/')}
      <div class="system-subnav" aria-label="System topics">{#each systemTopics as topic}<button class="navbtn subnav" class:active={page==='system/'+topic[0]} aria-current={page==='system/'+topic[0]?'page':undefined} on:click={()=>go('system/'+topic[0])}>{topic[1]}</button>{/each}</div>
     {/if}
    {/each}
   </nav>
  </aside>
  <header class="topbar">
   <button class="btn small menu" aria-expanded={navOpen} on:click={()=>navOpen=!navOpen}>Menu</button>
   <div class="topbar-title">{title(page)}</div>
   <div class="attention-wrap"><button class="pill attention-button" class:good={health&&!healthError&&!health.summary?.problems?.length} class:warn={healthError||health?.summary?.problems?.length} on:click={()=>go(attentionTarget())}>{healthError?'Status unavailable':!health?'Checking':health.summary?.problems?.length?`Attention · ${health.summary.problems.length}`:'Healthy'}</button>
    {#if health?.summary?.problems?.length}<div class="attention-popover"><strong>Needs attention</strong>{#each health.summary.problems.slice(0,5) as problem}<div class="attention-item">{problem}</div>{/each}<div class="attention-hint">Open {title(attentionTarget())}.</div></div>{/if}
   </div>
   <div class="topbar-user">{user?.display_name||user?.username}</div><button class="btn small" on:click={logout}>Sign out</button>
  </header>
  <main class="main">
   {#if page==='overview'}<Overview {health} onNavigate={go}/>
   {:else if page==='inventory'}<Hosts/>
   {:else if page==='environments'}<Environments/>
   {:else if page==='credentials'}<Credentials {health} onRefresh={refresh}/>
   {:else if page.startsWith('system/')}<SystemPage topic={page.slice(7)} {health} onRefresh={refresh} onNavigate={go}/>
   {:else if page==='mcp/settings'}<McpBootstrap onNavigate={go}/>
   {:else if page==='mcp'}<Mcp {health} onRefresh={refresh} onNavigate={go}/>
   {:else if page==='connections'}<Connections {health} onNavigate={go}/>{/if}
  </main>
 </div>
{/if}
<style>
 .system-subnav{display:grid;margin:.15rem 0 .6rem .75rem;border-left:1px solid #4b5e70;padding-left:.35rem}.subnav{font-size:.86rem;font-weight:500;padding:.5rem .7rem}.topbar-title{min-width:0;overflow-wrap:anywhere}
 @media(max-width:760px){.topbar{gap:.4rem}.topbar-title{font-size:.85rem}.attention-button{font-size:.75rem}}
</style>
