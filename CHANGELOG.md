# Changelog

English | [简体中文](CHANGELOG.zh-CN.md)

Published tags, their original notes and downloads remain in [GitHub Releases](https://github.com/zhu-chengdong/solidworks-ai/releases). Unpublished local candidates are not listed as public releases. All current releases are Windows x64 prereleases; native CAD acceptance targets SOLIDWORKS 2024.

## 0.12.0-rc2

- Adds native associative hole linear patterns, perpendicular two-direction grids, full-circle circular patterns and XZ/YZ mirrors through natural-language plans. No per-hole copy substitution.
- Supports local +Z Hole Wizard clearance, counterbore and countersink seeds, signed X/Y linear directions, and explicit instance counts including the seed. Circular patterns require a unique native cylindrical axis at the exact requested center.
- Reads native seed linkage, counts and spacings; independently checks actual cylinder axes, radii, axial intervals, complete removal volume and preservation of existing holes. Checks survive save/reopen and actual STEP reimport.
- A 180x120x12 mount combines a 2x3 grid, six-counterbore bolt circle and mirror for 14 physical holes, with an independent exact-volume check. Additional trials cover negative directions, YZ mirrors, countersinks/blind holes and a 22-to-24-to-22 mm parameter cycle on a separate copy.
- Adds a bilingual peer capability comparison and implementation roadmap. Reduces duplicate cross-process COM reads inside a locked readback.
- Fixes a stale three-preview capability hint. Planner view declarations now derive directly from the native isometric/front/top/right renderer, with a regression contract test to prevent false unsupported decisions.
- General body/component/offset-plane mirrors, arbitrary existing-feature replication, modeled-thread patterns and SOLIDWORKS2026 are not qualified by this release.

## 0.11.0-rc3

- Adds native ISO Hole Wizard clearance, counterbore, countersink and tapped holes in coarse M3/M4/M5/M6/M8/M10/M12 sizes, with standard-table dimensions and close/normal/loose fits. Supports signed principal-axis planar entries and explicit blind/Through All conditions.
- Adds real metric internal/external threads. Distinguishes manufacturing tap drills with cosmetic callouts from theoretical-carrier modeled threads; checks entry, material span, drill/thread depths and library sizes. Modeled entry is limited to local +Z cylinders. No cosmetic/polyline fallback for modeled requests.
- Independently verifies pitch and handedness from native helical B-Rep edges, plus nominal radius, Thread definitions, real material removal, save/reopen and STEP. An inactive PitchOverride value is never mistaken for the effective pitch. Actual STEP reimport verifies exact bounds, volume, pitch and handedness; native blind depth and full swept-profile extent are reported separately.
- Preserves and reports native-library profile Fix relations separately. App-created stock/position sketches use driving constraints without added Fix. Generic dimension edits cannot bypass standard-feature parameter management.
- Packaged natural-language acceptance combines local thickness editing, R4 fillets, C1 chamfers, four ISO hole families and a real M6 blind thread. Separate native trials cover six-axis entries, origin positioning, M6 internal and M8 external threads; all earlier releases remain available.
- STEP reimport volume comparisons use maximum native integration accuracy without relaxing the tolerance. A standard-hole plate and real M8 threaded shaft assembly passes native mate, interference, save/reopen and STEP checks. Homepage download links now use the matching release tag.
- SOLIDWORKS2026, fine/imperial/pipe/multiple-start and non-Z modeled threads are not locally qualified. This release does not certify manufacturing tolerances or strength.

## 0.10.0-rc1

- Structured natural-language plans now support ordered constant-radius fillets and distance-angle chamfers on new or uploaded parts.
- Selects native Z-parallel edges, extreme-Z planar outer loops or exact circular hole mouths. Checks expected edge counts, excludes hole loops from the outer perimeter and never silently reduces requested sizes.
- After reopening, verifies native Fillet/Chamfer definitions, radius, distance, angle, selected-edge count and solid volume. A two-hole mount passed R4 vertical-corner fillets and a full C1/45-degree top perimeter chamfer against an independent volume calculation.
- Includes actual packaged-UI acceptance and standalone relocation tests. Variable-radius/face fillets, ambiguous multiple top faces and SOLIDWORKS2026 are not locally qualified. Standard holes and threads follow as separate validated updates.

## 0.9.0-rc1

- Adds structured natural-language local editing of uploaded SLDPRT driving dimensions, using native names, old values and units. CAD bytes stay local.
- Edits a separate copy and verifies requested dimensions, untouched parameters and the feature tree after rebuilding, saving and reopening. Ambiguous targets require clarification.
- Native SOLIDWORKS2024 acceptance changes a two-hole plate from 8 to 12 mm thick and its bores from 8 to 10 mm, preserving outline and hole positions. Includes native files, STEP, four views, checked delivery ZIP and source hashes.
- Requires an editable parametric part. Standard holes, real threads and general edge treatments are subsequent releases. SOLIDWORKS2026 has not been locally qualified.

## 0.8.0-rc1

- Add sloped and circular-arc orthographic silhouettes using exact native sketches, extrusion and two-direction outside cuts. Sampled polygons are never used to construct CAD geometry.
- Add planar entries along TOP/Z, FRONT/Y and RIGHT/X for through holes, blind holes and cylindrical counterbores, with local material and intersecting-envelope checks.
- Add drill points and countersinks with explicit included angles, built as native cut-revolves. Distinguish cylindrical depth from total depth including the drill point; ask for missing definitions.
- Verify native cylinder intervals, cone angles and end radii/apices, revolve angle, cut depth/end condition, exact volume, bounds and fully defined sketches, both before saving and after reopening.
- Evaluate native B-Rep edges for curved projection checks only, with a 0.002 mm verification chord target and 0.025 mm projection tolerance. The solid retains analytical geometry.
- Add downloadable sloped/side-hole and curved/drill-point sample drawings to the existing workbench. The deterministic vector route uses zero model API tokens.
- Add English and Chinese repository documentation, version history and links to older releases. The workbench interface remains Chinese in this release.

Entries must lie on complete axis-normal planar faces in the three documented directions. Reverse/oblique holes, intersecting hole envelopes, arbitrary freeform surfaces and unexplained internal geometry require additional engineering definition.

## 0.7.0-rc3

- Reconstruct consistent stepped orthographic silhouettes and validate native B-Rep projections and visible internal lines.
- Associate hole leaders with diameters/depths; support Z-axis flat-bottom blind/through holes and through/blind counterbores.
- Ask for missing view roles, depths and bottom shape. Check local wall thickness and both counterbore depths.
- Reject hidden lines not explained by recognized holes rather than filling unknown cavities.
- Handle exploded DWG leaders/hatches and use task-unique native/STEP filenames to avoid SOLIDWORKS 2024 title collisions.
- Reopen saved models and verify real feature definitions, cylindrical intervals, flat bottoms, exact volume and editable sketches. Include a dimensioned five-hole example.

## 0.6.0-rc1

- Add immutable DXF/DWG/PDF uploads and source hashes.
- Build exact line/arc/circle/polyline extrusions, circular holes and through slots without model credentials or tokens.
- Ask for view selection, thickness, units and through intent; stop on dimension conflicts.
- Convert DWG through native SOLIDWORKS, exporting only Model and restoring export settings.
- Verify fully defined sketches, zero Fix constraints, reopened geometry, STEP solid count and four native previews; deliver a checksummed ZIP.
- Render 1–4 PDF pages locally as reference images for the existing vision-model workflow, rather than claiming exact vector recovery.
- Retain optional Magpie/ModelScope routing. Real free-channel model and assembly acceptance remains pending usable credentials/quota.

## 0.4.0-rc13

- Validate orthographic orientation against native camera readback in a fixed assembly base frame.
- Label and display the current isometric/front/top/right previews.
- Allow one preview-only automatic correction and second planner review when visual review identifies an orientation/label issue.
- Preserve earlier model/delivery revisions; do not replay failed/interrupted corrections or bypass geometry/mate failures with new pictures.
- Reject invalid original delivery packages before creating a revision job.

Public release notes and downloads: [0.8.0-rc1](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.8.0-rc1), [0.7.0-rc3](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.7.0-rc3), [0.6.0-rc1](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.6.0-rc1), [0.4.0-rc13](https://github.com/zhu-chengdong/solidworks-ai/releases/tag/v0.4.0-rc13).
