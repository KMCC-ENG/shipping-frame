export default function({parentElement,data,setStateValue}) {
 const root=parentElement.querySelector('.sf-editor');
 if(!root)return;
 const clone=x=>JSON.parse(JSON.stringify(x));
 if(root._sf?.version===2){
  const s=root._sf;s.send=setStateValue;s.color=data.color||'#2463aa';
  if(s.revision!==data.revision||s.bid!==data.beam){
   Object.assign(s,{shapes:clone(data.shapes||[]),draft:clone(data.draft||[]),revision:data.revision,bid:data.beam,selected:null,history:[],redo:[],hover:null,mouse:null,editing:null});root.querySelector('.sf-dimension-edit').hidden=true;s.fit();
  }else s.draw();
  return;
 }
 const el=s=>root.querySelector(s),svg=el('.sf-canvas'),layer=el('.sf-shapes'),draftLayer=el('.sf-draft'),labels=el('.sf-dimensions'),dialog=el('.sf-dimension-edit');
 const S=root._sf={version:2,shapes:clone(data.shapes||[]),draft:clone(data.draft||[]),revision:data.revision,bid:data.beam,color:data.color||'#2463aa',send:setStateValue,tool:'select',selected:null,history:[],redo:[],hover:null,mouse:null,editing:null,dimSpecs:[]};
 const val=s=>Number(el(s).value),status=t=>el('.sf-editor-status').textContent=t;
 const gid=()=>`s${Date.now().toString(36)}${Math.random().toString(36).slice(2,6)}`;
 const save=()=>{S.history.push(clone(S.shapes));if(S.history.length>80)S.history.shift();S.redo=[];};
 const emit=(close=false)=>S.send('geometry',{shapes:clone(S.shapes),draft:clone(S.draft),close,event:Date.now()+Math.random(),revision:S.revision});
 const commit=()=>{draw();emit();};
 const selected=()=>S.shapes.find(s=>s.id===S.selected);
 const fmt=v=>Number(v.toFixed(6)).toString();
 const ns='http://www.w3.org/2000/svg';
 function arcPts(c,r,a0,a1,n=96){const k=Math.max(3,Math.ceil(Math.abs(a1-a0)/(Math.PI*2)*n));return Array.from({length:k+1},(_,i)=>[c[0]+r*Math.cos(a0+(a1-a0)*i/k),c[1]+r*Math.sin(a0+(a1-a0)*i/k)]);}
 function edgeArc(a,b,r,cw=false,large=false){
  const dx=b[0]-a[0],dy=b[1]-a[1],d=Math.hypot(dx,dy);if(d<1e-10)return [b];if(r<d/2-1e-9)throw Error('Radius must be at least half the edge length.');
  const mid=[(a[0]+b[0])/2,(a[1]+b[1])/2],off=Math.sqrt(Math.max(0,r*r-d*d/4));
  for(const sign of [1,-1]){const c=[mid[0]-dy/d*off*sign,mid[1]+dx/d*off*sign],a0=Math.atan2(a[1]-c[1],a[0]-c[0]),a1=Math.atan2(b[1]-c[1],b[0]-c[0]);let dt=((a1-a0)%(2*Math.PI)+2*Math.PI)%(2*Math.PI);if(cw)dt-=2*Math.PI;if((Math.abs(dt)>Math.PI+1e-8)===large||Math.abs(Math.abs(dt)-Math.PI)<1e-8)return arcPts(c,r,a0,a0+dt).slice(1);}
  return [b];
 }
 function rawPoints(s){
  if(s.type==='rectangle'){
   const {x,y,w,h}=s,r=Math.min(s.radius||0,w/2,h/2);if(!r)return [[x,y],[x+w,y],[x+w,y+h],[x,y+h]];
   let p=[];for(const [cx,cy,a]of [[x+w-r,y+r,-90],[x+w-r,y+h-r,0],[x+r,y+h-r,90],[x+r,y+r,180]])p.push(...arcPts([cx,cy],r,a*Math.PI/180,(a+90)*Math.PI/180));return p;
  }
  if(s.type==='circle')return arcPts([s.x,s.y],s.r,0,2*Math.PI);
  if(s.type==='arc'){const p=arcPts([s.x,s.y],s.r,s.a0*Math.PI/180,s.a1*Math.PI/180);return s.close==='segment'?p:[[s.x,s.y],...p];}
  let p=[];for(let i=0;i<(s.points||[]).length;i++){const a=s.points[i],b=s.points[(i+1)%s.points.length];p.push(a);if(s.arcs?.[i]){const q=s.arcs[i];p.push(...edgeArc(a,b,q.r,q.clockwise,q.large));}}return p;
 }
 function transformed(s,p){
  const outline=rawPoints(s);if(!outline.length)return p;
  const xs=outline.map(q=>q[0]),ys=outline.map(q=>q[1]),cx=(Math.min(...xs)+Math.max(...xs))/2,cy=(Math.min(...ys)+Math.max(...ys))/2,t=(s.rotation||0)*Math.PI/180;
  return p.map(([x,y])=>{let a=x-cx,b=y-cy;if(s.mirror)a=-a;return [cx+a*Math.cos(t)-b*Math.sin(t),cy+a*Math.sin(t)+b*Math.cos(t)];});
 }
 const points=s=>transformed(s,rawPoints(s));
 function bakePolygon(s){if(!s.rotation&&!s.mirror)return;s.points=transformed(s,s.points);if(s.mirror)for(const a of Object.values(s.arcs||{}))a.clockwise=!a.clockwise;s.rotation=0;s.mirror=false;}
 function path(p,closed=true){return p.length?'M'+p.map(q=>`${q[0]},${-q[1]}`).join('L')+(closed?'Z':''):'';}
 function sizePx(){const v=svg.viewBox.baseVal;return Math.max(v.width/Math.max(svg.clientWidth,1),v.height/Math.max(svg.clientHeight||400,1));}
 function screen(p){
  const v=svg.viewBox.baseVal,w=svg.clientWidth||900,h=svg.clientHeight||400,scale=Math.min(w/v.width,h/v.height);
  return [(p[0]-v.x)*scale+(w-v.width*scale)/2,(-p[1]-v.y)*scale+(h-v.height*scale)/2];
 }
 function addPath(target,p,color,fill='none',closed=false){const q=document.createElementNS(ns,'path');q.setAttribute('d',path(p,closed));q.setAttribute('stroke',color);q.setAttribute('stroke-width',String(1.5*sizePx()));q.setAttribute('fill',fill);target.append(q);return q;}
 function createPreview(mouse){
  const a=mouse.start,b=mouse.end;
  if(S.tool==='rectangle')return {type:'rectangle',x:Math.min(a[0],b[0]),y:Math.min(a[1],b[1]),w:Math.abs(a[0]-b[0]),h:Math.abs(a[1]-b[1])};
  return {type:S.tool==='arc'?'arc':'circle',x:a[0],y:a[1],r:Math.hypot(a[0]-b[0],a[1]-b[1]),a0:val('.sf-a0'),a1:val('.sf-a1'),close:'sector'};
 }
 function draw(){
  layer.replaceChildren();
  for(const s of S.shapes){
   let p;try{p=points(s);}catch{continue;}if(p.length<3)continue;
   const n=addPath(layer,p,s.id===S.selected?'#e28b32':s.op==='subtract'?'#c34b50':S.color,s.op==='subtract'?'#f8fafc':S.color,true);
   n.setAttribute('fill-opacity',s.op==='subtract'?'1':'.13');n.setAttribute('data-id',s.id);if(s.op==='subtract')n.setAttribute('stroke-dasharray',`${4*sizePx()},${3*sizePx()}`);
   if(s.id===S.selected&&s.type==='polygon')for(const [i,p]of transformed(s,s.points).entries()){
    const dot=document.createElementNS(ns,'circle');dot.setAttribute('cx',p[0]);dot.setAttribute('cy',-p[1]);dot.setAttribute('r',3*sizePx());dot.setAttribute('fill','#e28b32');dot.style.pointerEvents='none';layer.append(dot);
    if(s.points.length<=20){const text=document.createElementNS(ns,'text');text.setAttribute('x',p[0]+5*sizePx());text.setAttribute('y',-p[1]-5*sizePx());text.setAttribute('font-size',9*sizePx());text.setAttribute('fill','#9a5a16');text.style.pointerEvents='none';text.textContent=String(i+1);layer.append(text);}
   }
  }
  draftLayer.replaceChildren();
  if(S.draft.length){const p=S.draft.concat(S.tool==='line'&&S.hover?[S.hover]:[]);addPath(draftLayer,p,'#168063');for(const p of S.draft){const c=document.createElementNS(ns,'circle');c.setAttribute('cx',p[0]);c.setAttribute('cy',-p[1]);c.setAttribute('r',3*sizePx());c.setAttribute('fill','#168063');draftLayer.append(c);}}
  if(S.mouse?.mode==='create'){const p=createPreview(S.mouse);if((p.w>0&&p.h>0)||p.r>0)addPath(draftLayer,rawPoints(p),'#168063','#dceee7',true);}
  drawDimensions();
 }
 S.draw=draw;
 function fit(){
  const p=S.shapes.flatMap(s=>{try{return points(s);}catch{return [];}}).concat(S.draft);
  let x0=0,x1=3,y0=0,y1=3;if(p.length){x0=Math.min(...p.map(q=>q[0]));x1=Math.max(...p.map(q=>q[0]));y0=Math.min(...p.map(q=>q[1]));y1=Math.max(...p.map(q=>q[1]));}
  let w=Math.max(3,x1-x0+2),h=Math.max(3,y1-y0+2),ratio=(svg.clientWidth||900)/(svg.clientHeight||400);if(w/h<ratio)w=h*ratio;else h=w/ratio;
  svg.setAttribute('viewBox',`${(x0+x1-w)/2} ${-(y0+y1+h)/2} ${w} ${h}`);draw();
 }
 S.fit=fit;
 function pworld(e){
  const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;const q=p.matrixTransform(svg.getScreenCTM().inverse());let a=[q.x,-q.y];
  if(el('.sf-snap').checked){const step=Math.max(.001,val('.sf-grid-step'));a=a.map(x=>Math.round(x/step)*step);const near=S.shapes.flatMap(s=>{try{return points(s);}catch{return [];}}).concat(S.draft);const vertex=near.find(p=>Math.hypot(a[0]-p[0],a[1]-p[1])<sizePx()*8);if(vertex)a=[...vertex];}
  if(el('.sf-ortho').checked&&S.tool==='line'&&S.draft.length){const prev=S.draft.at(-1);if(Math.abs(a[0]-prev[0])<Math.abs(a[1]-prev[1]))a[0]=prev[0];else a[1]=prev[1];}return a;
 }
 function shift(s,dx,dy){if(s.type==='polygon')s.points=s.points.map(p=>[p[0]+dx,p[1]+dy]);else{s.x+=dx;s.y+=dy;}}
 function fields(s){
  if(!s)return;el('.sf-op').value=s.op||'add';const p=s.type==='polygon'?s.points[0]:[s.x,s.y];el('.sf-z').value=p[0];el('.sf-y').value=p[1];
  for(const [k,selector]of [['w','.sf-w'],['h','.sf-h'],['r','.sf-r'],['a0','.sf-a0'],['a1','.sf-a1']])if(s[k]!==undefined)el(selector).value=s[k];if(s.radius!==undefined)el('.sf-r').value=s.radius;
 }
 function validate(s){
  if(s.type==='polygon'){if(s.points.length<3||s.points.some(p=>p.some(x=>!Number.isFinite(x))))throw Error('An outline needs three finite points.');for(const [i,a]of Object.entries(s.arcs||{}))edgeArc(s.points[Number(i)],s.points[(Number(i)+1)%s.points.length],a.r,a.clockwise,a.large);}
  else{if(!Number.isFinite(s.x)||!Number.isFinite(s.y))throw Error('Enter finite coordinates.');for(const k of s.type==='rectangle'?['w','h']:['r'])if(!Number.isFinite(s[k])||s[k]<=0)throw Error('Dimensions must be positive finite numbers.');}
 }
 function finish(){
  const p=clone(S.draft);if(p.length>1&&Math.hypot(p[0][0]-p.at(-1)[0],p[0][1]-p.at(-1)[1])<1e-10)p.pop();
  if(p.length<3){status('A closed outline needs at least three points.');return;}
  save();S.shapes.push({id:gid(),type:'polygon',points:p,op:el('.sf-op').value});S.draft=[];S.hover=null;S.selected=S.shapes.at(-1).id;commit();status('Outline closed. Click an edge dimension to set its exact length.');
 }
 function addDimension(spec,centre=null){
  if(!Number.isFinite(spec.value)||spec.value<=1e-10)return;
  const a=screen(spec.a),b=screen(spec.b),dx=b[0]-a[0],dy=b[1]-a[1],len=Math.hypot(dx,dy)||1;let nx=dy/len,ny=-dx/len;
  if(centre){const c=screen(centre);if(nx*((a[0]+b[0])/2-c[0])+ny*((a[1]+b[1])/2-c[1])<0){nx=-nx;ny=-ny;}}
  let x=(a[0]+b[0])/2+nx*23,y=(a[1]+b[1])/2+ny*23;
  const w=svg.clientWidth||900,h=svg.clientHeight||400;
  for(let k=0;k<7;k++){x=Math.max(48,Math.min(w-48,x));y=Math.max(18,Math.min(h-22,y));if(!S.dimSpecs.some(t=>Math.abs(t.screen[0]-x)<78&&Math.abs(t.screen[1]-y)<26))break;x+=nx*20;y+=ny*20;}
  spec.screen=[x,y];S.dimSpecs.push(spec);
  const button=document.createElement('button');button.type='button';button.className='sf-size-label'+(spec.source==='live'||spec.source==='creating'?' sf-live-dimension':'');button.style.left=x+'px';button.style.top=y+'px';
  button.textContent=(spec.prefix?spec.prefix+' ':'')+fmt(spec.value)+'″';button.dataset.dimKind=spec.kind;button.dataset.dimSource=spec.source;if(spec.id)button.dataset.shape=spec.id;if(spec.edge!==undefined)button.dataset.edge=String(spec.edge);
  button.setAttribute('aria-label','Edit '+(spec.kind==='length'?'line length':spec.kind==='w'?'width':spec.kind==='h'?'height':'radius')+' in inches');
  button.onclick=e=>{e.stopPropagation();beginDimension(spec);};labels.append(button);
 }
 function shapeDimensions(s,source='shape'){
  const common={source,id:s.id};
  if(s.type==='rectangle'){
   const p=transformed(s,[[s.x,s.y],[s.x+s.w,s.y],[s.x+s.w,s.y+s.h],[s.x,s.y+s.h]]),c=[(p[0][0]+p[2][0])/2,(p[0][1]+p[2][1])/2];
   addDimension({...common,kind:'w',prefix:'W',value:s.w,a:p[3],b:p[2]},c);addDimension({...common,kind:'h',prefix:'H',value:s.h,a:p[1],b:p[2]},c);
  }else if(s.type==='circle'||s.type==='arc'){
   const t=s.type==='arc'?(s.a0+s.a1)/2*Math.PI/180:0,p=transformed(s,[[s.x,s.y],[s.x+s.r*Math.cos(t),s.y+s.r*Math.sin(t)]]);
   addDimension({...common,kind:'r',prefix:'R',value:s.r,a:p[0],b:p[1]});
  }else if(s.type==='polygon'){
   const p=transformed(s,s.points),c=[p.reduce((v,q)=>v+q[0],0)/p.length,p.reduce((v,q)=>v+q[1],0)/p.length];
   for(let i=0;i<p.length;i++){const j=(i+1)%p.length,a=s.arcs?.[i];addDimension({...common,kind:a?'r':'length',prefix:a?'R':'',value:a?a.r:Math.hypot(p[j][0]-p[i][0],p[j][1]-p[i][1]),edge:i,a:p[i],b:p[j]},c);}
  }
 }
 function drawDimensions(){
  labels.replaceChildren();S.dimSpecs=[];
  if(S.mouse?.mode==='create'){shapeDimensions(createPreview(S.mouse),'creating');return;}
  if(S.draft.length){
   for(let i=0;i<S.draft.length-1;i++)addDimension({source:'draft',kind:'length',edge:i,a:S.draft[i],b:S.draft[i+1],value:Math.hypot(S.draft[i+1][0]-S.draft[i][0],S.draft[i+1][1]-S.draft[i][1])});
   if(S.tool==='line'&&S.hover)addDimension({source:'live',kind:'length',edge:S.draft.length-1,a:S.draft.at(-1),b:S.hover,value:Math.hypot(S.hover[0]-S.draft.at(-1)[0],S.hover[1]-S.draft.at(-1)[1])});
  }else if(selected())shapeDimensions(selected());
 }
 function beginDimension(spec){
  S.editing=clone(spec);dialog.hidden=false;dialog.style.left=Math.max(5,Math.min((svg.clientWidth||900)-225,spec.screen?.[0]||100))+'px';dialog.style.top=Math.max(5,Math.min((svg.clientHeight||400)-85,(spec.screen?.[1]||100)+10))+'px';
  el('.sf-dimension-title').textContent=({length:'Length',w:'Width',h:'Height',r:'Radius'}[spec.kind])+' (in)';const input=el('.sf-dimension-value');input.value=String(spec.value);input.removeAttribute('aria-invalid');input.focus();input.select();
 }
 function cancelDimension(){S.editing=null;dialog.hidden=true;root.focus({preventScroll:true});}
 function endpoint(spec,length){const dx=spec.b[0]-spec.a[0],dy=spec.b[1]-spec.a[1],d=Math.hypot(dx,dy)||1;return [spec.a[0]+length*(d===1&&dx===0&&dy===0?1:dx/d),spec.a[1]+length*dy/d];}
 function applyDimension(){
  const spec=S.editing;if(!spec)return;const input=el('.sf-dimension-value'),n=Number(input.value);
  if(!Number.isFinite(n)||n<=0){input.setAttribute('aria-invalid','true');status('Enter a positive dimension in inches.');return;}
  try{
   if(spec.source==='live'){S.draft.push(endpoint(spec,n));S.hover=null;cancelDimension();draw();status('Exact line length set. Continue from the new endpoint.');return;}
   if(spec.source==='draft'){S.draft[spec.edge+1]=endpoint(spec,n);S.hover=null;cancelDimension();draw();return;}
   let s=spec.source==='creating'?createPreview(S.mouse):clone(S.shapes.find(s=>s.id===spec.id));
   if(!s)return;
   if(s.type==='polygon'){
    bakePolygon(s);
    if(spec.kind==='length')s.points[(spec.edge+1)%s.points.length]=endpoint(spec,n);
    else{const a=s.points[spec.edge],b=s.points[(spec.edge+1)%s.points.length];if(n<Math.hypot(a[0]-b[0],a[1]-b[1])/2)throw Error('Arc radius must be at least half the edge length.');s.arcs[spec.edge].r=n;}
   }else{s[spec.kind]=n;if(s.type==='rectangle'&&s.radius)s.radius=Math.min(s.radius,s.w/2,s.h/2);}
   validate(s);save();
   if(spec.source==='creating'){s.id=gid();s.op=el('.sf-op').value;S.shapes.push(s);S.mouse=null;S.selected=s.id;}
   else S.shapes[S.shapes.findIndex(q=>q.id===spec.id)]=s;
   fields(s);cancelDimension();commit();status('Dimension set. Connected endpoints and their adjacent dimensions update together.');
  }catch(e){status(e.message||String(e));}
 }
 el('[data-dimension=apply]').onclick=applyDimension;el('[data-dimension=cancel]').onclick=cancelDimension;
 el('.sf-dimension-value').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();e.stopPropagation();applyDimension();}if(e.key==='Escape'){e.preventDefault();e.stopPropagation();cancelDimension();}};
 root.querySelectorAll('[data-tool]').forEach(button=>button.onclick=()=>{
  cancelDimension();S.tool=button.dataset.tool;S.hover=null;S.mouse=null;root.querySelectorAll('[data-tool]').forEach(q=>q.classList.toggle('active',q===button));svg.style.cursor=S.tool==='pan'?'grab':S.tool==='select'?'default':'crosshair';if(S.tool!=='select')S.selected=null;draw();status(S.tool==='line'?'Click the start point, then move. Click the live length or press Tab to type its exact size.':'Draw with the mouse, or use numeric fields. Click size labels to edit.');
 });
 svg.onpointerdown=e=>{
  if(e.button!==0&&e.button!==1)return;if(S.editing)return;root.focus({preventScroll:true});const p=pworld(e);svg.setPointerCapture(e.pointerId);
  if(S.tool==='pan'||e.button===1){S.mouse={mode:'pan',client:[e.clientX,e.clientY],vb:svg.getAttribute('viewBox').split(/\s+/).map(Number)};return;}
  if(S.tool==='line'){if(S.draft.length>2&&Math.hypot(p[0]-S.draft[0][0],p[1]-S.draft[0][1])<sizePx()*10){finish();return;}S.draft.push(p);S.hover=null;draw();return;}
  if(S.tool==='select'){const id=e.target.getAttribute('data-id');S.selected=id;fields(selected());if(id){save();S.mouse={mode:'move',start:p,shape:clone(selected()),moved:false};}draw();return;}
  S.mouse={mode:'create',start:p,end:p};draw();
 };
 svg.onpointermove=e=>{
  if(S.editing)return;const p=pworld(e);el('.sf-coordinates').textContent=`z ${p[0].toFixed(4)}, y ${p[1].toFixed(4)} in`;
  if(!S.mouse){if(S.tool==='line'&&S.draft.length){S.hover=p;draw();}return;}
  if(S.mouse.mode==='pan'){const v=S.mouse.vb,sc=v[2]/svg.clientWidth;svg.setAttribute('viewBox',`${v[0]-(e.clientX-S.mouse.client[0])*sc} ${v[1]-(e.clientY-S.mouse.client[1])*sc} ${v[2]} ${v[3]}`);draw();}
  else if(S.mouse.mode==='move'){const s=selected();if(!s)return;Object.assign(s,clone(S.mouse.shape));shift(s,p[0]-S.mouse.start[0],p[1]-S.mouse.start[1]);S.mouse.moved=true;draw();}
  else{S.mouse.end=p;draw();}
 };
 svg.onpointerup=()=>{
  if(S.editing)return;const mouse=S.mouse;S.mouse=null;if(!mouse)return;
  if(mouse.mode==='move'){if(mouse.moved){fields(selected());commit();}else{S.history.pop();draw();}return;}
  if(mouse.mode==='create'){const s={id:gid(),...createPreview(mouse),op:el('.sf-op').value};try{validate(s);}catch{draw();return;}save();S.shapes.push(s);S.selected=s.id;fields(s);commit();}
 };
 svg.onwheel=e=>{e.preventDefault();if(S.editing)return;const v=svg.viewBox.baseVal,p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;const q=p.matrixTransform(svg.getScreenCTM().inverse()),f=e.deltaY>0?1.15:1/1.15,w=Math.max(.02,Math.min(10000,v.width*f)),h=w*v.height/v.width;svg.setAttribute('viewBox',`${q.x+(v.x-q.x)*w/v.width} ${q.y+(v.y-q.y)*h/v.height} ${w} ${h}`);draw();};
 function action(name){
  const before=clone(S.shapes),historyLength=S.history.length;
  try{
   if(name==='close-panel'){cancelDimension();emit(true);status('Drawing kept in the current design. Closing sketcher…');return;}
   if(name==='fit'){fit();return;}
   if(name==='undo'){if(S.history.length){S.redo.push(clone(S.shapes));S.shapes=S.history.pop();S.selected=null;commit();}return;}
   if(name==='redo'){if(S.redo.length){S.history.push(clone(S.shapes));S.shapes=S.redo.pop();S.selected=null;commit();}return;}
   if(name==='vertex'){S.draft.push([val('.sf-z'),val('.sf-y')]);S.hover=null;draw();return;}
   if(name==='close'){finish();return;}
   if(name==='clear-draft'){S.draft=[];S.hover=null;cancelDimension();draw();return;}
   if(name==='clear'){save();S.shapes=[];S.selected=null;S.draft=[];S.hover=null;cancelDimension();commit();return;}
   let s=selected();
   if(name==='numeric'){
    if(S.tool==='line'&&!s){S.draft.push([val('.sf-z'),val('.sf-y')]);S.hover=null;draw();return;}
    s=s?clone(s):{id:gid(),type:['rectangle','circle','arc'].includes(S.tool)?S.tool:'rectangle',op:el('.sf-op').value};
    if(s.type==='polygon'){shift(s,val('.sf-z')-s.points[0][0],val('.sf-y')-s.points[0][1]);}
    else{s.x=val('.sf-z');s.y=val('.sf-y');if(s.type==='rectangle'){s.w=val('.sf-w');s.h=val('.sf-h');}else{s.r=val('.sf-r');s.a0=val('.sf-a0');s.a1=val('.sf-a1');if(s.type==='arc')s.close=s.close||'sector';}}
    s.op=el('.sf-op').value;validate(s);save();const i=S.shapes.findIndex(q=>q.id===s.id);if(i<0)S.shapes.push(s);else S.shapes[i]=s;S.selected=s.id;commit();return;
   }
   if(!s){status('Select a shape first.');return;}
   save();
   if(name==='fillet'){
    const r=val('.sf-r');if(!Number.isFinite(r)||r<=0)throw Error('Enter a positive fillet radius.');
    if(s.type==='rectangle')s.radius=Math.min(r,s.w/2,s.h/2);
    else if(s.type==='polygon'){
     bakePolygon(s);const i=Math.max(0,Math.round(val('.sf-corner'))-1)%s.points.length,n=s.points.length,v=s.points[i],prev=s.points[(i-1+n)%n],next=s.points[(i+1)%n];let u=[prev[0]-v[0],prev[1]-v[1]],w=[next[0]-v[0],next[1]-v[1]],lu=Math.hypot(...u),lw=Math.hypot(...w);u=u.map(x=>x/lu);w=w.map(x=>x/lw);
     const beta=Math.acos(Math.max(-1,Math.min(1,u[0]*w[0]+u[1]*w[1]))),dist=r/Math.tan(beta/2);if(!Number.isFinite(dist)||dist>=Math.min(lu,lw)*.95)throw Error('Radius is too large for this corner.');const p1=[v[0]+u[0]*dist,v[1]+u[1]*dist],p2=[v[0]+w[0]*dist,v[1]+w[1]*dist],bis=[u[0]+w[0],u[1]+w[1]],bn=Math.hypot(...bis),c=[v[0]+bis[0]/bn*r/Math.sin(beta/2),v[1]+bis[1]/bn*r/Math.sin(beta/2)],t0=Math.atan2(p1[1]-c[1],p1[0]-c[0]),t1=Math.atan2(p2[1]-c[1],p2[0]-c[0]),dt=((t1-t0+3*Math.PI)%(2*Math.PI))-Math.PI;s.points.splice(i,1,...arcPts(c,r,t0,t0+dt));delete s.arcs;
    }else throw Error('Fillet applies to rectangles and polygon outlines.');
   }
   if(name==='arc-edge'||name==='reverse-arc'){
    if(s.type!=='polygon')throw Error('Select a polygon outline to curve one edge.');const i=Math.max(0,Math.round(val('.sf-corner'))-1)%s.points.length,a=s.points[i],b=s.points[(i+1)%s.points.length],r=val('.sf-r');if(!Number.isFinite(r)||r<Math.hypot(a[0]-b[0],a[1]-b[1])/2)throw Error('Radius must be at least half the edge length.');s.arcs=s.arcs||{};s.arcs[i]={r,clockwise:name==='reverse-arc'?!(s.arcs[i]||{}).clockwise:false,large:false};
   }
   if(name==='delete'){S.shapes=S.shapes.filter(q=>q.id!==s.id);S.selected=null;}
   if(name==='copy'){const q=clone(s);q.id=gid();const d=val('.sf-grid-step');shift(q,d,d);S.shapes.push(q);S.selected=q.id;fields(q);}
   if(name==='rotate')s.rotation=((s.rotation||0)+90)%360;
   if(name==='mirror')s.mirror=!s.mirror;
   commit();
  }catch(e){S.shapes=before;while(S.history.length>historyLength)S.history.pop();draw();status(e.message||String(e));}
 }
 root.querySelectorAll('[data-act]').forEach(b=>b.onclick=()=>action(b.dataset.act));
 el('.sf-grid-step').onchange=()=>{const s=Math.max(.001,val('.sf-grid-step')),p=el('pattern');p.setAttribute('width',s);p.setAttribute('height',s);p.querySelector('path').setAttribute('d',`M${s} 0L0 0 0 ${s}`);};
 el('.sf-op').onchange=()=>{const s=selected();if(s){save();s.op=el('.sf-op').value;commit();}};
 root.onkeydown=e=>{
  if(e.target.tagName==='INPUT'||e.target.tagName==='SELECT'||S.editing)return;
  if(e.key==='Tab'&&S.tool==='line'&&S.draft.length){e.preventDefault();const a=S.draft.at(-1),b=S.hover||[a[0]+1,a[1]],value=Math.hypot(b[0]-a[0],b[1]-a[1]);beginDimension({source:'live',kind:'length',edge:S.draft.length-1,a,b,value:value||1,screen:screen(b)});return;}
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();action(e.shiftKey?'redo':'undo');}
  if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();action('delete');}
  if(e.key==='Escape'){S.draft=[];S.hover=null;S.mouse=null;draw();}
  if(e.key==='Enter'&&S.draft.length)finish();
 };
 // Native number spinners snap to their min/step grid. Explicit steppers keep
 // the promised +/-0.5 increment even after a user types 0.375 or 5.3 inches.
 root.querySelectorAll('input[type=number][step="0.5"]').forEach(input=>{
  if(input.closest('.sf-number-control'))return;
  const wrapper=document.createElement('span');wrapper.className='sf-number-control';input.parentNode.insertBefore(wrapper,input);wrapper.append(input);
  const buttons=document.createElement('span');buttons.className='sf-number-buttons';wrapper.append(buttons);
  const increment=direction=>{
   const current=Number(input.value),next=Number(((Number.isFinite(current)?current:0)+direction*.5).toFixed(10));
   if(input.min!==''&&next<Number(input.min))return;
   input.value=String(next);input.dispatchEvent(new input.ownerDocument.defaultView.Event('change',{bubbles:true}));
  };
  for(const direction of [1,-1]){const b=document.createElement('button');b.type='button';b.className='sf-number-step';b.textContent=direction>0?'+':'−';b.dataset.stepFor=input.className;b.dataset.stepSign=direction>0?'+':'-';b.setAttribute('aria-label',(direction>0?'Increase':'Decrease')+' by 0.5 inches');b.title=(direction>0?'+':'−')+'0.5 in';b.onclick=()=>increment(direction);buttons.append(b);}
  input.addEventListener('keydown',e=>{if(e.key==='ArrowUp'||e.key==='ArrowDown'){e.preventDefault();e.stopPropagation();increment(e.key==='ArrowUp'?1:-1);}});
 });
 if(S.draft.length){S.tool='line';root.querySelectorAll('[data-tool]').forEach(q=>q.classList.toggle('active',q.dataset.tool==='line'));}
 if(typeof ResizeObserver!=='undefined'){const observer=new ResizeObserver(()=>draw());observer.observe(svg);}
 el('.sf-grid-step').onchange();fit();
}
