"""Frame Load Analyzer — standalone Streamlit UI and future-host render_app()."""
from __future__ import annotations
from pathlib import Path
import copy,hashlib,json,math,traceback,inspect
import numpy as np
import pandas as pd
from frame_models import (PRESETS,SECTION_TYPES,base_model,new_beam,set_section_type,new_coil,new_rod,new_pin,new_block,
    next_id,two_layer_example,four_layer_example,block_example,welded_example,model_json,load_model,default_model,reset_tab)
from frame_geometry import Geometry,ModelError,component_profile,section_properties,polygons
from frame_engine import solve_frame,rod_geometry,thread_area,mesh_check
from frame_visuals import frame_svg,section_svg,make_chart,chart_csv,force_csv,num,beam_color
from frame_calculations import render_calculations

ROOT=Path(__file__).resolve().parent
_EDITOR=None
RESULT_TABS=['Bending moment','Shear force','Deflection','Stress','Forces','Calculations']

def result_tabs():
 import streamlit as st
 # Stateful tabs expose .open in recent Streamlit versions, so expensive
 # graphs/worksheets are built only when they are actually being viewed.
 if 'on_change' in inspect.signature(st.tabs).parameters:
  return st.tabs(RESULT_TABS,key='sf_result_tab',on_change='rerun')
 return st.tabs(RESULT_TABS)

def tab_is_open(tab):
 state=getattr(tab,'open',None)
 return state if isinstance(state,bool) else True

def initialize_state():
 import streamlit as st
 if 'sf_model' not in st.session_state:st.session_state.sf_model=default_model()
 if 'sf_epoch' not in st.session_state:st.session_state.sf_epoch=0
 if 'sf_editor_open' not in st.session_state:st.session_state.sf_editor_open=False

def activate_beam(bid):
 import streamlit as st
 st.session_state.sf_active_beam=bid

def beam_expanded(bid):
 import streamlit as st
 if st.session_state.get('sf_beam_panel_'+bid):activate_beam(bid)

def open_editor(bid):
 import streamlit as st
 activate_beam(bid);st.session_state.sf_editor_beam=bid;st.session_state.sf_editor_open=True

def close_editor():
 import streamlit as st
 st.session_state.sf_editor_open=False

def reset_inputs(tab):
 import streamlit as st
 reset_tab(st.session_state.sf_model,tab)
 groups={
  'Design':('sf_beam_','sf_coil_','sf_rod_','sf_pin_','sf_block_','sf_inspect_','sf_editor'),
  'Loading':('sf_load_','sf_share_','sf_allow_','sf_extra_'),
  'Material':('sf_mat_',)}
 exact={'Design':{'sf_layer_count','sf_active_beam','sf_selected_beam'},
        'Loading':{'sf_mesh','sf_shear','sf_curve_resolution'},'Material':set()}
 for k in list(st.session_state):
  if k.startswith(groups[tab]) or k in exact[tab] or k in {'sf_solution','sf_solution_digest','sf_mesh_result'}:del st.session_state[k]
 if tab=='Design':
  st.session_state.sf_epoch=st.session_state.get('sf_epoch',0)+1
  st.session_state.sf_editor_open=False

def beam_callback(key):
 if key.startswith('sf_beam_B'):
  return {'on_change':activate_beam,'args':(key.split('_')[2],)}
 return {}

def replace_model(m):
 import streamlit as st
 epoch=st.session_state.get('sf_epoch',0)+1
 for k in list(st.session_state):
  if k.startswith('sf_'):del st.session_state[k]
 st.session_state.sf_model=copy.deepcopy(m);st.session_state.sf_epoch=epoch
 st.session_state.sf_editor_open=False

def import_uploaded():
 import streamlit as st
 try:
  f=st.session_state.get('sf_model_upload')
  if f is None:raise ModelError('Choose a saved model JSON first.')
  if len(f.getvalue())>3_000_000:raise ModelError('Model JSON is too large (limit 3 MB).')
  m=load_model(f.getvalue().decode('utf-8'));replace_model(m)
 except (ModelError,ValueError,KeyError,UnicodeError) as e:st.session_state.sf_import_error=str(e)

def add_beam_layer():
 import streamlit as st
 m=st.session_state.sf_model;b=new_beam(next_id(m['beams'],'B'))
 b['y']=max((q['y'] for q in m['beams']),default=-5.)+5.
 m['beams'].append(b);activate_beam(b['id'])
 st.session_state['sf_beam_panel_'+b['id']]=True

def remove_beam_layer(bid):
 import streamlit as st
 m=st.session_state.sf_model
 if len(m['beams'])<=1:return
 index=next((i for i,b in enumerate(m['beams']) if b['id']==bid),None)
 if index is None:return
 m['beams'].pop(index)
 prefixes=['sf_beam_'+bid+'_','sf_inspect_'+bid+'_']
 # Remove attachments and their widget values so a subsequently reused ID
 # starts with fresh inputs rather than inheriting the deleted object's data.
 for kind,prefix in [('rods','sf_rod_'),('pins','sf_pin_'),('blocks','sf_block_'),('loads','sf_extra_')]:
  attached=lambda q:(q['weld']==bid or q['nut']==bid) if kind=='rods' else q['beam']==bid
  removed=[q for q in m[kind] if attached(q)]
  m[kind]=[q for q in m[kind] if not attached(q)]
  prefixes.extend(prefix+q['id']+'_' for q in removed)
 for c in m['coils']:
  for side in ['lower','upper']:
   if c.get(side)==bid:
    c[side]='Auto';st.session_state.pop('sf_coil_'+c['id']+'_'+side,None)
 for key in list(st.session_state):
  if key.startswith(tuple(prefixes)) or key in {'sf_beam_panel_'+bid,'sf_editor_draft_'+bid}:del st.session_state[key]
 if st.session_state.get('sf_active_beam')==bid:activate_beam(m['beams'][min(index,len(m['beams'])-1)]['id'])
 if st.session_state.get('sf_editor_beam')==bid:
  close_editor();st.session_state.pop('sf_editor_beam',None)

