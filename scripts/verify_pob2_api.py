#!/usr/bin/env python3
"""Exercise mutations on an explicitly named disposable PoB2 build, then restore.

Requires a test build with Spark and a life/resistance Ring 1. This acceptance
fixture is supplied locally, never bundled. No user/account paths are embedded.
The report includes build data: keep it private. The app and caller must use a
separate PoB2 test runtime; this script does not start, close or save the app.
"""
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port',type=int,required=True)
parser.add_argument('--owned-build-name',required=True)
parser.add_argument('--report-dir',type=str,required=True)
args=parser.parse_args()
import json,socket,math,time,base64,struct,xml.etree.ElementTree as E
from pathlib import Path
out=Path(args.report_dir).resolve();out.mkdir(parents=True,exist_ok=True)
with socket.create_connection(('127.0.0.1',args.port),timeout=5) as s:
 s.settimeout(30);f=s.makefile('rb');json.loads(f.readline())
 def call(action,params=None,allow_error=False):
  s.sendall((json.dumps({'action':action,'params':params or {}})+'\n').encode());raw=f.readline()
  if not raw:raise RuntimeError('Disconnected during '+action)
  r=json.loads(raw)
  if not r.get('ok') and not allow_error:raise RuntimeError(action+': '+str(r.get('error')))
  return r
 assert call('get_build_info')['info']['name']==args.owned_build_name
 original=call('export_build_xml')['xml'];(out/'before.xml').write_text(original);stats=call('get_stats')['stats'];records=[]
 def canon(xml):
  def visit(e):
   attrs=dict(e.attrib)
   for k in ('nodes','strNodes','dexNodes','intNodes'):
    if k in attrs:attrs[k]=','.join(sorted(attrs[k].split(',')))
   text=(e.text or '').strip()
   if e.tag=='URL' and '/passive-skill-tree/' in text:
    encoded=text.rsplit('/',1)[1];raw=base64.urlsafe_b64decode(encoded);assert raw[:4]==b'\x00\x00\x00\x06'
    pos=6;groups=[]
    for width in (2,2,4):
     count=raw[pos];pos+=1;groups.append(tuple(sorted(raw[pos+i*width:pos+(i+1)*width] for i in range(count))));pos+=count*width
    assert pos==len(raw)
    text=(text.rsplit('/',1)[0],raw[:6],tuple(groups))
   children=[visit(c) for c in e]
   if e.tag=='ConfigSet':children.sort(key=repr)
   return e.tag,tuple(sorted(attrs.items())),text,tuple(children)
  return {e.tag:visit(e) for e in E.fromstring(xml) if e.tag in ['Build','Items','Skills','Tree','Config','Notes','Party']}
 def restore():
  call('open_build_xml',{'xml':original,'name':args.owned_build_name})
  for _ in range(30):
   info=call('get_build_info',allow_error=True)
   if info.get('ok') and info.get('info',{}).get('name')==args.owned_build_name:break
   time.sleep(.05)
  restored=call('get_stats')['stats']
  for k,v in stats.items():
   if isinstance(v,(int,float)) and not isinstance(v,bool): assert math.isclose(v,restored[k],rel_tol=1e-9,abs_tol=1e-7),(k,v,restored[k])
  restored_xml=call('export_build_xml')['xml'];(out/'after.xml').write_text(restored_xml)
  assert canon(original)==canon(restored_xml),'Full XML differs after restore'
 def gem():
  groups=call('get_skills')['skills']['groups'];g=next(g for g in groups if any(x['name']=='Spark' for x in g['gems']));gi=next(x['index'] for x in g['gems'] if x['name']=='Spark')
  call('set_main_selection',{'mainSocketGroup':g['index'],'mainActiveSkill':1});before=call('get_stats')['stats']['TotalDPS']
  call('set_gem_level',{'groupIndex':g['index'],'gemIndex':gi,'level':19});after=call('get_stats')['stats']['TotalDPS'];assert before>after>0,(before,after)
  return {'spark_level20_dps':before,'spark_level19_dps':after}
 def config():
  call('set_config',{'enemyLevel':83});cfg=call('get_config')['config'];assert cfg['enemyLevel']==83
  assert 'name="enemyLevel"' in call('export_build_xml')['xml'];return {'enemyLevel':cfg['enemyLevel'],'effective':cfg['effectiveEnemyLevel']}
 def unequip():
  call('clear_item_slot',{'slotName':'Ring 1'});after=call('get_stats')['stats'];assert after['Life']!=stats['Life'] or after['FireResist']!=stats['FireResist'];return {k:after[k] for k in ['Life','FireResist','TotalDPS']}
 def equip():
  root=E.fromstring(original);iset=root.find('./Items/ItemSet');slot=next(x for x in iset.findall('Slot') if x.get('name')=='Ring 1');raw=next(x.text for x in root.findall('./Items/Item') if x.get('id')==slot.get('itemId'))
  r=call('add_item_text',{'text':raw,'slotName':'Ring 1'});return r
 def charm():
  call('set_flask_active',{'slotName':'Charm 1','active':True});x=E.fromstring(call('export_build_xml')['xml']);slot=next(e for e in x.findall('./Items/ItemSet/Slot') if e.get('name')=='Charm 1');assert slot.get('active')=='true';return {'active':True}
 def invalid():
  before=call('export_build_xml')['xml'];r=call('set_config',{'enemyLevel':83,'noSuchOption':5},True);assert not r['ok'];assert canon(before)==canon(call('export_build_xml')['xml']);return r
 def large():
  text='NATIVE TRANSPORT TEST\n'+'x'*600000;call('set_notes',{'text':text});assert call('get_notes')['notes']==text
  xml=call('export_build_xml')['xml'];assert E.fromstring(xml).find('Notes').text.strip()==text;return {'export_bytes':len(xml.encode())}
 for name,fn in [('gem',gem),('config',config),('unequip',unequip),('equip',equip),('charm',charm),('invalid_batch',invalid),('large_response',large)]:
  rec={'case':name}
  try:rec['result']=fn();rec['passed']=True
  except Exception as e:rec.update(passed=False,error=str(e))
  finally:
   try:restore();rec['rollback']=True
   except Exception as e:rec.update(rollback=False,rollback_error=str(e));records.append(rec);print(json.dumps(rec),flush=True);raise
  records.append(rec);print(json.dumps(rec),flush=True)
 (out/'results.json').write_text(json.dumps(records,indent=2))
 assert all(r['passed'] and r['rollback'] for r in records)
