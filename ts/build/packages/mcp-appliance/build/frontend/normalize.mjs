import { readFileSync, writeFileSync, readdirSync, statSync, mkdirSync, copyFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '../../usr/share/mcp-appliance/web');
const publicDir = join(here, 'public');
function walk(dir){
  for(const name of readdirSync(dir)){
    const p=join(dir,name), st=statSync(p);
    if(st.isDirectory()) walk(p);
    else if(/\.(js|css|html)$/.test(name)) writeFileSync(p,readFileSync(p,'utf8').replace(/[ \t]+$/gm,''));
  }
}
walk(root);
copyFileSync(join(publicDir, 'thinstation.svg'), join(root, 'thinstation.svg'));
if(process.env.BUILD_MCP_UI==='1'){
  const extra=join(root,'_operator');mkdirSync(extra,{recursive:true});
  for(const name of ['mcp_operator.py','mcp-operator-web','mcp-appliance-web','mcp_inventory.py', 'mcp_login.py','mcp_openai.py','mcp_acme.py', 'mcp_acme_authorization.py', 'mcp_ad_dns.py', 'mcp_http01.py', 'mcp_tlsalpn.py', 'mcp_certificate_form.py', 'mcp_certificate_names.py', 'mcp_storage.py', 'mcp_storage_worker.py'])copyFileSync(new URL('../../usr/bin/'+name,import.meta.url),join(extra,name));
  copyFileSync(new URL('../../usr/lib64/systemd/system/mcp-openai-tunnel.service',import.meta.url),join(extra,'mcp-openai-tunnel.service'));
  copyFileSync(new URL('../install-dev-operator.py',import.meta.url),join(extra,'install-dev-operator.py'));
  const files={};
  function hashes(dir, prefix='') {for(const name of readdirSync(dir)){const path=join(dir,name),relative=prefix+name;if(statSync(path).isDirectory())hashes(path,relative+'/');else if(relative!=='operator-release.json')files[relative]=createHash('sha256').update(readFileSync(path)).digest('hex')}}
  hashes(root);
  writeFileSync(join(root,'operator-release.json'),JSON.stringify({version:1,source_sha:process.env.CI_COMMIT_SHA||'',pipeline:process.env.CI_PIPELINE_ID||'',files},null,2)+'\n');
}