def ninput(label,value,key,step=.5,minimum=None,maximum=None,format=None,help=None):
 import streamlit as st
 # Dependent limits (for example the section-inspection station after changing
 # beam length) must also apply to an existing widget's retained value.
 retained=st.session_state.get(key)
 if retained is not None and ((minimum is not None and retained<minimum) or (maximum is not None and retained>maximum)):
  del st.session_state[key]
 if minimum is not None:value=max(value,minimum)
 if maximum is not None:value=min(value,maximum)
 kw={'label':label,'value':float(value),'step':float(step),'key':key,**beam_callback(key)}
 if minimum is not None:kw['min_value']=float(minimum)
 if maximum is not None:kw['max_value']=float(maximum)
 if format:kw['format']=format
 elif '(in)' in label:kw['format']='%.6f'
 if help:kw['help']=help
 return float(st.number_input(**kw))

def choose(label,choices,current,key,**kw):
 import streamlit as st
 if key in st.session_state and st.session_state[key] not in choices:del st.session_state[key]
 return st.selectbox(label,choices,index=choices.index(current) if current in choices else 0,key=key,**beam_callback(key),**kw)

def delete_object(kind,ident):
 import streamlit as st
 m=st.session_state.sf_model;m[kind]=[q for q in m[kind] if q['id']!=ident]

def rod_size_mode(ident):
 import streamlit as st
 for suffix in ['_radius','_d']:st.session_state.pop('sf_rod_'+ident+suffix,None)

def add_object(kind,bid=None):
 import streamlit as st
 m=st.session_state.sf_model
 prefix={'coils':'C','rods':'T','pins':'R','blocks':'P','loads':'F'}[kind];i=next_id(m[kind],prefix)
 if kind=='coils':q=new_coil(i)
 elif kind=='rods':
  if len(m['beams'])<2:return
  q=new_rod(i);q['weld']=m['beams'][0]['id'];q['nut']=m['beams'][-1]['id']
 elif kind=='pins':
  q=new_pin(i);q['beam']=bid or m['beams'][0]['id'];b=next(b for b in m['beams'] if b['id']==q['beam']);q['x']=b['x']+b['length']/2
 elif kind=='blocks':
  q=new_block(i);q['beam']=bid or m['beams'][-1]['id'];b=next(b for b in m['beams'] if b['id']==q['beam']);q['x']=b['x']+b['length']/2
  try:
   g=Geometry(m);z0,y0,z1,y1=g.bounds(b['id']);q['y']=y0-q['height'];q['z']=(z0+z1)/2;q['depth']=max(z1-z0,.1)
  except (ModelError,ValueError):q['y']=b['y']-1
 else:q={'id':f'F{i}','name':f'Load {i}','beam':bid or m['beams'][0]['id'],'kind':'Point','x':12.,'end':20.,'value':-100.}
 m[kind].append(q)

