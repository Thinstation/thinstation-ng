export const systemTopics=[
 ['network','Network','Interfaces, addressing and DNS'],
 ['storage','Storage','Disks, filesystems and LVM'],
 ['certificates','Certificates','ACME and HTTPS identity'],
 ['services','Services','Local service health'],['logs','Logs','Recent appliance events'],
 ['notice','Login notice','Console and sign-in banner']
];
export const topPages=[
 ['overview','Overview'],['connections','AI Connector'],['mcp','MCP'],
 ['inventory','Inventory'],['credentials','Credentials'],['system','System']
];
const aliases={
 overview:'overview',hosts:'inventory',credentials:'credentials',
 network:'system/network',settings:'system/certificates',storage:'system/storage',system:'system/network',
 'system/overview':'overview','system/inventory':'inventory','system/credentials':'credentials'
};
export function route(value){
 const p=String(value||'').replace(/^#\/?/,'');
 if(Object.hasOwn(aliases,p))return aliases[p];
 if(['overview','connections','mcp','mcp/settings','inventory','credentials'].includes(p)||systemTopics.some(t=>p==='system/'+t[0]))return p;
 return 'overview';
}
export function title(value){
 const p=route(value);
 if(p.startsWith('system/'))return 'System / '+systemTopics.find(t=>p==='system/'+t[0])[1];
 if(p==='mcp/settings')return 'MCP / Update policy';
 return ({overview:'Overview',connections:'AI Connector',mcp:'MCP',inventory:'Inventory',credentials:'Credentials'})[p]||'Overview';
}
