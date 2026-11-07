"""Hand-calculation style worksheet. Formulas and derivations live here only."""
from __future__ import annotations
import io,json,math
import numpy as np
import pandas as pd
from frame_geometry import section_properties,ModelError
from frame_visuals import num,overall_fbd,member_fbd,section_svg,coil_fbd,rod_fbd,beam_color


def render_calculations(s):
 import streamlit as st
 st.subheader('Calculation worksheet')
 st.caption('Equations → substitutions → results. All forces are lbf, lengths in inches, stresses in psi. Upward forces and counterclockwise couples are positive.')
 m=s.model;lo=m['loading'];mat=m['materials']['frame'];rm=m['materials']['rod'];fac=lo['factor']
 st.markdown('### 1. Section geometry and removed material')
 st.write('The coil circles remove intersecting material from the main beam components. Rectangular blocks remain welded contact pads. Properties are evaluated along each beam; a complete uncut section is not used through a seat.')
 st.latex(r'A(x)=\int_{\Omega_{\rm remaining}(x)}dA,\qquad \bar y(x)=\frac{\int_{\Omega_{\rm remaining}(x)}y\,dA}{A(x)}')
 st.latex(r'I(x)=\int_{\Omega_{\rm remaining}(x)}(y-\bar y(x))^2\,dA,\qquad S_t(x)=\frac{I(x)}{c_t(x)},\quad S_b(x)=\frac{I(x)}{c_b(x)}')
 st.write('A worked numerical section calculation is shown with each beam below, at its critical nominal-stress location.')
 st.markdown('### 2. Weight assigned to this frame')
 if lo['equal_frames']:
  st.latex(r'W_{\rm coils,frame}=\frac{W_{\rm package}}{n_{\rm frames}}'+fr'=\frac{{{lo["coil_weight"]:.6g}}}{{{lo["frames"]}}}=\boxed{{{s.checks["coil_load_per_frame"]:.6g}\ \mathrm{{lbf}}}}')
 else:
  st.latex(r'W_{\rm coils,frame}=f_{\rm frame}W_{\rm package}'+fr'=({lo["frame_share"]:.6g})({lo["coil_weight"]:.6g})=\boxed{{{s.checks["coil_load_per_frame"]:.6g}\ \mathrm{{lbf}}}}')
 shares=sum(c.get('share',1) for c in s.coils)
 st.latex(r'W_i=W_{\rm coils,frame}\frac{w_i}{\sum_j w_j}')
 if s.coils:
  st.dataframe(pd.DataFrame([{'Coil':c['id'],'x (in)':c['x'],'Relative share':c.get('share',1),'Assigned weight (lbf)':c['weight'],'Factored weight (lbf)':c['applied_weight']} for c in s.coils]),hide_index=True,width='stretch')
 st.latex(r'W_b=\gamma_f\int_{x_0}^{x_1} A_b(x)\,dx')
 for w in s.weights:
  st.latex(fr'W_{{{w["member"]}}}=({mat["density"]:.7g})\int A_{{{w["member"]}}}(x)\,dx=\boxed{{{w["weight"]:.6g}\ \mathrm{{lbf}}}}')
 st.latex(r'W_{\rm rod}=\gamma_r\frac{\pi d^2}{4}L_{\rm geometric}')
 if s.rods:st.dataframe(pd.DataFrame([{'Rod':r['id'],'Diameter (in)':r['diameter'],'Geometric length (in)':r['nut_y_value']-r['weld_y_value'],'Self-weight (lbf)':r['weight']} for r in s.rods]),hide_index=True,width='stretch')
 st.caption('Density is expressed as weight per volume at standard gravity. Rod mass uses its nominal cylindrical envelope and is applied at its welded attachment. Nut, washer and weld-metal weights are excluded. Beam weights include blocks and the removed coil-seat volume.')
 st.write('Member/rod self-weight is **included**.' if lo['self_weight'] else 'Member/rod self-weight is **excluded by the Loading setting**; the calculated weights above remain available for review.')
 Wc=sum(c['weight'] for c in s.coils);Ws=sum(w['weight'] for w in s.weights)+sum(r['weight'] for r in s.rods)
 extra=-sum(q['value'] for q in m.get('loads',[]))
 st.latex(r'W_{\rm applied}=D\left(W_{\rm coils,frame}+W_{\rm self}+W_{\rm additional,down}\right)')
 st.latex(fr'W_{{\rm applied}}=({fac:.6g})\left({Wc:.6g}+{(Ws if lo["self_weight"] else 0):.6g}+({extra:.6g})\right)=\boxed{{{s.checks["total_downward"]:.6g}\ \mathrm{{lbf}}}}')
 st.markdown('### 3. Whole-frame free body and lifting reactions')
 st.image(overall_fbd(s),width='stretch')
 st.latex(r'\sum F_y=0:\quad \sum_j R_j-W_{\rm applied}=0')
 st.latex(r'\sum M_O=0:\quad \sum_j R_j x_j-\sum_i W_i x_i-\int w(x)x\,dx=0')
 if lo['equal_reactions']:
  st.latex(r'R_j=\frac{W_{\rm applied}}{n_{\rm holes}}'+fr'=\frac{{{s.checks["total_downward"]:.6g}}}{{{len(s.reactions)}}}=\boxed{{{s.reactions[0]["force"]:.6g}\ \mathrm{{lbf}}}}')
  st.write('Equal reactions were selected and checked against the assembled external moment. Two reference lifting-point elevations remove rigid translation/rotation; other lifting points can move under this idealized equalizing rigging.')
 elif len(s.reactions)==2:
  a,b=s.reactions;xa,xb=a['x'],b['x'];L=xb-xa
  Mext=sum(p['force']*p['x'] for p in s.reactions)-s.checks['moment_residual']
  abouta=Mext-s.checks['total_downward']*xa
  st.latex(r'R_2=\frac{\sum_i W_i(x_i-x_1)+\int w(x)(x-x_1)\,dx}{x_2-x_1}')
  st.latex(fr'R_2=\frac{{{abouta:.7g}}}{{{xb:.7g}-{xa:.7g}}}=\boxed{{{b["force"]:.7g}\ \mathrm{{lbf}}}}')
  st.latex(fr'R_1=W_{{\rm applied}}-R_2={s.checks["total_downward"]:.7g}-{b["force"]:.7g}=\boxed{{{a["force"]:.7g}\ \mathrm{{lbf}}}}')
 else:st.write('More than two level supports: reactions also depend on beam deformation and contact compatibility. They are solved together with the internal contact forces.')
 st.dataframe(pd.DataFrame([{'Hole':p['id'],'Beam':p['beam'],'x (in)':p['x'],'Reaction upward (lbf)':p['force']} for p in s.reactions]),hide_index=True,width='stretch')
 st.markdown('### 4. Coil contact and rod forces')
 st.write('A coil is a rigid vertical spacer. Bearing forces are compression-only and can be zero when a gap opens. Rods have no initial preload and carry tension only.')
 st.latex(r'C_i-H_i-W_i=0,\qquad g_i\geq0,\quad N_i\geq0,\quad g_iN_i=0')
 st.latex(r'A_t=\frac{\pi}{4}\left(d-\frac{0.9743}{n}\right)^2,\qquad k_r=\frac{E_rA_t}{L_r},\qquad T_r=k_r\max(v_{\rm nut}-v_{\rm weld},0)')
 if s.coils:
  ci=st.selectbox('Coil free-body diagram',[c['id'] for c in s.coils],key='sf_calc_coil')
  c=next(c for c in s.coils if c['id']==ci)
  cs=[q for q in s.forces if q.get('coil')==ci]
  st.image(coil_fbd(s,c),width='stretch')
  bot=sum(q['force'] for q in cs if q['kind']=='coil_lower');top=sum(q['force'] for q in cs if q['kind']=='coil_upper')
  st.latex(fr'C-H-W={bot:.7g}-{top:.7g}-{c["applied_weight"]:.7g}=\boxed{{{bot-top-c["applied_weight"]:.3g}\ \mathrm{{lbf}}}}')
 if s.rods:
  ri=st.selectbox('Worked rod',[r['id'] for r in s.rods],key='sf_calc_rod')
  r=next(r for r in s.rods if r['id']==ri)
  st.image(rod_fbd(r),width='stretch')
  st.latex(fr'A_t=\frac{{\pi}}{{4}}\left({r["diameter"]:.6g}-\frac{{0.9743}}{{{r["tpi"]:.6g}}}\right)^2=\boxed{{{r["At"]:.7g}\ \mathrm{{in^2}}}}')
  st.latex(fr'k_r=\frac{{({rm["E"]:.7g})({r["At"]:.7g})}}{{{r["effective_length"]:.7g}}}=\boxed{{{r["k"]:.7g}\ \mathrm{{lbf/in}}}}')
  st.latex(fr'T_r=k_r\Delta L=({r["k"]:.7g})({r["extension"]:.7g})=\boxed{{{r["tension"]:.7g}\ \mathrm{{lbf}}}}')
  st.latex(fr'\sigma_r=\frac{{T_r}}{{A_t}}=\frac{{{r["tension"]:.7g}}}{{{r["At"]:.7g}}}=\boxed{{{r["stress"]:.7g}\ \mathrm{{psi}}}}')
  st.caption('Auto free length is a geometric estimate between attachment seats; a manually entered effective length is used when Auto length is unchecked.')
 st.write('These contact/rod forces are a **coupled numerical solution** of beam deformation and the conditions above. The diagrams and worked equilibrium equations below use those solved forces.')
 st.markdown('### 5. Worked beam calculations')
 for bid,r in s.beam_results.items():
  with st.expander(bid+' · '+r['beam']['name'],expanded=(bid==next(iter(s.beam_results)))):
   st.image(member_fbd(s,bid),width='stretch')
   p=r['peak_stress'];x=p['x'];b=r['beam'];gg=s.geometry
   st.markdown('**Critical nominal-stress section**')
   st.latex(fr'x_s=\boxed{{{x:.7g}\ \mathrm{{in}}}}')
   probe=min(max(x,b['x']+1e-8),b['x']+b['length']-1e-8)
   # Use the same one-sided section as the force recovery.
   probe=min(max(x,p['element_start']+1e-8),p['element_end']-1e-8)
   if b.get('section_type')!='Custom properties':
    gross=gg.section(bid,probe,cut=False);net=gg.section(bid,probe);removed=gross.difference(net)
    gs=section_properties(gross);ns=section_properties(net)
    left,right=st.columns([1,1.3])
    with left:st.image(section_svg(net,ns,f'{bid} at x={num(x)} in',color=beam_color(m,bid)),width='stretch')
    with right:
     ar=removed.area
     st.latex(fr'A=A_g-A_r={gs.A:.7g}-{ar:.7g}=\boxed{{{ns.A:.7g}\ \mathrm{{in^2}}}}')
     if ar>1e-9:
      rs=section_properties(removed,allow_sliver=True)
      st.latex(r'\bar y=\frac{A_g\bar y_g-A_r\bar y_r}{A_g-A_r}')
      st.latex(fr'\bar y=\frac{{({gs.A:.6g})({gs.yc:.6g})-({rs.A:.6g})({rs.yc:.6g})}}{{{ns.A:.6g}}}=\boxed{{{ns.yc:.7g}\ \mathrm{{in}}}}')
      st.latex(r'I=\left[I_g+A_g(\bar y_g-\bar y)^2\right]-\left[I_r+A_r(\bar y_r-\bar y)^2\right]')
      st.latex(fr'I=[{gs.I:.6g}+({gs.A:.6g})({gs.yc-ns.yc:.6g})^2]-[{rs.I:.6g}+({rs.A:.6g})({rs.yc-ns.yc:.6g})^2]=\boxed{{{ns.I:.7g}\ \mathrm{{in^4}}}}')
     else:
      st.latex(fr'\bar y=\boxed{{{ns.yc:.7g}\ \mathrm{{in}}}},\qquad I=\boxed{{{ns.I:.7g}\ \mathrm{{in^4}}}}')
     st.latex(fr'c_t={ns.ctop:.7g}\ \mathrm{{in}},\qquad c_b={ns.cbottom:.7g}\ \mathrm{{in}}')
   else:st.write('This custom section uses the user-entered A, I and extreme-fibre distances; it has no geometric outline for automatic material removal.')
   st.markdown('**Internal forces from the left-hand cut**')
   st.latex(r'V(x)=\sum_{x_i\leq x}F_i+\int_{x_0}^{x}q(s)\,ds')
   st.latex(r'M(x)=\sum_{x_i\leq x}F_i(x-x_i)+\int_{x_0}^{x}q(s)(x-s)\,ds')
   st.dataframe(pd.DataFrame([{'Contribution':q['name'],'Moment at this cut (lbf·in)':q['value']} for q in r['moment_terms']]),hide_index=True,width='stretch')
   vals='+'.join(f'({q["value"]:.6g})' for q in r['moment_terms'] if abs(q['value'])>1e-8) or '0'
   st.latex(fr'M(x_s)={vals}=\boxed{{{p["M"]:.7g}\ \mathrm{{lbf\,in}}}}')
   st.latex(fr'V(x_s)=\boxed{{{p["V"]:.7g}\ \mathrm{{lbf}}}}')
   st.markdown('**Bending stresses at the remaining material surfaces**')
   st.latex(r'\sigma_t=-\frac{Mc_t}{I},\qquad \sigma_b=\frac{Mc_b}{I}')
   st.latex(fr'\sigma_t=-\frac{{({p["M"]:.7g})({p["ctop"]:.7g})}}{{{p["I"]:.7g}}}=\boxed{{{p["stress_top"]:.7g}\ \mathrm{{psi}}}}')
   st.latex(fr'\sigma_b=\frac{{({p["M"]:.7g})({p["cbottom"]:.7g})}}{{{p["I"]:.7g}}}=\boxed{{{p["stress_bottom"]:.7g}\ \mathrm{{psi}}}}')
   st.caption('Stress is nominal remaining-section bending stress. The maximum can occur away from the maximum moment because I and c change through the seats.')
   st.markdown('**Deflection from curvature and shear**')
   st.latex(r'G=\frac{E}{2(1+\nu)},\qquad \frac{d\theta}{dx}=\frac{M(x)}{EI(x)}')
   st.latex(r'v(x)=v_0+\theta_0\ell+\int_0^\ell\frac{(\ell-s)M(s)}{EI(s)}\,ds-\int_0^\ell\frac{V(s)}{GA_s(s)}\,ds')
   p=r['peak_deflection']
   st.latex(fr'x_v={p["x"]:.7g}\ \mathrm{{in}},\qquad v(x_v)=({p["v_reference"]:.6g})+({p["rotation_term"]:.6g})+({p["bending_term"]:.6g})+({p["shear_term"]:.6g})')
   st.latex(fr'v(x_v)=\boxed{{{p["v"]:.8g}\ \mathrm{{in}}}}')
   st.caption('Positive v is upward. Movement is relative to the lifting reference, not solely the member’s local bending bow. The shear integral is zero when shear deformation is disabled.')
 st.markdown('### 6. Equilibrium and numerical checks')
 st.latex(fr'\sum R-W={s.checks["reaction_sum"]:.8g}-{s.checks["total_downward"]:.8g}=\boxed{{{s.checks["vertical_residual"]:.3g}\ \mathrm{{lbf}}}}')
 st.latex(fr'\sum M_O=\boxed{{{s.checks["moment_residual"]:.3g}\ \mathrm{{lbf\,in}}}}')
 st.dataframe(pd.DataFrame(s.checks['beam_equilibrium']),hide_index=True,width='stretch')
 st.caption(f"Maximum free force residual: {s.checks['free_force_residual']:.3g} lbf. Maximum free moment residual: {s.checks['free_moment_residual']:.3g} lbf·in. Contact penetration: {s.checks['max_contact_penetration']:.3g} in. End-displacement recovery mismatch: {s.checks['max_recovery_mismatch']:.3g} in.")
 with st.expander('Advanced formulation, convergence and model scope'):
  st.write('The force-based beam element integrates variable bending/shear flexibility. Four-point Gauss integration is used inside each element; critical geometry changes are mesh boundaries. Gravity is represented by each element’s mean line load.')
  st.latex(r'A_s=\frac{I^2}{\int Q(y)^2/b(y)\,dy}')
  st.write('Effective shear area is a Jourawski energy estimate assuming uniform shear over the material width at each level; this is an approximation for open, hollow and built-up sections.')
  st.latex(r'\min_{d,e}\ \frac12d^TK_bd+\frac12\sum_r k_re_r^2-f^Td')
  st.latex(r'g_0+B_cd\geq0,\qquad B_rd+e\geq0,\qquad e\geq0')
  st.write('OSQP identifies an initial contact set, followed by a working-set solution of the equilibrium/compatibility equations. Primal gaps, compression multipliers, rod extension compatibility and force balance are verified independently. Tiny numerical stabilization selects otherwise free unloaded positions; a result is rejected if it supplies a material support force. Contacts are enforced as inequalities, without a contact penalty stiffness. ADMM residuals in the table describe the initial state before working-set refinement.')
  st.dataframe(pd.DataFrame(s.iterations),hide_index=True,width='stretch')
  for note in s.warnings:st.write('• '+note)
  st.write('No chain-angle/tilt analysis, lateral-torsional buckling, local cutout stress concentration, lifting-hole bearing/tear-out, weld/HAZ strength, pad bending or tube ovalization is included. A material yield comparison or user-entered allowable is not a complete lifting-capacity assessment.')
  st.markdown('[Beam formulation — Duke University](https://people.duke.edu/~hpgavin/StructuralDynamics/StructuralElements.pdf) · [OSQP formulation](https://osqp.org/docs/solver/index.html) · [Steel preset — SSAB](https://www.ssab.com/en-ca/brands-and-products/commercial-steel/structural-steel/csa-g40-21-13/44w) · [B7 — Portland Bolt](https://www.portlandbolt.com/technical/specifications/astm-a193/)')