def beam_editor(m,b):
 import streamlit as st
 bid=b['id'];prefix='sf_beam_'+bid
 b['name']=st.text_input('Beam name',b['name'],key=prefix+'_name',on_change=activate_beam,args=(bid,))
 st.button('Inspect this beam',key=prefix+'_inspect',on_click=activate_beam,args=(bid,),width='stretch')
 st.button('Remove layer',key=prefix+'_remove',on_click=remove_beam_layer,args=(bid,),disabled=len(m['beams'])<=1,
  help='Removes this layer and its attached rods, lifting points, blocks and additional loads.',width='stretch')
 cols=st.columns(2)
 with cols[0]:b['x']=ninput('Start x (in)',b['x'],prefix+'_x')
 with cols[1]:b['length']=ninput('Length (in)',b['length'],prefix+'_length',minimum=.01)
 b['y']=ninput('Vertical datum y (in)',b['y'],prefix+'_y',help='The section lower-left datum before component offsets. Positive y is upward.')
 typ=choose('Cross section',SECTION_TYPES,b['section_type'],prefix+'_type')
 if typ!=b['section_type']:
  b.setdefault('_section_archive',{})[b['section_type']]=copy.deepcopy(b['components'])
  if typ in b['_section_archive']:b['components']=copy.deepcopy(b['_section_archive'][typ]);b['section_type']=typ
  else:set_section_type(b,typ)
  if st.session_state.get('sf_editor_beam')==bid:close_editor()
 if typ=='Custom properties':
  st.caption('Manual uniform properties have no outline for automatic cuts or block attachments. Use Custom draw when a coil intersects this member.')
  p=b['manual']
  for key,label,default in [('A','Area A (in²)',2.),('I','Bending Ixx (in⁴)',1.5),('ctop','Neutral axis to top (in)',2.),('cbottom','Neutral axis to bottom (in)',1.),('As','Effective shear area (in²)',1.),('width','Display width (in)',3.)]:
   p[key]=ninput(label,p.get(key,default),prefix+'_manual_'+key,step=.5 if key in ['ctop','cbottom','width'] else .01,minimum=.000001,format='%.6f')
  b['auto_cut']=False
 else:
  b['auto_cut']=st.checkbox('Coils create cutouts',value=b.get('auto_cut',True),key=prefix+'_cuts',on_change=activate_beam,args=(bid,),help='All intersecting coil cylinders remove material from these components. Leave enabled for the shipping frames we discussed.')
  if typ=='Custom draw':
   st.caption('Use the section sketcher in the main panel. Your drawing defines actual material and holes.')
   st.button('Open section sketcher',key=prefix+'_open_sketcher',on_click=open_editor,args=(bid,),width='stretch')
  else:
   if typ=='Section + flat bar':
    c=b['components'][0];c['shape']=choose('Main shape',['Angle','C-channel','HSS'],c['shape'],prefix+'_base_shape')
   for i,c in enumerate(b['components']):
    with st.expander(f'Component {i+1} · {c["shape"]}',expanded=(len(b['components'])==1)):
     cp=prefix+'_'+typ+'_'+str(i)
     col1,col2=st.columns(2)
     with col1:c['h']=ninput('Height (in)' if c['shape']!='Flat bar' else 'Bar thickness / height (in)',c['h'],cp+'_h',minimum=.001)
     with col2:c['w']=ninput('Width (in)',c['w'],cp+'_w',minimum=.001)
     if c['shape']!='Flat bar':c['t']=ninput('Wall / leg thickness (in)',c['t'],cp+'_t',minimum=.001)
     c['flip_y']=st.checkbox('Flip vertically',value=c.get('flip_y',False),key=cp+'_fy',on_change=activate_beam,args=(bid,))
     c['flip_z']=st.checkbox('Mirror horizontally',value=c.get('flip_z',False),key=cp+'_fz',on_change=activate_beam,args=(bid,))
     c['rotation']=choose('Section rotation',[0,90,180,270],c.get('rotation',0),cp+'_rot')
     if i:
      if typ=='Section + flat bar':
       placement=choose('Bar placement',['Above main shape','Below main shape','Custom offset'],b.get('bar_placement','Above main shape'),cp+'_barplace');b['bar_placement']=placement
       if placement!='Custom offset':
        try:
         pp=component_profile(b['components'][0]);c['dy']=pp.bounds[3] if placement=='Above main shape' else pp.bounds[1]-c['h']
        except ModelError:pass
        st.caption(f'Automatic vertical offset: {num(c["dy"])} in')
       else:c['dy']=ninput('Vertical offset (in)',c.get('dy',0),cp+'_dy')
      else:c['dy']=ninput('Vertical offset (in)',c.get('dy',0),cp+'_dy')
      c['dz']=ninput('Side offset in section (in)',c.get('dz',0),cp+'_dz')
     full=st.checkbox('Full beam length',value=('length' not in c and c.get('start',0)==0),key=cp+'_full',on_change=activate_beam,args=(bid,))
     if full:c.pop('length',None);c['start']=0.
     else:
      c['start']=ninput('Start from beam left end (in)',c.get('start',0),cp+'_start',minimum=0.)
      c['length']=ninput('Component length (in)',c.get('length',b['length']),cp+'_clength',minimum=.001)
   st.caption('Idealized uniform thickness and sharp corners. Welded components share curvature; their actual lengths and offsets are retained.')
 # Lifting points and pads belong to the selected member's Design section.
 st.markdown('**Lifting points on this beam**')
 st.button('＋ Add lifting point',key=prefix+'_addpin',on_click=add_object,args=('pins',bid),width='stretch')
 for p in [q for q in m['pins'] if q['beam']==bid]:
  with st.expander(p['id']+' · lifting point'):
   pp='sf_pin_'+p['id'];p['x']=ninput('Position x (in)',p['x'],pp+'_x')
   p['diameter']=ninput('Hole diameter for schematic (in)',p.get('diameter',.75),pp+'_d',minimum=.001)
   manual=st.checkbox('Set display elevation',value=p.get('y') is not None,key=pp+'_manualy')
   p['y']=ninput('Hole centre y (in)',p.get('y') if p.get('y') is not None else b['y']+1,pp+'_y') if manual else None
   st.button('Remove lifting point',key=pp+'_del',on_click=delete_object,args=('pins',p['id']))
 st.markdown('**Welded rectangular blocks**')
 st.button('＋ Add rectangular block',key=prefix+'_addblock',on_click=add_object,args=('blocks',bid),width='stretch')
 for q in [q for q in m['blocks'] if q['beam']==bid]:
  with st.expander(q['id']+' · rectangular block'):
   qp='sf_block_'+q['id'];q['name']=st.text_input('Block name',q['name'],key=qp+'_name')
   for k,label in [('x','Centre x (in)'),('y','Bottom y (in)'),('length','Length along beam (in)'),('height','Vertical height (in)'),('depth','Depth / thickness (in)'),('z','Depth centre z (in)')]:
    q[k]=ninput(label,q.get(k,0),qp+'_'+k,minimum=.001 if k in ['length','height','depth'] else None)
   st.caption('Welded contact pad. Set its face against the coil and its other face against the parent section. It remains rectangular.')
   st.button('Remove block',key=qp+'_del',on_click=delete_object,args=('blocks',q['id']))


