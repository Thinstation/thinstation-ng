// Save feedback must outlive unrelated health/status polling.
export function acknowledgement(response){
 if(response?.ok!==true)throw new Error('The server did not acknowledge this save.');
 const cfg=response.config||response.status?.config;
 if(!cfg||typeof cfg!=='object'||Array.isArray(cfg)||!Array.isArray(cfg.alternative_names)||typeof cfg.directory_url!=='string'||typeof cfg.primary_domain!=='string'||!['dns-01','http-01','tls-alpn-01'].includes(cfg.challenge)){
  throw new Error('The server did not return a valid saved configuration.');
 }
 return cfg;
}
export function invalidFields(form){
 if(!form)return ['The configuration form is not ready.'];
 return Array.from(form.elements).filter(el=>el.willValidate&&!el.validity.valid).map(el=>{
  const label=el.getAttribute('aria-label')||el.labels?.[0]?.querySelector('span')?.textContent?.trim()||el.name||'Field';
  return label+': '+(el.validationMessage||'Check this value.');
 });
}
export async function timedRequest(operation,milliseconds=30000){
 const controller=new AbortController();
 const timer=setTimeout(()=>controller.abort(),milliseconds);
 try{return await operation(controller.signal)}
 catch(error){
  if(controller.signal.aborted)throw new Error('The request timed out. The server may still have received it. Retry the save to confirm; no certificate is requested by saving.');
  throw error;
 }finally{clearTimeout(timer)}
}
