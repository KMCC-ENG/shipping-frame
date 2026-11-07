"""Exact SVG geometry previews, force diagrams and Plotly result curves."""
from __future__ import annotations
from html import escape
import csv,io,json,math
import numpy as np
from shapely.geometry import box,Point
from shapely.ops import unary_union
from shapely.affinity import translate
from frame_geometry import Geometry,ModelError,polygons,section_properties
from frame_engine import rod_geometry,critical_samples

COLORS=['#2463aa','#168063','#8850b5','#b46718','#2d8c9f']
NAVY='#18334b';MUTED='#61758a';GREEN='#168063';RED='#c34b50';BLUE='#2463aa';ORANGE='#c58429'
def num(v,n=4):
 if abs(v)<1e-11:return '0'
 if abs(v)<10**(-n):return f'{v:.3g}'
 return f'{v:,.{n}f}'.rstrip('0').rstrip('.')
def esc(s):return escape(str(s),quote=True)

def beam_color(model,bid):
 return COLORS[next((i for i,b in enumerate(model['beams']) if b['id']==bid),0)%len(COLORS)]

def ruler_ticks(a,b):
 span=max(b-a,.001);raw=span/5;power=10**math.floor(math.log10(raw));base=raw/power
 step=next(t for t in [1,2,2.5,5,10] if t>=base)*power
 return [float(x) for x in np.arange(math.ceil(a/step)*step,b+step*1e-6,step)]

def svg_path(g,xy):
 out=[]
 for p in polygons(g):
  for rr in [p.exterior,*p.interiors]:
   pts=[xy(x,y) for x,y in rr.coords]
   out.append('M'+'L'.join(f'{x:.5f},{y:.5f}' for x,y in pts)+'Z')
 return ' '.join(out)

