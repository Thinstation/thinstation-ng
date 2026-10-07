<script>
  import { api, json } from './lib/api.js';
  export let health=null; export let onRefresh=()=>{};
  let search='', selected=null, result='', requests=[], wizard=false, step=1, sourceRequest=null, inventory={hosts:{},groups:{}};
  let form={kind:'secret',name:'',type:'api-token',project:'',purpose:'',scopes:'',hosts:'',secret:'',private_key:'',passphrase:'',protect:true,comment:'',ad_domain:'',ad_username:'',ad_password:'',login_username:''};
  $: creds=health?.vault?.credentials||[];
  $: filtered=creds.filter(c=>JSON.stringify(c).toLowerCase().includes(search.toLowerCase()));
  const list=v=>String(v||'').split(/[\n,]+/).map(x=>x.trim()).filter(Boolean);
  const targetList=v=>Array.isArray(v)?v:list(v);
  function inventoryHosts(){ return Object.keys(inventory?.hosts||{}).sort(); }
  function inventoryGroups(){ return Object.keys(inventory?.groups||{}).sort(); }
  function hasTarget(value,target){ return targetList(value).includes(target); }
  function toggleTarget(target,which='form'){
    if(which==='form'){
      const cur=targetList(form.hosts);
      form.hosts=(cur.includes(target)?cur.filter(x=>x!==target):[...cur,target]).join(', ');
    }else if(selected){
      const cur=targetList(selected.hostsText);
      selected.hostsText=(cur.includes(target)?cur.filter(x=>x!==target):[...cur,target]).join(', ');
    }
  }
  let unlockSeconds=600, unlockScopes='';
  function targetLabel(target){
    if(target.startsWith('host:')) return 'Host: '+target.slice(5);
    if(target.startsWith('group:')) return 'Group: '+target.slice(6);
    return target;
  }
  async function unlockVault(){try{const response=await json('/api/vault/unlock','POST',{seconds:Number(unlockSeconds||600),scopes:list(unlockScopes)});const expires=response?.vault?.lease?.expires;result=expires?'Vault unlocked until '+new Date(expires*1000).toLocaleString()+'.':'Vault unlocked.';await onRefresh()}catch(e){result=e.message}}
  async function lockVault(){try{await json('/api/vault/lock','POST',{});result='Vault locked.';await onRefresh()}catch(e){result=e.message}}
  async function loadRequests(){try{requests=(await api('/api/vault/credential-requests')).requests||[]}catch(e){result=e.message}}
  async function loadInventory(){
    try{
      const r=await api('/api/config/hosts');
      inventory=JSON.parse(r.value||'{}');
      if(!inventory.hosts)inventory.hosts={};
      if(!inventory.groups)inventory.groups={};
    }catch(e){result=e.message}
  }
  function open(c){selected={...c,scopesText:(c.scopes||[]).join(', '),hostsText:(c.allowed_hosts||[]).join(', '),newName:'',loginUsername:c.username||''};result=''}
  function newWizard(req=null){
    sourceRequest=req; const t=(req?.type||'').toLowerCase();
    const kind=t==='active-directory'?'ad':t.includes('ssh')?(t.includes('import')?'ssh-import':'ssh-generate'):'secret';
    form={kind,name:req?.name||'',type:req?.type||'api-token',project:req?.project||'',purpose:req?.purpose||'',scopes:(req?.scopes||[]).join(', '),hosts:(req?.hosts||[]).join(', '),secret:'',private_key:'',passphrase:'',protect:true,comment:req?.project?req.project+' credential':'',ad_domain:'',ad_username:'',ad_password:'',login_username:''};
    step=1;wizard=true;result='';
  }
  function setType(type){
    const kind=type==='ssh-generate'?'ssh-generate':type==='ssh-import'?'ssh-import':type==='active-directory'?'ad':'secret';
    form={...form,type,kind,secret:'',private_key:'',passphrase:'',ad_password:'',login_username:''};
  }
  function closeWizard(){wizard=false;sourceRequest=null;form={...form,secret:'',private_key:'',passphrase:'',ad_password:'',login_username:''}}
  function stepReady(target){
    if(target<=1)return true;
    if(!form.name.trim())return false;
    if(target<=2)return true;
    if(target<=3)return true;
    if(form.kind==='secret')return !!form.secret&&(form.type!=='password'||!!form.login_username.trim());
    if(form.kind==='ad')return !!form.ad_domain.trim()&&!!form.ad_username.trim()&&!!form.ad_password;
    if(form.kind==='ssh-import')return !!form.private_key&&!!form.login_username.trim();
    if(form.kind==='ssh-generate')return !!form.login_username.trim();
    return true;
  }
  function goStep(target){
    target=Math.max(1,Math.min(4,target));
    if(target<step){step=target;return}
    if(!stepReady(target)){
      result=target>=4?'Complete the required credential material before Review.':'Enter a credential name before continuing.';
      return;
    }
    result='';step=target;
  }

  async function saveCredential(){
    try{
      const scopes=list(form.scopes),hosts=list(form.hosts); if(!form.name.trim())throw new Error('Credential name is required');
      if(form.kind==='secret'){
        if(!form.secret)throw new Error('Credential value is required');
        await json('/api/vault/put','POST',{name:form.name.trim(),secret:form.type==='password'?JSON.stringify({username:form.login_username.trim(),password:form.secret}):form.secret,scopes,hosts,type:form.type.trim()||'secret',purpose:form.purpose.trim(),project:form.project.trim()});
      }else if(form.kind==='ad'){
        if(!form.ad_domain.trim()||!form.ad_username.trim()||!form.ad_password)throw new Error('Domain, username and password are required');
        const adSecret=JSON.stringify({domain:form.ad_domain.trim(),username:form.ad_username.trim(),password:form.ad_password});
        await json('/api/vault/put','POST',{name:form.name.trim(),secret:adSecret,scopes,hosts,type:'active-directory',purpose:form.purpose.trim(),project:form.project.trim(),metadata:{domain:form.ad_domain.trim(),username:form.ad_username.trim()}});
        form.ad_password='';
      }else if(form.kind==='ssh-generate'){
        await json('/api/vault/generate-ssh-key','POST',{name:form.name.trim(),purpose:form.purpose.trim()||'admin',target:hosts[0]||'',scopes,username:form.login_username.trim(),comment:form.comment.trim()||form.name.trim(),protect:form.protect});
        if(hosts.length>1)await json('/api/vault/hosts','POST',{name:form.name.trim(),hosts});
      }else{
        if(!form.private_key)throw new Error('Private key is required');
        await json('/api/vault/import-ssh-key','POST',{name:form.name.trim(),purpose:form.purpose.trim()||'admin',target:hosts[0]||'',scopes,username:form.login_username.trim(),private_key:form.private_key,passphrase:form.passphrase});
        if(hosts.length>1)await json('/api/vault/hosts','POST',{name:form.name.trim(),hosts});
      }
      if(sourceRequest)await json('/api/vault/credential-request/dismiss','POST',{id:sourceRequest.id});
      result='Credential added.';closeWizard();await onRefresh();await loadRequests();
    }catch(e){result=e.message}
  }
  async function dismiss(req){try{await json('/api/vault/credential-request/dismiss','POST',{id:req.id});await loadRequests()}catch(e){result=e.message}}
  async function saveSelected(){
    try{
      const original=selected.name;
      if(selected.type==='ssh-key')await json('/api/vault/login','POST',{name:original,username:selected.loginUsername.trim()});
      await json('/api/vault/scopes','POST',{name:original,scopes:list(selected.scopesText)});
      await json('/api/vault/hosts','POST',{name:original,hosts:list(selected.hostsText)});
      const renamed=selected.newName.trim();
      if(renamed&&renamed!==original)await json('/api/vault/rename','POST',{old:original,new:renamed});
      result='Credential saved.';selected=null;await onRefresh();
    }catch(e){result=e.message}
  }
  async function pinLocal(){
    try{await json('/api/vault/pin-local','POST',{name:selected.name});result='Credential pinned to the local bootstrap provider and marked non-exportable.';selected=null;await onRefresh()}
    catch(e){result=e.message}
  }
  async function deleteSelected(){
    try{await json('/api/vault/delete','POST',{name:selected.name});result='Credential deleted.';selected=null;await onRefresh()}
    catch(e){result=e.message}
  }
  loadRequests(); loadInventory();
