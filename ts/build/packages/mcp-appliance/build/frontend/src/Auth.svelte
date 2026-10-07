<script>
  import { api, json, setBootstrapToken, setCsrf } from './lib/api.js';
  export let issue='';
  export let registration={registered:false};
  export let onAuthenticated=()=>{};
  let mode='login', error='', token='', username='', password='', displayName='', email='', password2='';
  let smtpHost='', smtpPort=587, mailFrom='', mailUser='', mailPass='', starttls=true;
  let storage=null, selectedDisk='', provisioning=false;
  const fmtBytes=(n)=>{ const u=['B','KiB','MiB','GiB','TiB']; let v=Number(n||0),i=0; while(v>=1024&&i<u.length-1){v/=1024;i++} return v.toFixed(i?1:0)+' '+u[i]; };
  let resetId='', resetPassword='', resetPassword2='';
  const hash=new URLSearchParams(location.hash.startsWith('#')?location.hash.slice(1):location.hash);
  let resetToken=hash.get('reset')||'';
  if(resetToken) mode='reset';
  const boot=hash.get('token')||'';
  if(boot){ token=boot; setBootstrapToken(token); }

  async function bootstrap(){
    error='';
    try{
      setBootstrapToken(token.trim());
      await api('/api/health');
      storage=await api('/api/storage');
      selectedDisk=storage?.candidates?.[0]?.path||'';
      mode=storage?.mounted?'register':'storage';
    }catch(e){ error=e.message; }
  }
  async function provisionStorage(){
    error='';
    if(!selectedDisk){ error='Select a disk to provision.'; return; }
    provisioning=true;
    try{
      const r=await json('/api/storage/provision','POST',{device:selectedDisk,confirm:'PROVISION'});
      storage=r.storage||await api('/api/storage');
      if(!storage?.mounted) throw new Error('Persistent storage did not mount.');
      mode='register';
    }catch(e){ error=e.message; }
    finally{ provisioning=false; }
  }
  async function login(){
    error='';
    try{
      const r=await json('/api/login','POST',{username:username.trim(),password});
      password=''; setCsrf(r.csrf); onAuthenticated(r.user,r.csrf);
    }catch(e){ password=''; error=e.message; }
  }
  async function register(){
    error='';
    try{
      if(password!==password2) throw new Error('Passwords do not match');
      const r=await json('/api/register','POST',{
        username:username.trim(),display_name:displayName.trim(),email:email.trim(),password,
        mail:{smtp_host:smtpHost.trim(),smtp_port:Number(smtpPort||587),from:mailFrom.trim(),user:mailUser.trim(),password:mailPass,starttls}
      });
      password=password2=mailPass=''; setBootstrapToken(''); setCsrf(r.csrf); history.replaceState(null,'',location.pathname); onAuthenticated(r.user,r.csrf);
    }catch(e){ password=password2=mailPass=''; error=e.message; }
  }
  async function requestReset(){
    error='';
    try{ const r=await json('/api/password-reset/request','POST',{identifier:resetId.trim()}); error=r.message; }
    catch(e){ error=e.message; }
  }
  async function completeReset(){
    error='';
    try{
      if(resetPassword!==resetPassword2) throw new Error('Passwords do not match');
      const r=await json('/api/password-reset/complete','POST',{token:resetToken,password:resetPassword});
      resetPassword=resetPassword2=''; resetToken=''; history.replaceState(null,'',location.pathname); setCsrf(r.csrf); onAuthenticated(r.user,r.csrf);
    }catch(e){ error=e.message; }
  }
</script>

