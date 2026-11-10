"""Section geometry for Frame Load Analyzer. All distances in inches.

Section plane is (z, y). I is integral((y-yc)^2 dA), about the
horizontal centroidal bending axis (the user's section Ixx).
Curves are polygonized with a documented, configurable angular resolution.
"""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
import json, math
import numpy as np
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection, Point, box, LineString
from shapely.ops import unary_union
from shapely.affinity import translate, rotate, scale
from shapely.geometry.polygon import orient

class ModelError(ValueError):
    pass

@dataclass(frozen=True)
class Section:
    A: float
    yc: float
    zc: float
    I: float
    Iyy: float
    Izy: float
    ymin: float
    ymax: float
    zmin: float
    zmax: float
    As: float = 0.
    @property
    def ctop(self): return self.ymax-self.yc
    @property
    def cbottom(self): return self.yc-self.ymin
    @property
    def Stop(self): return self.I/max(self.ctop,1e-14)
    @property
    def Sbottom(self): return self.I/max(self.cbottom,1e-14)
    @property
    def S(self): return min(self.Stop,self.Sbottom)
    def data(self):
        return {**self.__dict__,'ctop':self.ctop,'cbottom':self.cbottom,
                'Stop':self.Stop,'Sbottom':self.Sbottom,'S':self.S}

def polygons(g):
    if isinstance(g, Polygon): return [g]
    if hasattr(g,'geoms'):
        return [p for a in g.geoms for p in polygons(a)]
    return []

@lru_cache(maxsize=2048)
def vertical_bearing_gap(lower,upper):
    """First vertical closure between two sections with separated y envelopes.

    Faces must overlap in section depth z. Using only envelope y bounds can
    falsely seat a narrow upper section on an angle's web located to its side.
    Polygon faces are piecewise linear, so their minimum vertical separation
    occurs at a z vertex or at the limit of a vertex interval.
    """
    z0=max(lower.bounds[0],upper.bounds[0]);z1=min(lower.bounds[2],upper.bounds[2])
    if z1-z0<=1e-9:return None
    levels={z0,z1}
    for region in [lower,upper]:
        for p in polygons(region):
            for ring in [p.exterior,*p.interiors]:levels.update(z for z,y in ring.coords if z0<z<z1)
    levels=sorted(levels);probes=list(levels)
    for a,b in zip(levels[:-1],levels[1:]):
        h=b-a
        if h>1e-10:probes.extend([a+h*1e-7,(a+b)/2,b-h*1e-7])
    y0=min(lower.bounds[1],upper.bounds[1])-1;y1=max(lower.bounds[3],upper.bounds[3])+1
    gaps=[]
    for z in probes:
        line=LineString([(z,y0),(z,y1)]);a=lower.intersection(line);b=upper.intersection(line)
        if not a.is_empty and not b.is_empty:gaps.append(b.bounds[1]-a.bounds[3])
    return max(0.,min(gaps)) if gaps else None

def ring_integrals(coords):
    a=np.asarray(coords,dtype=float)
    x,y=a[:-1,0],a[:-1,1];xx,yy=a[1:,0],a[1:,1]
    cross=x*yy-xx*y
    return np.array([cross.sum()/2,((x+xx)*cross).sum()/6,
        ((y+yy)*cross).sum()/6,((y*y+y*yy+yy*yy)*cross).sum()/12,
        ((x*x+x*xx+xx*xx)*cross).sum()/12,
        ((2*x*y+x*yy+xx*y+2*xx*yy)*cross).sum()/24])

@lru_cache(maxsize=2048)
def section_properties(g, with_shear=False, allow_sliver=False):
    # Shapely geometries are immutable/hashable and Section is frozen. Reuse
    # identical material sections at different beam stations and reruns. The
    # exact geometry is the key: no rounding or stiffness approximation.
    if g.is_empty or g.area<=1e-10:
        raise ModelError('A coil cut removes the complete section. Change the beam or coil position/dimensions.')
    # Shift first, to avoid cancellation for a small section far from the datum.
    ox,oy=g.centroid.x,g.centroid.y
    local=translate(g,xoff=-ox,yoff=-oy)
    vals=np.zeros(6)
    for pp in polygons(local):
        p=orient(pp,sign=1)
        vals+=ring_integrals(p.exterior.coords)
        for hole in p.interiors: vals+=ring_integrals(hole.coords)
    A,Qz,Qy,I0,J0,P0=vals
    zc,yc=Qz/A,Qy/A
    I=I0-A*yc*yc;Iyy=J0-A*zc*zc;Izy=P0-A*yc*zc
    # Removed slivers can have a valid area but effectively zero own inertia.
    # They are allowed only for subtraction arithmetic in the worksheet; an
    # actual remaining beam section always retains the positive-I guard.
    if not np.isfinite(I) or I < -1e-12 or (I<=1e-12 and not allow_sliver):
        raise ModelError('The section has zero/invalid bending inertia.')
    I=max(0.,I)
    z0,y0,z1,y1=g.bounds
    s=Section(float(A),float(yc+oy),float(zc+ox),float(I),float(Iyy),float(Izy),y0,y1,z0,z1)
    if with_shear:
        av=effective_shear_area(g,s)
        s=Section(**{**s.__dict__,'As':av})
    return s

