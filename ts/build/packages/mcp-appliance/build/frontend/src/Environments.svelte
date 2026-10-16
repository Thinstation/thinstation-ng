<script>
  import {onMount} from 'svelte';
  import {api,json} from './lib/api.js';
  import CreateEnvironment from './CreateEnvironment.svelte';
  import {confirmationState} from './lib/environment-confirmation.js';
  import {activeStates,terminalStates,actionLabels,splitInventory,actionState,updateState,
          filterRows,chooseTargets,toggleVisible,timeLabel,stageLabel} from './lib/environment-state.js';
  import './operator.css';
  import './environments.css';

  let data=null,loading=false,loadError='',error='',notice='',tab='installed';
  let installedQuery='',catalogQuery='',stagingQuery='',selected=[],stageSelected=[],expanded='';
  let creator=null,queueFailures=[];
  let menu=null,menuTrigger=null,confirmation=null,acknowledged=false,dialog;
  let job=null,logError='',polling=false,disposed=false;
  let pending=[],queueJob=null,queueRunning=false,submitting=false,total=0,completed=0;
  let fedoraUrl='',updatesUrl='',sourceBase={fedora_url:'',updates_url:''},formLoaded=false,saving=false;
  $: inventory=splitInventory(data);
  $: installed=filterRows(inventory.installed,installedQuery);
  $: catalog=filterRows(data?.catalog||[],catalogQuery,['id','title','description']);
  $: staging=filterRows(inventory.staging,stagingQuery,['name','environment','kind','state']);
  $: visibleSelectable=installed.filter(row=>actionState(row,'check').enabled||actionState(row,'rebuild').enabled||actionState(row,'delete').enabled);
  $: allVisible=visibleSelectable.length>0&&visibleSelectable.every(row=>selected.includes(row.name));
  $: someVisible=visibleSelectable.some(row=>selected.includes(row.name));
  $: selectedUpdate=chooseTargets(inventory.installed,selected,'update');
  $: selectedRebuild=chooseTargets(inventory.installed,selected,'rebuild');
  $: selectedDelete=chooseTargets(inventory.installed,selected,'delete');
  $: stageDelete=chooseTargets(inventory.staging,stageSelected,'delete');
  $: visibleStages=staging.filter(row=>actionState(row,'delete').enabled);
  $: confirmationGate=confirmationState(confirmation,acknowledged,disabled);
  $: allCheck=inventory.installed.filter(row=>actionState(row,'check').enabled);
  $: sourcesDirty=fedoraUrl!==sourceBase.fedora_url||updatesUrl!==sourceBase.updates_url;
  $: disabled=loading||!!loadError||queueRunning||submitting||!!creator;
  $: jobs=data?.jobs||[];
  $: tabs=[['installed','Installed',inventory.installed.length],['catalog','Catalog',data?.catalog?.length||0],
           ['staging','Staging & recovery',inventory.staging.length],['operations','Operations',jobs.length],['settings','Settings',null]];

  function setSources(sources={}) {
    sourceBase={fedora_url:sources.fedora_url||'',updates_url:sources.updates_url||''};
    fedoraUrl=sourceBase.fedora_url;updatesUrl=sourceBase.updates_url;formLoaded=true;
  }
  async function refresh() {
    if(loading||disposed)return;
    loading=true;
    try {
      const next=await api('/api/operator/environments');
      if(disposed)return;
      if(!formLoaded||!sourcesDirty)setSources(next.sources);
      data=next;loadError='';
      const names=new Set(splitInventory(next).installed.map(row=>row.name));
      selected=selected.filter(name=>names.has(name));
      const stages=new Set(splitInventory(next).staging.map(row=>row.name));stageSelected=stageSelected.filter(name=>stages.has(name));
    } catch(e) {loadError=e.message;} finally {loading=false;}
  }
  function chooseTab(value) {tab=value;closeMenu();expanded='';}
  function tabKey(event,index) {
    let next=index;
    if(event.key==='ArrowRight')next=(index+1)%tabs.length;
    else if(event.key==='ArrowLeft')next=(index+tabs.length-1)%tabs.length;
    else if(event.key==='Home')next=0;
    else if(event.key==='End')next=tabs.length-1;
    else return;
    event.preventDefault();chooseTab(tabs[next][0]);
    document.getElementById('env-tab-'+tabs[next][0])?.focus();
  }
  function toggle(name,checked) {selected=checked?[...new Set([...selected,name])]:selected.filter(value=>value!==name);}
  function closeMenu(focus=false) {menu=null;if(focus)menuTrigger?.focus();}
  function openMenu(event,row) {
    if(menu?.row.name===row.name){closeMenu(true);return;}
    menuTrigger=event.currentTarget;
    const rect=menuTrigger.getBoundingClientRect();
    menu={row,left:Math.max(12,Math.min(innerWidth-272,rect.right-260)),top:Math.max(12,Math.min(rect.bottom+5,innerHeight-340))};
  }
  function outside(event) {if(menu&&!event.target.closest('.env-menu,.env-row-menu'))closeMenu();}
  function keydown(event) {
    if(event.key==='Escape'){closeMenu(true);if(confirmation)cancelConfirmation();}
    if(confirmation&&event.key==='Tab'&&dialog){
      const items=[...dialog.querySelectorAll('button:not(:disabled),input:not(:disabled)')];
      const first=items[0],last=items.at(-1);
      if(event.shiftKey&&(document.activeElement===first||document.activeElement===dialog)){event.preventDefault();last?.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
    }
  }
  function focusDialog(node) {node.focus();}
  function focusMenu(node) {node.querySelector('button:not(:disabled)')?.focus();}
  function cancelConfirmation(){confirmation=null;acknowledged=false;menuTrigger?.focus();}
  function propose(action,rows) {
    closeMenu();error='';notice='';
    if(disabled||!rows.length)return;
    if(action==='check'){runQueue(action,rows);return;}
    confirmation={action,rows:[...rows]};acknowledged=false;
  }
  async function confirmOperation() {
    if(!confirmationState(confirmation,acknowledged,disabled).ready)return;
    const {action,rows}=confirmation;
    await runQueue(action,rows);
  }
  async function runQueue(action,rows) {
    pending=rows.map(row=>({name:row.name,action,...(action==='delete'?{delete_token:row.delete_token,confirmation:'DELETE '+row.name}:{})}));
    queueFailures=[];
    total=pending.length;completed=0;queueRunning=true;confirmation=null;error='';
    await submitNext();
  }
  async function submitNext() {
    if(disposed||submitting||queueJob)return;
    if(!pending.length){queueRunning=false;notice=`Finished ${completed} of ${total} environment operations.${queueFailures.length?' '+queueFailures.length+' failed; see Operations.':''}`;return;}
    const next=pending[0];pending=pending.slice(1);submitting=true;
    try {
      const result=await json('/api/operator/environments/start','POST',next);
      if(!result?.id)throw new Error('The worker did not return a job identifier.');
      queueJob=result;job=result;
      if(!disposed)await refresh();
    } catch(e) {
      error=`${next.name}: ${e.message} Remaining operations were not submitted.`;
      if(next.action==='check'){completed++;queueFailures=[...queueFailures,next.name];}else{pending=[];queueRunning=false;}
    } finally {submitting=false;}
    if(queueRunning&&!queueJob&&!disposed)await submitNext();
  }
  function stopQueue() {pending=[];notice='No further operations will be submitted. The current worker will finish.';}
  async function viewJob(id) {
    if(!id)return;
    closeMenu();logError='';
    try{job=await api('/api/operator/environments/jobs/'+encodeURIComponent(id));}catch(e){logError=e.message;}
  }
  async function poll() {
    if(polling||disposed)return;
    polling=true;
    try {
      if(queueJob){
        const id=queueJob.id;
        const result=await api('/api/operator/environments/jobs/'+encodeURIComponent(id));
        if(disposed)return;
        queueJob=result;if(job?.id===id)job=result;logError='';
        if(terminalStates.has(result.state)){
          completed++;queueJob=null;
          if(result.state==='failed'||['canceled','cancelled'].includes(result.state)){
            queueFailures=[...queueFailures,result.name];
            if(result.action==='check'){notice=`Check failed for ${result.name}; checking remaining environments.`;}
            else{pending=[];queueRunning=false;error=`${result.name}: ${result.error||'operation failed'}. Remaining operations were not submitted.`;}
          }
          await refresh();if(queueRunning&&!disposed)await submitNext();
        }
      } else if(job?.id&&activeStates.has(job.state)) {
        await viewJob(job.id);
        if(job&&!activeStates.has(job.state))await refresh();
      } else if((data?.jobs||[]).some(row=>activeStates.has(row.state)))await refresh();
    } catch(e) {logError='Job status is unavailable; the queue is paused until status can be verified. '+e.message;}
    finally {polling=false;}
  }
  async function created(value){creator=null;job=value;notice='Creation queued for '+value.name+'. Track it in Operations.';await refresh();}
  async function saveSources() {
    if(saving||!sourcesDirty)return;
    saving=true;error='';notice='';
    try {
      const result=await json('/api/operator/environments/sources/save','POST',{fedora_url:fedoraUrl,updates_url:updatesUrl,fallback:false});
      setSources(result);data={...data,sources:result};notice='Package sources saved. No environment has been updated.';
    } catch(e){error=e.message;}finally{saving=false;}
  }
  onMount(()=>{disposed=false;refresh();const timer=setInterval(poll,3000);return()=>{disposed=true;pending=[];clearInterval(timer);};});
</script>

<svelte:window on:click={outside} on:keydown={keydown} on:resize={()=>closeMenu()}/>
<div class="page operator-page environment-page">
  <div class="page-title"><div><h1>Environments</h1><p>Manage persistent execution environments independently of the appliance OS.</p></div><div class="actions"><button class="btn primary" disabled={disabled||!data?.capabilities?.install} on:click={()=>chooseTab('catalog')}>New environment</button><button class="btn" on:click={refresh} disabled={loading}>{loading?'Refreshing...':'Refresh'}</button></div></div>
  {#if loadError}<div class="notice warn" role="alert">Could not refresh environments. {loadError} {data?'Showing the last inventory; environment actions are disabled.':''}</div>{/if}
  {#if error}<div class="notice bad" role="alert">{error}</div>{/if}
  {#if notice}<div class="notice" role="status">{notice}</div>{/if}
  {#if queueRunning}<div class="notice env-queue" role="status"><span>{completed} of {total} finished. {queueJob?`${actionLabels[queueJob.action]}: ${queueJob.name}`:'Submitting next job...'} {pending.length} waiting.</span><button class="btn small" on:click={stopQueue} disabled={!pending.length}>Stop after current</button></div>{/if}
  <div class="operator-tabs" role="tablist" aria-label="Environment sections">
    {#each tabs as entry,index}<button role="tab" id={'env-tab-'+entry[0]} aria-selected={tab===entry[0]} aria-controls={'env-panel-'+entry[0]} tabindex={tab===entry[0]?0:-1} class:active={tab===entry[0]} on:click={()=>chooseTab(entry[0])} on:keydown={event=>tabKey(event,index)}>{entry[1]}{#if data&&entry[2]!==null}<span class="env-count">{entry[2]}</span>{/if}</button>{/each}
  </div>
  {#if !data}<section class="panel"><div class="env-empty">{loading?'Reading environment inventory...':'Environment inventory is unavailable. Use Refresh to retry.'}</div></section>
  {:else}
    <div class="panel" role="tabpanel" id={'env-panel-'+tab} aria-labelledby={'env-tab-'+tab}>
      {#if tab==='installed'}
        <div class="panel-head"><div class="env-panel-title"><h2>Installed environments</h2><p>{inventory.installed.length} environments. Internal staging and retained copies are listed separately.</p></div></div>
        <div class="env-toolbar">
          <label class="field"><span>Find an environment</span><input type="search" bind:value={installedQuery} placeholder="Name, profile or operating system"/></label>
          <div class="actions"><button class="btn small" disabled={disabled||!allCheck.length} on:click={()=>propose('check',allCheck)}>Check all updates</button><button class="btn small primary" disabled={disabled||!selectedUpdate.length} on:click={()=>propose('update',selectedUpdate)}>Update selected{selectedUpdate.length?` (${selectedUpdate.length})`:''}</button><button class="btn small" disabled={disabled||!selectedRebuild.length} on:click={()=>propose('rebuild',selectedRebuild)}>Redeploy selected{selectedRebuild.length?` (${selectedRebuild.length})`:''}</button><button class="btn small danger" disabled={disabled||!selectedDelete.length} on:click={()=>propose('delete',selectedDelete)}>Delete selected{selectedDelete.length?` (${selectedDelete.length})`:''}</button></div>
          <div class="env-selection"><span>{selected.length} selected</span>{#if selected.length}<button class="btn subtle small" on:click={()=>selected=[]}>Clear selection</button>{/if}</div>
        </div>
        <div class="table-wrap"><table class="table env-table" aria-label="Installed environments">
          <colgroup><col class="env-check-col"/><col class="env-name-col"/><col class="env-os-col"/><col class="env-status-col"/><col class="env-action-col"/></colgroup>
          <thead><tr><th class="env-check-col"><input type="checkbox" aria-label="Select all visible eligible environments" checked={allVisible} indeterminate={someVisible&&!allVisible} disabled={!visibleSelectable.length||disabled} on:change={event=>selected=toggleVisible(selected,visibleSelectable,event.currentTarget.checked)}/></th><th scope="col">Environment</th><th scope="col" class="env-os-cell">Operating system</th><th scope="col">Update status</th><th scope="col" class="env-action-col">Actions</th></tr></thead>
          <tbody>{#each installed as env (env.name)}{@const status=updateState(env)}{@const selectable=actionState(env,'check').enabled||actionState(env,'rebuild').enabled||actionState(env,'delete').enabled}
            <tr class:selected={selected.includes(env.name)}><td class="env-check-col"><input type="checkbox" aria-label={'Select '+env.name} checked={selected.includes(env.name)} disabled={disabled||!selectable} on:change={event=>toggle(env.name,event.currentTarget.checked)}/></td><td><button class="env-name" aria-expanded={expanded===env.name} on:click={()=>expanded=expanded===env.name?'':env.name}>{env.title||env.name}</button>{#if env.title&&env.title!==env.name}<span class="env-meta mono">{env.name}</span>{/if}<span class="env-meta">{env.description}</span><span class="env-mobile-meta">{env.os} / {env.package_manager==='none'?'No package manager':env.package_manager?.toUpperCase()}</span></td><td class="env-os-cell">{env.os}<span class="env-meta">{env.package_manager==='none'?'Package manager unavailable':env.package_manager?.toUpperCase()}</span></td><td><span class="pill" class:good={status.tone==='good'} class:warn={status.tone==='warn'} class:bad={status.tone==='bad'}>{status.label}</span><span class="env-meta">{env.last_checked?'Checked '+timeLabel(env.last_checked):env.last_check_attempt?'Attempted '+timeLabel(env.last_check_attempt):'No completed check recorded'}</span></td><td class="env-action-col"><button class="btn small env-row-menu" aria-label={'Actions for '+env.name} aria-expanded={menu?.row.name===env.name} on:click={event=>openMenu(event,env)}>&#8942;</button></td></tr>
            {#if expanded===env.name}<tr class="env-detail-row"><td colspan="5"><div class="env-detail"><h3>Environment details</h3><dl><dt>Environment ID</dt><dd class="mono">{env.name}</dd><dt>Root directory</dt><dd class="mono">{data.root}/{env.name}</dd><dt>Definition</dt><dd>{env.rebuild_available?'Stored definition available for redeployment.':'No validated stored definition is available.'}</dd><dt>Profile tools</dt><dd><div class="env-tools">{#each env.key_packages||[] as tool}<code>{tool}</code>{/each}{#if !env.key_packages?.length}Not recorded{/if}</div></dd><dt>Latest operation</dt><dd>{env.operation_action?actionLabels[env.operation_action]||env.operation_action:'None recorded'}{env.operation_state?' / '+env.operation_state:''}{#if env.latest_job} <button class="btn small" on:click={()=>viewJob(env.latest_job)}>View latest log</button>{/if}</dd></dl></div></td></tr>{/if}
          {/each}</tbody>
        </table></div>
        {#if !installed.length}<div class="env-empty"><h3>{inventory.installed.length?'No matching environments':'No environments installed'}</h3><p>{inventory.installed.length?'Try a different search.':'Open Catalog to inspect available profiles.'}</p></div>{/if}
        <div class="env-footer"><p>Showing {installed.length} of {inventory.installed.length}. Check all updates includes all eligible installed environments, not only the current filter.</p><p>Bulk work runs one environment at a time while this page stays open. Leaving stops further submissions; an already submitted job continues.</p></div>
      {:else if tab==='catalog'}
        <div class="panel-head"><div class="env-panel-title"><h2>Environment catalog</h2><p>Available profiles, their intended tools and supported base systems.</p></div></div>
        <div class="env-toolbar"><label class="field"><span>Find a profile</span><input type="search" bind:value={catalogQuery} placeholder="Profile name or purpose"/></label><span class="env-caption">{catalog.length} of {data.catalog?.length||0} profiles</span></div>
        <div class="table-wrap"><table class="table env-table" aria-label="Environment catalog"><colgroup><col class="env-name-col"/><col class="env-os-col"/><col class="env-status-col"/></colgroup><thead><tr><th scope="col">Profile</th><th scope="col" class="env-os-cell">Supported bases</th><th scope="col">Availability</th></tr></thead><tbody>
          {#each catalog as item (item.id)}<tr><td><button class="env-name" aria-expanded={expanded===item.id} on:click={()=>expanded=expanded===item.id?'':item.id}>{item.title}</button><span class="env-meta">{item.description}</span><span class="env-mobile-meta">{item.supported_bases?.join(' / ')}</span></td><td class="env-os-cell">{item.supported_bases?.join(' / ')||'Not specified'}</td><td><span class="pill" class:good={item.installed}>{item.installed?'Installed':'Available profile'}</span><span class="env-meta">{item.install_note}</span><button class="btn small primary" disabled={disabled||!item.install_available} on:click={()=>creator=item}>Create</button></td></tr>
            {#if expanded===item.id}<tr class="env-detail-row"><td colspan="3"><div class="env-detail"><h3>{item.title}</h3><dl><dt>Profile ID</dt><dd class="mono">{item.id}</dd><dt>Intended tools</dt><dd><div class="env-tools">{#each item.key_packages||[] as tool}<code>{tool}</code>{/each}</div></dd><dt>Provisioning</dt><dd>{item.install_note} Use Create to choose a name and base, then review the exact package recipe.</dd></dl></div></td></tr>{/if}
          {/each}
        </tbody></table></div>{#if !catalog.length}<div class="env-empty">No profiles match this search.</div>{/if}
        <div class="env-footer">Profile contents describe the definition, not a live verification that every listed tool is installed.</div>
      {:else if tab==='staging'}
        <div class="panel-head"><div class="env-panel-title"><h2>Staging &amp; recovery</h2><p>In-progress or leftover build directories and retained previous copies. These are not installed environments.</p></div></div>
        <div class="env-toolbar"><label class="field"><span>Find a staging entry</span><input type="search" bind:value={stagingQuery} placeholder="Directory, environment or state"/></label><span class="env-caption">{staging.length} entries / {stageSelected.length} selected</span><button class="btn small danger" disabled={disabled||!stageDelete.length} on:click={()=>propose('delete',stageDelete)}>Delete selected staging{stageDelete.length?` (${stageDelete.length})`:''}</button></div>
        <div class="table-wrap"><table class="table env-table" aria-label="Staging and recovery entries"><colgroup><col class="env-check-col"/><col class="env-name-col"/><col class="env-status-col"/><col class="env-os-col"/><col class="env-action-col"/></colgroup><thead><tr><th class="env-check-col"><input type="checkbox" aria-label="Select all eligible staging entries" disabled={disabled||!visibleStages.length} checked={visibleStages.length>0&&visibleStages.every(row=>stageSelected.includes(row.name))} on:change={event=>stageSelected=toggleVisible(stageSelected,visibleStages,event.currentTarget.checked)}/></th><th scope="col">Directory</th><th scope="col">Purpose / state</th><th scope="col" class="env-os-cell">Last modified</th><th scope="col">Actions</th></tr></thead><tbody>
          {#each staging as row (row.name)}<tr><td class="env-check-col"><input type="checkbox" aria-label={'Select staging '+row.name} disabled={disabled||!actionState(row,'delete').enabled} checked={stageSelected.includes(row.name)} on:change={event=>stageSelected=toggleVisible(stageSelected,[row],event.currentTarget.checked)}/></td><td><span class="mono">{row.name}</span>{#if row.environment}<span class="env-meta">For {row.environment}</span>{/if}<span class="env-mobile-meta">{timeLabel(row.modified_at)}</span></td><td><span class="pill" class:bad={row.state==='failed'}>{stageLabel(row)}</span><span class="env-meta">{row.state||'No matching job recorded'}</span></td><td class="env-os-cell">{timeLabel(row.modified_at)}</td><td>{#if row.latest_job}<button class="btn small" on:click={()=>viewJob(row.latest_job)}>View</button>{/if}<button class="btn small danger" title={row.delete_reason} disabled={disabled||!actionState(row,'delete').enabled} on:click={()=>propose('delete',[row])}>Delete</button></td></tr>{/each}
        </tbody></table></div>{#if !staging.length}<div class="env-empty">{inventory.staging.length?'No entries match this search.':'No staging or retained recovery directories found.'}</div>{/if}
        <div class="env-footer">No automatic cleanup is performed. A directory may still be mounted or referenced by a running process.</div>
      {:else if tab==='operations'}
        <div class="panel-head"><div class="env-panel-title"><h2>Recent operations</h2><p>Worker status and logs, separate from package update availability.</p></div></div>
        <div class="table-wrap"><table class="table env-table" aria-label="Environment operations"><thead><tr><th scope="col">Environment / action</th><th scope="col">State</th><th scope="col" class="env-os-cell">Created</th><th scope="col" class="env-action-col">Log</th></tr></thead><tbody>{#each jobs as operation (operation.id)}<tr><td><strong>{operation.name}</strong><span class="env-meta">{actionLabels[operation.action]||operation.action}</span><span class="env-mobile-meta">{timeLabel(operation.created_at)}</span></td><td><span class="pill" class:bad={operation.state==='failed'} class:good={['completed','succeeded'].includes(operation.state)}>{operation.state}</span></td><td class="env-os-cell">{timeLabel(operation.created_at)}</td><td><button class="btn small" on:click={()=>viewJob(operation.id)}>View</button></td></tr>{/each}</tbody></table></div>
        {#if !jobs.length}<div class="env-empty">No recent operations were returned by the backend.</div>{/if}<div class="env-footer">The most recent {jobs.length} recorded operations. Opening a log does not rerun the operation.</div>
      {:else if tab==='settings'}
        <div class="panel-head"><div class="env-panel-title"><h2>Package sources</h2><p>Preferred Fedora repositories for execution-environment package operations.</p></div><span class="pill">{data.sources?.source||'Default configuration'}</span></div>
        <form class="panel-body env-form" on:submit|preventDefault={saveSources}>
          <p class="env-caption">Leave either field empty to use its upstream Fedora source. These settings do not change the immutable appliance OS.</p>
          <div class="form-grid"><label class="field wide"><span>Fedora base repository URL</span><input bind:value={fedoraUrl} disabled={saving} autocomplete="off" spellcheck="false" placeholder="https://mirror.example/fedora/$releasever/$basearch/"/><small class="env-caption">The $releasever and $basearch placeholders are expanded by the worker.</small></label><label class="field wide"><span>Fedora updates repository URL</span><input bind:value={updatesUrl} disabled={saving} autocomplete="off" spellcheck="false" placeholder="https://mirror.example/updates/$releasever/$basearch/"/></label></div>
          <div class="env-settings-help">HTTPS only, without embedded credentials or URL fragments. Automatic fallback after a mirror failure is not available. Ubuntu and other distribution sources remain managed by their environment definitions.</div>
          <div class="actions"><button type="submit" class="btn primary" disabled={saving||!sourcesDirty}>{saving?'Saving...':'Save changes'}</button><button type="button" class="btn" disabled={saving||!sourcesDirty} on:click={()=>setSources(sourceBase)}>Reset changes</button><span class="env-caption" role="status">{sourcesDirty?'Unsaved changes':'No pending changes'}</span></div>
        </form>
      {/if}
    </div>
  {/if}
  {#if job||logError}<section class="panel env-job" aria-label="Operation log"><div class="panel-head"><div class="env-panel-title"><h2>Operation log</h2>{#if job}<p>{job.name} / {actionLabels[job.action]||job.action}</p>{/if}</div>{#if job}<span class="pill" class:bad={job.state==='failed'}>{job.state}</span><button class="btn small" disabled={polling} on:click={()=>viewJob(job.id)}>Refresh log</button><button class="btn subtle small" on:click={()=>{job=null;logError='';}}>Close log</button>{/if}</div><div class="panel-body">{#if logError}<div class="notice warn" role="alert">{logError}</div>{/if}{#if job}<div class="env-caption">Job {job.id} / {job.package_source||'Package source not recorded'}</div>{#if activeStates.has(job.state)}<progress aria-label="Worker-reported progress" max="100" value={Number(job.progress)||0}></progress>{/if}{#if job.error}<p class="env-log-error">{job.error}</p>{/if}<pre aria-label="Worker log output">{job.log_tail||'No output recorded yet.'}</pre>{/if}</div></section>{/if}
</div>

{#if menu}<div class="env-menu" use:focusMenu role="group" aria-label={'Actions for '+menu.row.name} style:left={menu.left+'px'} style:top={menu.top+'px'}><button on:click={()=>{expanded=menu.row.name;closeMenu(true);}}>View details</button>{#each ['check','update','rebuild'] as action}{@const permission=actionState(menu.row,action)}<button disabled={disabled||!permission.enabled} title={permission.reason} on:click={()=>propose(action,[menu.row])}>{actionLabels[action]}</button>{/each}<hr/><button class="danger" title={menu.row.delete_reason} disabled={disabled||!actionState(menu.row,'delete').enabled} on:click={()=>propose('delete',[menu.row])}>Delete</button><small>Active mounts or processes block deletion. Redeploy requires a stored definition.</small></div>{/if}
{#if confirmation}
  <div class="modal-backdrop">
    <div class="panel modal env-confirm" role="dialog" aria-modal="true" aria-labelledby="env-confirm-title" tabindex="-1" bind:this={dialog} use:focusDialog>
      <div class="panel-head"><h2 id="env-confirm-title">{actionLabels[confirmation.action]} {confirmation.rows.length} environment{confirmation.rows.length===1?'':'s'}?</h2></div>
      <div class="panel-body">
        <p>{confirmation.action==='delete'?'Permanently removes only these selected root directories, including packages and local files inside them. Stored definitions are archived. External paths are not deleted. Mounted or active roots are refused.':confirmation.action==='rebuild'?'Redeploy recreates each environment from its stored definition. Local customizations may be lost. Workers must pass their existing checks before replacing an environment.':'Package updates modify each selected environment and may affect tools used by active workloads.'}</p>
        <ul aria-label="Selected targets">{#each confirmation.rows as row}<li>{#if row.title&&row.title!==row.name}{row.title} {/if}<code>{row.name}</code></li>{/each}</ul>
        <p class="env-caption">Operations are submitted one at a time. Keep this page open; a failed job stops the remaining queue.</p>
        <label for="env-confirm-reviewed" class="env-confirm-review"><input id="env-confirm-reviewed" type="checkbox" bind:checked={acknowledged}/><span>I have reviewed these targets and the effect of this operation.</span></label>
        <p id="env-confirm-status" class="env-confirm-status" class:good={confirmationGate.ready} role="status" aria-live="polite">{confirmationGate.message}</p>
      </div>
      <div class="modal-actions"><button class="btn" on:click={cancelConfirmation}>Cancel</button><span class="spacer"></span><button class="btn" class:danger={confirmation.action==='delete'} class:primary={confirmation.action!=='delete'} disabled={!confirmationGate.ready} aria-describedby="env-confirm-status" on:click={confirmOperation}>Confirm {actionLabels[confirmation.action].toLowerCase()}</button></div>
    </div>
  </div>
{/if}

{#if creator}<CreateEnvironment profile={creator} existing={inventory.installed.map(row=>row.name)} onClose={()=>creator=null} onCreated={created}/>{/if}
