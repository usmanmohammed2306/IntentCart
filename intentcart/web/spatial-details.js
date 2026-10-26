// Read-only presentation of returned records. A diagram is never evidence.
export const TOPICS={
 laptop:[['video','Video',['native_displays','protocols']],['power','Charging',['charge_watts']]],
 dock:[['video','Video',['protocol','displays','max_height','max_hz','output_connector']],['power','Charging',['pd_watts','adapter_for']],['software','Software',['minimum_os','hdcp','gaming']]],
 monitor:[['video','Picture',['height','hz']],['connection','Connection',['connector']]],
 power:[['power','Output',['watts']],['connection','Matches',['adapter_for']]],
 cable:[['connection','Connection',['connector','direction']],['video','Capacity',['count','max_height','max_hz']]]
};
const names={native_displays:'Native screens',protocols:'Connections',charge_watts:'Charging requirement',protocol:'Display connection',displays:'Screen support',max_height:'Resolution limit',height:'Resolution',max_hz:'Refresh limit',hz:'Refresh',output_connector:'Display connector',pd_watts:'Dock charging',adapter_for:'Matching adapter',minimum_os:'System version',hdcp:'Protected video',gaming:'Gaming',connector:'Connector',direction:'Direction',watts:'Power output',count:'Cable count'};
const values={altmode:'USB-C video',displaylink:'DisplayLink software',hdmi:'HDMI',displayport:'DisplayPort','usb-c':'USB-C',tb3:'Thunderbolt 3',tb4:'Thunderbolt 4','dock-to-display':'Dock to screen','display-to-dock':'Screen to dock',bidirectional:'Either direction'};
export function readable(field,value){
 if(Array.isArray(value))return value.map(v=>values[v]||String(v)).join(' · ');
 if(typeof value==='boolean')return value?'Yes':'No';
 if(value===null||value===undefined)return 'Not checked';
 if(['height','max_height'].includes(field))return value===2160?'4K':value===1080?'Full HD':String(value)+' px';
 return (values[value]||String(value))+(['pd_watts','watts','charge_watts'].includes(field)?' W':['hz','max_hz'].includes(field)?' Hz':'');
}
export function safeSourceUrl(value){try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password&&!u.hostname.endsWith('.invalid')?u.href:null;}catch{return null;}}
export function partDetails(goal,plan,products=[],laptops=[],evidence=[]){
 const chosen=new Map((plan?.items||[]).map(i=>[i.product_id,i]));
 const laptop=laptops.find(p=>p.id===goal.laptop_id);
 return Object.fromEntries(Object.entries(TOPICS).map(([kind,topics])=>{
  const records=kind==='laptop'?(laptop?[laptop]:[]):products.filter(p=>p.kind===kind&&chosen.has(p.id));
  const ids=new Set(records.map(p=>p.id));
  const rows=[...new Map(evidence.filter(e=>ids.has(e.product_id)).map(e=>[e.source_id||e.id||JSON.stringify([e.product_id,e.field,e.value,e.url]),e])).values()];
  const groups=topics.map(([id,label,fields])=>({id,label,facts:fields.flatMap(field=>{
   if(kind==='laptop'&&laptop&&Object.hasOwn(laptop,field))return [{label:names[field],value:readable(field,laptop[field]),product:laptop.name,source_id:null,url:safeSourceUrl(laptop.source_url),date:laptop.observed_on||null,kind:laptop.source_url?'Catalog laptop record':'Fictional laptop record'}];
   const matches=rows.filter(e=>e.field===field);
   return matches.length?matches.map(e=>({label:names[field],value:readable(field,e.value),product:records.find(p=>p.id===e.product_id)?.name||e.product_id,source_id:e.source_id||e.id||null,url:safeSourceUrl(e.url),date:e.observed_on||e.observed_at||null,kind:e.kind==='manufacturer'?'Manufacturer record':'Fictional specification record'})):[{label:names[field],value:'Not checked',source_id:null,url:null}];
  })}));
  return [kind,{records:records.map(p=>({id:p.id,name:p.name,quantity:chosen.get(p.id)?.quantity||1,price_cents:kind==='laptop'?null:p.price_cents,variant:p.variant||null})),groups,owned:kind==='laptop'||kind==='monitor'&&goal.reuse_monitor,confirmed:!!plan}];
 }));
}
export function diagramEdges(present=[]){
 const known=new Set(present);
 return [['laptop','dock'],['dock','monitor'],['dock','power'],['dock','cable']].filter(([a,b])=>known.has(a)&&known.has(b)).map(([from,to])=>({from,to,label:'Planning relationship'}));
}
