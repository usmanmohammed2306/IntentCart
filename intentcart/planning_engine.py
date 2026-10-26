"""Constraint compiler and bounded verified planning tools; no model or network calls.
Search exhaustion is not a proof that a real-world setup is impossible.
"""
from __future__ import annotations
import copy,math,re,uuid,itertools
from datetime import date
from decimal import Decimal,ROUND_HALF_UP
from .workspace import Workspace,Item,Dimensions,Pose,Connection,polygon,overlap,analyze,digest
from .planning_models import Planning,Goal,SavedState
from . import device_research as research

def point_in(p,poly):
 x,z=p;inside=False
 for a,b in zip(poly,poly[1:]+poly[:1]):
  cross=(x-a[0])*(b[1]-a[1])-(z-a[1])*(b[0]-a[0])
  if abs(cross)<1e-7 and min(a[0],b[0])-1e-7<=x<=max(a[0],b[0])+1e-7 and min(a[1],b[1])-1e-7<=z<=max(a[1],b[1])+1e-7:return True
  if (a[1]>z)!=(b[1]>z) and x<(b[0]-a[0])*(z-a[1])/(b[1]-a[1])+a[0]:inside=not inside
 return inside

def segments_cross(a,b,c,d):
 def orient(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
 return orient(a,b,c)*orient(a,b,d)<-1e-7 and orient(c,d,a)*orient(c,d,b)<-1e-7

def simple_polygon(poly):
 if len(poly)<3 or len(set(poly))!=len(poly):return False
 if abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(poly,poly[1:]+poly[:1])))<1e-7:return False
 for i in range(len(poly)):
  for j in range(i+1,len(poly)):
   if j==i+1 or (i==0 and j==len(poly)-1):continue
   a,b,c,d=poly[i],poly[(i+1)%len(poly)],poly[j],poly[(j+1)%len(poly)]
   def on(a,b,q):return abs((b[0]-a[0])*(q[1]-a[1])-(b[1]-a[1])*(q[0]-a[0]))<1e-7 and min(a[0],b[0])-1e-7<=q[0]<=max(a[0],b[0])+1e-7 and min(a[1],b[1])-1e-7<=q[1]<=max(a[1],b[1])+1e-7
   if segments_cross(a,b,c,d) or any((on(a,b,c),on(a,b,d),on(c,d,a),on(c,d,b))):return False
 return True

def contained(rect,outline):
 # Split every footprint edge at all outline intersections, including vertices
 # and collinear contacts. Corners alone miss a concave notch.
 if not all(point_in(p,outline) for p in rect):return False
 for a,b in zip(rect,rect[1:]+rect[:1]):
  dx,dz=b[0]-a[0],b[1]-a[1];length=dx*dx+dz*dz;cuts={0.,1.}
  if length<1e-12:continue
  for c,d in zip(outline,outline[1:]+outline[:1]):
   ex,ez=d[0]-c[0],d[1]-c[1];den=dx*ez-dz*ex
   if abs(den)>1e-10:
    t=((c[0]-a[0])*ez-(c[1]-a[1])*ex)/den;u=((c[0]-a[0])*dz-(c[1]-a[1])*dx)/den
    if -1e-9<=t<=1+1e-9 and -1e-9<=u<=1+1e-9:cuts.add(max(0.,min(1.,t)))
   else:
    for q in (c,d):
     if abs((q[0]-a[0])*dz-(q[1]-a[1])*dx)<1e-7:
      t=((q[0]-a[0])*dx+(q[1]-a[1])*dz)/length
      if 0<=t<=1:cuts.add(t)
  cuts=sorted(cuts)
  if any(not point_in((a[0]+dx*(x+y)/2,a[1]+dz*(x+y)/2),outline) for x,y in zip(cuts,cuts[1:])):return False
 return True
def intersects(a,b):
 return any(point_in(p,b) for p in a) or any(point_in(p,a) for p in b) or any(segments_cross(p,q,r,s) for p,q in zip(a,a[1:]+a[:1]) for r,s in zip(b,b[1:]+b[:1]))
def outline_for(w,p):
 if w.surface.kind not in ('desk','shelf','shared'):return None
 if p.outline:
  points=[(v.x,v.z) for v in p.outline]
  if not simple_polygon(points):raise ValueError('Usable outline must be a simple, nonzero polygon.')
  return points
 if w.surface.kind in ('desk','shelf','shared') and w.surface.width and w.surface.depth:return polygon(w.surface.width,w.surface.depth,Pose())
 return None

