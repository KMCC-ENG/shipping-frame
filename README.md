# Frame Load Analyzer

A separate Python/Streamlit app for the nominal bending response of shipping frames, with **beam layers added individually**. Units are **inches, lbf and psi**. The layout follows the earlier tube stress and centre-of-gravity apps, with independent source files and state keys so the apps can be combined later.

## Start the app

Use **Python 3.11 or 3.12**. Extract the ZIP and open a terminal in the folder containing this README.

```text
python -m pip install -r requirements.txt
python -m streamlit run shipping_frame_calculator.py
```

On Windows, after installing the requirements, you can also double-click `run_app.bat`. The app opens in your browser. Once Python and the requirements are installed, it can run locally without internet; the section editor uses bundled JavaScript/CSS and needs no Node installation or external drawing service.

For Streamlit Community Cloud, upload **all Python files, `requirements.txt`, the `assets` folder and `.streamlit/config.toml`** to a separate GitHub repository. Select `shipping_frame_calculator.py` as the main file. Keep the relative folder structure. Existing tube apps remain separate.

## Enter a frame

1. In **Design**, click **Add beam layer** to add one layer at a time. There is no fixed layer-count limit. A fully welded built-up section counts as one layer.
2. Expand each beam's row, then set its longitudinal start, length and vertical datum. Choose an angle, HSS, C-channel, a listed welded combination, a section with a flat bar, **Custom draw**, or **Custom properties**. Expanding/editing a beam or clicking **Inspect this beam** selects its cross-section view; the **Inspect beam** controls can also switch the view.
3. For welded combinations, set the component dimensions, orientation and offsets. Components can cover different portions of the beam length. Full composite action is assumed where the components overlap; weld capacity is not calculated.
4. Add lifting holes and rectangular blocks under the design inputs for their parent beam.
5. Add coils by centre x, centre y and outside radius. Intersecting coil cylinders automatically remove main-member material. You do not enter separate cutout radii or positions. Explicit lower/upper bearing selections are available when Auto chooses the wrong adjacent member.
6. Add rods by position, diameter/radius, thread pitch, welded beam and the beam with the nut on top. The schematic shows the weld in red and the nut/washer in gold. Override estimated attachment elevations and effective free lengths when needed.
7. In **Loading**, enter the total coil-package weight and how it is shared between longitudinal shipping frames. Enter relative coil weight shares if the coils have different weights. Beam/block/rod self-weight can be included automatically.
8. Review **Material**, then inspect the result tabs. The default load multiplier is 1.0 for static gravity; any project lifting multiplier must be supplied by the user.