def design_panel(m):
 import streamlit as st
 st.button('Reset Design',key='sf_reset_design',on_click=reset_inputs,args=('Design',),width='stretch')
 st.button('＋ Add beam layer',key='sf_add_beam',on_click=add_beam_layer,width='stretch')
 st.caption('A fully welded combination counts as one layer.')
 ids=[b['id'] for b in m['beams']];names={b['id']:b['name'] for b in m['beams']}
 for i,b in enumerate(m['beams']):
  kw={'expanded':b['id']==st.session_state.get('sf_active_beam',ids[0])}
  if 'on_change' in inspect.signature(st.expander).parameters:
   kw.update(key='sf_beam_panel_'+b['id'],on_change=beam_expanded,args=(b['id'],))
  with st.expander(b['id']+' · '+b['name'],**kw):beam_editor(m,b)
 st.divider();st.markdown('**Coils and automatic cutouts**')
 st.button('＋ Add coil',key='sf_add_coil',on_click=add_object,args=('coils',),width='stretch')
 for c in m['coils']:
  with st.expander(c['id']+' · '+c['name']):
   cp='sf_coil_'+c['id'];c['name']=st.text_input('Coil name',c['name'],key=cp+'_name')
   col1,col2=st.columns(2)
   with col1:c['x']=ninput('Centre x (in)',c['x'],cp+'_x')
   with col2:c['y']=ninput('Centre y (in)',c['y'],cp+'_y')
   c['r']=ninput('Outside radius (in)',c['r'],cp+'_r',minimum=.001)
   with st.expander('Bearing beam selection'):
    c['lower']=choose('Lower bearing beam',['Auto','None']+ids,c.get('lower','Auto'),cp+'_lower')
    c['upper']=choose('Upper bearing beam',['Auto','None']+ids,c.get('upper','Auto'),cp+'_upper')
   st.button('Remove coil',key=cp+'_del',on_click=delete_object,args=('coils',c['id']))
 st.divider();st.markdown('**Threaded rods**')
 st.button('＋ Add rod',key='sf_add_rod',on_click=add_object,args=('rods',),disabled=len(ids)<2,width='stretch')
 if len(ids)<2:st.caption('Add another beam layer to connect a threaded rod.')
 for r in m['rods']:
  with st.expander(r['id']+' · '+r['name']):
   rp='sf_rod_'+r['id'];r['name']=st.text_input('Rod name',r['name'],key=rp+'_name')
   r['x']=ninput('Rod centre x (in)',r['x'],rp+'_x')
   radius=st.checkbox('Enter rod radius',value=False,key=rp+'_radius_mode',on_change=rod_size_mode,args=(r['id'],))
   dd=ninput('Radius (in)' if radius else 'Diameter (in)',r['diameter']/2 if radius else r['diameter'],rp+('_radius' if radius else '_d'),minimum=.001)
   r['diameter']=dd*2 if radius else dd
   r['tpi']=ninput('Threads per inch',r['tpi'],rp+'_tpi',step=1,minimum=.1)
   r['weld']=choose('Welded to beam',ids,r['weld'],rp+'_weld',format_func=lambda k:k+' · '+names[k])
   nuts=[x for x in ids if x!=r['weld']]
   r['nut']=choose('Nut on TOP of beam',nuts,r['nut'],rp+'_nut',format_func=lambda k:k+' · '+names[k])
   auto_heights=st.checkbox('Estimate attachment seat heights',value=r.get('weld_y') is None and r.get('nut_y') is None,key=rp+'_heights')
   if auto_heights:r['weld_y']=None;r['nut_y']=None
   else:
    r['weld_y']=ninput('Weld attachment y (in)',r.get('weld_y') if r.get('weld_y') is not None else 0.,rp+'_wy')
    r['nut_y']=ninput('Nut bearing face y (in)',r.get('nut_y') if r.get('nut_y') is not None else 5.,rp+'_ny')
   r['auto_length']=st.checkbox('Estimate effective free length',value=r.get('auto_length',True),key=rp+'_autoL')
   if not r['auto_length']:r['free_length']=ninput('Effective free length (in)',r['free_length'],rp+'_L',minimum=.001)
   try:
    ya,yn,L=rod_geometry(r,Geometry(m));At=thread_area(r['diameter'],r['tpi'])
    st.caption(f'Used free length: {num(L)} in · Tensile area: {num(At,5)} in². Override estimated lengths for your actual welded joint.')
   except (ModelError,ValueError,KeyError):pass
   st.caption('Hand-tight nut, zero preload. Passing through an intermediate beam does not fix the rod to it.')
   st.button('Remove rod',key=rp+'_del',on_click=delete_object,args=('rods',r['id']))
 return st.session_state.get('sf_active_beam',ids[0])


