"""Exact automatic line-discount reconciliation in integer minor units.
No coupon guessing, membership claim, tax calculation or payment authority.
"""
import re

def validate(data,lines,totals):
 if not isinstance(data.get('line_items'),list) or len(data['line_items'])>12:raise ValueError('Invalid merchant line collection.')
 observed=[];discounts={};by_index={};gross=0
 for index,row in enumerate(data['line_items']):
  if not isinstance(row,dict) or not isinstance(row.get('item'),dict):raise ValueError('Invalid merchant item.')
  item=row.get('item') or {};gid=item.get('id','');qty=row.get('quantity');price=item.get('price')
  if not re.fullmatch(r'gid://shopify/ProductVariant/[1-9][0-9]*',gid) or type(qty) is not int or not 1<=qty<=4 or type(price) is not int or price<0:raise ValueError('Invalid exact merchant line.')
  ident=int(gid.rsplit('/',1)[1]);t=totals(row.get('totals'));base=price*qty;disc=-sum(t.get(k,0) for k in ('items_discount','discount'))
  if not {'subtotal','total'}<=t.keys() or set(t)-{'subtotal','total','items_discount','discount'} or t['subtotal']!=base or not 0<=disc<=base or t['total']!=base-disc:raise ValueError('Merchant line price or discount does not reconcile.')
  if ident in discounts:raise ValueError('Repeated merchant variant line needs separate review.')
  gross+=base;observed.append((ident,qty,price));discounts[ident]=disc;by_index[index]=disc
 if sorted(observed)!=sorted((v['variant_id'],v['quantity'],v['unit_minor']) for v in lines):raise ValueError('Merchant changed an item, quantity or price.')
 discount=sum(discounts.values());cost=totals(data.get('totals'))
 if cost.get('subtotal')!=gross or -sum(cost.get(k,0) for k in ('items_discount','discount'))!=discount:raise ValueError('Merchant basket discount differs from its exact lines.')
 if not isinstance(data.get('discounts',{}),dict):raise ValueError('Invalid merchant discount metadata.')
 applied=(data.get('discounts') or {}).get('applied',[]);codes=(data.get('discounts') or {}).get('codes',[])
 if codes or not isinstance(applied,list) or len(applied)>12:raise ValueError('Unsupported coupon or discount data.')
 allocations={k:0 for k in by_index};applied_total=0
 for row in applied:
  if not isinstance(row,dict):raise ValueError('Invalid automatic discount.')
  amount=row.get('amount');parts=row.get('allocations')
  if row.get('automatic') is not True or type(amount) is not int or amount<0 or not isinstance(parts,list) or len(parts)>12:raise ValueError('An automatic, allocated merchant discount is required.')
  part_total=0
  for part in parts:
   if not isinstance(part,dict):raise ValueError('Invalid discount allocation.')
   path=part.get('path','');value=part.get('amount');match=re.fullmatch(r'\$\.line_items\[(\d+)\]',path)
   if not match or int(match[1]) not in allocations or type(value) is not int or value<0:raise ValueError('Invalid merchant discount allocation.')
   allocations[int(match[1])]+=value;part_total+=value
  if part_total!=amount:raise ValueError('Merchant discount allocation changed.')
  applied_total+=amount
 if applied_total!=discount or allocations!=by_index:raise ValueError('Merchant discount metadata does not reconcile.')
 return {'discount_minor':discount,'line_discounts':{str(k):v for k,v in discounts.items()},'gross_minor':gross}
