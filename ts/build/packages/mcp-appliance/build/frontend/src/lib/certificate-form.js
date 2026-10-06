// Keep transport details and inactive method fields out of the input form.
export const production='https://acme-v02.api.letsencrypt.org/directory';
export const staging='https://acme-staging-v02.api.letsencrypt.org/directory';
export const methods=[
 {value:'dns-01',label:'DNS-01',enabled:true},
 {value:'http-01',label:'HTTP-01',enabled:true},
 {value:'tls-alpn-01',label:'TLS-ALPN-01',enabled:true}
];
export const lines=value=>String(value||'').split(/[\s,]+/).filter(Boolean);
export const addressText=value=>String(value||'').replace(/^https:\/\//i,'');
export function directoryAddress(value){
 const v=String(value||'').trim();
 return v.includes('://')?v:'https://'+v;
}
export function cleanName(value){
 const v=String(value||'').trim();
 if(!/^https?:\/\//i.test(v))return v;
 try{const u=new URL(v);if(!u.port&&!u.username&&!u.password&&!u.search&&!u.hash&&u.pathname==='/')return u.hostname;}catch{}
 return v;
}
export function eligibleCredential(c,host){
 if(!host||c.type!=='active-directory'||!(c.scopes||[]).some(s=>s==='acme'||s==='*'))return false;
 const norm=s=>String(s||'').toLowerCase().replace(/\.$/,'');
 const targets=(c.allowed_hosts||[]).map(norm),ids=[host.alias,host.hostname,host.address].map(norm);
 return !targets.length||targets.some(t=>ids.includes(t)||t.startsWith('host:')&&ids.includes(t.slice(5))||t.startsWith('group:')&&(host.groups||[]).map(norm).includes(t.slice(6)));
}
export function payload(config,names,sources,authority,caAddress,alpnSources=''){
 const result={};
 for(const key of ['enabled','automatic','email','primary_domain','challenge','key_algorithm','renew_days','accept_terms','test_only'])result[key]=config[key];
 result.internal_ca=authority==='internal';
 result.primary_domain=cleanName(config.primary_domain);
 result.alternative_names=lines(names).map(cleanName);
 result.directory_url=authority==='production'?production:authority==='staging'?staging:directoryAddress(caAddress);
 if(authority==='staging')result.test_only=true;
 if(config.challenge==='dns-01'){
  result.dns_provider=config.dns_provider;result.credential=config.credential||'';
  if(config.dns_provider==='active-directory')for(const key of ['ad_host','ad_zone','ad_realm','ad_ttl','ad_propagation_timeout'])result[key]=config[key];
  else result.dns_hook=config.dns_hook||'';
 }else if(config.challenge==='http-01'){
  result.http_mode=config.http_mode;result.http_ready=config.http_ready;
  if(config.http_mode==='standalone'){
   result.http_public_access=!!config.http_public_access;
   result.http_source_networks=config.http_public_access?[]:lines(sources);
  }
 }else if(config.challenge==='tls-alpn-01'){
  result.alpn_ready=!!config.alpn_ready;
  result.alpn_public_access=!!config.alpn_public_access;
  result.alpn_source_networks=config.alpn_public_access?[]:lines(alpnSources);
 }
 return result;
}
