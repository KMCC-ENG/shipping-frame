"""Variable-section beam/contact analysis, inches / lbf / psi.

Planar bending or coupled vertical/lateral elastic bending. Coils are rigid vertical spacers.
Coil/member and member/member contacts carry compression; rods are finite-EA/L,
zero-preload, tension-only links. Small deflections; no chain-angle or tilt solve.
The formulation returns nominal beam stresses, not notch/weld/lug local peaks.
"""
from __future__ import annotations
from dataclasses import dataclass,field
import copy,json,math,warnings
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve, MatrixRankWarning
from scipy.optimize import minimize_scalar, brentq
from shapely.geometry import Point,box,GeometryCollection
from frame_geometry import Geometry,ModelError,polygons,vertical_bearing_gap
from frame_models import incomplete_inputs

GROOT,GWEIGHT=np.polynomial.legendre.leggauss(4)

def thread_area(d,tpi):
    if d<=0 or tpi<=0 or d-.9743/tpi<=0:raise ModelError('Rod diameter/thread pitch gives an invalid tensile area.')
    return math.pi/4*(d-.9743/tpi)**2

def element_flexibility(L,E,G,points,As_enabled=True,q=0.):
    """Integrated force-based Timoshenko element. points=(w,s,Section).

    End-force equilibrium and integrated curvature/shear compatibility provide
    both stiffness and a consistent distributed-load vector for variable EI/GA.
    q is the element's mean signed distributed load, positive upward.
    """
    J=np.array([sum(w*x**n/(E*s.I) for w,x,s in points) for n in range(4)])
    H=np.array([sum(w*x**n/(G*s.As) for w,x,s in points) for n in range(2)]) if As_enabled else np.zeros(2)
    C=np.array([[J[1],-J[0]],[L*J[1]-J[2]-H[0],-L*J[0]+J[1]]])
    D=np.array([[0,-1,0,1],[-1,-L,1,0]],float)
    T=np.array([[1,0],[0,1],[-1,0],[L,-1]],float)
    pD=np.linalg.solve(C,D)
    K=T@pD;K=(K+K.T)/2
    e0=np.array([q*J[2]/2,q*(L*J[2]-J[3])/2-q*H[1]])
    p0=np.linalg.solve(C,-e0)
    rq=T@p0+np.array([0,0,-q*L,q*L*L/2])
    return K,-rq,J,H


def bending_compliance(section,E):
    inertia=np.array([[section.I,section.Izy],[section.Izy,section.Iyy]],float)
    return np.linalg.inv(inertia)/E


def coupled_element_flexibility(L,E,G,points,shear=True,q=0.):
    """Force-based two-plane beam with the full centroidal inertia tensor.

    Nodal order is v, theta, w, psi. The lateral moment is work-conjugate
    to positive lateral slope, so curvature and stress use the same tensor.
    Shear uses independent directional energy-area approximations.
    """
    J=np.zeros((4,2,2));H=np.zeros((2,2,2))
    for weight,x,section in points:
        compliance=bending_compliance(section,E)
        for n in range(4):J[n]+=weight*x**n*compliance
        if shear:
            for n in range(2):H[n]+=weight*x**n*np.diag([1/(G*section.As),1/(G*section.Asz)])
    C=np.zeros((4,4));D=np.zeros((4,8));T=np.zeros((8,4))
    indices=[[0,1,4,5],[2,3,6,7]]
    d=np.array([[0,-1,0,1],[-1,-L,1,0]],float)
    t=np.array([[1,0],[0,1],[-1,0],[L,-1]],float)
    for i in range(2):
        D[np.ix_([2*i,2*i+1],indices[i])]=d
        T[np.ix_(indices[i],[2*i,2*i+1])]=t
        for j in range(2):
            C[2*i:2*i+2,2*j:2*j+2]=[
                [J[1,i,j],-J[0,i,j]],
                [L*J[1,i,j]-J[2,i,j]-H[0,i,j],-L*J[0,i,j]+J[1,i,j]]]
    K=T@np.linalg.solve(C,D);K=(K+K.T)/2
    e0=np.array([q*J[2,0,0]/2,q*(L*J[2,0,0]-J[3,0,0])/2-q*H[1,0,0],
                 q*J[2,1,0]/2,q*(L*J[2,1,0]-J[3,1,0])/2-q*H[1,1,0]])
    rq=T@np.linalg.solve(C,-e0)
    rq[4]-=q*L;rq[5]+=q*L*L/2
    return K,-rq,J,H

@dataclass
class Element:
    beam: str
    x0: float
    x1: float
    dofs: np.ndarray
    K: np.ndarray
    f: np.ndarray
    q: float
    points: list
    coupled: bool=False
    @property
    def L(self):return self.x1-self.x0

@dataclass
class Solution:
    model: dict
    geometry: Geometry
    beam_nodes: dict
    elements: list
    u: np.ndarray
    forces: list
    reactions: list
    beam_results: dict
    weights: list
    loads: list
    coils: list
    rods: list
    checks: dict
    iterations: list
    K: object
    B: object
    f: np.ndarray
    warnings: list
    lateral_reactions: list=field(default_factory=list)