</script>

<div class="page">
  <div class="page-title"><div><h1>Credentials</h1><p>Privileged credentials and permitted targets</p></div><div class="actions"><span class="pill">{creds.length} stored</span><button class="btn primary" on:click={()=>newWizard()}>Add credential</button></div></div>
  <section class="panel" style="margin-bottom:1rem">
    <div class="panel-head"><h2>Vault authorization</h2><span class="spacer"></span><span class:warn={health?.vault?.locked} class:ok={!health?.vault?.locked} class="pill">{health?.vault?.locked?'Locked':'Unlocked'}</span></div>
    <div class="panel-body stack">
      <p class="muted">{#if health?.vault?.locked}Unlock the vault before using protected credentials.{:else}Authorized until {health?.vault?.lease?.expires?new Date(health.vault.lease.expires*1000).toLocaleString():'the current lease ends'}.{/if}</p>
      <div class="form-grid">
        <label class="field"><span>Authorization duration (seconds)</span><input type="number" min="60" max="604800" bind:value={unlockSeconds}/></label>
        <label class="field"><span>Scopes</span><input bind:value={unlockScopes} placeholder="Leave blank for all permitted scopes"/></label>
      </div>
      <div class="actions"><button class="btn primary" disabled={!health?.vault?.locked} on:click={unlockVault}>Unlock</button><button class="btn" disabled={health?.vault?.locked} on:click={lockVault}>Lock now</button></div>
    </div>
  </section>
  {#if requests.filter(r=>!r.satisfied).length}
    <section class="panel" style="margin-bottom:1rem">
      <div class="panel-head"><h2>Requested credentials</h2><span class="pill warn">{requests.filter(r=>!r.satisfied).length} need your input</span></div>
      <div class="table-wrap"><table class="table"><thead><tr><th>Project</th><th>Credential</th><th>Type</th><th>Why</th><th></th></tr></thead><tbody>
      {#each requests.filter(r=>!r.satisfied) as r}
        <tr><td><strong>{r.project}</strong></td><td class="mono">{r.name}</td><td>{r.type}</td><td>{r.purpose||r.instructions||'Interactive credential required'}</td><td><div class="actions"><button class="btn small primary" on:click={()=>newWizard(r)}>Provide</button><button class="btn small subtle" on:click={()=>dismiss(r)}>Dismiss</button></div></td></tr>
      {/each}</tbody></table></div>
    </section>
  {/if}
  <div class="two-col">
    <section class="panel">
      <div class="panel-head"><h2>Credential inventory</h2><span class="spacer"></span><input style="max-width:300px" placeholder="Search credentials" bind:value={search}/></div>
      <div class="table-wrap"><table class="table"><thead><tr><th>Name</th><th>Type</th><th>Provider</th><th>Scopes</th><th>Targets</th><th></th></tr></thead><tbody>
      {#each filtered as c}<tr><td><strong>{c.name}</strong>{#if c.passphrase_protected}<div class="muted">protected key</div>{/if}{#if c.storage_class==='bootstrap'}<div class="muted">bootstrap · non-exportable</div>{/if}</td><td>{c.type||'secret'}</td><td>{c.provider||'local'}</td><td class="mono">{(c.scopes||[]).join(', ')||'—'}</td><td class="mono">{(c.allowed_hosts||[]).join(', ')||'all/unspecified'}</td><td><button class="btn small" on:click={()=>open(c)}>Open</button></td></tr>{/each}
      </tbody></table>{#if !filtered.length}<div class="empty">No matching credentials.</div>{/if}</div>
    </section>
    <section class="panel">
      <div class="panel-head"><h2>Credential details</h2></div>
      <div class="panel-body">
        {#if selected}
          <div class="detail-grid">
            <div class="detail-item"><div class="k">Name</div><div class="v">{selected.name}</div></div>
            <div class="detail-item"><div class="k">Type</div><div class="v">{selected.type||'secret'}</div></div>
            <div class="detail-item"><div class="k">Provider</div><div class="v">{selected.provider||'local'}</div></div>
            <div class="detail-item"><div class="k">Storage class</div><div class="v">{selected.storage_class||'managed'}{selected.exportable===false?' · non-exportable':''}</div></div>
            <div class="detail-item"><div class="k">Protection</div><div class="v">{selected.passphrase_protected?'Passphrase protected':'Standard vault protection'}</div></div>
            <div class="detail-item"><div class="k">Public key</div><div class="v">{selected.public_key?'Available':'Not applicable'}</div></div>
          </div>
          <div class="stack" style="margin-top:1rem">
            <label class="field"><span>Allowed scopes</span><input bind:value={selected.scopesText}/></label>
            <div class="field"><span>Allowed hosts / groups</span>
              <div class="selection-grid">
                {#each inventoryHosts() as h}
                  <label class="selection-card"><input type="checkbox" checked={hasTarget(selected.hostsText,'host:'+h)} on:change={()=>toggleTarget('host:'+h,'selected')}/><span><strong>Host: {h}</strong><small>{inventory.hosts[h]?.hostname||inventory.hosts[h]?.address||''}</small></span></label>
                {/each}
                {#each inventoryGroups() as g}
                  <label class="selection-card"><input type="checkbox" checked={hasTarget(selected.hostsText,'group:'+g)} on:change={()=>toggleTarget('group:'+g,'selected')}/><span><strong>Group: {g}</strong><small>{inventory.groups[g]?.description||((inventory.groups[g]?.hosts||[]).length+' member hosts')}</small></span></label>
                {/each}
                {#if !inventoryHosts().length&&!inventoryGroups().length}<div class="muted">No inventory targets are configured.</div>{/if}
              </div>
              {#if targetList(selected.hostsText).length}<div class="chip-row">{#each targetList(selected.hostsText) as t}<span class="pill">{targetLabel(t)}</span>{/each}</div>{/if}
            </div>
            {#if selected.type==='ssh-key'}<label class="field"><span>Login username</span><input bind:value={selected.loginUsername} autocomplete="username"/></label>{:else if selected.username}<div class="muted">Login: {selected.username}{selected.domain?' ('+selected.domain+')':''}</div>{/if}
            {#if selected.public_key}<div><button class="btn" on:click={()=>navigator.clipboard.writeText(selected.public_key)}>Copy public key</button></div>{/if}
            <hr style="border:0;border-top:1px solid var(--line);width:100%"/>
            <label class="field"><span>Rename credential</span><input bind:value={selected.newName}/></label>
            <div class="actions"><button class="btn primary" on:click={saveSelected}>Save</button>{#if (selected.provider||'local')==='local'&&selected.storage_class!=='bootstrap'}<button class="btn" on:click={()=>confirm('Pin this credential to the local bootstrap provider? This marks it non-exportable.')&&pinLocal()}>Pin local</button>{/if}<button class="btn danger" on:click={()=>confirm('Delete this credential?')&&deleteSelected()}>Delete</button></div>
          </div>
        {:else}<div class="empty">Select a credential to inspect scopes, targets, and administrative options.</div>{/if}
      </div>
    </section>
  </div>
  {#if result}<div class="notice" style="margin-top:1rem">{result}</div>{/if}
</div>

{#if wizard}
<div class="modal-backdrop">
  <section class="modal panel">
    <div class="panel-head"><h2>{sourceRequest?'Provide requested credential':'Add credential'}</h2><span class="spacer"></span><span class="pill">Step {step} of 4</span><button class="btn small subtle" on:click={closeWizard}>Close</button></div>
    <div class="wizard-steps">
      <button class:active={step===1} on:click={()=>goStep(1)}>Type</button>
      <button class:active={step===2} on:click={()=>goStep(2)}>Access</button>
      <button class:active={step===3} on:click={()=>goStep(3)}>{form.kind==='ssh-generate'||form.kind==='ssh-import'?'Key':'Credential'}</button>
      <button class:active={step===4} on:click={()=>goStep(4)}>Review</button>
    </div>
    <div class="panel-body stack">
      {#if sourceRequest}<div class="notice warn"><strong>{sourceRequest.project}</strong> requested <span class="mono">{sourceRequest.name}</span>. {sourceRequest.instructions||sourceRequest.purpose||''}</div>{/if}
      {#if step===1}
        <div class="form-grid">
          <label class="field wide"><span>Credential type</span>
            <select value={form.type} on:change={(e)=>setType(e.currentTarget.value)}>
              <option value="api-token">API token / API key</option>
              <option value="password">Username and password</option>
              <option value="client-secret">Client secret</option>
              <option value="active-directory">Active Directory</option>
              <option value="ssh-generate">SSH key — generate new</option>
              <option value="ssh-import">SSH key — import existing</option>
              <option value="secret">Other secret</option>
            </select>
          </label>
          <label class="field"><span>Credential name</span><input bind:value={form.name}/></label>
          <label class="field"><span>Project / application</span><input bind:value={form.project}/></label>
          <label class="field"><span>Purpose</span><input bind:value={form.purpose}/></label>
        </div>
      {:else if step===2}
        <div class="form-grid">
          <label class="field wide"><span>Allowed scopes / capabilities</span><input bind:value={form.scopes} placeholder="deploy, dns, gitlab"/></label>
        </div>
        <div class="field"><span>Allowed hosts or groups</span>
          <div class="selection-grid">
            {#each inventoryHosts() as h}
              <label class="selection-card"><input type="checkbox" checked={hasTarget(form.hosts,'host:'+h)} on:change={()=>toggleTarget('host:'+h)}/><span><strong>Host: {h}</strong><small>{inventory.hosts[h]?.hostname||inventory.hosts[h]?.address||''}</small></span></label>
            {/each}
            {#each inventoryGroups() as g}
              <label class="selection-card"><input type="checkbox" checked={hasTarget(form.hosts,'group:'+g)} on:change={()=>toggleTarget('group:'+g)}/><span><strong>Group: {g}</strong><small>{inventory.groups[g]?.description||((inventory.groups[g]?.hosts||[]).length+' member hosts')}</small></span></label>
            {/each}
            {#if !inventoryHosts().length&&!inventoryGroups().length}<div class="muted">No inventory targets are configured yet. Add hosts or groups from Inventory first.</div>{/if}
          </div>
          {#if targetList(form.hosts).length}<div class="chip-row">{#each targetList(form.hosts) as t}<span class="pill">{targetLabel(t)}</span>{/each}</div>{/if}
        </div>
        <div class="muted">Empty targets means unrestricted by inventory metadata. Prefer group assignments for reusable credentials.</div>
      {:else if step===3}
        {#if (form.kind==='secret'&&form.type==='password')||form.kind==='ssh-generate'||form.kind==='ssh-import'}<label class="field"><span>Login username</span><input bind:value={form.login_username} autocomplete="username" placeholder="automation"/></label><div class="muted">Used on assigned hosts. Inventory does not need a username.</div>{/if}
        {#if form.kind==='secret'}
          {#if form.type==='password'}<label class="field"><span>Password</span><input type="password" bind:value={form.secret} autocomplete="new-password"/></label>{:else}
          <label class="field"><span>Credential value</span><textarea bind:value={form.secret} autocomplete="off" placeholder="Write-only; the value will not be displayed again."></textarea></label>
          {/if}
        {:else if form.kind==='ad'}
          <div class="form-grid">
            <label class="field wide"><span>AD domain / realm</span><input bind:value={form.ad_domain} placeholder="example.org"/></label>
            <label class="field"><span>Username</span><input bind:value={form.ad_username} autocomplete="username"/></label>
            <label class="field"><span>Password</span><input type="password" bind:value={form.ad_password} autocomplete="new-password"/></label>
          </div>
          <div class="muted">Stored as one write-only Active Directory credential object for LDAP, Kerberos, WinRM, SMB, or domain-join handles.</div>
        {:else if form.kind==='ssh-generate'}
          <label><input type="checkbox" bind:checked={form.protect}/> Protect generated key with an appliance-generated passphrase</label>
          <label class="field"><span>Public-key comment</span><input bind:value={form.comment}/></label>
        {:else}
          <label class="field"><span>Private SSH key</span><textarea bind:value={form.private_key} autocomplete="off" placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"></textarea></label>
          <label class="field"><span>Existing key passphrase, if any</span><input type="password" bind:value={form.passphrase}/></label>
        {/if}
      {:else}
        <div class="detail-grid">
          <div class="detail-item"><div class="k">Name</div><div class="v">{form.name||'—'}</div></div>
          <div class="detail-item"><div class="k">Type</div><div class="v">{form.kind==='ad'?'Active Directory':form.kind==='secret'?(form.type||'secret'):form.kind==='ssh-generate'?'generated ssh-key':'imported ssh-key'}</div></div>
          <div class="detail-item"><div class="k">Project</div><div class="v">{form.project||'—'}</div></div>
          <div class="detail-item"><div class="k">Purpose</div><div class="v">{form.purpose||'—'}</div></div>
          {#if form.kind==='ad'||form.login_username}<div class="detail-item"><div class="k">Login username</div><div class="v">{form.kind==='ad'?form.ad_username:form.login_username}</div></div>{/if}
          <div class="detail-item"><div class="k">Scopes</div><div class="v mono">{form.scopes||'none'}</div></div>
          <div class="detail-item"><div class="k">Targets</div><div class="v mono">{form.hosts||'all/unspecified'}</div></div>
        </div>
        <div class="notice">The secret material is write-only. After saving, the UI shows metadata and public material only.</div>
      {/if}
    </div>
    <div class="modal-actions">
      <button class="btn" disabled={step===1} on:click={()=>goStep(step-1)}>Back</button><span class="spacer"></span>
      {#if step<4}<button class="btn primary" on:click={()=>goStep(step+1)}>Next</button>{:else}<button class="btn primary" on:click={saveCredential}>Save credential</button>{/if}
    </div>
  </section>
</div>
{/if}