def frame_front_geometry(model,geometry,bid):
 b=geometry.beams[bid];pieces=[]
 if b.get('section_type')=='Custom properties':
  pp=b['manual'];pieces=[box(b['x'],b['y'],b['x']+b['length'],b['y']+pp['ctop']+pp['cbottom'])]
 else:
  for c,p in zip(b['components'],geometry._profiles[bid]):
   xa=b['x']+c.get('start',0);xb=xa+c.get('length',b['length'])
   pieces.append(box(xa,b['y']+p.bounds[1],xb,b['y']+p.bounds[3]))
 g=unary_union(pieces)
 if b.get('auto_cut',True) and b.get('section_type')!='Custom properties':
  for c in model['coils']:g=g.difference(Point(c['x'],c['y']).buffer(c['r'],quad_segs=max(32,geometry.resolution//4)))
 pads=[box(q['x']-q['length']/2,q['y'],q['x']+q['length']/2,q['y']+q['height']) for q in model['blocks'] if q['beam']==bid]
 return unary_union([g,*pads]) if pads else g

def frame_svg(model,geometry=None,show_ids=True,inspect_x=None,inspect_beam=None):
 try:g=geometry or Geometry(model)
 except (ValueError,KeyError,TypeError):return ''
 regions=[];bounds=[];empty=[]
 for i,b in enumerate(model['beams']):
  try:p=frame_front_geometry(model,g,b['id']);regions.append((b,p,beam_color(model,b['id'])));bounds.append(p.bounds)
  except (ModelError,ValueError,KeyError):
   empty.append(b);bounds.append((b['x'],b['y'],b['x']+b['length'],b['y']))
 for c in model['coils']:bounds.append((c['x']-c['r'],c['y']-c['r'],c['x']+c['r'],c['y']+c['r']))
 if not bounds:return ''
 xmin=min(0.,min(b[0] for b in bounds));xmax=max(0.,max(b[2] for b in bounds));ymin=min(0.,min(b[1] for b in bounds));ymax=max(0.,max(b[3] for b in bounds))
 W=1120;H=440;sc=min(950/max(xmax-xmin,1),170/max(ymax-ymin,1));left=110+(950-(xmax-xmin)*sc)/2
 baseline=125+(170+(ymax-ymin)*sc)/2
 def xy(x,y):return left+(x-xmin)*sc,baseline-(y-ymin)*sc
 out=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="Frame design schematic">',
 '<rect width="1120" height="440" rx="14" fill="#f8fafc"/>',
 '<text x="25" y="29" font-family="Arial" font-size="13" fill="#61758a">FRAME VIEW · x right · y up · dimensions in inches</text>']
 for b,p,col in regions:
  out.append(f'<path d="{svg_path(p,xy)}" fill="{col}" fill-opacity=".12" stroke="{col}" stroke-width="1.8" fill-rule="evenodd"><title>{esc(b["name"])}</title></path>')
 for b in empty:
  x,y=xy(b['x'],b['y']);xx,_=xy(b['x']+b['length'],b['y']);col=beam_color(model,b['id'])
  out.append(f'<path d="M{x:.2f},{y:.2f}H{xx:.2f}" stroke="{col}" stroke-width="1.2" stroke-dasharray="4,5"/><text x="{x:.2f}" y="{y-10:.2f}" font-family="Arial" font-size="11" fill="{col}">{esc(b["id"])} · draw section</text>')
 for c in model['coils']:
  x,y=xy(c['x'],c['y']);r=c['r']*sc
  out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" fill="#edf3fa" fill-opacity=".8" stroke="#718ba5" stroke-width="1.3"><title>{esc(c["name"])}: x={num(c["x"])}; y={num(c["y"])}; R={num(c["r"])} in</title></circle>')
  out.append(f'<path d="M{x-4:.2f},{y:.2f}h8 M{x:.2f},{y-4:.2f}v8" stroke="#9bb0c5" stroke-width=".8"/>')
  if show_ids and r>9:out.append(f'<text x="{x:.2f}" y="{y+4:.2f}" text-anchor="middle" font-size="10" font-family="Arial" fill="{MUTED}">{esc(c["id"])}</text>')
 for rr in model['rods']:
  try:ya,yn,ll=rod_geometry(rr,g)
  except (ModelError,KeyError,ValueError):continue
  x,yy=xy(rr['x'],ya);_,ynp=xy(rr['x'],yn);rw=max(3,rr['diameter']*sc)
  out.append(f'<rect x="{x-rw/2:.2f}" y="{ynp-9:.2f}" width="{rw:.2f}" height="{yy-ynp+9:.2f}" fill="#fcf0d9" stroke="{ORANGE}" stroke-width="1.2"><title>{esc(rr["name"])}; welded to {esc(rr["weld"])}; nut on {esc(rr["nut"])}</title></rect>')
  out.append(f'<path d="M{x-rw/2:.2f},{yy:.2f}l-6,-6v6Z M{x+rw/2:.2f},{yy:.2f}l6,-6v6Z" fill="{RED}"><title>Welded to {esc(rr["weld"])}</title></path>')
  out.append(f'<rect x="{x-rw:.2f}" y="{ynp-6:.2f}" width="{rw*2:.2f}" height="5" rx="1" fill="#fff" stroke="{ORANGE}"/><path d="M{x-rw*1.2:.2f},{ynp:.2f}h{rw*2.4:.2f}" stroke="{ORANGE}" stroke-width="2"/>')
  if show_ids:out.append(f'<text x="{x:.2f}" y="{ynp-14:.2f}" text-anchor="middle" font-size="10" font-family="Arial" fill="{ORANGE}">{esc(rr["id"])}</text>')
 for q in model['blocks']:
  x,y=xy(q['x'],q['y']+q['height']);w=q['length']*sc;h=q['height']*sc
  out.append(f'<rect x="{x-w/2:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" fill="#d7e9e1" stroke="{GREEN}" stroke-width="1.4"><title>{esc(q["name"])}; welded to {esc(q["beam"])}</title></rect>')
  out.append(f'<path d="M{x-w/2:.2f},{y:.2f}l-5,5v-5Z" fill="{RED}"/>')
 for p in model['pins']:
  try:
   b=g.beams[p['beam']];pp=g.props(p['beam'],p['x']);y=p['y'] if p.get('y') is not None else pp.yc
  except (ValueError,KeyError):continue
  x,yy=xy(p['x'],y);r=max(5,p.get('diameter',.75)*sc/2)
  out.append(f'<circle cx="{x:.2f}" cy="{yy:.2f}" r="{r:.2f}" fill="white" stroke="{GREEN}" stroke-width="2.4"><title>{esc(p["name"])} on {esc(p["beam"])}, x={num(p["x"])} in</title></circle>')
  out.append(f'<path d="M{x:.2f},{yy+r+14:.2f}v-12m-4,5l4,-5l4,5" fill="none" stroke="{GREEN}" stroke-width="2"/>')
  if show_ids:out.append(f'<text x="{x:.2f}" y="{yy+r+29:.2f}" text-anchor="middle" font-size="11" font-family="Arial" fill="{GREEN}">{esc(p["id"])}</text>')
 if show_ids:
  for b,p,col in regions:
   y0,y1=g.bounds(b['id'])[1],g.bounds(b['id'])[3];_,yy=xy(xmin,(y0+y1)/2)
   out.append(f'<text x="{left-12:.1f}" y="{yy+4:.1f}" text-anchor="end" font-size="12" font-family="Arial" font-weight="bold" fill="{col}">{esc(b["id"])}</text>')
 # Additional loads are drawn at their actual member/position. Uniform input
 # is total force over the interval; display both total and intensity.
 for load in model.get('loads',[]):
  bid=load['beam'];force=load['value']*model['loading']['factor']
  if bid not in g.beams or abs(force)<1e-10:continue
  xa=load['x'];xb=load.get('end',xa) if load['kind']=='Uniform' else xa
  positions=np.linspace(xa,xb,max(3,min(15,int(abs(xb-xa)*sc/40)+1))) if xb>xa else [xa]
  tails=[]
  for xx in positions:
   try:s=g.props(bid,float(xx));yy=s.ymin if force>0 else s.ymax
   except (ModelError,ValueError):yy=g.bounds(bid)[1 if force>0 else 3]
   x,head=xy(xx,yy);tail=head+(36 if force>0 else -36);delta=6 if force>0 else -6;tails.append((x,tail))
   out.append(f'<path data-load="{esc(load["id"])}" data-direction="{"up" if force>0 else "down"}" d="M{x:.2f},{tail:.2f}V{head:.2f}m-4,{delta}l4,{-delta}l4,{delta}" fill="none" stroke="{RED}" stroke-width="1.8"/>')
  tx=sum(x for x,y in tails)/len(tails);ty=(max(y for x,y in tails)+16) if force>0 else (min(y for x,y in tails)-9)
  label=f'{load["id"]} · {bid}: {num(abs(force),2)} lbf'
  if xb>xa:
   label+=f' total · {num(abs(force)/(xb-xa),3)} lbf/in'
   out.append(f'<path d="M{tails[0][0]:.2f},{tails[0][1]:.2f}L{tails[-1][0]:.2f},{tails[-1][1]:.2f}" stroke="{RED}" fill="none"/>')
  out.append(f'<text x="{tx:.2f}" y="{ty:.2f}" text-anchor="middle" font-family="Arial" font-size="11" fill="{RED}">{esc(label)}</text>')
 # Numeric rulers are in the common frame coordinates, including negative
 # positions and offsets. They do not reset to a selected member's left end.
 x0,_=xy(xmin,ymin);x1,_=xy(xmax,ymin)
 out.append(f'<path data-axis="X" d="M{x0:.2f},385H{x1+12:.2f}m-6,-4l6,4l-6,4" fill="none" stroke="{MUTED}"/>')
 out.append(f'<path data-axis="Y" d="M76,326V100m-4,6l4,-6l4,6" fill="none" stroke="{MUTED}"/>')
 for value in ruler_ticks(xmin,xmax):
  xx,_=xy(value,ymin);out.append(f'<path d="M{xx:.2f},381v8" stroke="{MUTED}"/><text x="{xx:.2f}" y="405" text-anchor="middle" font-family="Arial" font-size="11" fill="{MUTED}">{num(value,3)}</text>')
 for value in ruler_ticks(ymin,ymax):
  _,yy=xy(xmin,value);out.append(f'<path d="M72,{yy:.2f}h8" stroke="{MUTED}"/><text x="65" y="{yy+4:.2f}" text-anchor="end" font-family="Arial" font-size="11" fill="{MUTED}">{num(value,3)}</text>')
 out.append(f'<text x="42" y="91" font-family="Arial" font-size="12" fill="{MUTED}">Y (in)</text><text x="1060" y="427" text-anchor="end" font-family="Arial" font-size="12" fill="{MUTED}">X (in) · common frame datum</text>')
 if inspect_x is not None:
  xx,_=xy(inspect_x,ymin);col=beam_color(model,inspect_beam);label=f'Section {inspect_beam or ""} · X={num(inspect_x)} in'
  out.append(f'<path data-section-beam="{esc(inspect_beam or "")}" data-section-x="{inspect_x:.12g}" d="M{xx:.2f},96V385" stroke="{col}" stroke-width="1.7" stroke-dasharray="7,5"/>')
  out.append(f'<circle cx="{xx:.2f}" cy="385" r="3.5" fill="{col}"/><text x="{min(max(xx,190),930):.2f}" y="84" text-anchor="middle" font-family="Arial" font-size="12" font-weight="bold" fill="{col}">{esc(label)}</text>')
 out.append('<text x="25" y="52" font-size="10" font-family="Arial" fill="#61758a">Red triangles: welds · Gold: rods/nuts · Green circles: lifting points</text></svg>')
 return ''.join(out)

def section_svg(g,section=None,caption='',width=420,color=BLUE):
 if g.is_empty:return ''
 s=section or section_properties(g);z0,y0,z1,y1=g.bounds;sc=min(300/max(z1-z0,.1),270/max(y1-y0,.1));W=420;H=390
 def xy(z,y):return 60+(z-z0)*sc,325-(y-y0)*sc
 out=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="Remaining cross section">',
 '<rect width="420" height="390" rx="12" fill="#f8fafc"/>',f'<text x="20" y="26" font-family="Arial" font-size="12" fill="{MUTED}">{esc(caption)}</text>',
 f'<path d="{svg_path(g,xy)}" fill="{color}" fill-opacity=".12" stroke="{color}" stroke-width="1.8" fill-rule="evenodd"/>']
 _,yy=xy(s.zc,s.yc);xx,_=xy(s.zc,s.yc)
 out.append(f'<path d="M35,{yy:.2f}H390" stroke="{GREEN}" stroke-width="1.4" stroke-dasharray="6,4"/><circle cx="{xx:.2f}" cy="{yy:.2f}" r="4" fill="{GREEN}"/>')
 out.append(f'<text x="25" y="{max(48,yy-9):.2f}" font-family="Arial" font-size="11" fill="{GREEN}">Centroidal bending axis</text>')
 out.append(f'<text x="20" y="357" font-family="Arial" font-size="12" fill="{NAVY}">Width {num(z1-z0)} in · Height {num(y1-y0)} in</text>')
 out.append(f'<text x="20" y="378" font-family="Arial" font-size="12" fill="{MUTED}">A={num(s.A)} in² · I={num(s.I)} in⁴</text></svg>')
 return ''.join(out)

def fbd_svg(xmin,xmax,loads,title='',uniform=None):
 """An actual free-body diagram. Bearing distributions may be condensed for display."""
 W=1080;H=310;span=max(xmax-xmin,1.);left=65;sc=950/span;beam_y=145
 def xp(x):return left+(x-xmin)*sc
 out=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}">',
 '<rect width="1080" height="310" rx="12" fill="#f8fafc"/>',
 f'<text x="24" y="28" font-family="Arial" font-size="15" font-weight="bold" fill="{NAVY}">{esc(title)}</text>',
 f'<path d="M{xp(xmin):.2f},{beam_y}H{xp(xmax):.2f}" stroke="{NAVY}" stroke-width="5"/>']
 # Put nearby labels on alternate rows. Arrow lengths encode direction only.
 active=[p for p in loads if abs(p['F'])>1e-7]
 active.sort(key=lambda q:(q['F']<0,q['x']))
 last={True:-1e9,False:-1e9};row={True:0,False:0}
 for p in active:
  x=xp(p['x']);up=p['F']>0
  if x-last[up]<105:row[up]=(row[up]+1)%3
  else:row[up]=0
  last[up]=x;offset=row[up]*20
  col=GREEN if p.get('kind')=='Lifting reaction' else BLUE if p.get('kind')=='Rod tension' else RED
  tail=beam_y+58 if up else beam_y-58
  head=beam_y+3 if up else beam_y-3
  out.append(f'<path d="M{x:.2f},{tail}V{head}" stroke="{col}" stroke-width="1.7" fill="none"/>')
  dy=7 if up else -7
  out.append(f'<path d="M{x-4:.2f},{head+dy}L{x:.2f},{head}L{x+4:.2f},{head+dy}" fill="none" stroke="{col}" stroke-width="1.7"/>')
  label_y=tail+17+offset if up else tail-8-offset
  out.append(f'<text x="{x:.2f}" y="{label_y}" text-anchor="middle" font-family="Arial" font-size="10.5" fill="{col}">{esc(p.get("label","F"))}: {num(abs(p["F"]),2)} lbf</text>')
 last_x=-1e9;position_row=0
 for xx in sorted({p['x'] for p in active}):
  x=xp(xx);position_row=1-position_row if x-last_x<38 else 0;last_x=x
  out.append(f'<text x="{x:.2f}" y="{beam_y+17+position_row*12}" text-anchor="middle" font-family="Arial" font-size="9" fill="{MUTED}">{num(xx,3)}</text>')
 if uniform:
  out.append(f'<text x="25" y="279" font-family="Arial" font-size="11" fill="{MUTED}">{esc(uniform)}</text>')
 out.append(f'<text x="25" y="297" font-family="Arial" font-size="10" fill="{MUTED}">x positions in inches from common datum; arrows show direction, not relative magnitude.</text></svg>')
 return ''.join(out)

