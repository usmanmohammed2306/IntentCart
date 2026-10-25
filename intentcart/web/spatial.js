// Read-only illustration. Camera, highlights and spacing never change a task or call an API.
import {animate,createSpring} from './vendor/anime-4.5.0.esm.min.js';
const make=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const labels={laptop:'Laptop',monitor:'Screens',dock:'Dock',cable:'Cables',power:'Power'};
export function layoutScreens(value){const n=Number.isInteger(value)?Math.min(4,Math.max(1,value)):2;return Array.from({length:n},(_,i)=>({x:(i-(n-1)/2)*(n>2?1.16:1.55),scale:n>2?.73:1}));}
export function presentation(goal={},plan=null,products=[],laptops=[]){
 const parts={laptop:laptops.find(p=>p.id===goal.laptop_id)?.name||'Your laptop'};
 for(const kind of ['monitor','dock','cable','power']){const rows=(plan?.items||[]).map(i=>({item:i,product:products.find(p=>p.id===i.product_id)})).filter(r=>r.product?.kind===kind);parts[kind]=rows.length?rows.map(r=>`${r.item.quantity} × ${r.product.name}`).join(' · '):plan?(kind==='monitor'&&goal.reuse_monitor?'Your existing screen':'No additional part in this plan'):'Illustrative '+labels[kind].toLowerCase();}
 if(plan&&goal.reuse_monitor&&!parts.monitor.startsWith('Your existing screen'))parts.monitor+=' · includes your existing screen';
 return {screens:layoutScreens(goal.displays).length,parts,context:plan?'Reviewed example plan':'Illustrative preview',confirmed:!!plan,present:plan?['laptop',...new Set((plan.items||[]).map(i=>products.find(p=>p.id===i.product_id)?.kind).filter(Boolean)),...(goal.reuse_monitor?['monitor']:[])]:Object.keys(labels)};
}
export function createSpatialWorkspace(host){
 const media=matchMedia('(prefers-reduced-motion: reduce)'),stage=host.querySelector('#desk-scene'),art=stage.querySelector('.workstation-art');
 const tools=make('div',undefined,'spatial-tools'),spread=make('button','Separate parts','spatial-spread');spread.type='button';spread.id='spatial-spread';spread.setAttribute('aria-pressed','false');
 const view=make('details',undefined,'spatial-view'),summary=make('summary','View'),viewMenu=make('div',undefined,'spatial-view-menu');view.append(summary,viewMenu);
 const parts=make('details',undefined,'spatial-parts'),partsSummary=make('summary','Parts'),partMenu=make('div',undefined,'spatial-part-menu');parts.append(partsSummary,partMenu);
 tools.append(spread,parts,view);stage.after(tools);
 const title=host.querySelector('#scene-story-title'),note=host.querySelector('#scene-story-note'),caption=host.querySelector('#scene-caption');
 let data=presentation(),signature='',selected=null,expanded=false,renderer,scene,camera,world,THREE,animation=null,visible=true,dead=false,groups={},meshes=[],drag=null,dragged=false,draws=0,attempted=false;
 const state={azimuth:.35,elevation:.37,zoom:1,spread:0,focusX:0,focusY:.62,focusZ:0};
 const instructions=make('p','Drag to look around. Select a part to see its details.','spatial-instructions');instructions.id='spatial-instructions';tools.after(instructions);
 const fallbacks=make('div',undefined,'spatial-fallback-actions');fallbacks.hidden=true;const retry=make('button','Try 3D again','text-button');retry.type='button';fallbacks.append(retry);tools.after(fallbacks);
 function status(){const kind=selected;title.textContent=kind?labels[kind]:'';note.textContent=kind?data.parts[kind]:'Illustrated layout · not measured product dimensions';caption.textContent=data.context;host.dataset.spatialSelection=kind||'none';}
 function draw(){if(!renderer||dead||!visible||document.hidden||!stage.isConnected)return;const rect=stage.getBoundingClientRect();if(!rect.width||!rect.height)return;
  const aspect=rect.width/rect.height;camera.left=-3.05;camera.right=3.05;camera.top=3.05/aspect;camera.bottom=-3.05/aspect;camera.zoom=state.zoom;camera.updateProjectionMatrix();
  camera.position.set(state.focusX+Math.sin(state.azimuth)*7,2.2+state.elevation*5,state.focusZ+Math.cos(state.azimuth)*7);camera.lookAt(state.focusX,state.focusY,state.focusZ);
  for(const [kind,group] of Object.entries(groups)){const base=group.userData.base;group.position.set(base.x+(kind==='power'?1.1:kind==='dock'?.45:0)*state.spread,base.y+(kind==='monitor'?.7:kind==='laptop'?.18:kind==='dock'?.4:kind==='cable'?.3:0)*state.spread,base.z+(kind==='laptop'?.45:kind==='power'?.4:0)*state.spread);}
  renderer.render(scene,camera);host.dataset.spatialFrames=String(++draws);
 }
 function motion(values){animation?.pause();if(media.matches||!visible||document.hidden){Object.assign(state,values);draw();return;}animation=animate(state,{...values,ease:createSpring({stiffness:170,damping:24,mass:.8}),onUpdate:draw});}
 function choose(kind){if(!Object.hasOwn(labels,kind))return;selected=kind;status();for(const b of partMenu.querySelectorAll('button'))b.setAttribute('aria-pressed',String(b.dataset.part===kind));
  if(renderer){for(const [k,g] of Object.entries(groups))g.traverse(o=>{if(o.isMesh&&o.material?.emissive){o.material.emissive.set(k===kind?0x58321f:0);o.material.emissiveIntensity=k===kind?.13:0;}});const p=groups[kind]?.position;motion({focusX:p?Math.max(-.8,Math.min(.8,p.x)):0,focusY:kind==='monitor'?1.05:.62,zoom:kind==='dock'||kind==='power'?1.24:1});}
 }
 for(const [kind,label] of Object.entries(labels)){const b=make('button',label);b.type='button';b.dataset.part=kind;b.setAttribute('aria-pressed','false');b.addEventListener('click',()=>{choose(kind);parts.open=false;partsSummary.focus({preventScroll:true});});partMenu.append(b);}
 const actions=[['Rotate left',()=>motion({azimuth:state.azimuth-.35})],['Rotate right',()=>motion({azimuth:state.azimuth+.35})],['Zoom in',()=>motion({zoom:Math.min(1.5,state.zoom+.15)})],['Zoom out',()=>motion({zoom:Math.max(.75,state.zoom-.15)})],['Reset view',()=>{selected=null;expanded=false;spread.setAttribute('aria-pressed','false');spread.textContent='Separate parts';partMenu.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed','false'));status();motion({azimuth:.35,elevation:.37,zoom:1,spread:0,focusX:0,focusY:.62,focusZ:0});}]];
 for(const [label,action] of actions){const b=make('button',label);b.type='button';b.addEventListener('click',action);viewMenu.append(b);}
 spread.addEventListener('click',()=>{expanded=!expanded;spread.setAttribute('aria-pressed',String(expanded));spread.textContent=expanded?'Put together':'Separate parts';motion({spread:expanded?1:0,focusY:expanded?.85:.62,zoom:expanded?.88:1});});
 for(const d of [view,parts])d.addEventListener('toggle',()=>{if(d.open)(d===view?parts:view).open=false;});
 function failure(){host.dataset.spatial='fallback';art.hidden=false;fallbacks.hidden=false;instructions.textContent='Illustrated preview. Use Parts to explore the details.';spread.disabled=true;for(const b of viewMenu.querySelectorAll('button'))b.disabled=true;}
 async function initialize(){if(attempted||dead)return;attempted=true;
  try{THREE=await import('./vendor/three.module.js');if(dead)return;
   renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,powerPreference:'low-power'});renderer.setPixelRatio(Math.min(devicePixelRatio||1,1.7));renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.1;
   const canvas=renderer.domElement;canvas.tabIndex=0;canvas.setAttribute('role','img');canvas.setAttribute('aria-label','Interactive illustrated workstation. Arrow keys rotate, plus and minus zoom, zero resets. Use the Parts menu to inspect components.');canvas.setAttribute('aria-describedby','spatial-instructions');canvas.className='spatial-canvas';stage.append(canvas);
   scene=new THREE.Scene();camera=new THREE.OrthographicCamera(-3,3,2,-2,.1,50);world=new THREE.Group();scene.add(world);
   scene.add(new THREE.HemisphereLight(0xffffff,0xa8aa94,3));const key=new THREE.DirectionalLight(0xfff2df,5);key.position.set(-3,6,5);key.castShadow=true;key.shadow.mapSize.set(1024,1024);key.shadow.camera.left=-5;key.shadow.camera.right=5;key.shadow.camera.top=5;key.shadow.camera.bottom=-5;key.shadow.normalBias=.025;scene.add(key);const fill=new THREE.DirectionalLight(0xdbe8f0,2);fill.position.set(4,3,-2);scene.add(fill);
   build();art.hidden=true;host.dataset.spatial='ready';fallbacks.hidden=true;spread.disabled=false;viewMenu.querySelectorAll('button').forEach(b=>b.disabled=false);instructions.textContent='Drag to look around. Select a part to see its details.';
   canvas.addEventListener('pointerdown',e=>{if(e.button!==0)return;drag={x:e.clientX,y:e.clientY,a:state.azimuth,e:state.elevation};dragged=false;animation?.pause();canvas.setPointerCapture(e.pointerId);});
   canvas.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.hypot(dx,dy)>5)dragged=true;state.azimuth=Math.max(-1.3,Math.min(1.3,drag.a+dx*.006));state.elevation=Math.max(.1,Math.min(.85,drag.e+dy*.003));draw();});
   canvas.addEventListener('pointerup',e=>{if(!drag)return;const wasDragged=dragged;drag=null;if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);if(wasDragged)return;const r=canvas.getBoundingClientRect(),ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),camera);const hit=ray.intersectObjects(meshes)[0];if(hit)choose(hit.object.userData.part);});
   canvas.addEventListener('pointercancel',()=>{drag=null;});canvas.addEventListener('lostpointercapture',()=>{drag=null;});
   canvas.addEventListener('keydown',e=>{let values;if(e.key==='ArrowLeft')values={azimuth:Math.max(-1.3,state.azimuth-.2)};if(e.key==='ArrowRight')values={azimuth:Math.min(1.3,state.azimuth+.2)};if(e.key==='ArrowUp')values={elevation:Math.min(.85,state.elevation+.1)};if(e.key==='ArrowDown')values={elevation:Math.max(.1,state.elevation-.1)};if(e.key==='+'||e.key==='=')values={zoom:Math.min(1.5,state.zoom+.15)};if(e.key==='-')values={zoom:Math.max(.75,state.zoom-.15)};if(e.key==='0'){e.preventDefault();actions.at(-1)[1]();return;}if(values){e.preventDefault();motion(values);}});
   canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();animation?.pause();failure();});canvas.addEventListener('webglcontextrestored',()=>{host.dataset.spatial='ready';art.hidden=true;fallbacks.hidden=true;spread.disabled=false;viewMenu.querySelectorAll('button').forEach(b=>b.disabled=false);draw();});
   resize();
  }catch{renderer?.dispose();renderer?.domElement.remove();renderer=null;failure();}
 }
 function build(){
  world.traverse(o=>{o.geometry?.dispose();if(o.material){o.material.map?.dispose();o.material.dispose();}});world.clear();groups={};meshes=[];
  const mat=(color,metalness=.1,roughness=.5)=>new THREE.MeshStandardMaterial({color,metalness,roughness});
  const geometry=size=>{const [w,h,d]=size;if(Math.min(w,h,d)<.04)return new THREE.BoxGeometry(w,h,d);const r=Math.min(w,h)*.06,b=Math.min(d*.12,.009),x=-w/2,y=-h/2,shape=new THREE.Shape();shape.moveTo(x+r,y);shape.lineTo(x+w-r,y);shape.quadraticCurveTo(x+w,y,x+w,y+r);shape.lineTo(x+w,y+h-r);shape.quadraticCurveTo(x+w,y+h,x+w-r,y+h);shape.lineTo(x+r,y+h);shape.quadraticCurveTo(x,y+h,x,y+h-r);shape.lineTo(x,y+r);shape.quadraticCurveTo(x,y,x+r,y);const g=new THREE.ExtrudeGeometry(shape,{depth:d-2*b,steps:1,bevelEnabled:true,bevelThickness:b,bevelSize:b,bevelSegments:2,curveSegments:4});g.translate(0,0,-d/2+b);return g;};
  const box=(parent,size,pos,color,part,metal=.1)=>{const mesh=new THREE.Mesh(geometry(size),mat(color,metal));mesh.position.set(...pos);mesh.castShadow=true;mesh.receiveShadow=true;if(part){mesh.userData.part=part;meshes.push(mesh);}parent.add(mesh);return mesh;};
  const group=(kind,pos)=>{const g=new THREE.Group();g.userData.base=new THREE.Vector3(...pos);g.position.copy(g.userData.base);world.add(g);groups[kind]=g;return g;};
  const desk=box(world,[5.5,.14,2.75],[0,-.12,0],0xd5c6af);desk.material.roughness=.9;
  box(world,[.13,1.08,.13],[-2.27,-.72,.91],0x343a38);box(world,[.13,1.08,.13],[2.27,-.72,.91],0x343a38);box(world,[.13,1.08,.13],[-2.27,-.72,-.92],0x343a38);box(world,[.13,1.08,.13],[2.27,-.72,-.92],0x343a38);
  const ground=new THREE.Mesh(new THREE.PlaneGeometry(30,30),new THREE.ShadowMaterial({color:0x2b3828,opacity:.14}));ground.rotation.x=-Math.PI/2;ground.position.y=-1.3;ground.receiveShadow=true;world.add(ground);
  const laptop=group('laptop',[0,0,.73]);box(laptop,[1.15,.05,.8],[0,.02,0],0xa3abae,'laptop',.65);const lid=box(laptop,[1.14,.73,.045],[0,.39,-.36],0x59626a,'laptop',.5);lid.rotation.x=-.16;
  const laptopScreen=box(laptop,[1.03,.62,.01],[0,.39,-.325],0x6e8a8c,'laptop');laptopScreen.rotation.x=-.16;box(laptop,[.95,.008,.34],[0,.052,-.08],0x303a3e,'laptop');box(laptop,[.29,.007,.2],[0,.053,.23],0x899397,'laptop',.3);
  const monitors=group('monitor',[0,0,-.66]);
  for(const [i,p] of layoutScreens(data.screens).entries()){
   const screen=new THREE.Group();screen.position.x=p.x;screen.scale.setScalar(p.scale);monitors.add(screen);box(screen,[.52,.04,.4],[0,.03,.06],0x505b60,'monitor',.6);box(screen,[.065,.45,.065],[0,.25,-.05],0x657278,'monitor',.6);box(screen,[1.48,.94,.075],[0,.92,0],0x303a40,'monitor',.4);
   const textureCanvas=document.createElement('canvas');textureCanvas.width=512;textureCanvas.height=320;const c=textureCanvas.getContext('2d');const gradient=c.createLinearGradient(0,0,512,320);gradient.addColorStop(0,i%2?'#a4b6aa':'#c5a78a');gradient.addColorStop(1,i%2?'#e3e9da':'#ede7d9');c.fillStyle=gradient;c.fillRect(0,0,512,320);c.fillStyle='#ffffff75';c.beginPath();c.arc(390,260,200,0,Math.PI*2);c.fill();c.fillStyle='#ffffffc0';c.fillRect(45,44,170,14);c.fillStyle='#ffffff70';c.fillRect(45,72,110,8);c.fillRect(45,93,145,8);c.fillStyle='#58746888';c.fillRect(45,228,48,48);c.fillStyle='#cb765eaa';c.fillRect(105,228,48,48);
   const texture=new THREE.CanvasTexture(textureCanvas);texture.colorSpace=THREE.SRGBColorSpace;const face=new THREE.Mesh(new THREE.PlaneGeometry(1.37,.82),new THREE.MeshBasicMaterial({map:texture}));face.position.set(0,.92,.041);face.userData.part='monitor';screen.add(face);meshes.push(face);
  }
  const dock=group('dock',[1.4,.04,.67]);box(dock,[.62,.15,.34],[0,.05,0],0x687777,'dock',.55);for(let i=0;i<3;i++)box(dock,[.09,.045,.008],[-.18+i*.18,.055,.175],0x202d32,'dock');box(dock,[.027,.012,.009],[.26,.08,.18],0xc67858,'dock');
  const power=group('power',[2.06,.015,-.06]);box(power,[.31,.2,.47],[0,.08,0],0x444d4d,'power',.2);
  const cables=group('cable',[0,.01,0]);for(const points of [[[0,.04,.33],[.4,.06,.5],[.75,.03,.78],[1.1,.05,.68]],[[1.45,.03,.55],[1.53,.04,.05],[1.25,.045,-.36],[.75,.08,-.6]],[[1.76,.03,.67],[2.02,.03,.53],[2.13,.035,.4],[2.06,.05,.2]]]){const curve=new THREE.CatmullRomCurve3(points.map(p=>new THREE.Vector3(...p)));const tube=new THREE.Mesh(new THREE.TubeGeometry(curve,20,.013,6,false),mat(0x4e5d5b));tube.userData.part='cable';cables.add(tube);meshes.push(tube);}
  if(data.confirmed)for(const [kind,g] of Object.entries(groups))g.visible=data.present.includes(kind);
  meshes=meshes.filter(o=>{for(let p=o;p&&p!==world;p=p.parent)if(!p.visible)return false;return true;});
  if(selected)choose(selected);draw();
 }
 function resize(){if(!renderer)return;const r=stage.getBoundingClientRect();if(r.width&&r.height){renderer.setSize(r.width,r.height,false);draw();}}
 const resizeObserver=new ResizeObserver(resize);resizeObserver.observe(stage);const visibilityObserver=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;if(visible){initialize();resize();}else animation?.pause();});visibilityObserver.observe(stage);
 const closeMenus=event=>{if(!tools.contains(event.target)){view.open=false;parts.open=false;}};document.addEventListener('pointerdown',closeMenus);tools.addEventListener('keydown',event=>{if(event.key==='Escape'){const target=parts.open?partsSummary:summary;parts.open=false;view.open=false;target.focus({preventScroll:true});}});
 const onVisibility=()=>{if(document.hidden)animation?.pause();else resize();};document.addEventListener('visibilitychange',onVisibility);const onMotion=()=>{animation?.pause();draw();};media.addEventListener('change',onMotion);
 retry.addEventListener('click',()=>{renderer?.dispose();renderer?.domElement.remove();renderer=null;attempted=false;initialize();});
 function dispose(){dead=true;animation?.pause();resizeObserver.disconnect();visibilityObserver.disconnect();document.removeEventListener('pointerdown',closeMenus);document.removeEventListener('visibilitychange',onVisibility);media.removeEventListener('change',onMotion);world?.traverse(o=>{o.geometry?.dispose();o.material?.map?.dispose();o.material?.dispose();});renderer?.dispose();}
 addEventListener('pagehide',event=>{if(!event.persisted)dispose();else animation?.pause();});
 status();
 return {host,update(next){const key=JSON.stringify(next);if(key===signature)return;signature=key;data=next;if(selected&&!data.present.includes(selected))selected=null;status();for(const b of partMenu.querySelectorAll('button'))b.hidden=data.confirmed&&!data.present.includes(b.dataset.part);if(renderer)build();},refresh:resize};
}
let transition=null,lastView=null;
export function animateJourney(view){if(view===lastView)return;lastView=view;transition?.revert();if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;const panel=document.querySelector(`[data-screen="${view}"]`);if(panel)transition=animate(panel,{opacity:[.5,1],translateY:[10,0],duration:340,ease:'out(3)',onComplete:()=>{panel.style.removeProperty('opacity');panel.style.removeProperty('transform');}});}