def loading_panel(m):
 import streamlit as st
 st.button('Reset Loading',key='sf_reset_loading',on_click=reset_inputs,args=('Loading',),width='stretch')
 q=m['loading'];q['coil_weight']=ninput('Total coil-package weight (lbf)',q['coil_weight'],'sf_load_W',step=100.,minimum=0.,format='%.3f')
 q['frames']=int(st.number_input('Number of shipping frames',min_value=1,max_value=100,value=int(q['frames']),step=1,key='sf_load_nframes'))
 q['equal_frames']=st.checkbox('Share package weight equally between frames',value=q['equal_frames'],key='sf_load_equalframes')
 if not q['equal_frames']:q['frame_share']=ninput('Share carried by this frame (0–1)',q['frame_share'],'sf_load_share',step=.05,minimum=0.,maximum=1.,format='%.4f')
 share=1/q['frames'] if q['equal_frames'] else q['frame_share']
 st.caption(f'Assigned coil weight: {num(q["coil_weight"]*share,3)} lbf per analyzed frame, before load multiplier.')
 with st.expander('Individual coil weight shares'):
  st.caption('Equal shares = 1 for every coil. Enter relative weights when they differ; shares are normalized to the assigned total.')
  for c in m['coils']:c['share']=ninput(c['id']+' · relative weight share',c.get('share',1),'sf_share_'+c['id'],step=.25,minimum=0.)
 q['self_weight']=st.checkbox('Include beam, block and rod self-weight',value=q['self_weight'],key='sf_load_selfweight')
 q['factor']=ninput('Lifting / load multiplier',q['factor'],'sf_load_factor',step=.1,minimum=.001,format='%.3f',help='1.0 means static gravity loading. Enter an appropriate project load multiplier; the app does not derive one from a lifting code.')
 st.markdown('**Lifting reactions**')
 q['equal_reactions']=st.checkbox('Assume equal reactions at all lifting holes',value=q['equal_reactions'],key='sf_load_equalholes')
 st.caption('Applies to holes on this frame. Equal reactions are accepted only when the entered loads and lifting positions also balance in moment.')
 with st.expander('Optional nominal-stress comparison'):
  q['allowable_beam']=ninput('Beam allowable bending stress (psi; 0 = none)',q.get('allowable_beam',0),'sf_allow_beam',step=1000.,minimum=0.,format='%.1f')
  q['allowable_rod']=ninput('Rod allowable tensile stress (psi; 0 = none)',q.get('allowable_rod',0),'sf_allow_rod',step=1000.,minimum=0.,format='%.1f')
 with st.expander('Additional beam loads'):
  st.button('＋ Add beam load',key='sf_add_load',on_click=add_object,args=('loads',))
  ids=[b['id'] for b in m['beams']]
  for z in m.get('loads',[]):
   with st.expander(z['id']+' · '+z['name']):
    k='sf_extra_'+z['id'];z['name']=st.text_input('Load name',z['name'],key=k+'_name')
    choices=ids if z['beam'] in ids else ids+[z['beam']]
    z['beam']=choose('Apply to beam',choices,z['beam'],k+'_beam',format_func=lambda q:q if q in ids else q+' (removed beam — reassign)')
    z['kind']=choose('Load type',['Point','Uniform'],z['kind'],k+'_kind')
    z['x']=ninput('Position / start x (in)',z['x'],k+'_x')
    if z['kind']=='Uniform':z['end']=ninput('End x (in)',z['end'],k+'_end')
    direction=choose('Direction',['Downward','Upward'],'Upward' if z['value']>0 else 'Downward',k+'_dir')
    amount=ninput('Total force (lbf)',abs(z['value']),k+'_mag',step=10.,minimum=0.)
    z['value']=amount*(1 if direction=='Upward' else -1)
    st.button('Remove load',key=k+'_del',on_click=delete_object,args=('loads',z['id']))
 with st.expander('Analysis settings'):
  a=m['analysis'];a['elements']=int(st.number_input('Mesh divisions per longest beam',min_value=8,max_value=400,value=int(a['elements']),step=8,key='sf_mesh'))
  a['timoshenko']=st.checkbox('Include shear deformation',value=a['timoshenko'],key='sf_shear')
  a['curve_resolution']=int(choose('Segments per full circle',[64,128,256,512],a.get('curve_resolution',128),'sf_curve_resolution'))
  st.caption('Geometry transitions, coil centres, rods and lifting points are inserted as extra mesh stations. Use Check mesh in Calculations to assess refinement.')


def material_panel(m):
 import streamlit as st
 st.button('Reset Material',key='sf_reset_material',on_click=reset_inputs,args=('Material',),width='stretch')
 for kind,label,default in [('frame','Frame beams and rectangular blocks','CSA G40.21 44W'),('rod','Threaded rods','ASTM A193 B7')]:
  st.markdown('**'+label+'**');a=m['materials'][kind]
  preset=choose('Material preset',list(PRESETS),a.get('name',default),'sf_mat_'+kind+'_preset')
  lastkey='sf_mat_'+kind+'_last'
  if lastkey not in st.session_state:st.session_state[lastkey]=preset
  if preset!=st.session_state[lastkey]:
   a.update(copy.deepcopy(PRESETS[preset]));st.session_state[lastkey]=preset
   for key in ['E','nu','density','Fy','Fu']:st.session_state.pop('sf_mat_'+kind+'_'+key,None)
  a['name']=preset
  for key,text,step in [('E','Young’s modulus E (psi)',1_000_000.),('nu','Poisson ratio',.01),('density','Weight density at 1g (lbf/in³)',.001),('Fy','Minimum yield strength (psi)',1000.),('Fu','Minimum tensile strength (psi)',1000.)]:
   a[key]=ninput(text,a[key],'sf_mat_'+kind+'_'+key,step=step,minimum=.000001 if key!='nu' else -.9,maximum=.489 if key=='nu' else None,format='%.6f' if key=='density' else '%.3f' if key=='nu' else '%.1f')
  st.caption('Defaults are starting values; edit to match your actual material. E and density affect the analysis; strengths are reference/comparison values.')
 st.caption('44W default yield applies through 2.5 in thickness. B7 default strengths apply through 2.5 in rod diameter. Use the applicable material/test data for other sizes.')
 st.info('B7 is heat-treated. Its supplied-material strength does not verify a welded rod attachment or its heat-affected region.')