def member_fbd(solution,bid):
 r=solution.beam_results[bid];b=r['beam'];loads=[]
 for p in r['point_loads']:
  if p['kind']!='Beam bearing':loads.append(p)
 bearing=[p for p in r['point_loads'] if p['kind']=='Beam bearing']
 for sign in [-1,1]:
  pp=[p for p in bearing if p['F']*sign>1e-7];ff=sum(p['F'] for p in pp)
  if abs(ff)>1e-7:loads.append({'x':sum(p['x']*p['F'] for p in pp)/ff,'F':ff,'label':'Bearing resultant','kind':'Beam bearing'})
 ee=[e for e in solution.elements if e.beam==bid];Q=sum(e.q*e.L for e in ee)
 if abs(Q)>1e-7:loads.append({'x':sum(e.q*e.L*(e.x0+e.x1)/2 for e in ee)/Q,'F':Q,'label':'Distributed load resultant','kind':'Distributed'})
 note='Distributed gravity/loading and beam bearing are shown as equivalent resultants; internal-force calculations retain their actual distributions.'
 return fbd_svg(b['x'],b['x']+b['length'],loads,b['id']+' · '+b['name']+' — free-body diagram',note)

def overall_fbd(solution):
 m=solution.model;loads=[{'x':p['x'],'F':p['force'],'label':p['id'],'kind':'Lifting reaction'} for p in solution.reactions]
 loads.extend({'x':c['x'],'F':-c['applied_weight'],'label':c['id']+' weight','kind':'Coil weight'} for c in solution.coils)
 factor=m['loading']['factor']
 if m['loading']['self_weight']:
  loads.extend({'x':w['x'],'F':-w['weight']*factor,'label':w['member']+' self-weight','kind':'Self-weight'} for w in solution.weights)
  if solution.rods:
   ww=sum(r['weight'] for r in solution.rods)
   if ww:loads.append({'x':sum(r['weight']*r['x'] for r in solution.rods)/ww,'F':-ww*factor,'label':'Rod weights','kind':'Self-weight'})
 for p in m.get('loads',[]):loads.append({'x':(p['x']+p['end'])/2 if p['kind']=='Uniform' else p['x'],'F':p['value']*factor,'label':p['name'],'kind':'Additional load'})
 return fbd_svg(min(b['x'] for b in m['beams']),max(b['x']+b['length'] for b in m['beams']),loads,'Whole frame / assigned coils — external forces')