def resolve(w,p,extra=(),today=None):
 today=today or date.today();extra=tuple(extra)+tuple(profile_dict(v) for v in p.profiles);facts={i.id:{} for i in w.items};issues=[];identities={};sources=[]
 registry={d['id']:d for d in reversed(research.catalog()+list(extra))}
 for b in p.devices:
  if b.item_id not in facts:continue
  d=registry.get(b.device_id)
  if d is None:issues.append({'code':'identity_unknown','item_id':b.item_id,'message':'Device profile unavailable.'});continue
  if not b.reviewed or b.source_digest!=d['digest'] or b.configuration not in d['configurations']:
   issues.append({'code':'source_changed','item_id':b.item_id,'message':'Exact variant/configuration/source changed or is not reviewed.'});continue
  reviewed=date.fromisoformat(d['reviewed_on'])
  if reviewed>today or (today-reviewed).days>180:
   issues.append({'code':'source_expired','item_id':b.item_id,'message':'Specification review is expired; review the current source before relying on it.'});continue
  identities[b.item_id]=d;facts[b.item_id]=copy.deepcopy(d['configurations'][b.configuration]);sources.extend(d['sources'])
 for obs in p.observations:
  if obs.state_id and obs.state_id!=p.active_state:continue
  if obs.item_id not in facts:continue
  if date.fromisoformat(obs.observed_on)>today:issues.append({'code':'future_observation','item_id':obs.item_id,'message':'Observation date is in the future.'});continue
  existing=facts[obs.item_id].get(obs.field)
  if existing is not None and existing!=obs.value:
   issues.append({'code':'fact_conflict','item_id':obs.item_id,'message':'Conflicting '+obs.field+'; select the correct configuration/source instead of silently replacing it.'});facts[obs.item_id].pop(obs.field,None)
  else:facts[obs.item_id][obs.field]=obs.value
 for i in w.items:
  if i.dimensions and i.dimensions.basis!='illustrative':
   for key,value in [('width_mm',i.dimensions.width),('depth_mm',i.dimensions.depth),('height_mm',i.dimensions.height)]:
    if key in facts[i.id] and isinstance(facts[i.id][key],(int,float)) and abs(facts[i.id][key]-value)>.1:
     issues.append({'code':'dimension_conflict','item_id':i.id,'message':'Measured/declared dimensions differ from the selected manufacturer configuration.'})
    facts[i.id][key]=value
 return {'facts':facts,'identities':identities,'issues':issues,'sources':list({research.digest(s):s for s in sources}.values())}

def physical(w,p):
 outline=outline_for(w,p);problems=[];rects={};unknown=[]
 if outline is None:return {'status':'unknown','issues':[{'code':'no_measured_surface','message':'No measured horizontal usable surface.'}],'unknown':[i.id for i in w.items]}
 obstacles=[[ (q.x,q.z) for q in z.points] for z in p.obstacles]
 if any(not simple_polygon(v) for v in obstacles):raise ValueError('Obstacle polygons must be simple and nonzero.')
 for i in w.items:
  if not i.dimensions or i.dimensions.basis=='illustrative':unknown.append(i.id);continue
  d=i.dimensions;rect=polygon(d.width,d.depth,i.pose);rects[i.id]=rect
  if not contained(rect,outline):problems.append({'code':'outside_outline','item_ids':[i.id],'message':i.name+' extends outside the usable outline.'})
  for z in w.surface.zones:
   if overlap(rect,polygon(z.width,z.depth,z.pose)):problems.append({'code':'reserved_overlap','item_ids':[i.id],'message':i.name+' intersects '+z.name})
  for z,poly in zip(p.obstacles,obstacles):
   if intersects(rect,poly):problems.append({'code':'obstacle_overlap','item_ids':[i.id],'message':i.name+' intersects '+z.name})
 rows=list(rects)
 for n,a in enumerate(rows):
  for b in rows[n+1:]:
   if overlap(rects[a],rects[b]):problems.append({'code':'item_overlap','item_ids':[a,b],'message':'Measured item footprints overlap.'})
 return {'status':'conflict' if problems else 'unknown' if unknown else 'pass','issues':problems,'unknown':unknown}