def render_sidebar():
 import streamlit as st
 m=st.session_state.sf_model
 with st.sidebar:
  st.markdown('### Frame inputs')
  tabs=st.tabs(['Design','Loading','Material'])
  with tabs[0]:selected=design_panel(m)
  with tabs[1]:loading_panel(m)
  with tabs[2]:material_panel(m)
  st.divider();calculate=st.button('Calculate / refresh results',key='sf_calculate',type='primary',width='stretch')
  with st.expander('Examples and saved designs'):
   choice=st.selectbox('Editable example',['Two-layer frame','Four-layer frame','Frame with blocks','Partial-length welded combination'],key='sf_example_choice')
   funcs={'Two-layer frame':two_layer_example,'Four-layer frame':four_layer_example,'Frame with blocks':block_example,'Partial-length welded combination':welded_example}
   st.button('Load example',key='sf_load_example',on_click=lambda:replace_model(funcs[st.session_state.sf_example_choice]()),width='stretch')
   st.caption('Examples are illustrative layouts, not qualified shipping designs. The previous uncut report is not used as a validation case.')
   st.download_button('Save design JSON',model_json(m),file_name='shipping_frame_design.json',mime='application/json',key='sf_save_model',width='stretch')
   st.file_uploader('Open saved design',type=['json'],key='sf_model_upload')
   st.button('Load uploaded design',key='sf_import_model',on_click=import_uploaded,width='stretch')
   if st.session_state.get('sf_import_error'):st.error(st.session_state.sf_import_error)
 return m,selected,calculate


def apply_editor_payload(bid,payload):
 import streamlit as st
 if not payload or payload.get('revision')!=st.session_state.sf_epoch:return
 shapes=payload.get('shapes',[])
 if not isinstance(shapes,list) or len(shapes)>300:return
 beam=next((x for x in st.session_state.sf_model['beams'] if x['id']==bid),None)
 if beam and beam['section_type']=='Custom draw':
  beam['components'][0]['drawing']=copy.deepcopy(shapes)
  st.session_state['sf_editor_draft_'+bid]=copy.deepcopy(payload.get('draft',[]))
 if payload.get('close'):close_editor()

def preview_geometry(m):
 """Keep unfinished custom members visible as placeholders, without inventing material."""
 empty=[b['id'] for b in m['beams'] if b['section_type']=='Custom draw' and not b['components'][0].get('drawing')]
 preview={**m,'beams':[b for b in m['beams'] if b['id'] not in empty]}
 return Geometry(preview),empty

def render_editor(m,bid):
 import streamlit as st
 global _EDITOR
 bid=st.session_state.get('sf_editor_beam',bid)
 b=next((b for b in m['beams'] if b['id']==bid),None)
 if b is None:return
 if b['section_type']!='Custom draw' or not st.session_state.get('sf_editor_open',False):return
 if _EDITOR is None:
  paths={name:next((p for p in [ROOT/'assets'/name,ROOT/name] if p.is_file()),None) for name in ['section_editor.html','section_editor.css','section_editor.js']}
  missing=[name for name,p in paths.items() if p is None]
  if missing:
   st.error('The sketcher needs these files in the assets folder beside shipping_frame_calculator.py: '+', '.join(missing))
   st.button('Close sketcher',key='sf_close_sketcher_missing',on_click=close_editor)
   return
  _EDITOR=st.components.v2.component('sf_section_sketcher',html=paths['section_editor.html'].read_text(encoding='utf8'),css=paths['section_editor.css'].read_text(encoding='utf8'),js=paths['section_editor.js'].read_text(encoding='utf8'))
 key='sf_editor_'+bid
 def changed():
  state=st.session_state.get(key,{})
  payload=state.get('geometry') if isinstance(state,dict) else getattr(state,'geometry',None)
  apply_editor_payload(bid,payload)
 st.markdown('### Draw custom section · '+b['name'])
 st.caption('Draw material boundaries in the section plane. Shapes are normalized to a local lower-left datum; the beam’s x/y inputs place the member in the frame. Add/subtract operations run in drawing order. Closed regions only; open lines are construction until closed.')
 _EDITOR(data={'shapes':b['components'][0].get('drawing',[]),'draft':st.session_state.get('sf_editor_draft_'+bid,[]),'beam':bid,'color':beam_color(m,bid),'revision':st.session_state.sf_epoch},key=key,on_geometry_change=changed,height='content')