def coil_fbd(solution,coil):
 """Collinear vertical forces at the upper seat, centre and lower seat."""
 cc=[q for q in solution.forces if q.get('coil')==coil['id']]
 lower=sum(q['force'] for q in cc if q['kind']=='coil_lower')
 upper=sum(q['force'] for q in cc if q['kind']=='coil_upper')
 C=520;cy=155;R=48
 out=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 320" role="img" aria-label="Coil free body">',
 '<rect width="1080" height="320" rx="12" fill="#f8fafc"/>',
 f'<text x="24" y="28" font-family="Arial" font-size="15" font-weight="bold" fill="{NAVY}">{esc(coil["id"])} — coil free body · x={num(coil["x"])} in</text>',
 f'<circle cx="{C}" cy="{cy}" r="{R}" fill="#edf3fa" stroke="{BLUE}" stroke-width="2"/>',
 f'<path d="M{C},{cy-R-68}V{cy-R}m-5,-8l5,8l5,-8 M{C},{cy+R+68}V{cy+R}m-5,8l5,-8l5,8" fill="none" stroke="{BLUE}" stroke-width="2"/>',
 f'<path d="M{C},{cy}V{cy+R-7}m-5,-8l5,8l5,-8" fill="none" stroke="{RED}" stroke-width="2"/>',
 f'<text x="550" y="67" font-family="Arial" font-size="13" fill="{BLUE}">Upper bearing H = {num(upper,3)} lbf ↓</text>',
 f'<text x="550" y="180" font-family="Arial" font-size="13" fill="{RED}">Weight W = {num(coil["applied_weight"],3)} lbf ↓</text>',
 f'<text x="550" y="257" font-family="Arial" font-size="13" fill="{BLUE}">Lower bearing C = {num(lower,3)} lbf ↑</text>',
 f'<text x="24" y="301" font-family="Arial" font-size="11" fill="{MUTED}">All three forces act on the coil on the same vertical line. A zero bearing force indicates an unloaded/open seat.</text></svg>']
 return ''.join(out)