def arrange(w,p,node_limit=12000):
 out=copy.deepcopy(w);outline=outline_for(out,p)
 if outline is None:return out,{'status':'needs_measurements','nodes':0,'message':'Measure a usable surface before arranging.'}
 if len(out.items)>16:return out,{'status':'search_limit','nodes':0,'message':'Arrange at most sixteen items per space; create per-space groups for a larger room.'}
 if any(not i.dimensions or i.dimensions.basis=='illustrative' for i in out.items):return out,{'status':'needs_measurements','nodes':0,'message':'Exact in-use footprints are required; illustrative sizes are not substituted.'}
 bounds=(min(x for x,z in outline),max(x for x,z in outline),min(z for x,z in outline),max(z for x,z in outline));reserved=[polygon(z.width,z.depth,z.pose) for z in out.surface.zones];obstacles=[[(q.x,q.z) for q in r.points] for r in p.obstacles]
 fixed=[i for i in out.items if i.locked];moving=sorted([i for i in out.items if not i.locked],key=lambda i:(-i.dimensions.width*i.dimensions.depth,i.id));placed=[];nodes=0;cutoff=False
 def valid(rect,item):
  x=sum(v[0] for v in rect)/len(rect);z=sum(v[1] for v in rect)/len(rect)
  for g in p.goals:
   if g.kind=='reach' and g.required and p.seating and (not g.state_id or g.state_id==p.active_state) and (not g.item_id or g.item_id==item.id) and (not g.category or g.category==item.kind):
    if math.hypot(x-p.seating.x,z-p.seating.z)>float(g.value)+1e-7:return False
  return contained(rect,outline) and not any(overlap(rect,r) for _,r in placed) and not any(overlap(rect,r) for r in reserved) and not any(intersects(rect,r) for r in obstacles)
 for i in fixed:
  rect=polygon(i.dimensions.width,i.dimensions.depth,i.pose)
  if not valid(rect,i):return w,{'status':'locked_conflict','nodes':nodes,'message':'A locked item conflicts with the surface, another locked item or reserved area.'}
  placed.append((i,rect))
 def search(n):
  nonlocal nodes,cutoff
  if n==len(moving):return True
  i=moving[n];d=i.dimensions
  for yaw in dict.fromkeys([i.pose.yaw,0.,math.pi/2]):
   width=abs(d.width*math.cos(yaw))+abs(d.depth*math.sin(yaw));depth=abs(d.width*math.sin(yaw))+abs(d.depth*math.cos(yaw));xs={i.pose.x,bounds[0]+width/2,bounds[1]-width/2};zs={i.pose.z,bounds[2]+depth/2,bounds[3]-depth/2}
   if p.seating:
    xs.add(p.seating.x);zs.add(p.seating.z)
    for g in p.goals:
     if g.kind=='reach' and g.required and isinstance(g.value,(int,float)):
      xs.update([p.seating.x-g.value,p.seating.x+g.value]);zs.update([p.seating.z-g.value,p.seating.z+g.value])
   for _,r in placed:
    xs.update([min(x for x,z in r)-width/2,max(x for x,z in r)+width/2]);zs.update([min(z for x,z in r)-depth/2,max(z for x,z in r)+depth/2])
   for r in reserved+obstacles:
    xs.update([min(x for x,z in r)-width/2,max(x for x,z in r)+width/2]);zs.update([min(z for x,z in r)-depth/2,max(z for x,z in r)+depth/2])
   # Include concave outline corners; only actual containment passes are used.
   for x,z in outline:xs.update([x+width/2,x-width/2]);zs.update([z+depth/2,z-depth/2])
   candidates=sorted(itertools.product(xs,zs),key=lambda p:(abs(p[0]-i.pose.x)+abs(p[1]-i.pose.z),p))
   for x,z in candidates:
    nodes+=1
    if nodes>node_limit:cutoff=True;return False
    pose=Pose(x=float(x),z=float(z),yaw=yaw);r=polygon(d.width,d.depth,pose)
    if valid(r,i):
     old=i.pose;i.pose=pose;placed.append((i,r))
     if search(n+1):return True
     placed.pop();i.pose=old
  return False
 success=search(0)
 return (out if success else w),{'status':'found' if success else 'search_limit' if cutoff else 'no_layout_in_search','nodes':nodes,'message':'Verified bounding footprints; no load/ergonomic certificate.' if success else 'No layout found in this bounded placement search; this does not prove all real arrangements impossible.'}

def costs(w,p,today=None):
 today=today or date.today();rows=[];unknown=[];total=0;has_allowance=False
 for i in w.items:
  if i.owned:rows.append({'item_id':i.id,'amount_minor':0,'basis':'owned / no new purchase'});continue
  offers=[o for o in p.offers if o.item_id==i.id or o.device_id and any(b.item_id==i.id and b.device_id==o.device_id for b in p.devices)]
  current=[o for o in offers if date.fromisoformat(o.observed_on)<=today<=date.fromisoformat(o.valid_until) and o.stock!='out_of_stock' and (not p.region or not o.region or p.region==o.region)]
  values=[]
  for o in current:
   charges=[o.shipping_minor,o.tax_minor,o.duty_minor]
   if any(x is None for x in charges):continue
   rate=Decimal(1)
   if o.currency!=w.currency:
    fx=next((f for f in p.exchange_rates if f.currency==o.currency and date.fromisoformat(f.observed_on)<=today<=date.fromisoformat(f.valid_until)),None)
    if not fx:continue
    rate=Decimal(str(fx.rate))
   amount=int((Decimal(o.amount_minor+sum(charges))*rate).quantize(Decimal('1'),rounding=ROUND_HALF_UP));values.append((amount,o))
  if values:
   amount,offer=min(values,key=lambda x:(x[0],x[1].id));rows.append({'item_id':i.id,'amount_minor':amount,'offer_id':offer.id,'observed_on':offer.observed_on,'stock':offer.stock,'return_days':offer.return_days,'qualified':True,'url':offer.url});total+=amount
  elif not offers and i.price_cents is not None:
   has_allowance=True;rows.append({'item_id':i.id,'amount_minor':i.price_cents,'basis':'user-declared item allowance; no live offer'});total+=i.price_cents
  else:unknown.append({'item_id':i.id,'reason':'Missing/expired offer, regional/FX mismatch, stock unavailable or unknown landed charges.'})
 purchases=any(not i.owned for i in w.items)
 if purchases and (has_allowance or not p.offers):
  if w.shipping_cents is None or w.tax_cents is None:unknown.append({'reason':'Shipping/tax unknown.'})
  else:total+=w.shipping_cents+w.tax_cents
 return {'status':'unknown' if unknown else 'over_budget' if w.budget_cents is not None and total>w.budget_cents else 'within_budget' if w.budget_cents is not None else 'no_budget_declared','total_minor':None if unknown else total,'currency':w.currency,'rows':rows,'unknown':unknown,'basis':'Declared or dated reviewed offers, not a payment quote or delivery guarantee.'}