def validate_model(model,geometry=None):
    missing=incomplete_inputs(model)
    if missing:raise ModelError('Complete the required inputs. '+ ' '.join(missing[:8]))
    g=geometry or Geometry(model);bs=g.beams;ids=list(bs)
    if not bs:raise ModelError('Add at least one beam layer.')
    if len(bs)!=len(model['beams']):raise ModelError('Beam IDs must be unique.')
    for name in ['frame','rod']:
        a=model['materials'][name]
        for k in ['E','density','Fy','Fu']:
            if not math.isfinite(float(a[k])) or a[k]<=0:raise ModelError(f'{name} material: {k} must be positive.')
        if not -.9<a['nu']<.49:raise ModelError('Poisson ratio must be between -0.9 and 0.49.')
    for b in bs.values():
        if b['length']<=0:raise ModelError(b['name']+': length must be positive.')
        if b.get('section_type')=='Custom properties':
            p=b['manual']
            if any(p[k]<=0 for k in ['A','I','ctop','cbottom','As']):raise ModelError('Manual section properties must be positive.')
            if b.get('auto_cut',False):raise ModelError('Automatic cutouts require section geometry. Use Custom draw instead of properties alone.')
        else:
            for c in b['components']:
                if c.get('length',b['length'])<=0 or c.get('start',0)<0 or c.get('start',0)+c.get('length',b['length'])>b['length']+1e-8:
                    raise ModelError(b['name']+': component start/length must lie inside the beam length.')
    for c in model['coils']:
        if c['r']<=0 or c.get('share',1)<0:raise ModelError('Coil radius must be positive; its weight share cannot be negative.')
    for i,a in enumerate(model['coils']):
        for b in model['coils'][i+1:]:
            if math.hypot(a['x']-b['x'],a['y']-b['y'])<a['r']+b['r']-1e-7:
                raise ModelError(f"{a['name']} and {b['name']} overlap. Move or resize a coil.")
    for p in model['pins']:
        if p['beam'] not in bs:raise ModelError('A lifting point refers to a removed beam.')
        b=bs[p['beam']]
        if not b['x']-1e-8<=p['x']<=b['x']+b['length']+1e-8:raise ModelError('A lifting point lies outside its beam.')
        if p.get('diameter',.75)<=0:raise ModelError('Lifting-hole display diameter must be positive.')
    if len(model['pins'])<2:raise ModelError('Add at least two lifting points to the selected beams.')
    if len({(p['beam'],round(p['x'],9)) for p in model['pins']})!=len(model['pins']):raise ModelError('Duplicate lifting points are not allowed.')
    if max(p['x'] for p in model['pins'])-min(p['x'] for p in model['pins'])<1e-6:raise ModelError('Lifting points must span two different horizontal positions.')
    for r in model['rods']:
        if r['weld'] not in bs or r['nut'] not in bs or r['weld']==r['nut']:raise ModelError('Each rod must connect two different active beams.')
        thread_area(r['diameter'],r['tpi'])
        if model['materials']['rod'].get('name')=='ASTM A193 B7' and r['diameter']>2.5:
            raise ModelError('The B7 preset strengths apply up to 2.5 in diameter. Use Custom material and the applicable size-dependent properties for a larger rod.')
        for key in ['weld','nut']:
            b=bs[r[key]]
            if not b['x']-1e-8<=r['x']<=b['x']+b['length']+1e-8:raise ModelError(r['name']+': position is outside an attachment beam.')
    for q in model['blocks']:
        if q['beam'] not in bs:raise ModelError('A block refers to a removed beam.')
        if min(q['height'],q['depth'],q['length'])<=0:raise ModelError('Block dimensions must be positive.')
        b=bs[q['beam']]
        if q['x']-q['length']/2<b['x']-1e-8 or q['x']+q['length']/2>b['x']+b['length']+1e-8:raise ModelError('A block extends beyond its parent beam.')
        if b.get('section_type')=='Custom properties':raise ModelError('Blocks require a geometric section. Use Custom draw for their parent beam.')
        block=box(q.get('z',0)-q['depth']/2,q['y'],q.get('z',0)+q['depth']/2,q['y']+q['height'])
        parent=g.section(q['beam'],q['x'],blocks=False)
        if parent.distance(block)>1e-7:raise ModelError(q['name']+': the block does not touch its parent section. Adjust its height/offset.')
        rect=box(q['x']-q['length']/2,q['y'],q['x']+q['length']/2,q['y']+q['height'])
        for c in model['coils']:
            if rect.intersection(Point(c['x'],c['y']).buffer(c['r'],quad_segs=64)).area>1e-7:
                raise ModelError(q['name']+': rectangular block overlaps '+c['name']+'. Set its face tangent to the coil. Blocks are contact pads and are not automatically cut.')
    lo=model['loading']
    if lo['coil_weight']<0 or lo['frames']<1 or not 0<=lo['frame_share']<=1 or lo['factor']<=0:raise ModelError('Weight must be nonnegative, frame count >=1, frame share 0–1, and load multiplier positive.')
    if lo['coil_weight']>0 and (not model['coils'] or sum(c.get('share',1) for c in model['coils'])<=0):raise ModelError('Add coils with positive weight shares before applying total coil weight.')
    for q in model.get('loads',[]):
        if q['beam'] not in bs:raise ModelError('An additional load refers to a removed beam.')
        b=bs[q['beam']];end=q.get('end',q['x']) if q['kind']=='Uniform' else q['x']
        if q['x']<b['x']-1e-8 or end>b['x']+b['length']+1e-8 or (q['kind']=='Uniform' and end<=q['x']):raise ModelError('An additional load lies outside its beam or has an invalid interval.')
    analysis=model['analysis']
    if analysis.get('coupled_bending'):
        for b in bs.values():
            if b.get('section_type')=='Custom properties':
                p=b['manual']
                if min(p['Iyy'],p['cleft'],p['cright'])<=0 or (analysis['timoshenko'] and p['Asz']<=0):
                    raise ModelError(b['name']+': lateral inertia, fiber distances and shear area must be positive.')
        if not analysis.get('free_lateral',True):
            seen=set()
            for q in analysis.get('lateral_constraints',[]):
                if q['beam'] not in bs:raise ModelError('A lateral constraint refers to a removed beam.')
                b=bs[q['beam']]
                if not b['x']<=q['x']<=b['x']+b['length']:raise ModelError('A lateral constraint lies outside its beam.')
                if q['kind'] not in ['Displacement','Rotation','Displacement and rotation']:raise ModelError('Choose a lateral constraint type.')
                components=['w','psi'] if q['kind']=='Displacement and rotation' else ['w'] if q['kind']=='Displacement' else ['psi']
                for component in components:
                    key=(q['beam'],round(q['x'],9),component)
                    if key in seen:raise ModelError('Duplicate lateral restraints are not allowed.')
                    seen.add(key)
    return g


def rod_geometry(r,g):
    x=r['x'];d=r['diameter']
    ya=g.top_seat(r['weld'],x,d) if r.get('weld_y') is None else r['weld_y']
    yn=g.top_seat(r['nut'],x,d) if r.get('nut_y') is None else r['nut_y']
    if yn<=ya+1e-6:raise ModelError(r['name']+': the nut seat must be above the welded attachment in this vertical-rod model.')
    L=yn-ya if r.get('auto_length',True) else r['free_length']
    if L<=0:raise ModelError('Rod effective free length must be positive.')
    return ya,yn,L