def rod_fbd(rod):
 C=520
 return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 320" role="img" aria-label="Rod free body">'
 '<rect width="1080" height="320" rx="12" fill="#f8fafc"/>'
 f'<text x="24" y="28" font-family="Arial" font-size="15" font-weight="bold" fill="{NAVY}">{esc(rod["id"])} — vertical rod free body · x={num(rod["x"])} in</text>'
 f'<rect x="{C-6}" y="90" width="12" height="120" fill="#fcf0d9" stroke="{ORANGE}" stroke-width="2"/>'
 f'<path d="M{C},90V43m-5,8l5,-8l5,8 M{C},210V270m-5,-8l5,8l5,-8" stroke="{BLUE}" fill="none" stroke-width="2"/>'
 f'<path d="M{C-6},210l-7,-7v7Z M{C+6},210l7,-7v7Z" fill="{RED}"/>'
 f'<text x="550" y="64" font-family="Arial" font-size="13" fill="{BLUE}">T = {num(rod["tension"],3)} lbf ↑</text>'
 f'<text x="550" y="101" font-family="Arial" font-size="12" fill="{MUTED}">Nut end · {esc(rod["nut"])}</text>'
 f'<text x="550" y="210" font-family="Arial" font-size="12" fill="{MUTED}">Weld end · {esc(rod["weld"])}</text>'
 f'<text x="550" y="262" font-family="Arial" font-size="13" fill="{BLUE}">T = {num(rod["tension"],3)} lbf ↓</text>'
 f'<text x="24" y="301" font-family="Arial" font-size="11" fill="{MUTED}">Forces shown act on the rod. Rod self-weight is lumped at its welded beam in the frame model.</text></svg>')