def effective_shear_area(g,s):
    """Jourawski energy estimate: As=I²/integral(Q(y)²/b(y) dy).

    Horizontal shear is treated as uniform over the material width b(y).
    This is an approximation for open/thin-walled/built-up sections.
    """
    levels=[s.ymin,s.ymax]
    for p in polygons(g):
        levels.extend(y for _,y in p.exterior.coords)
        for h in p.interiors:levels.extend(y for _,y in h.coords)
    # Each interval has a consistent polygon topology. Three Gauss points
    # exactly recover 5/6*A for a solid rectangle.
    levels=np.unique(np.round(np.r_[levels,np.linspace(s.ymin,s.ymax,13)],10))
    roots,weights=np.polynomial.legendre.leggauss(3)
    integ=0.;margin=max(s.zmax-s.zmin,1.)
    for lo,hi in zip(levels[:-1],levels[1:]):
        if hi-lo<1e-11:continue
        for t,w in zip(roots,weights):
            y=(lo+hi)/2+t*(hi-lo)/2
            width=g.intersection(LineString([(s.zmin-margin,y),(s.zmax+margin,y)])).length
            above=g.intersection(box(s.zmin-margin,y,s.zmax+margin,s.ymax+margin))
            Q=above.area*(above.centroid.y-s.yc) if not above.is_empty else 0.
            if width<1e-12:
                if abs(Q)>1e-8:
                    raise ModelError('A cut leaves disconnected material above/below a gap. This section needs a local shell/solid model.')
                continue
            integ+=(hi-lo)/2*w*Q*Q/width
    if integ<=0:raise ModelError('Could not determine the section shear area.')
    return float(min(s.A,s.I*s.I/integ))

def arc_points(center,r,a0,a1,n=128):
    count=max(3,int(abs(a1-a0)/(2*math.pi)*n)+1)
    ts=np.linspace(a0,a1,count)
    return [(center[0]+r*math.cos(t),center[1]+r*math.sin(t)) for t in ts]

def edge_arc(a,b,r,clockwise=False,large=False,n=128):
    a=np.array(a,float);b=np.array(b,float);d=np.linalg.norm(b-a)
    if d<1e-10:return [tuple(b)]
    if r<d/2-1e-9:raise ModelError('Arc radius must be at least half its chord length.')
    mid=(a+b)/2;perp=np.array([-(b-a)[1],(b-a)[0]])/d
    off=math.sqrt(max(0,r*r-d*d/4))
    for c in [mid+perp*off,mid-perp*off]:
        t0=math.atan2(a[1]-c[1],a[0]-c[0]);t1=math.atan2(b[1]-c[1],b[0]-c[0])
        dt=(t1-t0)%(2*math.pi)
        if clockwise:dt=dt-2*math.pi
        if (abs(dt)>math.pi+1e-8)==bool(large) or abs(abs(dt)-math.pi)<1e-8:
            return arc_points(c,r,t0,t0+dt,n)[1:]
    raise ModelError('Could not construct this arc.')

