"""Bounded source/declaration checks for monitor external-power chains.
No electrical safety, dynamic multiport allocation or physical installation claim.
"""
def check(workspace,facts):
 routes=[];questions=[];used_power=set();used_cables=set()
 for screen in [i for i in workspace.items if i.kind=='monitor' and facts[i.id].get('pd_input_watts')]:
  sf=facts[screen.id];need=sf['pd_input_watts']
  power=next((i for i in workspace.items if i.kind=='power' and i.id not in used_power and facts[i.id].get('usb_c') is True and facts[i.id].get('power_watts',0)>=need),None)
  cable=next((i for i in workspace.items if i.kind=='cable' and i.id not in used_cables and facts[i.id].get('link_type')=='usb_c_power' and facts[i.id].get('pd_watts',0)>=need),None)
  if not power or not cable:
   questions.append(screen.name+': external power needs a reviewed charger and a separate adequate USB-C power cable.');continue
  used_power.add(power.id);used_cables.add(cable.id)
  routes.append({'source':power.id,'target':screen.id,'cable_id':cable.id,'status':'qualified','kind':'power','basis':'Recorded single-device charger output and dedicated power cable meet monitor input; use the selected charger port only.','power_watts':need,'host_passthrough_watts':sf.get('pd_passthrough_watts')})
 return {'routes':routes,'questions':questions}
