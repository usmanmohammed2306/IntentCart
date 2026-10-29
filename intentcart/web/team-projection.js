// A visual projection, isolated from saved layouts and purchase authority.
export function projectTeam(catalog,data,request,poses=new Map(),focusId=null){
 const products=new Map(catalog.products.map(p=>[p.id,p]));
 const view={schema_version:2,name:request?.data.title||data.team.name,currency:'USD',budget_cents:request?.data.budget_cents??null,shipping_cents:null,tax_cents:null,surface:{kind:'unknown',width:null,depth:null,clearance_mm:null,zones:[]},items:[],connections:[],requirements:[],finish:'graphite'};
 const plan=request?.snapshot&&['ordered','fulfilled'].includes(request.state)?request.snapshot:request?.plan;
 const rows=[];
 if(request){
  const reused=[...(plan?.reuse||[])];
  const add=(sku,slot,label)=>{const index=reused.findIndex(a=>a.sku===sku),asset=index<0?null:reused.splice(index,1)[0];const line=plan?.purchase?.find(p=>p.sku===sku);rows.push({sku,key:request.id+':'+slot,label,asset,source:asset?'Reused':'To buy',price:line?.quote?.unit_cents??null});};
  add('dell-latitude-5440','host','Laptop');
  if(request.data.screens){add('dell-wd22tb4-180w','dock','Dock');for(let i=0;i<Math.min(4,request.data.screens);i++)add('dell-p2422h-dp','screen'+i,'Display '+(i+1));}
 }else{
  const assets=data.assets.slice(0,24),focused=data.assets.find(a=>data.team.id+':asset:'+a.id===focusId);if(focused&&!assets.some(a=>a.id===focused.id))assets.push(focused);
  for(const a of assets)rows.push({sku:a.sku,key:'asset:'+a.id,label:a.tag,asset:a,source:a.state,price:null});
 }
 for(let n=0;n<rows.length;n++){
  const row=rows[n],p=products.get(row.sku)||{name:row.sku,kind:'other'},kind=p.kind==='laptop'?'laptop':p.kind==='monitor'?'monitor':p.kind==='dock'?'dock':'other';
  let pose={x:(n%4-1.5)*650,z:Math.floor(n/4)*550,yaw:0};
  if(request){if(kind==='laptop')pose={x:-750,z:280,yaw:0};else if(kind==='dock')pose={x:-260,z:300,yaw:0};else pose={x:-200+(n-2)*650,z:-180,yaw:0};}
  const id=data.team.id+':'+row.key;pose=poses.get(id)||pose;
  view.items.push({id,kind,name:row.label,model:p.name,owned:!!row.asset,price_cents:row.asset?0:row.price,dimensions:null,pose:{...pose},ports:[],ports_confirmed:false,color:row.asset?'#8bafaa':'#8d98b0',locked:false,note:row.source,asset:row.asset,sku:row.sku});
 }
 if(request?.data.screens){const laptop=view.items[0],dock=view.items[1];const pairs=[[laptop,dock],...view.items.slice(2).map(m=>[dock,m])];for(const [a,b]of pairs)view.connections.push({id:a.id+'>'+b.id,source:a.id,target:b.id,source_port:'',target_port:'',status:'unknown',evidence:''});}
 return view;
}
