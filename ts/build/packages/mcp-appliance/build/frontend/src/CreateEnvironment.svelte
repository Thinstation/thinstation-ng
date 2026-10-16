<script>
  import {onMount} from 'svelte';
  import {json} from './lib/api.js';
  import {validName} from './lib/environment-state.js';
  export let profile;
  export let existing=[];
  export let onClose;
  export let onCreated;
  let name='',base=profile.bases?.[0]?.id||'',release=profile.bases?.[0]?.releases?.at(-1)||'';
  let plan=null,error='',busy=false,acknowledged=false,dialog;
  const priorFocus=document.activeElement;
  $: option=profile.bases?.find(item=>item.id===base);
  $: duplicate=existing.includes(name);
  $: nameError=!name?'Enter an environment name.':!validName(name)?'Use 1-63 lowercase letters, numbers or hyphens; start with a letter.':duplicate?'An environment with that name already exists.':'';
  function suggest() {
    const prefix=profile.id+'-'+(base==='fedora'?'f':base==='ubuntu'?'u':base)+'-'+release.replaceAll('.','');
    name=prefix;
    for(let i=2;existing.includes(name);i++)name=prefix+'-'+i;
  }
  function changeBase() {release=profile.bases.find(item=>item.id===base)?.releases?.at(-1)||'';plan=null;}
  function close() {if(busy)return;onClose();priorFocus?.focus();}
  function keys(event) {
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close();return;}
    if(event.key!=='Tab'||!dialog)return;
    const focusable=[...dialog.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled)')];
    const first=focusable[0],last=focusable.at(-1);
    if(event.shiftKey&&(document.activeElement===first||document.activeElement===dialog)){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  }
  async function review() {
    if(nameError||busy)return;
    busy=true;error='';
    try{plan=await json('/api/operator/environments/plan','POST',{name,profile:profile.id,base,release});acknowledged=false;}
    catch(e){error=e.message;}finally{busy=false;}
  }
  async function create() {
    if(!plan||!acknowledged||busy)return;
    busy=true;error='';
    try{
      const job=await json('/api/operator/environments/start','POST',{action:'install',name,profile:profile.id,base,release,plan_token:plan.plan_token,confirmation:plan.confirmation});
      if(!job?.id)throw new Error('Creation did not return a job identifier. Refresh Operations before retrying.');
      onCreated(job);priorFocus?.focus();
    }catch(e){error=e.message;}finally{busy=false;}
  }
  onMount(()=>{suggest();dialog?.focus();});
</script>
<svelte:window on:keydown={keys}/>
<div class="modal-backdrop">
 <div class="panel modal env-create" role="dialog" aria-modal="true" aria-labelledby="env-create-title" tabindex="-1" bind:this={dialog}>
  <div class="panel-head"><div class="env-panel-title"><h2 id="env-create-title">Create environment</h2><p>{profile.title} / {plan?'2. Review and create':'1. Name and base system'}</p></div></div>
  <div class="panel-body">
   {#if error}<div role="alert" class="notice bad">{error}</div>{/if}
   {#if !plan}
    <div class="form-grid">
     <label class="field wide"><span>Environment name</span><input bind:value={name} maxlength="63" autocomplete="off" spellcheck="false" disabled={busy} aria-describedby="env-name-help"/></label>
     <p id="env-name-help" class="env-caption wide">{nameError||'This name becomes the persistent root directory. Existing roots are never overwritten.'}</p>
     <label class="field"><span>Base system</span><select bind:value={base} on:change={changeBase} disabled={busy}>{#each profile.bases||[] as item}<option value={item.id}>{item.id==='fedora'?'Fedora':item.id==='ubuntu'?'Ubuntu':item.id}</option>{/each}</select></label>
     <label class="field"><span>Release</span><select bind:value={release} disabled={busy}>{#each option?.releases||[] as value}<option value={value}>{value}</option>{/each}</select></label>
    </div>
    <p class="notice">{profile.install_note}</p>
    <p class="env-caption">Only base systems supported by this recipe and configured on this appliance are offered. Package availability is verified during provisioning.</p>
   {:else}
    <dl class="operator-details"><dt>Name</dt><dd class="mono">{plan.name}</dd><dt>Base</dt><dd>{plan.manifest.base} {plan.manifest.release}</dd><dt>Repository source</dt><dd>{plan.manifest.source} / signature verification required</dd><dt>Root directory</dt><dd class="mono">/var/prstnt/mcp-appliance/chroots/{plan.name}</dd><dt>Packages</dt><dd><div class="env-tools">{#each plan.manifest.packages as item}<code>{item}</code>{/each}</div></dd></dl>
    <p class="notice">{plan.note}</p><p>{plan.warning}</p>
    <label class="operator-check"><input type="checkbox" bind:checked={acknowledged} disabled={busy}/><span>I reviewed the name, base system and packages to create.</span></label>
   {/if}
  </div>
  <div class="modal-actions"><button class="btn" disabled={busy} on:click={close}>Cancel</button>{#if plan}<button class="btn" disabled={busy} on:click={()=>{plan=null;error='';}}>Back</button>{/if}<span class="spacer"></span>{#if plan}<button class="btn primary" disabled={busy||!acknowledged} on:click={create}>{busy?'Creating...':'Create environment'}</button>{:else}<button class="btn primary" disabled={busy||!!nameError||!release} on:click={review}>{busy?'Checking...':'Review configuration'}</button>{/if}</div>
 </div>
</div>