def pack_boxes(sizes,bag,node_limit=20000):
 """Finite axis-aligned 3D bounding-box search. Success is checked placement;
 exhaustion is not proof of infeasibility. Closed boxes omit packing padding.
 """
 if len(sizes)>12:return {'status':'search_limit','nodes':0,'placements':[]}
 if not sizes:return {'status':'found','nodes':0,'placements':[]}
 if any(not any(all(v<=b for v,b in zip(o,bag)) for o in set(itertools.permutations(s))) for s in sizes):return {'status':'individual_box_too_large','nodes':0,'placements':[]}
 order=sorted(enumerate(sizes),key=lambda v:-math.prod(v[1]));placed=[];nodes=0;cutoff=False
 def search(n):
  nonlocal nodes,cutoff
  if n==len(order):return True
  original,size=order[n]
  points=itertools.product(*[sorted({0.}|{pos[k]+dim[k] for _,pos,dim in placed}) for k in range(3)])
  for pos in points:
   for dim in sorted(set(itertools.permutations(size))):
    nodes+=1
    if nodes>node_limit:cutoff=True;return False
    if any(pos[k]+dim[k]>bag[k]+1e-8 for k in range(3)):continue
    if any(all(pos[k]<p[k]+d[k]-1e-8 and p[k]<pos[k]+dim[k]-1e-8 for k in range(3)) for _,p,d in placed):continue
    placed.append((original,pos,dim))
    if search(n+1):return True
    placed.pop()
  return False
 success=search(0)
 return {'status':'found' if success else 'search_limit' if cutoff else 'no_pack_in_search','nodes':nodes,'placements':[{'index':i,'position':pos,'size':dim} for i,pos,dim in placed] if success else []}

def evaluate(w,p,extra=(),today=None):
 today=today or date.today();resolved=resolve(w,p,extra,today);facts=resolved['facts'];phys=physical(w,p);cost=costs(w,p,today);checks=[]
 def add(g,status,reason):checks.append({'id':g.id,'text':g.text,'kind':g.kind,'status':status,'reason':reason,'required':g.required})
 for g in p.goals:
  if g.state_id and g.state_id!=p.active_state:continue
  selected=[i for i in w.items if (not g.item_id or i.id==g.item_id) and (not g.category or i.kind==g.category)];fs=[facts.get(i.id,{}) for i in selected]
  if g.item_id and not selected:add(g,'unknown','The referenced item is absent from this state. Review the target before claiming this condition is satisfied.');continue
  status='unknown';reason='This condition needs an explicit supported fact or human judgment.'
  if g.kind=='count':
   actual=sum(i.kind==g.category for i in w.items);status='met' if actual==g.value else 'unmet';reason=f'{actual} {g.category} item(s); requested {g.value}.'
  elif g.kind=='no_purchase':status='met' if all(i.owned for i in w.items) else 'unmet';reason='No new purchase.' if status=='met' else 'Proposed purchases remain.'
  elif g.kind=='surface_fit':status={'pass':'met','conflict':'unmet','unknown':'unknown'}[phys['status']];reason=('Measure a horizontal usable support surface, or change this physical-fit requirement.' if outline_for(w,p) is None else 'Record the operating footprint for: '+', '.join(i.name for i in w.items if i.id in phys['unknown']) if phys['status']=='unknown' else '; '.join(v['message'] for v in phys['issues']) if phys['status']=='conflict' else 'Rotated measured footprints, usable outline and reserved/obstacle zones checked.')
  elif g.kind=='budget':status='unknown' if cost['total_minor'] is None else 'met' if cost['total_minor']<=g.value else 'unmet';reason='All declared landed costs considered; unknown charges block a pass.'
  elif g.kind=='identity':status='met' if selected and all(i.id in resolved['identities'] for i in selected) else 'unknown';reason='Exact reviewed variant/configuration/source binding required.'
  elif g.kind in ('no_drill','no_clamp'):
   relevant=[i for i in selected if i.kind in ('monitor','other')];mounts=[facts[i.id].get('mount') for i in relevant]
   forbidden='drill' if g.kind=='no_drill' else 'clamp';status='unmet' if any(v==forbidden for v in mounts) else 'met' if all(v in ('freestanding','clamp','drill') and v!=forbidden for v in mounts) else 'unknown';reason='Recorded mounting method compared with the specific restriction; structural/load/installation safety remains separate.'
  elif g.kind=='max_weight':
   weights=[f.get('weight_g') for f in fs];status='unknown' if not weights or any(v is None for v in weights) else 'met' if sum(weights)<=float(g.value) else 'unmet';reason='Total selected equipment weight; missing weights remain unknown.'
  elif g.kind=='bag_fit':
   sizes=[[f.get(k) for k in ('width_mm','depth_mm','height_mm')] for f in fs]
   if p.bag_mm and sizes and all(all(isinstance(v,(int,float)) for v in s) for s in sizes):
    packing=pack_boxes(sizes,p.bag_mm);status='qualified' if packing['status']=='found' else 'unmet' if packing['status']=='individual_box_too_large' else 'unknown';reason='Simultaneous closed bounding-box packing '+packing['status']+'; '+str(packing['nodes'])+' searched nodes. Allow padding/protection and verify actual bag opening/access.'
  elif g.kind=='reach':
   if p.seating and isinstance(g.value,(int,float)) and selected:
    distances=[math.hypot(i.pose.x-p.seating.x,i.pose.z-p.seating.z) for i in selected];status='met' if max(distances)<=g.value else 'unmet';reason='Declared reach to selected item centers only; no ergonomic/medical suitability claim.'
  elif g.kind=='clearance':status='unknown' if w.surface.clearance_mm is None else 'met' if w.surface.clearance_mm>=float(g.value) else 'unmet';reason='User-declared vertical clearance compared to your stated threshold; access paths use reserved polygons.'
  elif g.kind=='handedness':
   values=[f.get('handedness') for f in fs];status='unknown' if not values or any(v is None for v in values) else 'met' if all(v in (g.value,'ambidextrous') for v in values) else 'unmet';reason='Exact variant handedness, not medical suitability.'
  elif g.kind=='noise':
   claims=[f.get('noise_claim') for f in fs];status='qualified' if claims and all(claims) else 'unknown';reason='Manufacturer noise descriptions are subjective; audition/measurement remains your decision.'
  elif g.kind=='display_mode':
   h,hz=g.value,g.value2;values=[(f.get('max_height'),f.get('max_hz')) for f in fs]
   routes=connections(w,p,resolved);video=[r for r in routes['routes'] if r.get('target') in {i.id for i in selected}];status='unknown' if routes['status']=='unknown' or len(video)<len(selected) or any(r.get('max_height') is None or r.get('max_hz') is None for r in video) else 'met' if video and all(r['max_height']>=h and r['max_hz']>=(hz or 60) for r in video) else 'unmet';reason='Mode requires a complete bounded route; missing host/cable/GPU/OS mode facts stay unknown.'
  elif g.kind=='native_displays':
   hosts=[i for i in selected if i.kind in ('laptop','desktop')];values=[facts[i.id].get('native_displays') for i in hosts];status='unknown' if not values or any(v is None for v in values) else 'met' if all(v>=float(g.value) for v in values) else 'unmet';reason='Each selected host native limit checked separately; no unapproved software workaround.'
  elif g.kind=='connections':
   result=connections(w,p,resolved);status=result['status'];reason=result['summary']
  elif g.kind=='availability':
   wanted={i.id for i in selected if not i.owned};relevant=[r for r in cost['rows'] if r.get('item_id') in wanted and r.get('offer_id')];status='met' if not wanted or len({r['item_id'] for r in relevant})==len(wanted) and all(r.get('stock')=='in_stock' for r in relevant) else 'unknown';reason='No purchase availability needed for owned items.' if not wanted else 'Every selected proposed purchase needs dated observed stock; delivery at a deadline is not guaranteed.'
  elif g.kind=='returnability':
   wanted={i.id for i in selected if not i.owned};relevant=[r for r in cost['rows'] if r.get('item_id') in wanted and r.get('offer_id')];status='met' if not wanted else 'qualified' if len({r['item_id'] for r in relevant})==len(wanted) and all(r.get('return_days') is not None for r in relevant) else 'unknown';reason='No proposed purchase to return.' if not wanted else 'Each selected proposed purchase needs regional return conditions; review exclusions before purchase.'
  elif g.kind=='power_region':
   status='qualified' if fs and all(f.get('voltage_min') is not None and f.get('voltage_max') is not None for f in fs) else 'unknown';reason='Recorded nameplate ranges only; plugs, grounding and electrical safety require local verification.'
  add(g,status,reason)
 hard=[c for c in checks if c['required'] and c['status'] in ('unmet','unknown')]
 if resolved['issues']:hard+=resolved['issues']
 return {'status':'NEEDS_INFO' if not checks or any(c.get('status')=='unknown' for c in hard) or resolved['issues'] else 'CONSTRAINTS_UNMET' if hard else 'READY_WITH_CAVEATS' if any(c['status']=='qualified' for c in checks) else 'READY','goals':checks,'physical':phys,'cost':cost,'connections':connections(w,p,resolved),'source_issues':resolved['issues'],'sources':resolved['sources'],'scope':'Goal-specific verified planning over declared geometry and reviewed facts. Not physical, medical, structural, procurement or delivery certification.'}