def assemble(model,elements_per_span=None):
    g=validate_model(model)
    mat=model['materials']['frame'];E=mat['E'];G=E/(2*(1+mat['nu']));analysis=model['analysis']
    count=int(elements_per_span or analysis.get('elements',72))
    coupled=bool(analysis.get('coupled_bending',False));ndpn=4 if coupled else 2
    if count<8 or count>400:raise ModelError('Use 8–400 mesh divisions per longest beam.')
    xmin=min(b['x'] for b in model['beams']);xmax=max(b['x']+b['length'] for b in model['beams']);span=xmax-xmin
    step=span/count
    critical=np.array(g.critical_x(),float)
    allx=np.unique(np.round(np.r_[critical,np.arange(xmin,xmax,step),xmax],9))
    nodes={};n=0
    for b in model['beams']:
        xs=allx[(allx>=b['x']-1e-8)&(allx<=b['x']+b['length']+1e-8)]
        # Collapse near-coincident circle/mesh coordinates.
        xs=np.array([x for i,x in enumerate(xs) if i==0 or x-xs[i-1]>max(span*1e-8,1e-7)])
        ids=np.arange(n,n+ndpn*len(xs)).reshape(-1,ndpn);n+=ndpn*len(xs)
        nodes[b['id']]={'x':xs,'dofs':ids}
    coil_dofs={c['id']:n+i for i,c in enumerate(model['coils'])};n+=len(coil_dofs)
    K=sparse.lil_matrix((n,n));f=np.zeros(n);elems=[];weightitems=[];external=[]
    factor=model['loading']['factor'];sw=model['loading']['self_weight']
    def vd(bid,x):
        b=nodes[bid];i=int(np.argmin(abs(b['x']-x)))
        if abs(b['x'][i]-x)>1e-6:raise ModelError('A load/connection missed its beam mesh node.')
        return int(b['dofs'][i,0])
    for b in model['beams']:
        nb=nodes[b['id']];W=0.;Wx=0.
        for i,(xa,xb) in enumerate(zip(nb['x'][:-1],nb['x'][1:])):
            L=xb-xa;pp=[];area_int=0.
            for t,w in zip(GROOT,GWEIGHT):
                xx=(xa+xb)/2+t*L/2
                try:s=g.props(b['id'],xx,shear=analysis['timoshenko'],coupled=coupled)
                except ModelError as exc:raise ModelError(f"{b['name']} at x={xx:.4f}: {exc}") from exc
                pp.append((w*L/2,xx-xa,s));area_int+=w*L/2*s.A
            # Also validate actual minimum sections at both ends, not only quadrature points.
            for xx in [xa+min(L*1e-6,1e-7),xb-min(L*1e-6,1e-7)]:g.props(b['id'],xx)
            wi=mat['density']*area_int;W+=wi;Wx+=wi*(xa+xb)/2
            q=-(wi/L)*factor if sw else 0.
            for load in model.get('loads',[]):
                if load['beam']==b['id'] and load['kind']=='Uniform' and xa>=load['x']-1e-8 and xb<=load['end']+1e-8:
                    q+=load['value']/(load['end']-load['x'])*factor
            formulation=coupled_element_flexibility if coupled else element_flexibility
            ke,fe,J,H=formulation(L,E,G,pp,analysis['timoshenko'],q)
            ids=nb['dofs'][i:i+2].flatten()
            for j,a in enumerate(ids):
                f[a]+=fe[j]
                for k,bb in enumerate(ids):K[a,bb]+=ke[j,k]
            elems.append(Element(b['id'],float(xa),float(xb),ids,ke,fe,float(q),pp,coupled))
        weightitems.append({'member':b['id'],'name':b['name'],'weight':W,'x':Wx/W if W else (b['x']+b['length']/2),'included':sw})
    for load in model.get('loads',[]):
        if load['kind']=='Point':
            value=load['value']*factor;f[vd(load['beam'],load['x'])]+=value
            external.append({'beam':load['beam'],'x':load['x'],'F':value,'kind':'Additional load','label':load['name']})
    share=1/model['loading']['frames'] if model['loading']['equal_frames'] else model['loading']['frame_share']
    per_frame=model['loading']['coil_weight']*share
    weightshare=sum(c.get('share',1) for c in model['coils'])
    coils=[]
    for c in model['coils']:
        W=per_frame*c.get('share',1)/weightshare if weightshare else 0.
        f[coil_dofs[c['id']]]-=W*factor
        coils.append({**c,'weight':W,'applied_weight':W*factor})
    rods=[]
    for r in model['rods']:
        ya,yn,L=rod_geometry(r,g);a=thread_area(r['diameter'],r['tpi']);rm=model['materials']['rod']
        volume=math.pi*r['diameter']**2/4*(yn-ya);W=volume*rm['density']
        rr={**r,'weld_y_value':ya,'nut_y_value':yn,'effective_length':L,'At':a,'k':rm['E']*a/L,'weight':W};rods.append(rr)
        if sw:
            f[vd(r['weld'],r['x'])]-=W*factor
            external.append({'beam':r['weld'],'x':r['x'],'F':-W*factor,'kind':'Rod self-weight','label':r['id']+' weight'})
        rod_rect=box(r['x']-r['diameter']/2,ya,r['x']+r['diameter']/2,yn)
        for c in model['coils']:
            if rod_rect.intersection(Point(c['x'],c['y']).buffer(c['r'],quad_segs=64)).area>1e-6:
                raise ModelError(r['name']+' intersects '+c['name']+'. Move the rod or coil.')
    rows=[];meta=[];ks=[];gaps=[]
    ordered_pins=sorted(model['pins'],key=lambda p:p['x'])
    reference_pins=[ordered_pins[0],ordered_pins[-1]] if model['loading']['equal_reactions'] else ordered_pins
    fixed_vertical={vd(p['beam'],p['x']) for p in reference_pins}
    ck=0. # Bearing is an exact inequality in the QP, not a penalty spring.
    def add(terms,kind,label,x,gap0,k,**kw):
        # Two prescribed zero elevations already satisfy this contact. Its
        # zero force removes a redundant constraint and fixes the otherwise
        # indeterminate sharing of coincident support reactions.
        if kind=='beam_contact' and all(dof in fixed_vertical for dof,value in terms):return
        rows.append(terms);ks.append(k);gaps.append(gap0)
        meta.append({'kind':kind,'label':label,'x':float(x),'initial_gap':float(gap0),'k':float(k),**kw})
    # Coil contacts: choose the closest actual remaining surface on each side.
    for c in coils:
        lower=[];upper=[]
        for b in model['beams']:
            if b['x']-1e-8<=c['x']<=b['x']+b['length']+1e-8:
                levels=g.levels_at(b['id'],c['x'])
                for a,z in levels:
                    if z<=c['y']-c['r']+1e-7:lower.append((z,b['id']))
                    if a>=c['y']+c['r']-1e-7:upper.append((a,b['id']))
        for side,candidates in [('lower',lower),('upper',upper)]:
            chosen=c.get(side,'Auto')
            if chosen=='None':continue
            if chosen!='Auto':candidates=[x for x in candidates if x[1]==chosen]
            if not candidates:
                if chosen not in ['Auto','None']:raise ModelError(c['name']+': selected '+side+' beam has no valid bearing face at this coil.')
                if side=='lower' and c['applied_weight']>0:raise ModelError(c['name']+': no lower bearing surface. Change its position or add a supporting beam.')
                continue
            surface,bid=(max(candidates) if side=='lower' else min(candidates))
            bc=vd(bid,c['x']);tc=coil_dofs[c['id']]
            if side=='lower':terms=[(tc,1.),(bc,-1.)];gap0=c['y']-c['r']-surface
            else:terms=[(bc,1.),(tc,-1.)];gap0=surface-c['y']-c['r']
            add(terms,'coil_'+side,c['id'],c['x'],max(0.,gap0),ck,beam=bid,coil=c['id'],surface_y=surface)
    # A rod pulls its welded beam upward and its nut-bearing beam downward.
    for r in rods:
        add([(vd(r['weld'],r['x']),1.),(vd(r['nut'],r['x']),-1.)],
            'rod',r['id'],r['x'],0.,r['k'],weld=r['weld'],nut=r['nut'])
    # Exact bearing inequalities at common mesh stations.
    # Candidate surfaces can close an initial gap; the closest intervening member
    # carries the load first, so no separate guessed beam/beam tie is introduced.
    for ia,a in enumerate(model['beams']):
        for b in model['beams'][ia+1:]:
            common=np.intersect1d(nodes[a['id']]['x'],nodes[b['id']]['x'])
            if len(common)<2:continue
            for ix,x in enumerate(common):
                ga=box(*g.bounds(a['id'],x)) if a.get('section_type')=='Custom properties' else g.section(a['id'],x)
                gb=box(*g.bounds(b['id'],x)) if b.get('section_type')=='Custom properties' else g.section(b['id'],x)
                if ga.intersection(gb).area>1e-7:raise ModelError(a['name']+' overlaps '+b['name']+f' at x={x:g}. Combine welded pieces into one layer or adjust offsets.')
                for low,up,lower_shape,upper_shape in [(a['id'],b['id'],ga,gb),(b['id'],a['id'],gb,ga)]:
                    gap=vertical_bearing_gap(lower_shape,upper_shape)
                    if gap is not None:
                        add([(vd(up,x),1.),(vd(low,x),-1.)],'beam_contact',low+'/'+up,x,gap,ck,lower=low,upper=up)
    B=sparse.lil_matrix((len(rows),n))
    for i,rr in enumerate(rows):
        for j,v in rr:B[i,j]=v
    pins=sorted(model['pins'],key=lambda p:p['x']);pin_dofs=[vd(p['beam'],p['x']) for p in pins]
    # Force/moment bookkeeping is taken directly from the assembled generalized
    # loads. Nodal couples from distributed loads are included in the moment.
    xd=np.zeros(n);rot=np.zeros(n,dtype=bool);vertical=np.zeros(n,dtype=bool);vertical_rot=np.zeros(n,dtype=bool)
    for bid,b in nodes.items():
        xd[b['dofs'][:,0]]=b['x'];rot[b['dofs'][:,1::2]]=True
        vertical[b['dofs'][:,0]]=True;vertical_rot[b['dofs'][:,1]]=True
    for c in coils:xd[coil_dofs[c['id']]]=c['x'];vertical[coil_dofs[c['id']]]=True
    total=-float(f[vertical].sum());moment=-float(np.dot(f[vertical],xd[vertical])+f[vertical_rot].sum())
    prescribed=np.zeros(n);equal_values=[]
    if model['loading']['equal_reactions']:
        eq=total/len(pins);unbalanced=eq*sum(p['x'] for p in pins)-moment
        if abs(unbalanced)>max(1e-4,abs(total)*span*1e-7):
            raise ModelError(f'Equal lifting reactions leave {unbalanced:,.3f} lbf·in unbalanced. The entered load resultant is not at the mean lifting-point position. Uncheck equal reactions or revise the balanced layout.')
        for p,d in zip(pins,pin_dofs):prescribed[d]+=eq;equal_values.append(eq)
        fixed=np.array([pin_dofs[0],pin_dofs[-1]],int)
    else:fixed=np.array(pin_dofs,int)
    lateral_fixed=[];references=[]
    if coupled:
        constraints=[] if analysis.get('free_lateral',True) else analysis.get('lateral_constraints',[])
        for bid,nb in nodes.items():
            affine_rows=[]
            for q in [q for q in constraints if q['beam']==bid]:
                i=int(np.argmin(abs(nb['x']-q['x'])))
                if abs(nb['x'][i]-q['x'])>1e-6:raise ModelError('A lateral restraint missed its mesh station.')
                axes=[2,3] if q['kind']=='Displacement and rotation' else [2] if q['kind']=='Displacement' else [3]
                for axis in axes:
                    dof=int(nb['dofs'][i,axis]);fixed=np.r_[fixed,dof]
                    affine_rows.append([1.,(q['x']-nb['x'][0])/span] if axis==2 else [0.,1.])
                    lateral_fixed.append({**q,'dof':dof,'component':'w' if axis==2 else 'psi'})
            # Complete only the two unloaded lateral rigid-body modes. These
            # reference conditions must develop zero physical force/moment.
            rank=np.linalg.matrix_rank(affine_rows) if affine_rows else 0
            for i in [0,len(nb['x'])-1]:
                row=[1.,(nb['x'][i]-nb['x'][0])/span]
                newrank=np.linalg.matrix_rank(affine_rows+[row])
                if newrank>rank:
                    dof=int(nb['dofs'][i,2]);references.append(dof);fixed=np.r_[fixed,dof]
                    affine_rows.append(row);rank=newrank
    return dict(model=model,g=g,nodes=nodes,elements=elems,K=K.tocsc(),f=f,prescribed=prescribed,
      B=B.tocsr(),k=np.array(ks),gap0=np.array(gaps),meta=meta,fixed=fixed,pins=pins,pin_dofs=pin_dofs,
      coils=coils,rods=rods,weights=weightitems,external=external,total=total,moment=moment,span=span,
      equal_values=equal_values,rotational=rot,lateral_fixed=lateral_fixed,lateral_references=references,
      vertical_fixed=np.array(pin_dofs if not equal_values else [pin_dofs[0],pin_dofs[-1]],int))


