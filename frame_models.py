"""Portable, versioned input dictionaries and editable reference layouts."""
from __future__ import annotations
import copy,json,math

SCHEMA='frame-load-analyzer/1'
PRESETS={
 'CSA G40.21 44W':{'name':'CSA G40.21 44W','E':29_000_000.,'nu':.30,'density':.2836,'Fy':44_000.,'Fu':64_000.},
 'ASTM A193 B7':{'name':'ASTM A193 B7','E':29_000_000.,'nu':.30,'density':.2836,'Fy':105_000.,'Fu':125_000.},
 'Custom steel':{'name':'Custom steel','E':29_000_000.,'nu':.30,'density':.2836,'Fy':36_000.,'Fu':58_000.},
}
SECTION_TYPES=['Angle','C-channel','HSS','Angle + angle','Angle + C-channel','Angle + HSS','Section + flat bar','Custom draw','Custom properties']

def component(shape='Angle',h=3.,w=3.,t=.375,**kw):
 return dict(shape=shape,h=h,w=w,t=t,dy=0.,dz=0.,start=0.,**kw)

def new_beam(index=1):
 return {'id':f'B{index}','name':f'Beam {index}','x':0.,'y':(index-1)*5.,'length':48.,
  'section_type':'Angle','auto_cut':True,'components':[component()],
  'manual':{'A':2.,'I':1.5,'ctop':2.,'cbottom':1.,'width':3.,'As':1.}}

def set_section_type(b,typ):
 """Initialize a new section choice. Existing choices are retained by UI archives."""
 b['section_type']=typ
 base=component(typ) if typ in ['Angle','C-channel','HSS'] else component()
 if typ=='HSS':base.update(h=4.,w=4.,t=.25)
 if typ.startswith('Angle +'):
  other={'Angle + angle':'Angle','Angle + C-channel':'C-channel','Angle + HSS':'HSS'}[typ]
  lower=component(other,h=4. if other=='HSS' else 3.,w=4. if other=='HSS' else 3.,t=.25 if other=='HSS' else .375)
  upper=component('Angle');upper['dy']=lower['h']
  b['components']=[lower,upper]
 elif typ=='Section + flat bar':
  b['components']=[base,component('Flat bar',h=.375,w=3.,t=.375)];b['components'][1]['dy']=3.
 elif typ=='Custom draw':
  b['components']=[component('Custom draw',drawing=[])]
 elif typ=='Custom properties':b['auto_cut']=False
 else:b['components']=[base]
 return b

def new_coil(index=1):return {'id':f'C{index}','name':f'Coil {index}','x':8.,'y':3.,'r':1.75,'share':1.,'lower':'Auto','upper':'Auto'}
def new_rod(index=1):return {'id':f'T{index}','name':f'Rod {index}','x':2.5,'diameter':.75,'tpi':10.,'weld':'B1','nut':'B2',
                           'free_length':5.,'auto_length':True,'weld_y':None,'nut_y':None}
def new_pin(index=1):return {'id':f'R{index}','name':f'Lift {index}','beam':'B1','x':1.5,'diameter':.75,'y':None}
def new_block(index=1):return {'id':f'P{index}','name':f'Block {index}','beam':'B2','x':16.,'y':3.,'length':2.,'height':1.,'depth':2.,'z':1.}
def next_id(items,prefix):
 existing={q['id'] for q in items};i=1
 while f'{prefix}{i}' in existing:i+=1
 return i

def base_model():
 return {'schema':SCHEMA,'title':'Shipping frame','units':'in-lbf-psi','beams':[], 'coils':[],'rods':[],'pins':[],'blocks':[],'loads':[],
  'materials':{'frame':copy.deepcopy(PRESETS['CSA G40.21 44W']),'rod':copy.deepcopy(PRESETS['ASTM A193 B7'])},
  'loading':{'coil_weight':0.,'frames':2,'equal_frames':True,'frame_share':.5,'self_weight':False,'factor':1.,'equal_reactions':False,
             'allowable_beam':0.,'allowable_rod':0.},
  'analysis':{'elements':72,'timoshenko':True,'curve_resolution':128,'regularization':1e-6}}

def default_model():
 """A new design has two members and no example coils, rods or lifting holes."""
 m=base_model();m['beams']=[new_beam(1),new_beam(2)]
 return m

def reset_tab(model,tab):
 """Reset the inputs owned by one tab; retain the other tabs' inputs."""
 defaults=default_model()
 if tab=='Design':
  for key in ['beams','coils','rods','pins','blocks']:model[key]=defaults[key]
 elif tab=='Loading':
  for key in ['loading','analysis','loads']:model[key]=defaults[key]
  for coil in model['coils']:coil['share']=1.
 elif tab=='Material':model['materials']=defaults['materials']
 else:raise ValueError('Unknown input tab: '+str(tab))
 return model

def two_layer_example(loaded=True):
 m=base_model();m['title']='Two-layer cut-seat frame'
 b=new_beam(1);t=new_beam(2);t.update(x=2.,y=4.,length=44.);t['components'][0].update(h=2.,flip_y=True)
 m['beams']=[b,t]
 for i,x in enumerate([8.,18.,30.,40.],1):
  c=new_coil(i);c.update(x=x);m['coils'].append(c)
 for i,x in enumerate([2.5,13.,24.,35.,45.5],1):
  r=new_rod(i);r['x']=x;m['rods'].append(r)
 for i,x in enumerate([1.5,46.5],1):
  p=new_pin(i);p['x']=x;m['pins'].append(p)
 m['loading'].update(coil_weight=2000. if loaded else 0.,self_weight=loaded)
 return m

