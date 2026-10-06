<script>
 import { onMount, tick } from 'svelte';
 import { acknowledgement, invalidFields, timedRequest } from './lib/certificate-save.js';
 import { api } from './lib/api.js';
 import { production, staging, methods, addressText, payload, eligibleCredential } from './lib/certificate-form.js';
 const endpoint='/api/operator/certificates';
 let state=null, config=null, names='', saved='', busy=false, message='', error='', report=null, forceConfirm=false;
 let authority='production', httpSources='', caAddress='', alpnSources='';
 let statusError='', formElement, feedbackElement, attempted=false, refreshSerial=0, disposed=false;
 $: draft=config?payload(config,names,httpSources,authority,caAddress,alpnSources):null;
 $: dirty=draft&&JSON.stringify(draft)!==saved;
 $: running=['queued','running'].includes(state?.job?.state);
 $: methodList=state?.challenge_types||methods;
 $: supported=methodList.some(m=>m.value===config?.challenge&&m.enabled);
 $: adHosts=state?.ad_inventory_hosts||[];
 $: selectedAD=adHosts.find(h=>h.alias===config?.ad_host);
 $: credentialOptions=config?.dns_provider==='active-directory'?(state?.credentials||[]).filter(c=>eligibleCredential(c,selectedAD)):(state?.credentials||[]);
 $: canRequest=Boolean(supported&&config?.enabled&&!dirty&&!busy&&!running&&state?.readiness?.ready);
 $: checks=report||(!dirty?state?.readiness:null);
 $: if(dirty) forceConfirm=false;
 function acceptState(value,replace=false,seed=false){
  state=value;
  if(replace){
   config={alpn_ready:false,alpn_public_access:false,alpn_source_networks:[],http_mode:'standalone',http_source_networks:[],http_public_access:false,ad_host:'',...value.config};
   names=config.alternative_names.join('\n');httpSources=config.http_source_networks.join('\n');alpnSources=config.alpn_source_networks.join('\n');
   authority=config.internal_ca?'internal':config.directory_url===production?'production':config.directory_url===staging?'staging':'custom';
   caAddress=addressText(config.directory_url);saved=JSON.stringify(payload(config,names,httpSources,authority,caAddress,alpnSources));report=null;
   if(seed&&value.settings_saved===false&&!config.primary_domain&&value.appliance_identity?.fqdn)config.primary_domain=value.appliance_identity.fqdn;
  }
 }
 async function refresh(replace=false){
  if(busy)return;
  const serial=++refreshSerial;
  try{
   const value=await timedRequest(signal=>api(endpoint,{signal}),15000);
   if(disposed||serial!==refreshSerial||busy)return;
   acceptState(value,replace,replace&&!config);statusError='';
   if(replace){error='';message='';attempted=false}
  }catch(e){if(!disposed&&serial===refreshSerial)statusError=e.message}
 }
 onMount(()=>{refresh(true);const timer=setInterval(()=>refresh(false),5000);return()=>{disposed=true;refreshSerial++;clearInterval(timer)}});
 async function revealFeedback(){await tick();feedbackElement?.focus({preventScroll:true});feedbackElement?.scrollIntoView({block:'nearest',behavior:'instant'})}

 function changeAuthority(event){
  authority=event.currentTarget.value;config.accept_terms=false;
  if(authority==='production'){caAddress=addressText(production);config.test_only=false}
  else if(authority==='staging'){caAddress=addressText(staging);config.test_only=true}
  else{if([addressText(production),addressText(staging)].includes(caAddress))caAddress='';config.test_only=false}
  report=null;
 }
 function changeMethod(event){config.challenge=event.currentTarget.value;config.http_ready=false;config.alpn_ready=false;report=null;forceConfirm=false}
 function changeServer(event){
  config.ad_host=event.currentTarget.value;
  const host=adHosts.find(h=>h.alias===config.ad_host);config.ad_server=host?.hostname||'';
  if(host){
   if(!config.ad_zone)config.ad_zone=host.hostname.split('.').slice(1).join('.');
   if(!config.ad_realm)config.ad_realm=config.ad_zone.toUpperCase();
  }
  if(!(state.credentials||[]).some(c=>c.name===config.credential&&eligibleCredential(c,host)))config.credential='';
  report=null;
 }
 function changeCredential(event){
  config.credential=event.currentTarget.value;
  const credential=(state.credentials||[]).find(c=>c.name===config.credential);
  if(config.dns_provider==='active-directory'&&credential?.domain)config.ad_realm=credential.domain.toUpperCase();
  report=null;
 }
 async function save(){
  if(busy||running||!supported)return;
  error='';message='';attempted=true;
  await tick();
  const invalid=invalidFields(formElement);
  if(invalid.length){error='Not saved. '+invalid.join(' ');await revealFeedback();return}
  const submitted=payload(config,names,httpSources,authority,caAddress,alpnSources);
  busy=true;refreshSerial++;
  try{
   const response=await timedRequest(signal=>api(endpoint+'/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(submitted),signal}),30000);
   const confirmed=acknowledgement(response);
   if(disposed)return;
   const updated=response.status||{...state,readiness:{ready:false,issues:[],warnings:[]},provider_ready:false};
   acceptState({...updated,config:confirmed},true);
   message=response.message||'Certificate settings saved. No certificate was requested.';
   statusError=response.status_warning||'';attempted=false;
  }catch(e){if(!disposed)error='Save not confirmed. '+e.message+' Your entries have been kept; correct the problem and retry.'}
  finally{busy=false;refreshSerial++}
  if(!disposed){await revealFeedback();if(!error)await refresh(false)}
 }
 async function validate(){if(busy)return;busy=true;refreshSerial++;error='';message='';try{report=await timedRequest(signal=>api(endpoint+'/validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(draft),signal}),15000);message=report.ready?'Local prerequisites are ready. Issuance still depends on CA access and domain validation.':'Resolve the prerequisites listed below.'}catch(e){error=e.message}finally{busy=false}await revealFeedback()}
 async function request(action){if(busy)return;busy=true;refreshSerial++;error='';message='';try{const r=await timedRequest(signal=>api(endpoint+'/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,confirm_force:action==='force'&&forceConfirm}),signal}),30000);message=r.message;forceConfirm=false}catch(e){error=e.message}finally{busy=false}await revealFeedback();await refresh()}
 async function authorize(kind){
  if(busy||dirty)return;busy=true;refreshSerial++;error='';message='';
  try{
   const body=kind==='automatic'?{revision:state?.authorization?.revision}:{};
   const r=await timedRequest(signal=>api(endpoint+'/authorization/'+kind,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal}),15000);
   message=r.message||'Authorization updated.';
  }catch(e){error=e.message}
  finally{busy=false}
  await revealFeedback();await refresh(false);
 }
</script>

<div class="stack certificates">
 <section class="panel">
  <div class="panel-head"><h2>Management certificate</h2><span class="spacer"></span><button class="btn small" type="button" on:click={()=>refresh(false)} disabled={busy}>Refresh status</button></div>
  <div class="panel-body stack">
   {#if state}
    <div class="actions">
     <span class:good={state.certificate.valid_now&&!state.certificate.self_issued} class:warn={state.certificate.self_issued} class:bad={!state.certificate.valid_now} class="pill">{!state.certificate.present?'Missing certificate':!state.certificate.valid_now?'Outside validity period':state.certificate.self_issued?'Self-issued certificate':'Within validity period'}</span>
     <span class="pill">ACME {state.config.enabled?'enabled':'disabled'}</span>
     {#if running}<span class="pill warn">Request {state.job.state}</span>{/if}
    </div>
    <div class="detail-grid">
     <div class="detail-item"><div class="k">Subject</div><div class="v">{state.certificate.subject||'Not available'}</div></div>
     <div class="detail-item"><div class="k">Issuer</div><div class="v">{state.certificate.issuer||'Not available'}</div></div>
     <div class="detail-item"><div class="k">Expires</div><div class="v">{state.certificate.not_after||'Not available'}{#if state.certificate.days_remaining!=null} ({state.certificate.days_remaining} days){/if}</div></div>
     <div class="detail-item"><div class="k">Certificate names</div><div class="v">{state.certificate.sans?.join(', ')||'Not available'}</div></div>
    </div>
    <div class="muted">{state.certificate.trust_note}</div>
   {:else}<div class="muted">Loading certificate status...</div>{/if}
  </div>
 </section>
 {#if statusError}<div class="notice warn" role="status">Status refresh: {statusError} Your current entries have not been replaced.</div>{/if}
 {#if config}
 <form class="panel" class:attempted bind:this={formElement} novalidate on:submit|preventDefault={save}>
  <div class="panel-head"><h2>ACME configuration</h2>{#if dirty}<span class="pill warn">Unsaved changes</span>{/if}</div>
  <fieldset class="panel-body stack" disabled={busy||running}>
   <label class="check"><input type="checkbox" bind:checked={config.enabled}/><span><strong>Enable ACME</strong><small>Save the configuration, then request a certificate separately.</small></span></label>
   <div class="form-grid">
    <label class="field"><span>Certificate authority</span><select bind:value={authority} on:change={changeAuthority}><option value="production">Let's Encrypt - production</option><option value="staging">Let's Encrypt - staging test</option><option value="internal">Internal CA</option><option value="custom">Other ACME CA</option></select></label>
    <label class="field"><span>Account email</span><input type="email" bind:value={config.email} placeholder="admin@example.com" autocomplete="email"/></label>
    {#if authority==='custom'||authority==='internal'}<label class="field wide"><span>CA directory address</span><div class="address-field"><span aria-hidden="true">https://</span><input aria-label="CA directory address" type="text" inputmode="url" bind:value={caAddress} on:blur={()=>caAddress=addressText(caAddress)} on:input={()=>{config.accept_terms=false;report=null}} placeholder="ca.example.com/directory" spellcheck="false"/></div><small class="muted">HTTPS is added automatically for CA communication, for every challenge type. An internal CA must already be trusted.</small></label>{/if}
    <label class="field"><span>Primary DNS name</span><input bind:value={config.primary_domain} placeholder="mcp.example.com" autocomplete="off" spellcheck="false"/><small class="muted">{authority==='internal'?'Short or fully qualified hostname. Short names are literal, but AD DNS-01 requires a fully qualified name.':'Fully qualified hostname only. Do not enter a protocol prefix.'}</small></label>
    {#if state.appliance_identity?.fqdn}<div class="field wide"><small class="muted">Appliance FQDN: <strong>{state.appliance_identity.fqdn}</strong></small>{#if config.primary_domain!==state.appliance_identity.fqdn}<button type="button" class="btn small" on:click={()=>{config.primary_domain=state.appliance_identity.fqdn;report=null}}>Use appliance FQDN</button>{/if}</div>{/if}
    <label class="field"><span>Alternative DNS names</span><textarea bind:value={names} placeholder="mcp-alias.example.com" spellcheck="false" rows="3"></textarea><small class="muted">One per line or comma-separated. Wildcards require DNS-01.{authority==='internal'?' Short hostnames are allowed only when the selected challenge method can validate a literal single-label identifier.':''}</small></label>
    <label class="field"><span>Domain validation</span><select bind:value={config.challenge} on:change={changeMethod}>{#each methodList as method}<option value={method.value} disabled={!method.enabled}>{method.label}{method.enabled?'':' - not yet integrated'}</option>{/each}{#if !methodList.some(m=>m.value===config.challenge)}<option value={config.challenge} disabled>{config.challenge} - unavailable</option>{/if}</select></label>
    <label class="field"><span>Key algorithm</span><select bind:value={config.key_algorithm}><option value="prime256v1">ECDSA P-256</option><option value="secp384r1">ECDSA P-384</option><option value="rsa">RSA-4096</option></select></label>
   </div>
   {#if authority==='internal'}<div class="notice">Internal names remain exactly as entered. The CA must permit and validate short names literally. <strong>Active Directory DNS-01 requires fully qualified certificate names</strong>; ACME validation does not apply the AD DNS search suffix to a single-label identifier. HTTPS trust verification remains enabled.</div>{/if}
   {#if config.challenge==='dns-01'}
    <label class="field"><span>DNS provider</span><select bind:value={config.dns_provider} on:change={()=>{report=null;forceConfirm=false}}><option value="active-directory">Active Directory DNS (Kerberos)</option><option value="custom">Custom DNS hook (advanced)</option></select></label>
    {#if config.dns_provider==='active-directory'}
     <div class="form-grid">
      <label class="field wide"><span>AD DNS server</span><select aria-label="AD DNS server" bind:value={config.ad_host} on:change={changeServer}><option value="">Select a host from Inventory</option>{#each adHosts as host}<option value={host.alias}>{host.alias} - {host.hostname}</option>{/each}{#if config.ad_host&&!selectedAD}<option value={config.ad_host} disabled>{config.ad_host} - no longer available</option>{/if}</select><small class="muted">Windows inventory hosts with a full DNS hostname. Selecting a host does not prove it runs AD DNS; Test AD connection checks that.</small></label>
      {#if !adHosts.length}<div class="notice warn">Add the domain controller as a Windows host with its canonical hostname in Inventory first.</div>{/if}
      {#if selectedAD}<div class="muted wide">Server: <strong>{selectedAD.hostname}</strong>{selectedAD.groups.length?' | Groups: '+selectedAD.groups.join(', '):''}</div>{/if}
      <label class="field"><span>AD DNS zone</span><input bind:value={config.ad_zone} placeholder="example.com" autocomplete="off" spellcheck="false"/></label>
      <label class="field"><span>Kerberos realm</span><input bind:value={config.ad_realm} placeholder="EXAMPLE.COM" autocomplete="off" spellcheck="false"/><small class="muted">Must match the domain in the selected AD credential.</small></label>
      <label class="field"><span>Challenge TTL (seconds)</span><input type="number" min="30" max="3600" step="1" bind:value={config.ad_ttl}/></label>
      <label class="field"><span>DNS propagation timeout (seconds)</span><input type="number" min="10" max="180" step="1" bind:value={config.ad_propagation_timeout}/></label>
     </div>
     <div class="notice">Uses secure Kerberos DNS updates without joining the appliance to AD. Select an Active Directory credential with the <code>acme</code> scope; its allowed targets must include this host or one of its inventory groups. Delegate DNS permissions to the service account, not Domain Admin access. The CA must see this internal DNS zone.</div>
    {/if}
    <div class="form-grid">
     {#if config.dns_provider==='custom'}<label class="field"><span>Installed DNS hook</span><select bind:value={config.dns_hook}><option value="">Select an integration</option>{#each state.dns_hooks as hook}<option value={hook}>{hook}</option>{/each}</select></label>{/if}
     <label class="field"><span>Vault credential</span><select aria-label="Vault credential" bind:value={config.credential} on:change={changeCredential}><option value="">{config.dns_provider==='active-directory'?'Select an assigned AD credential':'None - integration manages authentication'}</option>{#each credentialOptions as credential}<option value={credential.name}>{credential.name}</option>{/each}{#if config.credential&&!credentialOptions.some(c=>c.name===config.credential)}<option value={config.credential} disabled>{config.credential} - not eligible for this host</option>{/if}</select><small class="muted">{config.dns_provider==='active-directory'?'Only AD credentials with acme scope and matching host/group assignments are shown.':'Uses an authorized acme lease or grant.'} Secret values are never shown here.</small></label>
     {#if config.dns_provider==='active-directory'&&config.credential}
      <div class="field wide">
       <span>Credential authorization</span>
       <div class="notice stack">
        <div><strong>Manual use:</strong> {state.authorization?.manual?'Authorized until '+new Date(state.authorization.manual.expires*1000).toLocaleTimeString():'Not authorized'}</div>
        <div><strong>Automatic renewal:</strong> {state.authorization?.automatic_authorized?'Authorized for this saved configuration':'Not authorized'}</div>
        <small>{state.authorization?.reason}</small>
       </div>
       <div class="actions">
        <button type="button" class="btn" disabled={dirty||busy||running} on:click={()=>authorize('once')}>Authorize next operation</button>
        {#if config.automatic&&!state.authorization?.automatic_authorized}<button type="button" class="btn primary" disabled={dirty||busy||running||!state.authorization?.can_authorize_automatic} on:click={()=>authorize('automatic')}>Authorize automatic renewal</button>{/if}
        {#if state.authorization?.automatic_authorized}<button type="button" class="btn danger" disabled={busy||running} on:click={()=>authorize('revoke')}>Revoke automatic authorization</button>{/if}
       </div>
      </div>
     {/if}
    </div>
    {#if config.dns_provider==='custom'&&!state.dns_hooks.length}<div class="notice warn">No DNS integration is installed. An administrator must install a root-owned executable hook in <code>{state.dns_hook_directory}</code>. This page does not upload or run arbitrary scripts.</div>{/if}
   {:else if config.challenge==='http-01'}
    <label class="field"><span>HTTP responder</span><select bind:value={config.http_mode} on:change={()=>{config.http_ready=false;report=null;forceConfirm=false}}><option value="standalone">Appliance responder (recommended)</option><option value="external">External webroot (advanced)</option></select></label>
    {#if config.http_mode==='standalone'}
     <div class="notice">Starts a temporary HTTP listener on TCP 80 for this certificate request. Only exact <code>/.well-known/acme-challenge/</code> tokens are served; no web console or directory access is exposed. The listener and temporary firewall allowance are removed after the request. The console remains on HTTPS port 8443.</div>
     <label class="check"><input type="checkbox" bind:checked={config.http_public_access} on:change={()=>{config.http_ready=false;report=null}}/><span><strong>Allow public CA validation</strong><small>Temporarily permits inbound HTTP challenges from any source. Leave off for an internal CA and specify its validator addresses below.</small></span></label>
     {#if !config.http_public_access}<label class="field"><span>Allowed CA validation sources</span><textarea bind:value={httpSources} spellcheck="false" placeholder="192.0.2.10 or 2001:db8::10/128" rows="2" on:input={()=>config.http_ready=false}></textarea><small class="muted">IP addresses or CIDR networks, one per line or comma-separated. Use the source address the appliance sees, including NAT or a proxy where applicable.</small></label>{/if}
     <label class="check"><input type="checkbox" bind:checked={config.http_ready}/><span>I authorize temporary port-80 access and confirm that the CA can reach this appliance for every requested hostname.</span></label>
     <div class="muted">No DNS-provider credential is needed. Normal A/AAAA resolution must point to the responder, and upstream firewalls, NAT or reverse proxies must pass the challenge path to TCP 80. Existing services on port 80 are not stopped. Wildcard names require DNS-01.</div>
    {:else}
     <div class="notice">An external HTTP server must serve <code>/.well-known/acme-challenge/</code> from <code>{state.http_webroot}</code> on port 80 for every requested name. The appliance will write challenge files but will not start a listener or change firewall rules in this mode.</div>
     <label class="check"><input type="checkbox" bind:checked={config.http_ready}/><span>I have configured and verified that HTTP challenge route.</span></label>
    {/if}
   {:else if config.challenge==='tls-alpn-01'}
    <div class="notice">Uses a temporary TLS challenge responder on TCP 443. It negotiates only <code>acme-tls/1</code> and presents the active challenge certificate for the requested hostname. The management console remains on HTTPS port 8443.</div>
    <label class="check"><input type="checkbox" bind:checked={config.alpn_public_access} on:change={()=>{config.alpn_ready=false;report=null}}/><span><strong>Allow public CA validation</strong><small>Temporarily allows TLS challenges from any source. Leave off for an internal CA.</small></span></label>
    {#if !config.alpn_public_access}<label class="field"><span>Allowed CA validation sources</span><textarea bind:value={alpnSources} spellcheck="false" placeholder="192.0.2.10 or 2001:db8::10/128" rows="2" on:input={()=>config.alpn_ready=false}></textarea><small class="muted">Validator IP addresses or CIDR networks, one per line or comma-separated.</small></label>{/if}
    <label class="check"><input type="checkbox" bind:checked={config.alpn_ready}/><span>I authorize temporary port-443 access and confirm that the CA can reach this appliance for every requested hostname.</span></label>
    <div class="muted">No DNS credential or URL prefix is needed. DNS must resolve to the appliance and any upstream proxy must pass TLS through without terminating it. Existing services on port 443 are never stopped. Wildcards require DNS-01. Temporary challenge identities, listener and firewall access are removed when the request finishes.</div>
   {:else}
    <div class="notice warn">{methodList.find(m=>m.value===config.challenge)?.reason||'This challenge method is not available in the managed certificate workflow.'} No HTTP or DNS settings apply to this selection.</div>
   {/if}
   <div class="form-grid">
    <label class="field"><span>Renew when fewer than this many days remain</span><input type="number" min="1" max="60" step="1" bind:value={config.renew_days}/></label>
    <label class="check"><input type="checkbox" bind:checked={config.automatic}/><span><strong>Automatic renewal checks</strong><small>{state.schedule}. {state.timer_active?'Renewal timer is active.':'Renewal timer is not active; enabling this setting alone does not start the timer.'}</small></span></label>
   </div>
   <label class="check"><input type="checkbox" bind:checked={config.test_only} disabled={authority==='staging'}/><span><strong>Test issuance only</strong><small>Keep the current management certificate. Staging always uses this mode.</small></span></label>
   <label class="check"><input type="checkbox" bind:checked={config.accept_terms}/><span>I have reviewed and accept the selected CA's account terms and authorize account registration when I request a certificate.</span></label>
   {#if config.challenge==='dns-01'&&config.dns_provider==='active-directory'}
    <div class="actions"><button class="btn" type="button" disabled={dirty||busy||running||!state.provider_ready} on:click={()=>request('test-provider')}>Test AD connection</button><small class="muted">Uses the saved provider and an authorized vault lease or grant. Tests authentication and zone lookup without changing DNS or requesting a certificate.</small></div>
   {/if}
   <div class="save-feedback" bind:this={feedbackElement} tabindex="-1">
    {#if error}<div class="notice bad" role="alert">{error}</div>{/if}
    {#if message}<div class="notice" role="status">{message}</div>{/if}
    {#if busy}<div class="notice" role="status">Working... Your entries are retained until the server confirms the result.</div>{/if}
   </div>
   <div class="actions"><button class="btn primary" type="submit" disabled={!dirty||!supported}>{busy?'Saving...':'Save configuration'}</button><button class="btn" type="button" on:click={validate} disabled={!supported}>Check prerequisites</button><button class="btn subtle" type="button" on:click={()=>refresh(true)} disabled={!dirty}>Discard changes</button></div>
  </fieldset>
 </form>
 <section class="panel"><div class="panel-head"><h2>Requests and renewal</h2></div><div class="panel-body stack">
  {#if checks?.issues?.length}<div class="notice warn"><strong>Before requesting a certificate</strong>{#each checks.issues as issue}<div class="check-item">{issue}</div>{/each}</div>{/if}
  {#each checks?.warnings||[] as warning}<div class="notice warn">{warning}</div>{/each}
  {#if dirty}<div class="muted">Save configuration changes before issuing or renewing. Actions always use the saved configuration.</div>{/if}
  <div class="actions"><button class="btn primary" type="button" disabled={!canRequest} on:click={()=>request('issue')}>Issue / renew certificate</button><button class="btn" type="button" disabled={!canRequest} on:click={()=>forceConfirm=!forceConfirm}>Force renewal...</button></div>
  {#if forceConfirm}<div class="notice warn stack"><div>Force renewal requests a new certificate even when the current one is not due. The CA's issuance rate limits still apply.</div><div class="actions"><button class="btn danger" type="button" disabled={!canRequest} on:click={()=>request('force')}>Confirm force renewal</button><button class="btn" type="button" on:click={()=>forceConfirm=false}>Cancel</button></div></div>{/if}
  <div class:bad={state.job.state==='failed'} class="notice" role="status"><strong>{state.job.state==='idle'?'Last request':state.job.state}</strong><div>{state.job.message}</div>{#if state.job.updated_at}<small>{new Date(state.job.updated_at*1000).toLocaleString()}</small>{/if}</div>
  <div class="muted">Requests run separately from this page. Successful live issuance reloads only the web console; failed issuance keeps the existing certificate. Detailed logs remain root-only on the appliance.</div>
 </div></section>
 {/if}
</div>
<style>
 .save-feedback{scroll-margin:5rem;outline:none}.save-feedback:empty{display:none}.attempted input:invalid{border-color:var(--bad)}
 .address-field{display:flex;align-items:center;min-width:0;gap:.5rem}.address-field>span{color:var(--muted);flex:none}.address-field input{min-width:0;flex:1}
 .certificates{min-width:0}.certificates fieldset{border:0;margin:0;min-width:0}.check{display:flex;gap:.65rem;align-items:flex-start;font-size:.9rem}.check input{width:18px;min-width:18px;height:18px;min-height:18px;margin:.15rem 0 0}.check span{display:grid;gap:.2rem}.check small{color:var(--muted);line-height:1.45}.check-item{margin-top:.45rem}code{overflow-wrap:anywhere}.certificates small{line-height:1.4}.certificates .detail-item{min-width:0}.certificates .actions .btn{white-space:normal}.certificates .notice{overflow-wrap:anywhere}
</style>