def _polish_qp(P,q,A,lo,hi,x,y,max_steps=250):
    """Working-set refinement of the convex QP after OSQP identifies contacts.

    Solves the equality-constrained quadratic system, then adds violated gap
    constraints or releases negative bearing multipliers. The returned state is
    accepted only if every primal, dual and stationarity condition is verified.
    This avoids relying on ADMM's stopping status for stiff beam/rod systems.
    """
    from scipy.sparse.linalg import splu
    P=P+P.T-sparse.diags(P.diagonal())
    equal=np.flatnonzero(np.isfinite(hi)&(abs(hi-lo)<1e-14))
    inequalities=np.flatnonzero(~np.isin(np.arange(len(lo)),equal))
    active=set(int(i) for i in inequalities if y[i]<-1e-9)
    seen={}
    for step in range(max_steps):
        rows=np.r_[equal,sorted(active)].astype(int);C=A[rows].tocsc()
        H=sparse.bmat([[P,-C.T],[C,None]],format='csc')
        rhs=np.r_[-q,lo[rows]]
        try:
            factor=splu(H);z=factor.solve(rhs)
            for _ in range(3):z+=factor.solve(rhs-H@z)
        except RuntimeError:return None
        xx=z[:len(q)];multipliers=z[len(q):]
        if not np.isfinite(xx).all():return None
        gaps=A@xx-lo
        candidates=[i for i in inequalities if i not in active and gaps[i]<-2e-9]
        negative=[(multipliers[j],int(i)) for j,i in enumerate(rows) if i in active and multipliers[j]<-2e-8]
        if not candidates and not negative:
            yy=np.zeros(len(lo));yy[rows]=-multipliers
            stationarity=P@xx+q+A.T@yy
            if max(abs(stationarity))>2e-5:return None
            if len(inequalities) and min(gaps[inequalities]) < -2e-9:return None
            return xx,yy,step+1
        # OSQP supplies a close working set. Single-constraint pivots avoid
        # overspecifying almost coincident contact constraints.
        signature=tuple(sorted(active));seen[signature]=seen.get(signature,0)+1
        if seen[signature]>3:return None
        if negative:
            active.remove(min(negative)[1])
        else:
            active.add(min(candidates,key=lambda i:gaps[i]))
    return None