def make_chart(solution,quantity,beam='All beams',all_labels=False):
 import plotly.graph_objects as go
 quantities={'M':('Bending moment','lbf·in'),'V':('Shear force','lbf'),'v':('Vertical deflection','in'),
             'stress':('Nominal bending stress magnitude','psi'),'stress_top':('Top surface stress','psi'),'stress_bottom':('Bottom surface stress','psi')}
 title,unit=quantities[quantity];fig=go.Figure()
 for j,(bid,r) in enumerate(solution.beam_results.items()):
  if beam!='All beams' and beam!=bid:continue
  pp=r['samples'];col=COLORS[j%5]
  fig.add_trace(go.Scatter(x=[p['x'] for p in pp],y=[p[quantity] for p in pp],name=bid+' · '+r['beam']['name'],mode='lines',line=dict(color=col,width=2),
    customdata=[[p['I']] for p in pp],hovertemplate='x=%{x:.5f} in<br>'+title+'=%{y:.6g} '+unit+'<br>I=%{customdata[0]:.5f} in⁴<extra>%{fullData.name}</extra>'))
  crit=critical_samples(r,quantity)
  if not all_labels:
   crit=sorted(crit,key=lambda p:abs(p[quantity]),reverse=True)[:6]
  for p in crit:
   if abs(p[quantity])<1e-8:continue
   fig.add_annotation(x=p['x'],y=p[quantity],text=num(p[quantity],5 if quantity=='v' else 2),showarrow=True,arrowhead=0,ax=0,ay=-24 if p[quantity]>=0 else 24,font=dict(color=col,size=10))
 fig.update_layout(template='plotly_white',height=440,margin=dict(l=45,r=25,t=25,b=55),xaxis_title='x from common datum (in)',yaxis_title=f'{title} ({unit})',
  legend=dict(orientation='h',y=1.13),hovermode='closest',font=dict(family='Arial',color=NAVY),xaxis=dict(showgrid=True,gridcolor='#edf1f5'),yaxis=dict(zeroline=True,zerolinecolor='#aebdcb',gridcolor='#edf1f5'))
 return fig

def chart_csv(solution):
 f=io.StringIO();cols=['beam','x','side','V','M','v','theta','stress_top','stress_bottom','stress','A','I','yc','ctop','cbottom','element_start','element_end']
 w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
 for bid,r in solution.beam_results.items():
  for p in r['samples']:w.writerow({'beam':bid,**{k:p[k] for k in cols if k!='beam'}})
 return f.getvalue()

def force_csv(solution):
 f=io.StringIO();cols=['kind','label','x','force_lbf','gap_in','beam','weld','nut','lower','upper']
 w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
 for p in solution.forces:
  w.writerow({'kind':p['kind'],'label':p['label'],'x':p['x'],'force_lbf':p['force'],'gap_in':p['gap'],**{k:p.get(k,'') for k in cols[5:]}})
 for p in solution.reactions:w.writerow({'kind':'lifting_reaction','label':p['id'],'x':p['x'],'force_lbf':p['force'],'beam':p['beam']})
 return f.getvalue()