def connections(w,p,resolved=None):
 resolved=resolved or resolve(w,p);facts=resolved['facts'];hosts=[i for i in w.items if i.kind in ('laptop','desktop')];screens=[i for i in w.items if i.kind=='monitor'];routes=[];questions=[]
 confirmed=[e for e in w.connections if e.status=='user_confirmed'];routes=[{'source':e.source,'target':e.target,'basis':'User-confirmed route; not source-certified','status':'qualified','max_height':None,'max_hz':None} for e in confirmed]
 if not hosts and screens:return {'status':'unknown','routes':routes,'summary':'Select the exact host(s) before checking video routes.'}
 if len(hosts)>1 and any(i.kind in ('keyboard','mouse','monitor') for i in w.items):
  switches=[i for i in w.items if facts[i.id].get('switch_hosts',0)>=len(hosts) and facts[i.id].get('switch_mode')=='hardware_select' and facts[i.id].get('isolation_verified') is True]
  isolated=any(all(any(e.source==h.id and e.target==s.id for e in confirmed) for h in hosts) and all(any(e.source==s.id and e.target==i.id for e in confirmed) for i in w.items if i.kind in ('keyboard','mouse','monitor')) for s in switches)
  if not isolated:questions.append('Multiple hosts need explicit switching/isolation routes. Pairing alone does not establish isolation.')
 if len(hosts)==1:
  host=hosts[0];f=facts[host.id];native=f.get('native_displays');ports={'hdmi':f.get('hdmi_outputs',int(f.get('video_out_hdmi') is True)),'dp':f.get('dp_outputs',int(f.get('video_out_dp') is True)),'usb_c_dp':f.get('usb_c_video_outputs',int(f.get('video_out_usb_c') is True))};cables={i.id:facts[i.id] for i in w.items if i.kind=='cable'};used=set();native_used=0
  docks=[i for i in w.items if i.kind=='dock' and facts[i.id].get('driver_required') is True];dock_slots=sum(facts[i.id].get('displays',0) for i in docks) if f.get('usb_c') is True or f.get('usb_a') is True else 0
  confirmed_screens={e.target for e in confirmed if e.source==host.id and any(i.id==e.target for i in screens)}
  if confirmed_screens and len(confirmed_screens)<len(screens):questions.append('Some screen routes are user-confirmed without resource allocation; check all shared port/native limits explicitly before adding routes.')
  native_used=len(confirmed_screens)
  if screens and native is None:questions.append('Native display limit is unknown.')
  for screen in screens:
   if any(e.target==screen.id and e.source==host.id for e in confirmed):continue
   sf=facts[screen.id];chosen=None
   for port,link,accept in [('hdmi','hdmi_hdmi','video_in_hdmi'),('dp','dp_dp','video_in_dp'),('usb_c_dp','usb_c_dp','video_in_dp')]:
    cable=next((k for k,v in cables.items() if k not in used and v.get('link_type')==link),None)
    if cable and ports[port]>0 and native is not None and native_used<native and sf.get(accept) is True:
     chosen=(cable,port,'Source-based direct '+port.replace('_',' ')+' route');native_used+=1;ports[port]-=1;break
   if chosen is None and dock_slots>0 and p.allow_driver is True and sf.get('video_in_hdmi') is True:
    cable=next((k for k,v in cables.items() if k not in used and v.get('link_type')=='hdmi_hdmi'),None)
    if cable:chosen=(cable,'displaylink','Exact-revision vendor DisplayLink route, conditional on permitted software and OS support');dock_slots-=1
   if chosen:
    cable,port,basis=chosen;used.add(cable);cf=cables[cable];caps=[sf,cf] if port=='displaylink' else [sf,cf,f];height=min(v['max_height'] for v in caps) if all(isinstance(v.get('max_height'),(int,float)) for v in caps) else None;hz=min(v['max_hz'] for v in caps) if all(isinstance(v.get('max_hz'),(int,float)) for v in caps) else None
    routes.append({'source':host.id,'target':screen.id,'cable_id':cable,'basis':basis,'status':'qualified','max_height':height,'max_hz':hz})
   else:questions.append('No unconsumed compatible port/cable route to '+screen.name+'. Display count, software permission or exact facts may be missing.')
  for peripheral in [i for i in w.items if i.kind in ('mouse','keyboard')]:
   pf=facts[peripheral.id]
   if f.get('bluetooth') is True and pf.get('bluetooth') is True:routes.append({'source':host.id,'target':peripheral.id,'basis':'Recorded Bluetooth support; pairing/OS remain conditional','status':'qualified'})
   elif not any(e.target==peripheral.id for e in confirmed):questions.append('Peripheral connection is unknown for '+peripheral.name+'.')
 if not screens and not any(i.kind in ('keyboard','mouse') for i in w.items):return {'status':'met','routes':routes,'summary':'No external display/peripheral connection requested.'}
 return {'status':'unknown' if questions else 'qualified','routes':routes,'questions':questions,'summary':'; '.join(questions) if questions else 'Resource-counted declared/source-based routes; no installation, purchasing or security authority inferred.'}