def solve_contact(a):
    """Convex QP with exact unilateral bearing and finite-stiffness tie rods.

    Extra e_j >= 0 represent rod extension. B_rod*d + e_j >= 0,
    energy 1/2*k_j*e_j². Contact gaps >= 0 have no penalty stiffness.
    """
    import osqp
    K0=a['K'];n=K0.shape[0];f=a['f']+a['prescribed'];B=a['B'];g0=a['gap0']
    rodrows=[i for i,q in enumerate(a['meta']) if q['kind']=='rod'];nr=len(rodrows)
    eps=float(a['model']['analysis'].get('regularization',1e-6))
    base=K0+sparse.eye(n,format='csc')*eps
    P=sparse.block_diag([base,sparse.diags([a['k'][i] for i in rodrows])],format='csc') if nr else base
    extra=sparse.lil_matrix((len(a['meta']),nr))
    for j,i in enumerate(rodrows):extra[i,j]=1.
    A1=sparse.hstack([B,extra.tocsr()],format='csc')
    supports=sparse.lil_matrix((len(a['fixed']),n+nr))
    for i,d in enumerate(a['fixed']):supports[i,d]=1.
    parts=[A1,supports.tocsc()]
    lower=[-g0,np.zeros(len(a['fixed']))];upper=[np.full(len(g0),np.inf),np.zeros(len(a['fixed']))]
    if nr:
        ext=sparse.hstack([sparse.csc_matrix((nr,n)),sparse.eye(nr)],format='csc')
        parts.append(ext);lower.append(np.zeros(nr));upper.append(np.full(nr,np.inf))
    A=sparse.vstack(parts,format='csc');lo=np.concatenate(lower);hi=np.concatenate(upper)
    scaling=np.ones(n+nr)
    for node in a['nodes'].values():scaling[node['dofs'][:,1::2]]=1/max(a['span'],1.)
    D=sparse.diags(scaling);force_scale=max(100.,abs(a['total']))
    Ps=sparse.triu(D@P@D/force_scale,format='csc');As=A@D
    qs=np.r_[-f,np.zeros(nr)]*scaling/force_scale
    solver=osqp.OSQP()
    solver.setup(P=Ps,q=qs,A=As.tocsc(),l=lo,u=hi,verbose=False,
       eps_abs=1e-6,eps_rel=1e-6,max_iter=20000,polishing=True,
       polish_refine_iter=10,adaptive_rho_interval=50,check_termination=25)
    result=solver.solve(raise_error=False)
    polished=None
    if result.info.status_val in [1,2,7] and result.x is not None:
        polished=_polish_qp(Ps,qs,As.tocsc(),lo,hi,result.x,result.y)
    if polished is not None:
        result.x,result.y,polish_steps=polished
        status='Verified working-set solution'
    elif result.info.status_val in [1,2]:
        polish_steps=0;status=result.info.status
    else:
        raise ModelError('The current layout has no converged stable contact solution ('+result.info.status+'). Check supports, coil bearings and rod attachments.')
    xx=result.x*scaling;full=xx[:n]
    rawlam=-result.y[:len(g0)]*force_scale
    lam=np.maximum(rawlam,0.)
    gap=g0+B@full
    residual=K0@full-f-B.T@lam
    ground=eps*full
    free=np.setdiff1d(np.arange(n),a['fixed']);freeerr=float(abs(residual[free]).max())
    normload=max(1.,abs(a['total']))
    if freeerr>max(.02,normload*3e-5):raise ModelError(f'Contact solution residual is {freeerr:.3g}; the current numerical solution is not accepted. Adjust mesh/geometry.')
    contactrows=[i for i in range(len(gap)) if i not in rodrows]
    if contactrows and min(gap[contactrows]) < -1e-5:raise ModelError('Contact penetration exceeds the solver tolerance; this result is not accepted.')
    if contactrows and max(abs(lam[contactrows]*gap[contactrows]))>max(.001,normload*1e-6):raise ModelError('Contact force/gap complementarity failed; this result is not accepted.')
    if rodrows and max(abs(lam[rodrows]-a['k'][rodrows]*np.maximum(-gap[rodrows],0.)))>max(.01,normload*1e-5):raise ModelError('Rod force/extension compatibility failed; this result is not accepted.')
    if max(abs(ground))>max(.001,normload*1e-6):raise ModelError('A member has an unsupported mechanism. Add its missing physical contact or connection.')
    if a['equal_values'] and max(abs(residual[a['vertical_fixed']]))>max(.005,normload*1e-5):raise ModelError('Equal reactions require an additional support force in this layout. Use calculated reactions.')
    if a['lateral_references'] and max(abs(residual[a['lateral_references']]))>max(.005,normload*1e-5):
        raise ModelError('The lateral reference conditions carry a physical reaction. Review the lateral restraints.')
    history=[{'iteration':int(result.info.iter),'residual':freeerr,'active':int((lam>max(1e-5,normload*1e-8)).sum()),
              'energy':float(.5*xx@P@xx-np.dot(f,full)),'status':status,'primal_residual':float(result.info.prim_res),
              'dual_residual':float(result.info.dual_res),'polished':polish_steps or int(result.info.status_polish)}]
    return full,gap,lam,residual,history,freeerr,float(max(abs(ground)))