def four_layer_example():
 m=base_model();m['title']='Four-layer cut-seat example (illustrative dimensions)'
 bottom=new_beam(1);bottom['length']=52.34375
 hss=new_beam(2);hss.update(x=3.,length=46.34375,y=5.);set_section_type(hss,'HSS')
 mid=new_beam(3);mid.update(x=3.,length=46.34375,y=9.);mid['components'][0]['h']=3.5625
 top=new_beam(4);top.update(x=3.,length=41.,y=14.);top['components'][0].update(h=2.,flip_y=True)
 m['beams']=[bottom,hss,mid,top]
 for x in [12.71875,23.46875,34.21875,44.96875]:
  c=new_coil(len(m['coils'])+1);c.update(x=x,y=3.,r=2.);m['coils'].append(c)
 for x in [7.375,18.125,28.875,39.625]:
  c=new_coil(len(m['coils'])+1);c.update(x=x,y=12.5625,r=2.);m['coils'].append(c)
 for x in [9.515625,28.84375,48.1875]:
  r=new_rod(len(m['rods'])+1);r.update(x=x,weld='B1',nut='B3');m['rods'].append(r)
 for x in [4.140625,23.46875,42.828125]:
  r=new_rod(len(m['rods'])+1);r.update(x=x,weld='B3',nut='B4');m['rods'].append(r)
 for i,x in enumerate([1.75,50.59375],1):
  p=new_pin(i);p['x']=x;m['pins'].append(p)
 m['loading'].update(coil_weight=3964.8,self_weight=True)
 return m

def block_example():
 m=base_model();m['title']='Two-layer frame with rectangular blocks'
 b=new_beam(1);t=new_beam(2);t.update(x=2.,length=44.,y=5.);set_section_type(t,'HSS');t['components'][0].update(h=2.,w=2.,t=.25)
 b['components'][0]['h']=2.
 m['beams']=[b,t]
 for x,r,y in [(8.,2.,3.),(16.,1.,2.),(22.,2.,3.),(32.,1.,2.),(40.,2.,3.)]:
  c=new_coil(len(m['coils'])+1);c.update(x=x,r=r,y=y);m['coils'].append(c)
 for i,x in enumerate([16.,32.],1):
  q=new_block(i);q.update(x=x,y=3.,height=2.);m['blocks'].append(q)
 for i,x in enumerate([3.,12.,27.,36.,45.],1):
  r=new_rod(i);r['x']=x;m['rods'].append(r)
 for i,x in enumerate([1.5,46.5],1):
  p=new_pin(i);p['x']=x;m['pins'].append(p)
 m['loading'].update(coil_weight=2000.,self_weight=True)
 return m

def welded_example():
 m=two_layer_example();m['title']='Partial-length angle welded to HSS'
 b=m['beams'][0];b.update(length=54.,x=0.,y=0.);set_section_type(b,'Angle + HSS')
 b['components'][0].update(length=54.,h=3.,w=3.,t=.25)
 b['components'][1].update(start=5.,length=44.,dy=3.,h=3.)
 m['beams'][1].update(x=5.,y=7.,length=44.)
 for c in m['coils']:c['x']+=3.;c['y']+=3.
 for r in m['rods']:r['x']+=3.
 m['pins'][1]['x']=52.5
 return m

def model_json(model):return json.dumps(model,indent=2,allow_nan=False)
def load_model(text):
 from frame_geometry import ModelError
 try:m=json.loads(text)
 except (ValueError,TypeError) as e:raise ModelError('This is not a valid JSON model file.') from e
 if not isinstance(m,dict) or m.get('schema')!=SCHEMA:raise ModelError('Expected a Frame Load Analyzer model with schema '+SCHEMA)
 if m.get('units')!='in-lbf-psi':raise ModelError('This model must use inches, lbf and psi.')
 for name in ['beams','coils','rods','pins','blocks','loads']:
  if not isinstance(m.get(name),list):raise ModelError('Missing/invalid '+name+' list.')
  if any(not isinstance(q,dict) or not isinstance(q.get('id'),str) for q in m[name]):raise ModelError('Every '+name+' object needs a text ID.')
  if len({q['id'] for q in m[name]})!=len(m[name]):raise ModelError('IDs must be unique within '+name+'.')
 if not 2<=len(m['beams'])<=5:raise ModelError('A frame must have 2–5 beam layers.')
 # Reject unreasonable payloads before performing any geometry/FE work.
 if any(len(m[k])>300 for k in ['coils','rods','blocks','loads']) or len(m['pins'])>20:raise ModelError('Too many objects in this model.')
 def finite(obj):
  if isinstance(obj,dict):return all(finite(x) for x in obj.values())
  if isinstance(obj,list):return all(finite(x) for x in obj)
  if isinstance(obj,(int,float)):return math.isfinite(obj)
  return isinstance(obj,(str,bool,type(None)))
 if not finite(m):raise ModelError('All numeric inputs must be finite.')
 for b in m['beams']:
  for c in b.get('components',[]):
   if len(c.get('drawing',[]))>300:raise ModelError('A custom section is limited to 300 shapes.')
 return m