def render_forces(s):
 import streamlit as st
 st.markdown('**Lifting reactions**')
 st.dataframe(pd.DataFrame([{'Point':p['id'],'Beam':p['beam'],'Position x (in)':p['x'],'Upward reaction (lbf)':p['force']} for p in s.reactions]),hide_index=True,width='stretch')
 if s.rods:
  st.markdown('**Rod tensions**')
  st.dataframe(pd.DataFrame([{'Rod':r['id'],'Welded to':r['weld'],'Nut on':r['nut'],'x (in)':r['x'],'Free length (in)':r['effective_length'],'Tension (lbf)':r['tension'],'Tensile stress (psi)':r['stress'],'Extension (in)':r['extension']} for r in s.rods]),hide_index=True,width='stretch')
  allowable=s.model['loading'].get('allowable_rod',0.)
  if allowable>0:st.info(f'Peak rod tensile stress / entered allowable = {max(r["stress"] for r in s.rods)/allowable:.3f}. This comparison covers nominal rod tension only.')
 st.markdown('**Coil contacts**')
 contacts=[{'Coil':q['label'],'Side':q['kind'].removeprefix('coil_'),'Beam':q['beam'],'x (in)':q['x'],'Compression (lbf)':q['force'],'Gap (in)':max(q['gap'],0),'State':'Bearing' if q['active'] else 'Open / unloaded'} for q in s.forces if q['kind'].startswith('coil_')]
 if contacts:st.dataframe(pd.DataFrame(contacts),hide_index=True,width='stretch')
 with st.expander('Distributed beam-to-beam bearing forces'):
  cc=[{'Lower':q['lower'],'Upper':q['upper'],'x (in)':q['x'],'Compression at station (lbf)':q['force'],'Gap (in)':max(q['gap'],0.)} for q in s.forces if q['kind']=='beam_contact' and q['force']>1e-5]
  if cc:st.dataframe(pd.DataFrame(cc),hide_index=True,width='stretch')
  else:st.write('No loaded direct beam-to-beam contacts.')