def recover_element(e,u,g,model,s):
    """Force-based recovery integrates curvature and shear (not cubic interpolation)."""
    if e.coupled:return recover_coupled_element(e,u,g,model,s)
    s=float(s);end=e.K@u[e.dofs]-e.f;V0,M0=end[0],end[1]
    V=V0+e.q*s;M=-M0+V0*s+e.q*s*s/2
    E=model['materials']['frame']['E'];nu=model['materials']['frame']['nu'];G=E/(2*(1+nu))
    a=0.;bb=0.;sh=0.
    if s>0:
        for t,w in zip(GROOT,GWEIGHT):
            xx=s/2*(1+t);ss=g.props(e.beam,e.x0+xx,shear=model['analysis']['timoshenko'])
            mm=-M0+V0*xx+e.q*xx*xx/2
            vv=V0+e.q*xx
            a+=s/2*w*mm/(E*ss.I);bb+=s/2*w*(s-xx)*mm/(E*ss.I)
            if model['analysis']['timoshenko']:sh+=s/2*w*vv/(G*ss.As)
    theta=u[e.dofs[1]]+a;v=u[e.dofs[0]]+u[e.dofs[1]]*s+bb-sh
    # At component-length changes use the section on this element's own side.
    px=min(max(e.x0+s,e.x0+min(e.L*1e-7,1e-8)),e.x1-min(e.L*1e-7,1e-8))
    sec=g.props(e.beam,px)
    st=-M*sec.ctop/sec.I;sb=M*sec.cbottom/sec.I
    return {'x':e.x0+s,'V':float(V),'M':float(M),'v':float(v),'theta':float(theta),
       'stress_top':float(st),'stress_bottom':float(sb),'stress':float(max(abs(st),abs(sb))),
       'A':sec.A,'I':sec.I,'yc':sec.yc,'ctop':sec.ctop,'cbottom':sec.cbottom,
       'v_reference':float(u[e.dofs[0]]),'rotation_term':float(u[e.dofs[1]]*s),'bending_term':float(bb),'shear_term':float(-sh),
       'element_start':e.x0,'element_end':e.x1,'side':'right' if s<e.L/2 else 'left'}


def recover_coupled_element(e,u,g,model,s):
    s=float(s);end=e.K@u[e.dofs]-e.f
    V=np.array([end[0]+e.q*s,end[2]])
    M=np.array([-end[1]+end[0]*s+e.q*s*s/2,-end[3]+end[2]*s])
    mat=model['materials']['frame'];E=mat['E'];G=E/(2*(1+mat['nu']))
    shear=model['analysis']['timoshenko'];turn=np.zeros(2);bend=np.zeros(2);sh=np.zeros(2)
    if s>0:
        for root,weight in zip(GROOT,GWEIGHT):
            x=s/2*(1+root);sec=g.props(e.beam,e.x0+x,shear=shear,coupled=True)
            mm=np.array([-end[1]+end[0]*x+e.q*x*x/2,-end[3]+end[2]*x])
            curvature=bending_compliance(sec,E)@mm
            turn+=s/2*weight*curvature;bend+=s/2*weight*(s-x)*curvature
            if shear:sh+=s/2*weight*np.array([(end[0]+e.q*x)/(G*sec.As),end[2]/(G*sec.Asz)])
    origin=u[e.dofs[[0,2]]];rotation=u[e.dofs[[1,3]]]
    displacement=origin+rotation*s+bend-sh;angle=rotation+turn
    px=min(max(e.x0+s,e.x0+min(e.L*1e-7,1e-8)),e.x1-min(e.L*1e-7,1e-8))
    sec=g.props(e.beam,px,coupled=True)
    if g.beams[e.beam].get('section_type')=='Custom properties':
        vertices=[(z,y) for z in [sec.zmin,sec.zmax] for y in [sec.ymin,sec.ymax]]
    else:
        vertices=[(z,y) for polygon in polygons(g.section(e.beam,px)) for ring in [polygon.exterior,*polygon.interiors] for z,y in ring.coords]
    coefficients=bending_compliance(sec,1.)@M
    stresses=[-coefficients@np.array([y-sec.yc,z-sec.zc]) for z,y in vertices]
    critical=int(np.argmax(np.abs(stresses)))
    top=[v for (z,y),v in zip(vertices,stresses) if abs(y-sec.ymax)<1e-7]
    bottom=[v for (z,y),v in zip(vertices,stresses) if abs(y-sec.ymin)<1e-7]
    return {'x':e.x0+s,'V':float(V[0]),'M':float(M[0]),'v':float(displacement[0]),'theta':float(angle[0]),
       'lateral_V':float(V[1]),'lateral_M':float(M[1]),'w':float(displacement[1]),'psi':float(angle[1]),
       'stress_top':float(max(top,key=abs)),'stress_bottom':float(max(bottom,key=abs)),
       'stress':float(abs(stresses[critical])),'stress_signed':float(stresses[critical]),
       'stress_min':float(min(stresses)),'stress_max':float(max(stresses)),
       'critical_z':vertices[critical][0]-sec.zc,'critical_y':vertices[critical][1]-sec.yc,
       'A':sec.A,'I':sec.I,'Iyy':sec.Iyy,'Izy':sec.Izy,'yc':sec.yc,'ctop':sec.ctop,'cbottom':sec.cbottom,
       'v_reference':float(origin[0]),'rotation_term':float(rotation[0]*s),'bending_term':float(bend[0]),'shear_term':float(-sh[0]),
       'w_reference':float(origin[1]),'lateral_rotation_term':float(rotation[1]*s),'lateral_bending_term':float(bend[1]),'lateral_shear_term':float(-sh[1]),
       'element_start':e.x0,'element_end':e.x1,'side':'right' if s<e.L/2 else 'left'}