def apply_configuration(w,p,item_id,selection,extra=()):
 d=research.get(selection.device_id,tuple(extra)+tuple(profile_dict(v) for v in p.profiles))
 if not selection.reviewed or selection.source_digest!=d['digest']:raise ValueError('Review the exact current device/configuration first.')
 cfg=d['configurations'].get(selection.configuration)
 if cfg is None:raise ValueError('Unknown configuration.')
 out=copy.deepcopy(w);meta=copy.deepcopy(p);i=next((i for i in out.items if i.id==item_id),None)
 if not i or i.kind!=d['kind']:raise ValueError('Device kind does not match the selected item.')
 i.model=d['name'];i.name=d['name']
 if all(isinstance(cfg.get(k),(int,float)) for k in ('width_mm','depth_mm','height_mm')):
  i.dimensions=Dimensions(width=float(cfg['width_mm']),depth=float(cfg['depth_mm']),height=float(cfg['height_mm']),basis='manufacturer' if d['sources'][0].get('url','').startswith('https://') else 'reviewed_document',source=d['sources'][0].get('url','Local reviewed document'),state=selection.configuration)
 else:i.dimensions=None
 old_devices=copy.deepcopy(meta.devices);meta.devices=[b for b in meta.devices if b.item_id!=item_id]+[selection]
 if meta.allow_driver is True and old_devices!=meta.devices:meta.allow_driver=None;meta.driver_permission_token=None
 return out,meta

