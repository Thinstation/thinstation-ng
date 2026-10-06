<script>
 import {onMount} from 'svelte';
 import {api} from './lib/api.js';
 let issue='',error='',message='',busy=false,loaded=false;
 onMount(async()=>{try{issue=(await api('/api/config/issue')).value||'';loaded=true}catch(e){error=e.message}});
 async function save(){busy=true;error='';message='';try{await api('/api/config/issue',{method:'PUT',headers:{'Content-Type':'text/plain'},body:issue});message='Login notice saved.'}catch(e){error=e.message}finally{busy=false}}
</script>
<div class="page"><div class="page-title"><div><h1>Login notice</h1><p>Text shown on the console and web sign-in page.</p></div></div>
{#if error}<div class="notice warn" role="alert">{error}</div>{/if}{#if message}<div class="notice" role="status">{message}</div>{/if}
<form class="panel" on:submit|preventDefault={save}><div class="panel-body stack"><label class="field"><span>Notice text</span><textarea bind:value={issue} maxlength="4096" rows="10" disabled={!loaded||busy}></textarea></label><div class="actions"><button class="btn primary" disabled={!loaded||busy}>{busy?'Saving...':'Save notice'}</button></div></div></form></div>