<div class="login-shell">
  <div class="login-wrap">
    <div class="login-brand">
      <img class="login-wordmark" src="/watermark.png" alt="ThinStation" />
      <h1>MCP Appliance</h1>
      <div class="muted">Secure appliance management</div>
    </div>

    {#if issue}
      <div class="notice issue-login">{issue}</div>
    {/if}

    <div class="login-card">
      {#if !registration.registered && mode==='login'}
        <h2>Register appliance</h2>
        <p class="muted">Use the one-time token shown on the appliance console or scan its QR code.</p>
        <div class="field"><span>Bootstrap token</span><input type="password" bind:value={token} autocomplete="off" /></div>
        <div class="actions" style="margin-top:.8rem"><button class="btn primary" on:click={bootstrap}>Continue</button></div>
      {:else if mode==='storage'}
        <h2>Persistent storage</h2>
        <p class="muted">Choose a dedicated disk for appliance state. Administrator accounts, credentials, MCP generations, and configuration will persist here across reboots and ISO updates.</p>
        {#if storage?.candidates?.length}
          <div class="selection-grid" style="margin-top:1rem">
            {#each storage.candidates as disk}
              <label class="selection-card">
                <input type="radio" name="storage-disk" value={disk.path} bind:group={selectedDisk}/>
                <span>
                  <strong>{disk.path} · {fmtBytes(disk.size)}</strong>
                  <small>{[disk.model,disk.serial].filter(Boolean).join(' · ') || 'Unused whole disk'}</small>
                </span>
              </label>
            {/each}
          </div>
          <div class="notice warn" style="margin-top:1rem"><strong>This erases the selected disk.</strong> The entire device will become the appliance persistent filesystem labeled <span class="mono">prstnt</span>.</div>
          {#if storage?.formatter_available===false}
            <div class="notice warn" style="margin-top:.7rem">This appliance image does not contain the ext4 formatter required for provisioning. Boot an updated appliance ISO before continuing.</div>
          {/if}
          <div class="actions" style="margin-top:1rem">
            <button class="btn primary" disabled={provisioning||!selectedDisk||storage?.formatter_available===false} on:click={provisionStorage}>{provisioning?'Provisioning…':'Provision selected disk'}</button>
          </div>
        {:else}
          <div class="notice warn">No unused writable disks are available. Attach a dedicated disk, then restart this step.</div>
          <div class="actions" style="margin-top:1rem"><button class="btn" on:click={bootstrap}>Refresh disks</button></div>
        {/if}
      {:else if mode==='register'}
        <h2>Create first administrator</h2>
        <div class="form-grid">
          <label class="field"><span>Username</span><input bind:value={username} autocomplete="username" /></label>
          <label class="field"><span>Display name</span><input bind:value={displayName} autocomplete="name" /></label>
          <label class="field wide"><span>Email address</span><input type="email" bind:value={email} autocomplete="email" /></label>
          <label class="field"><span>Password</span><input type="password" bind:value={password} autocomplete="new-password" /></label>
          <label class="field"><span>Confirm password</span><input type="password" bind:value={password2} autocomplete="new-password" /></label>
        </div>
        <details style="margin-top:1rem"><summary>Outbound mail</summary>
          <div class="form-grid" style="margin-top:.8rem">
            <label class="field"><span>SMTP host</span><input bind:value={smtpHost}/></label>
            <label class="field"><span>Port</span><input type="number" bind:value={smtpPort}/></label>
            <label class="field"><span>From address</span><input type="email" bind:value={mailFrom}/></label>
            <label class="field"><span>SMTP user</span><input bind:value={mailUser}/></label>
            <label class="field wide"><span>SMTP password</span><input type="password" bind:value={mailPass}/></label>
            <label><input type="checkbox" bind:checked={starttls}/> Use STARTTLS</label>
          </div>
        </details>
        <div class="actions" style="margin-top:1rem"><button class="btn primary" on:click={register}>Complete registration</button></div>
      {:else if mode==='reset'}
        <h2>Choose a new password</h2>
        <div class="stack">
          <label class="field"><span>New password</span><input type="password" bind:value={resetPassword}/></label>
          <label class="field"><span>Confirm password</span><input type="password" bind:value={resetPassword2}/></label>
          <button class="btn primary" on:click={completeReset}>Set new password</button>
        </div>
      {:else if mode==='forgot'}
        <h2>Reset password</h2>
        <p class="muted">If the account exists and mail is configured, the appliance will send a reset link.</p>
        <label class="field"><span>Username or email</span><input bind:value={resetId}/></label>
        <div class="actions" style="margin-top:.8rem"><button class="btn primary" on:click={requestReset}>Send reset link</button><button class="btn" on:click={()=>mode='login'}>Cancel</button></div>
      {:else}
        <h2>Sign in</h2>
        <div class="stack">
          <label class="field"><span>Username or email</span><input bind:value={username} autocomplete="username"/></label>
          <label class="field"><span>Password</span><input type="password" bind:value={password} autocomplete="current-password" on:keydown={(e)=>e.key==='Enter'&&login()}/></label>
          <div class="actions"><button class="btn primary" on:click={login}>Sign in</button><button class="btn subtle" on:click={()=>mode='forgot'}>Forgot password?</button></div>
        </div>
      {/if}
      {#if error}<div class="notice warn" style="margin-top:.9rem">{error}</div>{/if}
    </div>
  </div>
</div>
