<script>
  import { api } from './lib/api.js';
  let document={hosts:{},groups:{}}, error='', notice='', view='hosts', editing=null, groupEditing=null, busy=false, loaded=false, revision='';
  $: hostRows=rows(document);
  $: inventoryGroups=groupRows(document);
  let form=blankHost(), groupForm=blankGroup();

  function blankHost(){ return {alias:'',address:'',hostname:'',platform:'linux',username:'',identity_file:'',groups:[]}; }
  function blankGroup(){ return {name:'',description:'',hosts:[]}; }
  function normalize(){
    if(!document || typeof document!=='object' || Array.isArray(document)) throw new Error('The saved inventory is not a JSON object.');
    document.hosts ??= {};
    if(typeof document.hosts!=='object' || Array.isArray(document.hosts)) throw new Error('The saved hosts inventory is invalid.');
    document.groups ??= {};
    if(typeof document.groups!=='object' || Array.isArray(document.groups)) throw new Error('The saved groups inventory is invalid.');
    for(const [name,g] of Object.entries(document.groups)){
      if(!g || typeof g!=='object') document.groups[name]={hosts:[]};
      if(!Array.isArray(document.groups[name].hosts)) document.groups[name].hosts=[];
    }
  }
  function rows(inventory){
    return Object.entries(inventory.hosts||{}).map(([alias,h])=>({
      ...(h||{}),alias,
      groups:Object.entries(inventory.groups||{}).filter(([,g])=>(g.hosts||[]).includes(alias)).map(([n])=>n)
    })).sort((a,b)=>a.alias.localeCompare(b.alias));
  }
  function groupRows(inventory){
    return Object.entries(inventory.groups||{}).map(([name,g])=>({...g,name,hosts:g.hosts||[]})).sort((a,b)=>a.name.localeCompare(b.name));
  }
  async function load(){
    if(busy)return; busy=true;error=''; notice='';
    try{
      const r=await api('/api/config/hosts');
      document=JSON.parse(r.value||'{}'); normalize();revision=r.revision||'';loaded=true;
    }catch(e){ error=e.message; }finally{busy=false}
  }
  async function persist(next,message){
    const result=await api('/api/config/hosts',{method:'PUT',headers:{'Content-Type':'application/json',...(revision?{'If-Match':revision}:{})},body:JSON.stringify(next,null,2)+'\n'});
    revision=result.revision||'';
    document=typeof result.value==='string'?JSON.parse(result.value):next;normalize();
    notice=message;
    if(result.runtime_notice)notice+=' '+result.runtime_notice;
  }

  function editHost(row){
    editing=row.alias; groupEditing=null;
    form={alias:row.alias,address:row.address||'',hostname:row.hostname||'',platform:row.platform||'linux',username:row.username||'',identity_file:row.identity_file||'',groups:[...(row.groups||[])]};
  }
  function addHost(){ editing='';groupEditing=null;form=blankHost();view='hosts'; }
  function cancelHost(){ editing=null;form=blankHost(); }
  function toggleHostGroup(name){ form.groups=form.groups.includes(name)?form.groups.filter(x=>x!==name):[...form.groups,name]; }
  function validateHost(){
    const alias=form.alias.trim().toLowerCase();
    if(!alias)throw new Error('Alias is required.');
    if(['__proto__','constructor','prototype'].includes(alias)||! /^[a-z0-9._-]+$/.test(alias))throw new Error('Alias may contain only letters, numbers, dot, underscore, and hyphen.');
    if(!form.address.trim())throw new Error('Address is required.');


    return alias;
  }
  async function saveHost(){
    if(busy||!loaded)return;busy=true;error='';notice='';
    try{
      const alias=validateHost(), next=JSON.parse(JSON.stringify(document)); next.hosts=next.hosts||{};next.groups=next.groups||{};
      if(alias!==editing&&Object.hasOwn(next.hosts,alias))throw new Error('A host with that alias already exists. Open it to edit instead.');
      const existing=editing?{...next.hosts[editing]}:{};
      if(editing&&editing!==alias){
        delete next.hosts[editing];
        for(const g of Object.values(next.groups))g.hosts=(g.hosts||[]).map(x=>x===editing?alias:x);
      }
      delete existing.username;delete existing.identity_file;
      next.hosts[alias]={...existing,address:form.address.trim(),hostname:form.hostname.trim()||null,platform:form.platform,...(form.username.trim()?{username:form.username.trim()}:{}),...(form.identity_file.trim()?{identity_file:form.identity_file.trim()}:{})};
      for(const [name,g] of Object.entries(next.groups)){
        const members=new Set(g.hosts||[]);
        form.groups.includes(name)?members.add(alias):members.delete(alias);
        g.hosts=[...members].sort();
      }
      await persist(next,'Host inventory saved.');editing=null;form=blankHost();
    }catch(e){error=e.message}finally{busy=false}
  }
  async function removeHost(alias){
    if(busy||!loaded)return;busy=true;error='';notice='';
    try{
      const next=JSON.parse(JSON.stringify(document));delete next.hosts[alias];
      for(const g of Object.values(next.groups||{}))g.hosts=(g.hosts||[]).filter(x=>x!==alias);
      await persist(next,'Host removed.');if(editing===alias)cancelHost();
    }catch(e){error=e.message}finally{busy=false}
  }

  function editGroup(row){ groupEditing=row.name;editing=null;groupForm={name:row.name,description:row.description||'',hosts:[...(row.hosts||[])]};view='groups'; }
  function addGroup(){ groupEditing='';editing=null;groupForm=blankGroup();view='groups'; }
  function cancelGroup(){ groupEditing=null;groupForm=blankGroup(); }
  function toggleGroupHost(alias){ groupForm.hosts=groupForm.hosts.includes(alias)?groupForm.hosts.filter(x=>x!==alias):[...groupForm.hosts,alias]; }
  function validateGroup(){
    const name=groupForm.name.trim().toLowerCase();
    if(!name)throw new Error('Group name is required.');
    if(['__proto__','constructor','prototype'].includes(name)||! /^[a-z0-9._-]+$/.test(name))throw new Error('Group name may contain only letters, numbers, dot, underscore, and hyphen.');
    return name;
  }
  async function saveGroup(){
    if(busy||!loaded)return;busy=true;error='';notice='';
    try{
      const name=validateGroup(),next=JSON.parse(JSON.stringify(document));next.groups=next.groups||{};
      if(name!==groupEditing&&Object.hasOwn(next.groups,name))throw new Error('A group with that name already exists. Open it to edit instead.');
      const existing=groupEditing?{...next.groups[groupEditing]}:{};
      if(groupEditing&&groupEditing!==name)delete next.groups[groupEditing];
      next.groups[name]={...existing,description:groupForm.description.trim(),hosts:[...new Set(groupForm.hosts)].sort()};
      await persist(next,'Group saved.');groupEditing=null;groupForm=blankGroup();
    }catch(e){error=e.message}finally{busy=false}
  }
  async function removeGroup(name){
    if(busy||!loaded)return;busy=true;error='';notice='';
    try{
      const next=JSON.parse(JSON.stringify(document));delete next.groups[name];
      await persist(next,'Group removed.');if(groupEditing===name)cancelGroup();
    }catch(e){error=e.message}finally{busy=false}
  }
  load();
