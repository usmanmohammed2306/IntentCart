// Original, procedural rendering aids. None measures a real product or proves fit.
export function lightingEnvironment(T,renderer){
 const room=new T.Scene();room.background=new T.Color('#111b28');
 for(const [w,h,pos,color] of [[6,4,[0,5,0],[3,3.6,4.2]],[3,3,[-5,1,1],[.3,1.2,1.05]],[2,4,[4,2,-3],[1.3,1.5,1.8]]]){
  const light=new T.Mesh(new T.PlaneGeometry(w,h),new T.MeshBasicMaterial({color:new T.Color(...color),side:T.DoubleSide}));light.position.set(...pos);light.lookAt(0,0,0);room.add(light);
 }
 const pmrem=new T.PMREMGenerator(renderer);let target;
 try{target=pmrem.fromScene(room,.02,.1,20,{size:64});}finally{pmrem.dispose();room.traverse(o=>{o.geometry?.dispose();o.material?.dispose();});}
 return {texture:target.texture,dispose:()=>target.dispose()};
}
export function surfaceTexture(T){
 const canvas=document.createElement('canvas');canvas.width=512;canvas.height=256;const c=canvas.getContext('2d');c.fillStyle='#b9b4a9';c.fillRect(0,0,512,256);
 for(let i=0;i<160;i++){const y=i*1.7;c.strokeStyle=`rgba(${i%3?50:235},${i%3?55:231},${i%3?58:220},${i%3?.025:.04})`;c.lineWidth=i%4===0?1.2:.5;c.beginPath();for(let x=0;x<=512;x+=8){const yy=y+Math.sin(x*.009+i*.7)*1.5+Math.sin(x*.022+i)*.35;x?c.lineTo(x,yy):c.moveTo(x,yy);}c.stroke();}
 const map=new T.CanvasTexture(canvas);map.colorSpace=T.SRGBColorSpace;map.wrapS=map.wrapT=T.RepeatWrapping;map.repeat.set(2,1);map.anisotropy=2;return map;
}
export function screenTexture(T,index=0){
 const canvas=document.createElement('canvas');canvas.width=1024;canvas.height=576;const c=canvas.getContext('2d');c.fillStyle='#071521';c.fillRect(0,0,1024,576);
 const g=c.createRadialGradient(index?790:350,300,20,550,250,730);g.addColorStop(0,index?'#57a996':'#608caa');g.addColorStop(.5,index?'#194a48':'#1c3a51');g.addColorStop(1,'#091522');c.fillStyle=g;c.fillRect(0,0,1024,576);
 for(let i=0;i<6;i++){c.strokeStyle=`rgba(189,237,221,${.04+i*.012})`;c.lineWidth=2;c.beginPath();c.ellipse(650,330,160+i*62,80+i*40,-.6,0,Math.PI*2);c.stroke();}
 c.fillStyle='#0d2029aa';c.fillRect(38,38,260,478);c.strokeStyle='#a3dfd71a';c.strokeRect(38.5,38.5,260,478);for(let i=0;i<3;i++){c.fillStyle=['#79b4a9','#7eacc5','#d8c7a3'][i];c.beginPath();c.arc(60+i*18,60,3,0,Math.PI*2);c.fill();}
 for(let i=0;i<6;i++){c.fillStyle=i===0?'#9cdcc025':'#92adbb12';c.fillRect(59,96+i*60,218,44);c.fillStyle='#b7d6dd38';c.fillRect(74,111+i*60,108-i*9,4);c.fillStyle='#b7d6dd1c';c.fillRect(74,124+i*60,153-i*7,3);}
 const map=new T.CanvasTexture(canvas);map.colorSpace=T.SRGBColorSpace;return map;
}
export function laptopKeys(T,parent){
 const geometry=new T.BoxGeometry(.052,.009,.041),material=new T.MeshStandardMaterial({color:0x1b2932,metalness:.2,roughness:.42}),keys=new T.InstancedMesh(geometry,material,52);const transform=new T.Object3D();let i=0;
 for(let row=0;row<4;row++)for(let col=0;col<13;col++){transform.position.set((col-6)*.063,.064,-.21+row*.055);transform.updateMatrix();keys.setMatrixAt(i++,transform.matrix);}
 keys.castShadow=true;keys.receiveShadow=true;keys.userData.part='laptop';parent.add(keys);return keys;
}
export function placementGuides(T,parent){
 const group=new T.Group();group.name='illustrative-placement-guides';parent.add(group);
 const grid=new T.GridHelper(5.4,27,0x729f9d,0x41646c);grid.position.y=-.041;grid.scale.z=.5;grid.material.transparent=true;grid.material.opacity=.16;grid.material.depthWrite=false;group.add(grid);
 const frame=new T.LineSegments(new T.BufferGeometry(),new T.LineBasicMaterial({color:0x9cedd4,transparent:true,opacity:.8,depthTest:false,depthWrite:false}));frame.renderOrder=3;frame.frustumCulled=false;group.add(frame);
 const arc=new T.Line(new T.BufferGeometry(),new T.LineBasicMaterial({color:0xa0dbc8,transparent:true,opacity:.65,depthTest:false}));arc.renderOrder=3;arc.frustumCulled=false;group.add(arc);
 const box=new T.Box3();let selected=null;
 return {update(object,mode,dragging,accent){
  selected=object;group.visible=!!object;if(!object)return;object.updateWorldMatrix(true,true);box.setFromObject(object,true);if(box.isEmpty()){group.visible=false;return;}
  const x0=box.min.x-.045,x1=box.max.x+.045,z0=box.min.z-.045,z1=box.max.z+.045,y=-.038,l=Math.min(.19,(x1-x0)*.25,(z1-z0)*.25),vertices=[];
  for(const [x,z,sx,sz] of [[x0,z0,1,1],[x1,z0,-1,1],[x1,z1,-1,-1],[x0,z1,1,-1]])vertices.push(x,y,z,x+sx*l,y,z,x,y,z,x,y,z+sz*l);
  frame.geometry.setAttribute('position',new T.Float32BufferAttribute(vertices,3));frame.material.color.set(accent);frame.material.opacity=dragging?.95:.65;grid.visible=mode==='move'&&dragging;
  arc.visible=mode==='rotate';if(arc.visible){const cx=(x0+x1)/2,cz=(z0+z1)/2,r=Math.max(.33,Math.max(x1-x0,z1-z0)*.58),points=[];for(let i=0;i<=48;i++){const a=i/48*Math.PI*1.75;points.push(cx+Math.sin(a)*r,y,cz+Math.cos(a)*r);}arc.geometry.setAttribute('position',new T.Float32BufferAttribute(points,3));arc.material.color.set(accent);}
 },get selected(){return selected;}};
}