def shape_polygon(shape,resolution=128):
    typ=shape.get('type','polygon')
    if typ=='rectangle':
        x,y,w,h=[float(shape.get(k,0)) for k in ['x','y','w','h']]
        if min(w,h)<=0:raise ModelError('Rectangle width and height must be positive.')
        rr=max(0,min(float(shape.get('radius',0)),w/2,h/2))
        g=box(x,y,x+w,y+h) if rr==0 else box(x+rr,y+rr,x+w-rr,y+h-rr).buffer(rr,quad_segs=max(8,resolution//4))
    elif typ=='circle':
        r=float(shape.get('r',0))
        if r<=0:raise ModelError('Circle radius must be positive.')
        g=Point(float(shape.get('x',0)),float(shape.get('y',0))).buffer(r,quad_segs=max(12,resolution//4))
    elif typ=='arc':
        r=float(shape.get('r',0));a0=math.radians(float(shape.get('a0',0)));a1=math.radians(float(shape.get('a1',90)))
        if r<=0 or abs(a1-a0)<1e-8:raise ModelError('Arc needs a positive radius and a nonzero angle.')
        c=(float(shape.get('x',0)),float(shape.get('y',0)))
        pts=arc_points(c,r,a0,a1,resolution)
        if shape.get('close','sector')=='sector':pts=[c]+pts
        g=Polygon(pts)
    elif typ=='polygon':
        pp=shape.get('points',[])
        if len(pp)<3:raise ModelError('Close the outline with at least three vertices.')
        pts=[]
        for i,a in enumerate(pp):
            p=(float(a[0]),float(a[1]));pts.append(p)
            arcs=shape.get('arcs',{})
            arc=arcs.get(str(i))
            if arc:
                b=pp[(i+1)%len(pp)]
                pts.extend(edge_arc(p,b,float(arc['r']),arc.get('clockwise',False),arc.get('large',False),resolution))
        g=Polygon(pts)
    else:raise ModelError('Unknown drawing shape: '+str(typ))
    if not g.is_valid:raise ModelError('A custom outline crosses itself or contains an invalid hole. Edit the drawing.')
    center=((g.bounds[0]+g.bounds[2])/2,(g.bounds[1]+g.bounds[3])/2)
    if shape.get('mirror',False):g=scale(g,xfact=-1,yfact=1,origin=center)
    if abs(float(shape.get('rotation',0)))>1e-12:
        g=rotate(g,float(shape['rotation']),origin=center)
    return g

def drawing_geometry(shapes,resolution=128):
    g=GeometryCollection()
    for s in shapes:
        pp=shape_polygon(s,resolution)
        g=g.difference(pp) if s.get('op','add')=='subtract' else g.union(pp)
    if g.is_empty:raise ModelError('Draw at least one closed material region.')
    if not g.is_valid:raise ModelError('The section drawing is not valid.')
    return g

@lru_cache(maxsize=2048)
def _profile_cached(spec_json,resolution):
    c=json.loads(spec_json);typ=c.get('shape','Angle')
    h=float(c.get('h',3));w=float(c.get('w',3));t=float(c.get('t',.375))
    if typ=='Custom draw':
        g=drawing_geometry(c.get('drawing',[]),resolution)
    else:
        if min(h,w,t)<=0:raise ModelError('Section dimensions must be positive.')
        if typ=='Angle':
            if t>=min(h,w):raise ModelError('Angle thickness must be smaller than height and width.')
            g=unary_union([box(0,0,w,t),box(0,t,t,h)])
        elif typ=='C-channel':
            if 2*t>=h or t>=w:raise ModelError('Channel needs height > 2t and width > t.')
            g=unary_union([box(0,0,w,t),box(0,h-t,w,h),box(0,t,t,h-t)])
        elif typ=='HSS':
            if 2*t>=min(h,w):raise ModelError('HSS wall must leave a positive inside width and height.')
            g=box(0,0,w,h).difference(box(t,t,w-t,h-t))
        elif typ=='Flat bar':g=box(0,0,w,h)
        else:raise ModelError('Unknown section type '+typ)
    if c.get('flip_y',False):g=scale(g,1,-1,origin=(0,0))
    if c.get('flip_z',False):g=scale(g,-1,1,origin=(0,0))
    if c.get('rotation',0):g=rotate(g,float(c['rotation']),origin=(0,0))
    # Normalize to a lower-left component datum before applying offsets.
    g=translate(g,-g.bounds[0],-g.bounds[1])
    return translate(g,float(c.get('dz',0)),float(c.get('dy',0)))

def component_profile(component,resolution=128):
    return _profile_cached(json.dumps(component,sort_keys=True),int(resolution))

class Geometry:
    def __init__(self,model):
        self.model=model;self.beams={b['id']:b for b in model['beams']}
        self.resolution=int(model.get('analysis',{}).get('curve_resolution',128))
        self._profiles={b['id']:[component_profile(c,self.resolution) for c in b['components']]
                        for b in model['beams'] if b.get('section_type')!='Custom properties'}
        self._gcache={};self._scache={}
    def active_components(self,b,x):
        for c,p in zip(b.get('components',[]),self._profiles.get(b['id'],[])):
            start=b['x']+c.get('start',0);end=start+c.get('length',b['length'])
            if start-1e-9<=x<=end+1e-9:
                yield c,translate(p,yoff=b['y'])
    def section(self,bid,x,cut=True,blocks=True):
        b=self.beams[bid]
        if b.get('section_type')=='Custom properties':raise ModelError('Manual section has no geometric outline.')
        key=(bid,round(float(x),10),cut,blocks)
        if key in self._gcache:return self._gcache[key]
        pieces=[p for c,p in self.active_components(b,x)]
        if not pieces:raise ModelError(f"{b['name']}: no material at x={x:g}. Component lengths must cover the beam.")
        g=unary_union(pieces)
        if cut and b.get('auto_cut',True):
            for coil in self.model.get('coils',[]):
                dx=x-coil['x'];r=coil['r']
                if abs(dx)<r:
                    dy=math.sqrt(max(0,r*r-dx*dx));yc=coil['y']
                    z0,y0,z1,y1=g.bounds
                    if yc+dy>y0 and yc-dy<y1:
                        g=g.difference(box(z0-1,yc-dy,z1+1,yc+dy))
        if blocks:
            pads=[]
            for q in self.model.get('blocks',[]):
                if q['beam']==bid and abs(x-q['x'])<=q['length']/2+1e-9:
                    pads.append(box(q.get('z',0)-q['depth']/2,q['y'],q.get('z',0)+q['depth']/2,q['y']+q['height']))
            if pads:g=unary_union([g,*pads])
        self._gcache[key]=g
        return g
    def props(self,bid,x,shear=False):
        key=(bid,round(float(x),10),bool(shear))
        if key in self._scache:return self._scache[key]
        b=self.beams[bid]
        if b.get('section_type')=='Custom properties':
            p=b['manual'];h=p['ctop']+p['cbottom'];yc=b['y']+p['cbottom']
            s=Section(p['A'],yc,0.,p['I'],p.get('Iyy',p['I']),0.,b['y'],b['y']+h,-p.get('width',1)/2,p.get('width',1)/2,p.get('As',p['A']*5/6))
        else:s=section_properties(self.section(bid,x),shear)
        self._scache[key]=s
        return s
    def bounds(self,bid,x=None,cut=False):
        b=self.beams[bid]
        if b.get('section_type')=='Custom properties':
            p=b['manual'];return (-p.get('width',1)/2,b['y'],p.get('width',1)/2,b['y']+p['ctop']+p['cbottom'])
        if x is None:
            ps=[translate(g,yoff=b['y']) for g in self._profiles[bid]]
            return unary_union(ps).bounds
        return self.section(bid,x,cut=cut).bounds
    def levels_at(self,bid,x):
        g=self.section(bid,x) if self.beams[bid].get('section_type')!='Custom properties' else None
        if g is None:
            s=self.props(bid,x);return [(s.ymin,s.ymax)]
        return [(p.bounds[1],p.bounds[3]) for p in polygons(g) if p.area>1e-10]
    def top_seat(self,bid,x,diameter=0.):
        b=self.beams[bid]
        if b.get('section_type')=='Custom properties':return self.props(bid,x).ymax
        g=self.section(bid,x);edges=[]
        for pp in polygons(g):
            p=orient(pp,sign=1)
            coords=list(p.exterior.coords)
            for a,c in zip(coords[:-1],coords[1:]):
                if abs(a[1]-c[1])<1e-8 and a[0]-c[0]>=max(diameter,1e-8):edges.append(a[1])
        return max(edges) if edges else g.bounds[3]
    def critical_x(self):
        xs=[]
        for b in self.model['beams']:
            xs.extend([b['x'],b['x']+b['length']])
            if b.get('section_type')!='Custom properties':
                for c,p in zip(b['components'],self._profiles[b['id']]):
                    xs.extend([b['x']+c.get('start',0),b['x']+c.get('start',0)+c.get('length',b['length'])])
                    for coil in self.model.get('coils',[]):
                        for y in [p.bounds[1]+b['y'],p.bounds[3]+b['y']]:
                            d=y-coil['y']
                            if abs(d)<coil['r']:
                                h=math.sqrt(coil['r']**2-d*d);xs.extend([coil['x']-h,coil['x']+h])
        for c in self.model.get('coils',[]):xs.extend([c['x']-c['r'],c['x'],c['x']+c['r']])
        for q in self.model.get('blocks',[]):xs.extend([q['x']-q['length']/2,q['x'],q['x']+q['length']/2])
        for kind in ['rods','pins','loads']:
            for q in self.model.get(kind,[]):
                xs.append(q['x'])
                if kind=='loads' and q.get('kind')=='Uniform':xs.append(q['end'])
        return xs