The default design has **2 beams and no coils, rods, lifting points, blocks or additional loads**. Examples are added only when you choose to load one. The schematic and remaining-section view update while you edit. Press **Calculate results** (or the sidebar's **Calculate / refresh results**) to run the full analysis. After a design, loading or material change, the old results are hidden until you calculate again. Switching views and changing the inspection station reuse the current solution.

Each beam row has a **Remove layer** button. Removing a layer also removes rods connected to it, its lifting points, blocks and additional loads. Coil bearing selections referencing it return to Auto; the coils and other layers are retained. At least one layer remains. A newly added layer opens for editing and becomes the inspected beam. Saved models can contain more than five layers.

Identical immutable material sections share a bounded property cache, including their shear properties. This avoids repeating polygon integrations at every station when the section is unchanged. Exact geometry is the cache key; section properties and the mechanical equations are unchanged. On Streamlit versions with stateful tabs, only the selected result tab is rendered, so hidden graphs and calculation worksheets do not add work to each refresh.

A colored dashed line on the frame marks the selected section's **X position**. The X/Y rulers use the common frame datum. A beam keeps its color in the schematic, section preview, sketcher and calculation-page section drawings. Additional point loads and distributed loads appear on their assigned beams, including direction and factored magnitude; uniform loads also show intensity.

Inch-based dimension buttons change values by **0.5 in**. You can type exact decimal values, including smaller fractions such as 0.375 in. Counts, angles, material properties and loads retain their own unit-appropriate steps.

**Reset Design**, **Reset Loading** and **Reset Material** affect only their own tab. Design reset restores two beams and removes the designed coils/rods/holes/blocks, while retaining loading and materials. Loading reset clears additional loads, restores loading/analysis defaults and resets coil weight shares, while retaining geometry/materials. Material reset restores the default steels. If retained loads reference beams removed by a design reset, reassign those loads in Loading; they are not silently moved to another beam.

## Cross sections and section drawing

Preset dimensions are idealized **outside height, outside width and uniform thickness**, with sharp corners. They are not a database of certified rolled-section properties. Use actual wall thickness and dimensions; use Custom draw or manual properties when rolled radii or other details materially affect the result.

The section plane has horizontal **z** and vertical **y**. The app's `I`/`Ixx` is the second moment about the horizontal centroidal bending axis, `integral((y-ybar)^2 dA)`. Confirm your CAD axis before entering a manual Ixx.

Select **Custom draw**, then click **Open section sketcher**. A new section starts with a **blank canvas**. Click **Close sketcher** when finished; the drawing remains in your current design and reappears when reopened. Save the design JSON to keep completed outlines between browser sessions. The sketcher's input fields stay light with dark text in either app theme.

When drawing a polyline, click its starting point and move the cursor: a live length appears next to the segment. Click that dimension, or press **Tab**, enter a length in inches and press **Enter** to place the endpoint. The start point and current direction are retained. Select a finished shape and click its size labels to edit line lengths, rectangle width/height or circle/arc radius. Changing a polygon edge moves its endpoint, which also changes the adjoining edge; this is a simple geometric editor, not a solver that locks all existing dimensions. Close an outline before calculating section properties.

**Custom draw** provides rectangles, circles, closed polylines, arcs, fillets, curved polygon edges, numerical dimensions/coordinates, snap, ortho, pan/zoom, move, copy, rotate, mirror, delete and undo/redo. Add/subtract material operations run in drawing order. Open polylines remain construction until you close them. Numeric rectangle coordinates locate its lower-left corner; circle/arc coordinates locate its centre. Select a shape to edit its exact values. Corner/edge numbers start at 1. The outline is normalized to its lower-left local datum before the beam's position and component offsets are applied.

Curves are polygonized using the selected circle resolution. A closed outline is required to calculate section area and inertia. Invalid self-crossing regions are rejected. Built-up sections must be physically connected to develop the assumed composite action.

**Custom properties** accepts A, I, neutral-axis-to-top/bottom distances and effective shear area As. Ixx alone is insufficient for stress, shear flexibility and self-weight. This option has no geometric outline, so it cannot generate coil-seat removals or accept blocks. Use Custom draw for those members. Manual properties represent one uniform section for the full member length.

## Blocks, rods and lifting holes

- A **rectangular block** belongs to its welded parent beam; it is not an extra layer. Enter its longitudinal centre, bottom elevation, length along the beam, vertical height, depth and depth centre. It must touch its parent and be tangent to the coil. Its material, weight, local section contribution and coil contact are included. It stays rectangular rather than being automatically cut by the coil. Presence of a block does not guarantee a positive contact force during lifting.
- Rods are **hand-tight, with zero preload and tension only**. Their stiffness uses E times the tensile stress area divided by effective free length. A rod passing through an intermediate beam is not automatically tied to that beam. The entered welded end and top nut seat define its force path. Nut, washer and weld-metal weights are excluded; rod weight uses its nominal cylindrical envelope and is lumped at its welded beam.
- Lifting forces are assigned directly to the selected beam at each entered x. Hole diameter/elevation are shown on the schematic. Separate lifting plates, hole material removal, pin bearing and tear-out are outside this model.

Default frame steel is **CSA G40.21 44W** (E 29,000,000 psi, nu 0.30, weight density 0.2836 lbf/in³, Fy 44,000 psi, Fu 64,000 psi). Default rods are **ASTM A193 B7** (same E/nu/density, Fy 105,000 psi, Fu 125,000 psi through 2.5 in diameter). All values are editable. The 44W default yield applies through 2.5 in thickness. Supplied B7 strength does not establish the strength of its welded attachment or heat-affected region.

## Results and calculation worksheet

The result tabs are **Bending moment, Shear force, Deflection, Stress, Forces and Calculations**. Graphs can show one beam or all beams, with critical labels and hover values. Stress can show the magnitude envelope or signed top/bottom values. Duplicate longitudinal positions in CSV data retain either side of point loads and section changes.

**Calculations** contains equations, numerical substitutions and boxed results, with whole-frame, beam, coil and rod free-body diagrams. It shows actual remaining-section properties, weight allocation, lifting reactions, rod tension/stress, critical member moments/stresses, deflection terms and equilibrium checks. Coil/rod selectors let you review each connection. Advanced numerical details are collapsed below the worked calculations.

Use **Check mesh with finer divisions** in Calculations to compare peak nominal stress, movement and rod tension at a finer mesh (up to 400 divisions). A separate circle-resolution setting controls drawn-curve accuracy. Refinement of one does not replace checking the other.

Save a design as JSON and reopen it later. Chart and force data are downloadable as CSV. The `examples` folder contains the same editable layouts as the example menu.

## Mechanical model and limits

The solver uses small-deflection, linearly elastic, variable-section planar beam elements, with optional shear deformation. Section area, centroid, inertia, shear area and self-weight vary through coil cutouts, blocks and partial-length welded components. Coils are rigid vertical spacers. Coil/beam and beam/beam bearing is frictionless and compression-only; rods can go slack. Bearing faces must overlap in section depth.

OSQP supplies an initial contact set. A working-set refinement solves the coupled equilibrium/compatibility equations. The app independently checks gaps, compression multipliers, rod force/extension compatibility, stabilization forces and external force/moment balance before accepting a result. Contact itself uses inequality constraints, not a guessed penalty stiffness. Tiny numerical stabilization is rejected if it provides a material support force.

Shear area uses a Jourawski energy estimate with shear assumed uniform across material width at each elevation. This is approximate for angles, HSS and built-up profiles. If a cut removes the complete section or leaves material separated by an unsupported vertical gap, the model is rejected. Deep undercut seats, local lips, disconnected material or other local load paths may require shell/solid analysis.

Normal lifting mode restrains vertical movement at the entered lifting points and leaves member rotations free; it assumes level lifting and ignores horizontal chain forces. It does not solve chain geometry or package tilt. With two holes, reactions satisfy external force/moment equilibrium. With more holes, their stiffness compatibility also matters. A layout requiring a downward chain reaction is rejected; the app does not automatically solve a different slack-chain or tilted rigging arrangement.

**Assume equal reactions** applies to the holes on the analyzed frame, separately from weight sharing between shipping frames. The external moment must balance that assumption. In equal-reaction mode, loads are prescribed at all holes and two reference elevations remove rigid motion; other lifting points may move, as with ideal equalizing rigging. An incompatible layout is flagged rather than balanced by an invented restraining moment.

This is a **nominal beam-analysis tool, not a complete lifting-capacity check**. It does not calculate local notch stress concentration, weld/HAZ capacity, lifting-hole strength, pad bending, tube ovalization, torsion, biaxial bending, lateral-torsional buckling, rigging loads or plastic redistribution. An elastic stress above the entered yield strength is flagged; its associated deformation/load redistribution has not been corrected for yielding. Deflection is movement relative to the lifting reference, including any settlement/contact movement, not just the member's local bow.

The earlier reports that used uncut beam sections are **not validation references** for these cut frames. The four-layer example includes the discussed 3,964.8 lbf package weight, but its geometry is illustrative and must not be treated as a confirmed reconstruction of the original CAD frame. Examples can exceed yield and are not qualified shipping designs.

## Compatibility and source files

| File | Responsibility |
| --- | --- |
| `shipping_frame_calculator.py` | Standalone entry point and importable `render_app()`; only `main()` sets the page configuration |
| `frame_models.py` | Versioned `frame-load-analyzer/1` JSON input model and examples |
| `frame_geometry.py` | Material outlines, cutouts, section properties and bearing clearances |
| `frame_engine.py` | Importable `solve_frame(model)` and mesh comparison |
| `frame_visuals.py` | Frame/section schematics, FBDs, graphs and CSVs |
| `frame_calculations.py` | Worked calculation worksheet |
| `assets/` | Offline section sketcher HTML/CSS/JavaScript |
| `tests/`, `verification/` | Reference checks and recorded verification results |

UI/session keys start with `sf_`. The analysis modules do not require a running Streamlit page. Schema, units and naming are explicit for future integration; this app does not import or change the previous tube apps.

## Recheck the source

```text
python -m pip install pytest
python -m pytest tests -q
```

Optional developer checks for the sketcher use Node 24.15+:

```text
npm install --prefix tests
npm test --prefix tests
```

Node is **not required to run the app**. Reference coverage includes solid/hollow/angle sections, section subtraction, bearing depth alignment, closed-form simply supported beams with bending/shear deflection, asymmetric/equal reactions, unilateral contact, finite rod stiffness, block engagement, mesh refinement, single-layer and more-than-five-layer models, model round trips and Streamlit control/worksheet interactions. The recorded checks are implementation verification, not certification of a particular shipping frame.

The files in `verification/` retain the original mechanical benchmark record. The updated interface, tab resets and editable sketch dimensions are covered by the current tests in `tests/`.

## Technical references

- [Duke University: structural beam-element formulations](https://people.duke.edu/~hpgavin/StructuralDynamics/StructuralElements.pdf)
- [OSQP: quadratic-program formulation and optimality conditions](https://osqp.org/docs/solver/index.html)
- [SSAB: CSA G40.21 44W properties](https://www.ssab.com/en-ca/brands-and-products/commercial-steel/structural-steel/csa-g40-21-13/44w)
- [Portland Bolt: ASTM A193 size-dependent properties](https://www.portlandbolt.com/technical/specifications/astm-a193/)
- [Streamlit: components v2](https://docs.streamlit.io/develop/api-reference/custom-components/st.components.v2.component)
- [Shapely: geometric operations and curve approximation](https://shapely.readthedocs.io/en/stable/manual.html)
