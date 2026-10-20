import json
from pathlib import Path
names=['Metro','Drift','Summit','Forma','Atlas','Transit','Rainline','Daybreak','Switch','Trail','Studio','Nomad','Signal','Lift','Cove','Field','Contour','Roam','Loop','Scout','Slate','Journey','Arc','Cloud']
# weight grams, liters, laptop inches, rain/organization/comfort/style (0..1), price cents
specs=[(780,22,16,.8,.9,.8,.7,6900),(460,18,14,.4,.5,.6,.9,4900),(1050,30,16,.9,.6,.95,.4,8900),(710,20,16,.5,.8,.7,.98,7900),(1160,32,17,.85,.95,.85,.6,9900),(850,24,16,.75,.95,.9,.75,8400),(920,22,16,1,.7,.8,.7,7600),(510,20,15,.45,.6,.75,.7,3900),(740,24,16,.7,.85,.8,.85,7200),(990,28,15,.85,.5,.95,.5,6500),(620,18,14,.5,.7,.65,.95,5900),(1100,35,17,.8,.8,.9,.6,9500),(680,21,16,.65,.95,.75,.9,8700),(430,18,14,.5,.4,.8,.65,4500),(590,20,15,.7,.65,.75,.9,6200),(820,26,16,.9,.65,.85,.6,5800),(760,23,16,.7,.8,.95,.85,9300),(980,30,16,.65,.75,.9,.7,7900),(670,22,16,.6,.9,.8,.8,5400),(550,20,15,.7,.5,.8,.5,3400),(800,21,16,.8,.85,.75,.95,8800),(1200,38,17,.85,.9,.9,.5,10900),(700,24,16,.8,.8,.85,.85,8100),(390,17,13,.4,.4,.7,.8,2900)]
colors=['#386457','#d3946b','#495d78','#bcb7a4','#816855','#71745c']
products=[]
for i,(name,s) in enumerate(zip(names,specs)):
 w,l,lap,r,o,c,sty,price=s
 products.append(dict(id=f'bag-{i+1:02d}',name=name+' Pack',tag=['City essential','Carry less','Go further','Designed for everyday'][i%4],price_cents=price,weight_g=w,capacity_l=l,laptop_inches=lap,rain=r,organization=o,comfort=c,style=sty,color=colors[i%6],features=[round((1300-w)/1000,3),r,o,round(l/40,3),c,sty,round((12000-price)/10000,3)],description=f'A fictional {l}L backpack for the IntentCart sandbox store. Fits up to a {lap}-inch laptop.'))
Path('intentcart/data/catalog.json').write_text(json.dumps(products,indent=2)+'\n')