def state_design(w,p,state_id,extra=()):
 state=next((s for s in p.states if s.id==state_id),None)
 if not state:raise ValueError('Unknown workspace state.')
 out=copy.deepcopy(state.workspace if state.workspace is not None else w);meta=copy.deepcopy(p)
 if state.devices is not None:meta.devices=copy.deepcopy(state.devices)
 out.items=[i for i in out.items if i.id not in state.hidden];out.connections=[e for e in out.connections if any(i.id==e.source for i in out.items) and any(i.id==e.target for i in out.items)];meta.devices=[b for b in meta.devices if any(i.id==b.item_id for i in out.items)]
 for i in out.items:
  if i.id in state.poses:i.pose=state.poses[i.id]
 for item_id,cfg in state.configurations.items():
  b=next((b for b in meta.devices if b.item_id==item_id),None)
  if b:b.configuration=cfg;out,meta=apply_configuration(out,meta,item_id,b,extra)
 if p.allow_driver is True and (state.devices is not None and state.devices!=p.devices or sum(i.kind=='monitor' for i in out.items)!=sum(i.kind=='monitor' for i in w.items)):
  meta.allow_driver=None;meta.driver_permission_token=None
 if state.outline is not None:meta.outline=copy.deepcopy(state.outline)
 if state.obstacles is not None:meta.obstacles=copy.deepcopy(state.obstacles)
 meta.seating=state.seating;meta.bag_mm=state.bag_mm
 meta.active_state=state.id
 if state.clearance_mm is not None:out.surface.clearance_mm=state.clearance_mm
 if state.surface_width is not None:out.surface.width=state.surface_width
 if state.surface_depth is not None:out.surface.depth=state.surface_depth
 return out,meta


def profile_dict(p):
 value=p.model_dump() if hasattr(p,'model_dump') else copy.deepcopy(p)
 # JSON has one number type. A browser serializes300.0 as300; both denote
 # the same fact. Canonicalize integral floats before binding reviewed facts.
 # Booleans and genuinely different values remain distinct. Existing bindings
 # are never rewritten: a mismatched prior digest still requires review.
 def numbers(v):
  if isinstance(v,float) and v.is_integer():return int(v)
  if isinstance(v,list):return [numbers(x) for x in v]
  if isinstance(v,dict):return {k:numbers(x) for k,x in v.items()}
  return v
 value.pop('digest',None);value=numbers(value);value['digest']=research.digest(value);return value

def repair_suggestions(w,p):
 """Explicit counterfactuals, never silent relaxation of a required goal."""
 suggestions=[]
 if physical(w,p)['status']=='conflict':
  for i in [i for i in w.items if not i.locked and i.kind not in ('laptop','desktop')][:4]:
   alt=copy.deepcopy(w);alt.items=[x for x in alt.items if x.id!=i.id];alt.connections=[x for x in alt.connections if x.source!=i.id and x.target!=i.id];placed,receipt=arrange(alt,p,node_limit=3000)
   if receipt['status']=='found':suggestions.append({'change':'Use a separate/packed state without '+i.name,'removed_item_id':i.id,'physical_status':'pass','workspace':placed.model_dump(),'requires_goal_review':[g.id for g in p.goals if g.kind=='count' and g.category==i.kind],'scope':'Physical alternative only; review quantity, connections and workload before choosing.'})
 return suggestions

def candidate_designs(w,p,extra=(),limit=12):
 """Minimal item-count repairs, then bounded alternative exact-variant choices."""
 from .planning_models import DeviceSelection
 base=copy.deepcopy(w);meta=copy.deepcopy(p);issues=[];new=[]
 for g in p.goals:
  if g.kind!='count' or g.state_id and g.state_id!=p.active_state:continue
  current=[i for i in base.items if i.kind==g.category];desired=int(g.value)
  if desired<0 or desired>12:issues.append('Requested count is outside the per-kind planning bound.');continue
  if len(current)>desired:
   removable=sorted([i for i in current if not i.locked],key=lambda i:(i.owned,i.id));needed=len(current)-desired
   if len(removable)<needed:issues.append('Locked '+g.category+' items prevent this quantity change.');continue
   ids={i.id for i in removable[:needed]};base.items=[i for i in base.items if i.id not in ids];base.connections=[e for e in base.connections if e.source not in ids and e.target not in ids];meta.devices=[b for b in meta.devices if b.item_id not in ids]
  elif len(current)<desired:
   for n in range(desired-len(current)):
    i=Item(id=uuid.uuid4().hex,kind=g.category,name='Proposed '+g.category,owned=False);base.items.append(i);new.append(i.id)
 if len(base.items)>48:return [],['Workspace item bound exceeded.']
 choices=[];profiles=research.catalog()+[profile_dict(v) for v in p.profiles]+list(extra)
 for item_id in new:
  i=next(i for i in base.items if i.id==item_id);options=[]
  for d in profiles:
   if d['kind']!=i.kind:continue
   for cfg,values in d['configurations'].items():
    if i.kind=='laptop' and cfg!='in_use':continue
    if i.kind=='monitor' and values.get('mount')!='freestanding':continue
    if p.allow_driver is False and (values.get('driver_required') or values.get('requires_software')):continue
    hand=[g.value for g in p.goals if g.kind=='handedness' and g.category==i.kind]
    if hand and values.get('handedness') not in hand+['ambidextrous']:continue
    options.append((d,cfg))
  # Prefer known declared costs; no missing price is treated as cheap.
  def key(v):
   offers=[o.amount_minor for o in p.offers if o.device_id==v[0]['id']];return (not bool(offers),min(offers) if offers else 0,v[0]['id'],v[1])
  options.sort(key=key);choices.append((item_id,options[:4] or [(None,None)]))
 candidates=[]
 for combo in itertools.islice(itertools.product(*(opts for _,opts in choices)),limit) if choices else [()]:
  out=copy.deepcopy(base);context=copy.deepcopy(meta)
  for (item_id,_),(d,cfg) in zip(choices,combo):
   if d is None:continue
   selection=DeviceSelection(item_id=item_id,device_id=d['id'],configuration=cfg,source_digest=d['digest'],reviewed=True);out,context=apply_configuration(out,context,item_id,selection,extra)
  if context.allow_driver is True and (context.devices!=p.devices or sum(i.kind=='monitor' for i in out.items)!=sum(i.kind=='monitor' for i in w.items)):
   context.allow_driver=None;context.driver_permission_token=None
  if any(g.kind=='surface_fit' and g.required for g in context.goals):out,placement=arrange(out,context)
  else:placement={'status':'not_requested','nodes':0}
  assessment=evaluate(out,context,extra);scoped=scope_assessment(out,context,extra,active=assessment);changes=sum(1 for i in out.items if not any(i.model_dump()==old.model_dump() for old in w.items))+sum(1 for old in w.items if not any(i.id==old.id for i in out.items));candidates.append({'workspace':out.model_dump(),'planning':context.model_dump(),'assessment':assessment,'scope_assessment':scoped,'placement':placement,'changed_items':changes,'identity_review_required':[b.item_id for b in context.devices if b.item_id in new],'counterfactuals':repair_suggestions(out,context) if placement['status'] in ('no_layout_in_search','locked_conflict','search_limit') else []})
 status_rank={'READY':0,'READY_WITH_CAVEATS':1,'NEEDS_INFO':2,'CONSTRAINTS_UNMET':3}
 candidates.sort(key=lambda c:(status_rank[c['scope_assessment']['status']],sum(g['required'] and g['status'] in ('unknown','unmet') for g in c['assessment']['goals']),c['assessment']['cost']['total_minor'] is None,c['assessment']['cost']['total_minor'] or 0,c['changed_items']))
 return candidates,issues