def render_app():
 import streamlit as st
 initialize_state()
 st.markdown('''<style>.block-container{max-width:1580px;padding-top:1.3rem;padding-bottom:2rem}[data-testid="stSidebar"]{min-width:380px;max-width:405px}[data-testid="stSidebar"] .block-container{padding-top:1rem}[data-testid="stSidebar"] h3{font-size:1.05rem}[data-testid="stMetricValue"]{font-size:1.45rem}div[data-testid="stTabs"] button{font-size:.88rem}@media(max-width:750px){[data-testid="stSidebar"]{min-width:0;max-width:92vw}}</style>''',unsafe_allow_html=True)
 m,bid,calculate=render_sidebar()
 st.title('Frame Load Analyzer')
 st.caption('Shipping-frame design · add beam layers as needed · automatic coil seats · inches / lbf / psi')
 render_editor(m,bid)
 try:
  g,incomplete=preview_geometry(m)
  left,right=st.columns([3.15,1.2],gap='medium')
  with right:
   st.subheader('Remaining cross section')
   ids=[b['id'] for b in m['beams']]
   bid=st.radio('Inspect beam',ids,index=None if 'sf_active_beam' in st.session_state else (ids.index(bid) if bid in ids else 0),key='sf_active_beam',horizontal=True)
   b=next(b for b in m['beams'] if b['id']==bid)
   # The inspector resets its bounds automatically when another beam is selected.
   x=ninput('Inspect at frame x (in)',(b['x']+b['length']/2),'sf_inspect_'+bid+'_'+str(st.session_state.sf_epoch),minimum=b['x'],maximum=b['x']+b['length'])
   section_x=x
   if bid in incomplete:st.info('This section is blank. Open its sketcher and draw a closed material outline.')
   elif b['section_type']!='Custom properties':
    # At a piece end use the inside one-sided section.
    x=min(max(x,b['x']+1e-8),b['x']+b['length']-1e-8)
    gg=g.section(bid,x);ss=section_properties(gg)
    st.image(section_svg(gg,ss,bid+' · X='+num(section_x)+' in',color=beam_color(m,bid)),width='stretch')
   else:st.caption('Manual section properties; no material outline.')
  with left:
   st.subheader('Frame schematic')
   show=st.checkbox('Show component labels',value=True,key='sf_show_ids')
   svg=frame_svg(m,g,show,inspect_x=section_x,inspect_beam=bid)
   if svg:st.image(svg,width='stretch')
   st.caption('The dashed section line marks the inspected X position. X/Y rulers use the common frame datum. Additional-load arrows include the load multiplier; red triangles identify welds.')
 except (ModelError,KeyError,ValueError,TypeError) as e:
  st.error(str(e));return
 if incomplete:
  st.info('Finish the custom section for '+', '.join(incomplete)+' before calculating. Completed drawings are retained when you close the sketcher.')
  return
 # Reuse an unchanged numerical state during tab/inspector/editor-view interactions.
 digest=hashlib.sha256(model_json(m).encode()).hexdigest()
 hasload=m['loading']['self_weight'] or m['loading']['coil_weight']>0 or any(q.get('value',0)!=0 for q in m.get('loads',[]))
 if not hasload:
  st.info('Design preview is live. Enter coil weight or enable self-weight in Loading to calculate results. Load an editable example for a worked case.')
  tabs=result_tabs()
  for tab in tabs:
   with tab:st.write('Results will appear here after a nonzero load is entered.')
  return
 if st.session_state.get('sf_solution_digest')!=digest and not calculate:
  st.info('Inputs are ready. Press Calculate results to update the analysis. The schematic remains live while you edit.')
  calculate=st.button('Calculate results',key='sf_main_calculate',type='primary')
  if not calculate:
   for tab in result_tabs():
    with tab:st.caption('Calculate results for the current inputs to display this view.')
   return
 try:
  if calculate:
   with st.spinner('Updating cut sections, contacts and beam response…'):
    s=solve_frame(m)
   st.session_state.sf_solution=s;st.session_state.sf_solution_digest=digest
  else:s=st.session_state.sf_solution
 except (ModelError,ValueError,KeyError,TypeError,np.linalg.LinAlgError) as e:
  st.error(str(e));st.caption('The schematic remains editable. No result from an older design is displayed for this input.');return
 if calculate:st.toast('Calculated from the current design and loading.')
 peak=max((r['peak_stress'] for r in s.beam_results.values()),key=lambda p:p['stress'])
 disp=max(abs(r['peak_deflection']['v']) for r in s.beam_results.values());rodmax=max([r['tension'] for r in s.rods] or [0.])
 cols=st.columns(4)
 for col,label,value in zip(cols,['Peak nominal bending stress','Maximum |movement|','Maximum rod tension','Total applied frame load'],[num(peak['stress'],1)+' psi',num(disp,6)+' in',num(rodmax,2)+' lbf',num(s.checks['total_downward'],2)+' lbf']):col.metric(label,value)
 st.caption('Nominal 2D member response. Local cutout, weld and lifting-hole stresses are outside this beam calculation. Level lifting and vertical forces are assumed.')
 if peak['stress']>m['materials']['frame']['Fy']:
  st.warning('Calculated nominal bending stress exceeds the entered frame yield strength. These are elastic-model results; yielding and plastic redistribution are not modeled.')
 if s.rods and max(r['stress'] for r in s.rods)>m['materials']['rod']['Fy']:
  st.warning('Calculated rod tensile stress exceeds the entered rod yield strength. The rod model is linear elastic.')
 st.dataframe(pd.DataFrame([{'Beam':bid,'Name':r['beam']['name'],'Peak nominal stress (psi)':r['peak_stress']['stress'],'At x (in)':r['peak_stress']['x'],'Peak |moment| (lbf·in)':abs(r['peak_moment']['M']),'Max |movement| (in)':abs(r['peak_deflection']['v'])} for bid,r in s.beam_results.items()]),hide_index=True,width='stretch')
 if m['loading'].get('allowable_beam',0)>0:
  a=m['loading']['allowable_beam'];st.info(f'Peak nominal bending stress / entered allowable = {peak["stress"]/a:.3f}. This comparison covers nominal bending only.')
 tabs=result_tabs()
 ids=['All beams']+list(s.beam_results)
 for tab,quant in zip(tabs[:4],['M','V','v','stress']):
  if not tab_is_open(tab):continue
  with tab:
   view=st.selectbox('Show beam',ids,key='sf_result_beam_'+quant)
   q=quant
   if quant=='stress':
    surface=st.radio('Stress display',['Magnitude envelope','Top surface','Bottom surface'],horizontal=True,key='sf_stress_display')
    q={'Magnitude envelope':'stress','Top surface':'stress_top','Bottom surface':'stress_bottom'}[surface]
   all_labels=st.checkbox('Label all detected extrema',value=False,key='sf_labels_'+quant)
   st.plotly_chart(make_chart(s,q,view,all_labels),width='stretch',key='sf_plot_'+quant,config={'displaylogo':False,'scrollZoom':True,'toImageButtonOptions':{'format':'png','filename':'frame_'+quant,'scale':2}})
   st.caption('Labels identify critical values; hover for other positions. Duplicate x values preserve either side of a force or section change.')
 if tab_is_open(tabs[4]):
  with tabs[4]:render_forces(s)
 if tab_is_open(tabs[5]):
  with tabs[5]:
   render_calculations(s)
   if st.button('Check mesh with finer divisions',key='sf_mesh_check'):
    try:
     with st.spinner('Checking refinement…'):st.session_state.sf_mesh_result=(digest,mesh_check(s))
    except ModelError as e:st.error(str(e))
   mesh=st.session_state.get('sf_mesh_result')
   if mesh and mesh[0]==digest:st.dataframe(pd.DataFrame(mesh[1]),hide_index=True,width='stretch')
 st.divider();c1,c2,c3=st.columns(3)
 with c1:st.download_button('Download chart data CSV',chart_csv(s),'shipping_frame_chart_data.csv','text/csv',key='sf_chart_csv',width='stretch')
 with c2:st.download_button('Download forces CSV',force_csv(s),'shipping_frame_forces.csv','text/csv',key='sf_forces_csv',width='stretch')
 with c3:st.download_button('Save current design',model_json(m),'shipping_frame_design.json','application/json',key='sf_bottom_save',width='stretch')


def main():
 import streamlit as st
 st.set_page_config(page_title='Frame Load Analyzer',layout='wide',initial_sidebar_state='expanded')
 render_app()

if __name__=='__main__':main()