</script>

<div class="page">
  <div class="page-title">
    <div><h1>Inventory</h1><p>Hosts, groups, and connection targets available to MCP.</p><p>Saving changes briefly restarts an active MCP runtime; the console and tunnel remain running.</p></div>
    <div class="actions">
      <button class="btn" disabled={busy} on:click={load}>Refresh</button>
      <button class="btn primary" disabled={busy||!loaded} on:click={view==='hosts'?addHost:addGroup}>Add {view==='hosts'?'host':'group'}</button>
    </div>
  </div>

  <div class="connection-tabs inventory-tabs" style="margin-bottom:1rem">
    <button class:active={view==='hosts'} on:click={()=>view='hosts'}><strong>Hosts</strong><span>{hostRows.length} managed endpoint{hostRows.length===1?'':'s'}</span></button>
    <button class:active={view==='groups'} on:click={()=>view='groups'}><strong>Groups</strong><span>{inventoryGroups.length} inventory group{inventoryGroups.length===1?'':'s'}</span></button>
  </div>

  {#if error}<div class="notice warn" role="alert" style="margin-bottom:1rem">{error}</div>{/if}
  {#if notice}<div class="notice" role="status" style="margin-bottom:1rem">{notice}</div>{/if}

  {#if view==='hosts'}
  <div class="two-col">
    <section class="panel">
      <div class="panel-head"><h2>Hosts</h2><span class="spacer"></span><span class="pill">{hostRows.length}</span></div>
      <div class="table-wrap">
        <table class="table inventory-table"><thead><tr><th>Host</th><th>Address</th><th>Groups</th><th></th></tr></thead><tbody>
        {#each hostRows as row}
          <tr>
            <td><strong>{row.alias}</strong>{#if row.hostname}<div class="muted">{row.hostname}</div>{/if}<div class="muted">{row.platform} · Credential-managed login</div></td>
            <td class="mono">{row.address||'—'}</td>
            <td><div class="chip-row">{#each row.groups as g}<span class="pill">{g}</span>{/each}{#if !row.groups.length}<span class="muted">Ungrouped</span>{/if}</div></td>
            <td><button class="btn small" on:click={()=>editHost(row)}>Open</button></td>
          </tr>
        {/each}</tbody></table>
        {#if !hostRows.length}<div class="empty">{loaded?'No hosts are configured yet.':busy?'Loading inventory...':'Inventory could not be loaded.'}</div>{/if}
      </div>
    </section>
    <section class="panel">
      <div class="panel-head"><h2>{editing===null?'Host details':editing?'Edit host':'Add host'}</h2></div>
      <div class="panel-body stack">
        {#if editing===null}<div class="empty">Select a host or add a new one.</div>
        {:else}
          <div class="form-grid">
            <label class="field"><span>Alias</span><input bind:value={form.alias} placeholder="web01"/></label>
            <label class="field"><span>Platform</span><select bind:value={form.platform}><option value="linux">Linux</option><option value="windows">Windows</option></select></label>
            <label class="field wide"><span>Address</span><input bind:value={form.address} placeholder="192.0.2.10 or host.example.org"/></label>
            <label class="field wide"><span>Hostname / FQDN</span><input bind:value={form.hostname}/></label>
          </div>
          {#if form.username||form.identity_file}<details><summary>Legacy connection settings</summary><p class="muted">Retained for older connections without an eligible vault credential. Assigned credentials take precedence.</p><label class="field"><span>Legacy username (optional)</span><input bind:value={form.username}/></label><label class="field"><span>Legacy identity key path (optional)</span><input bind:value={form.identity_file}/></label></details>{/if}
          <div class="field"><span>Group membership</span>
            <div class="selection-grid">
              {#each inventoryGroups as g}<label class="selection-card"><input type="checkbox" checked={form.groups.includes(g.name)} on:change={()=>toggleHostGroup(g.name)}/><span><strong>{g.name}</strong><small>{g.description||'Inventory group'}</small></span></label>{/each}
              {#if !inventoryGroups.length}<div class="muted">No groups yet. Create a group from the Groups tab.</div>{/if}
            </div>
          </div>
          <div class="muted">The assigned credential supplies the username and authentication material. Assign credentials to this host or one of its groups in Credentials. Host assignments take precedence over group assignments; ambiguous matches are rejected.</div>
          <div class="actions"><button class="btn primary" disabled={busy} on:click={saveHost}>{busy?'Saving...':'Save'}</button><button class="btn" on:click={cancelHost}>Cancel</button>{#if editing}<button class="btn danger" on:click={()=>removeHost(editing)}>Remove</button>{/if}</div>
        {/if}
      </div>
    </section>
  </div>
  {:else}
  <div class="two-col">
    <section class="panel">
      <div class="panel-head"><h2>Groups</h2><span class="spacer"></span><span class="pill">{inventoryGroups.length}</span></div>
      <div class="table-wrap">
        <table class="table inventory-table"><thead><tr><th>Group</th><th>Members</th><th></th></tr></thead><tbody>
        {#each inventoryGroups as g}
          <tr><td><strong>{g.name}</strong><div class="muted">{g.description||'No description'}</div></td><td>{g.hosts.length} host{g.hosts.length===1?'':'s'}<div class="muted">{g.hosts.join(', ')||'Empty'}</div></td><td><button class="btn small" on:click={()=>editGroup(g)}>Open</button></td></tr>
        {/each}</tbody></table>
        {#if !inventoryGroups.length}<div class="empty">No groups are configured yet.</div>{/if}
      </div>
    </section>
    <section class="panel">
      <div class="panel-head"><h2>{groupEditing===null?'Group details':groupEditing?'Edit group':'Add group'}</h2></div>
      <div class="panel-body stack">
        {#if groupEditing===null}<div class="empty">Select a group or add a new one.</div>
        {:else}
          <div class="form-grid">
            <label class="field"><span>Group name</span><input bind:value={groupForm.name} placeholder="linux-servers"/></label>
            <label class="field wide"><span>Description</span><input bind:value={groupForm.description} placeholder="Linux infrastructure hosts"/></label>
          </div>
          <div class="field"><span>Member hosts</span>
            <div class="selection-grid">
              {#each hostRows as h}<label class="selection-card"><input type="checkbox" checked={groupForm.hosts.includes(h.alias)} on:change={()=>toggleGroupHost(h.alias)}/><span><strong>{h.alias}</strong><small>{h.hostname||h.address}</small></span></label>{/each}
              {#if !hostRows.length}<div class="muted">Add hosts before assigning group membership.</div>{/if}
            </div>
          </div>
          <div class="actions"><button class="btn primary" disabled={busy} on:click={saveGroup}>{busy?'Saving...':'Save'}</button><button class="btn" on:click={cancelGroup}>Cancel</button>{#if groupEditing}<button class="btn danger" on:click={()=>removeGroup(groupEditing)}>Remove</button>{/if}</div>
        {/if}
      </div>
    </section>
  </div>
  {/if}
</div>

<style>
  @media(max-width:760px){.inventory-table th:last-child,.inventory-table td:last-child{display:table-cell}.inventory-table td{overflow-wrap:anywhere}.inventory-table .btn{white-space:nowrap}}
</style>