def solve_frame(model,elements_per_span=None,refine_peaks=True):
    model=copy.deepcopy(model);a=assemble(model,elements_per_span)
    u,gap,lam,res,history,err,ground=solve_contact(a)
    g=a['g'];forces=[];pointloads=list(a['external'])
    for meta,ff,gg in zip(a['meta'],lam,gap):
        q={**meta,'force':float(ff),'gap':float(gg),'active':bool(ff>max(1e-5,abs(a['total'])*1e-8))};forces.append(q)
        if q['kind']=='coil_lower':pointloads.append({'beam':q['beam'],'x':q['x'],'F':-ff,'kind':'Coil contact','label':q['label']+' lower'})
        elif q['kind']=='coil_upper':pointloads.append({'beam':q['beam'],'x':q['x'],'F':ff,'kind':'Coil contact','label':q['label']+' upper'})
        elif q['kind']=='rod':
            pointloads.extend([{'beam':q['weld'],'x':q['x'],'F':ff,'kind':'Rod tension','label':q['label']},
                              {'beam':q['nut'],'x':q['x'],'F':-ff,'kind':'Rod tension','label':q['label']}])
        else:
            pointloads.extend([{'beam':q['lower'],'x':q['x'],'F':-ff,'kind':'Beam bearing','label':'Bearing'},
                              {'beam':q['upper'],'x':q['x'],'F':ff,'kind':'Beam bearing','label':'Bearing'}])
    reactions=[]
    for i,(p,d) in enumerate(zip(a['pins'],a['pin_dofs'])):
        rr=a['equal_values'][i] if a['equal_values'] else res[d]
        if rr < -max(.005,abs(a['total'])*1e-6):
            raise ModelError(f'Lifting hole {p["id"]} requires a downward reaction of {abs(rr):,.3f} lbf. A chain cannot provide that force in this level vertical-force model. Review lifting positions/loading or analyze the actual rigging.')
        pp={**p,'force':float(rr),'v':float(u[d])};reactions.append(pp)
        pointloads.append({'beam':p['beam'],'x':p['x'],'F':rr,'kind':'Lifting reaction','label':p['id']})
    for rr in a['rods']:
        link=next(q for q in forces if q['kind']=='rod' and q['label']==rr['id'])
        rr.update(tension=link['force'],extension=link['force']/rr['k'],stress=link['force']/rr['At'])
    results={};balance=[];maxrecovery=0.
    for b in model['beams']:
        ee=[e for e in a['elements'] if e.beam==b['id']];samples=[]
        for e in ee:
            ss=[recover_element(e,u,g,model,s) for s in np.linspace(0,e.L,5)]
            maxrecovery=max(maxrecovery,abs(ss[-1]['v']-u[e.dofs[len(e.dofs)//2]]))
            if e.coupled:maxrecovery=max(maxrecovery,abs(ss[-1]['w']-u[e.dofs[6]]))
            candidates=[e.L*i/4 for i in range(5)]
            if abs(e.q)>1e-12:
                s0=-(e.K@u[e.dofs]-e.f)[0]/e.q
                if 0<s0<e.L:candidates.append(s0)
            # Refine only candidate sampled extrema, preserving interactive speed.
            if refine_peaks:
                for quantity,absolute in [('stress',False),('v',True)]+([('w',True)] if e.coupled else []):
                    yy=[abs(x[quantity]) if absolute else x[quantity] for x in ss]
                    for i in range(1,4):
                        if yy[i]>=yy[i-1] and yy[i]>=yy[i+1] and max(yy)-min(yy)>1e-10:
                            def target(s):
                                r=recover_element(e,u,g,model,s)[quantity]
                                return -abs(r) if absolute else -r
                            z=minimize_scalar(target,bounds=(e.L*(i-1)/4,e.L*(i+1)/4),method='bounded',options={'xatol':max(1e-8,e.L*1e-5)})
                            if z.success:candidates.append(float(z.x))
            samples.extend(recover_element(e,u,g,model,s) for s in sorted(set(candidates)))
        peakstress=max(samples,key=lambda x:x['stress']);peakM=max(samples,key=lambda x:abs(x['M']));peakv=max(samples,key=lambda x:abs(x['v']))
        ll=[q for q in pointloads if q['beam']==b['id']]
        fy=sum(q['F'] for q in ll)+sum(e.q*e.L for e in ee)
        mz=sum(q['F']*q['x'] for q in ll)+sum(e.q*e.L*(e.x0+e.x1)/2 for e in ee)
        balance.append({'beam':b['id'],'force_residual':float(fy),'moment_residual':float(mz)})
        # Contributions to the cut's bending moment use actual solved point forces.
        x=peakstress['x'];terms=[]
        for kind in sorted({q['kind'] for q in ll}):
            terms.append({'name':kind,'value':sum(q['F']*(x-q['x']) for q in ll if q['kind']==kind and q['x']<=x+1e-8)})
        distributed=0.
        for e in ee:
            h=max(0,min(x,e.x1)-e.x0)
            distributed+=e.q*(h*(x-e.x0)-h*h/2)
        terms.append({'name':'Distributed gravity / loads','value':distributed})
        results[b['id']]={'beam':b,'samples':samples,'peak_stress':peakstress,'peak_moment':peakM,'peak_deflection':peakv,
                         'point_loads':ll,'moment_terms':terms}
        if model['analysis'].get('coupled_bending'):
            results[b['id']].update(peak_lateral_deflection=max(samples,key=lambda x:abs(x['w'])),
                                   peak_lateral_moment=max(samples,key=lambda x:abs(x['lateral_M'])))
    total=a['total'];rrsum=sum(p['force'] for p in reactions)
    checks={'total_downward':total,'coil_load_per_frame':sum(c['weight'] for c in a['coils']),
      'reaction_sum':rrsum,'vertical_residual':rrsum-total,
      'moment_residual':sum(p['force']*p['x'] for p in reactions)-a['moment'],
      'free_residual':err,'stabilizer_max_force':ground,'max_contact_penetration':max([max(0,-q['gap']) for q in forces if q['kind']!='rod'] or [0]),
      'max_recovery_mismatch':maxrecovery,'beam_equilibrium':balance,'dofs':len(u),'elements':len(a['elements']),
      'iterations':history[-1]['iteration'],'mesh_divisions':int(elements_per_span or model['analysis']['elements'])}
    free_mask=np.ones(len(u),dtype=bool);free_mask[a['fixed']]=False
    checks['free_force_residual']=float(max(abs(res[free_mask&~a['rotational']]),default=0.))
    checks['free_moment_residual']=float(max(abs(res[free_mask&a['rotational']]),default=0.))
    tol=max(.02,abs(total)*3e-5)
    if abs(checks['vertical_residual'])>tol or abs(checks['moment_residual'])>tol*a['span']:raise ModelError('Global force/moment balance failed. Inspect supports and contact connections.')
    coupled=model['analysis'].get('coupled_bending',False)
    mode='Coupled vertical and lateral bending' if coupled else 'Simplified planar bending'
    notes=[mode+'. Local notch, weld, lug, block and tube-wall strength require separate assessment.',
       'Coil cutouts modify the section and stiffness; circular geometry is polygonized for custom curved outlines.',
       'Coils are rigid vertical spacers; bearing is frictionless and represented by vertical resultants.',
       'Rod free-length auto values are geometric estimates. Override them to match the actual welded attachment and nut seat.']
    if model['materials']['rod']['name']=='ASTM A193 B7' and model['rods']:
        notes.append('B7 strengths describe supplied heat-treated rod. They do not establish the strength of its welded attachment/heat-affected region.')
    lateral_reactions=[{k:v for k,v in q.items() if k!='dof'}|{'reaction':float(res[q['dof']])} for q in a['lateral_fixed']]
    checks['bending_mode']=mode
    if coupled:
        notes.append('Lateral contacts and tie rods retain the vertical-only load path. Lateral bending uses centroidal force resultants and excludes eccentric-load torsion.')
        notes.append('Free lateral movement is reported relative to each member end-to-end reference chord.' if model['analysis'].get('free_lateral',True) else 'User-entered lateral restraints hold the selected lateral displacement or bending rotation at zero. Remaining unloaded rigid-body modes use zero-reaction reference conditions.')
        if any(b.get('section_type')=='Custom properties' for b in model['beams']):
            notes.append('Manual section stresses use the bounding rectangle defined by the entered centroid-to-edge distances. Draw the actual section to locate exact material-fiber peaks.')
    return Solution(model,g,a['nodes'],a['elements'],u,forces,reactions,results,a['weights'],pointloads,a['coils'],a['rods'],checks,history,a['K'],a['B'],a['f'],notes,lateral_reactions)


def critical_samples(result,quantity):
    pp=result['samples'];vals=[float(x[quantity]) for x in pp];idx={0,len(pp)-1,int(np.argmax(vals)),int(np.argmin(vals))}
    for i in range(1,len(pp)-1):
        if pp[i-1]['x']==pp[i]['x'] or pp[i+1]['x']==pp[i]['x']:continue
        if (vals[i]>vals[i-1] and vals[i]>vals[i+1]) or (vals[i]<vals[i-1] and vals[i]<vals[i+1]):idx.add(i)
    return [pp[i] for i in sorted(idx)]


def mesh_check(solution):
    n=solution.checks['mesh_divisions']
    if n>=400:raise ModelError('This design already uses the maximum 400 mesh divisions. A finer comparison is not available in this app.')
    other=solve_frame(solution.model,min(n*2,400),refine_peaks=True)
    rows=[]
    for bid,a in solution.beam_results.items():
        b=other.beam_results[bid]
        for name,key in [('Peak stress','peak_stress'),('Peak movement','peak_deflection')]:
            field='stress' if key=='peak_stress' else 'v';aa=abs(a[key][field]);bb=abs(b[key][field])
            rows.append({'beam':bid,'quantity':name,'current':aa,'refined':bb,'change_percent':100*(bb-aa)/max(bb,1e-12)})
        if solution.model['analysis'].get('coupled_bending'):
            aa=abs(a['peak_lateral_deflection']['w']);bb=abs(b['peak_lateral_deflection']['w'])
            rows.append({'beam':bid,'quantity':'Peak lateral movement','current':aa,'refined':bb,'change_percent':100*(bb-aa)/max(bb,1e-12)})
    for r in solution.rods:
        rr=next(q for q in other.rods if q['id']==r['id']);aa=r['tension'];bb=rr['tension']
        rows.append({'beam':r['id'],'quantity':'Rod tension','current':aa,'refined':bb,'change_percent':100*(bb-aa)/max(abs(bb),1e-12)})
    return rows