def state_reports(w,p,extra=()):
 reports=[]
 for s in p.states:
  current,context=state_design(w,p,s.id,extra);reports.append({'id':s.id,'name':s.name,'owner_label':s.owner_label,'required_goal_count':sum(g.required and (not g.state_id or g.state_id==s.id) for g in p.goals),'assessment':evaluate(current,context,extra)})
 return reports

def procurement(w,p,extra=(),states=None,active=None):
 reports=state_reports(w,p,extra) if states is None else states;by={r['id']:r for r in reports};rows=[];total=0;unknown=False;remaining=dict(p.inventory)
 for group in p.groups:
  gw,gp=state_design(w,p,group.state_id,extra) if group.state_id else (w,p)
  assessment=by[group.state_id]['assessment'] if group.state_id and group.state_id in by else active if active is not None else evaluate(gw,gp,extra)
  if not group.state_id:active=assessment
  value=assessment['cost']['total_minor'];amount=None if value is None else value*group.quantity;missing=[]
  for i in gw.items:
   if not i.owned:continue
   key=next((b.device_id for b in gp.devices if b.item_id==i.id),i.id)
   # A prototype marked owned is one object, not a supply of 100 classroom kits.
   available=remaining.get(key,1);needed=group.quantity
   if available<needed:missing.append({'item_id':i.id,'inventory_key':key,'needed':needed,'available':available})
   remaining[key]=max(0,available-needed)
  if missing:amount=None
  unknown|=amount is None
  if amount is not None:total+=amount
  rows.append({'name':group.name,'quantity':group.quantity,'responsible':group.responsible,'state_id':group.state_id,'unit_total_minor':value,'group_total_minor':amount,'assessment_status':assessment['status'],'inventory_shortfall':missing})
 return {'rows':rows,'total_minor':None if unknown else total,'currency':w.currency,'budget_minor':p.procurement_budget_minor,'status':'needs_inventory_or_costs' if unknown else 'over_budget' if p.procurement_budget_minor is not None and total>p.procurement_budget_minor else 'within_declared_budget' if p.procurement_budget_minor is not None else 'estimate_only','scope':'Per-space estimates consume explicit inventory counts once across groups. Not approval, stock reservation or a purchase order.'}


def scope_assessment(w,p,extra=(),active=None):
 active=evaluate(w,p,extra) if active is None else active;states=state_reports(w,p,extra);group=procurement(w,p,extra,states=states,active=active);issues=[];unmet=False
 for row in states:
  if not row['required_goal_count']:continue
  if row['assessment']['status'] in ('NEEDS_INFO','CONSTRAINTS_UNMET'):
   unmet|=row['assessment']['status']=='CONSTRAINTS_UNMET';issues.append('State '+row['name']+': '+('; '.join(g['text']+' — '+g['reason'] for g in row['assessment']['goals'] if g['required'] and g['status'] in ('unknown','unmet')) or 'Resolve source/fact conflicts.'))
 if p.groups and group['status'] in ('needs_inventory_or_costs','over_budget'):
  unmet|=group['status']=='over_budget';issues.append('Group procurement: '+group['status'].replace('_',' ')+'. Verify inventory, complete landed costs and the declared group budget.')
 if any(g.state_id and g.state_id not in {s.id for s in p.states} for g in p.goals):issues.append('A required goal refers to an unavailable saved state; review its target.')
 if any(g.state_id and g.state_id not in {s.id for s in p.states} for g in p.groups):issues.append('A procurement group refers to an unavailable saved state.')
 status=active['status']
 if issues:status='CONSTRAINTS_UNMET' if unmet and active['status']!='NEEDS_INFO' else 'NEEDS_INFO'
 return {'status':status,'issues':issues,'states':states,'procurement':group}
