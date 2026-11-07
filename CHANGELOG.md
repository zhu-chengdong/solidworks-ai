# Changelog

English | [简体中文](CHANGELOG.zh-CN.md)

Published tags, their original notes and downloads remain in [GitHub Releases](https://github.com/zhu-chengdong/solidworks-ai/releases). Unpublished local candidates are not listed as public releases. All current releases are Windows x64 prereleases; native CAD acceptance targets SOLIDWORKS 2024.

## 0.15.0-rc4

- Adds a manufacturing-drawing module: upload one SLDPRT and describe the drawing, using configured planning/review and execution models. Qualified scope is a single solid part, A3 landscape, first-angle front/top/left views and bounded scale selection.
- Creates geometry-associated overall and top-entry circular-hole position dimensions plus genuine native hole callouts. Reads actual diameter, through, counterbore and blind-hole variables; hole locations reference arc centers. Unsupported side/bottom-entry holes stop instead of disappearing from the drawing.
- Creates a real horizontal or vertical straight full section through a requested location, with native parent/cut/label/arrow/hatching readback. Fills this drawing's title and generated drawing identifier without changing the original part.
- Verifies views, associated dimensions and hole variables after save/reopen. Exports native PDF, checks its actual character coordinates for values, clipping and dimension-text collisions, then requests a visual model review. Packages SLDDRW, copied dependency, PDF, preview and SHA256.
- Adds geometry-based callout routing and dimension-text clearance from hole extension lines, stopping when the bounded sheet has no suitable location. Sol MAX rejected crossing leaders/text in an earlier candidate, which was retained and not published.
- Fixes starvation of native callbacks on the idle STA owner, retaining serial work, draining accepted calls and releasing cached interfaces on their owning thread. Drawing document opens use one explicit call with local boundary/return-code/PID/identity diagnostics and no failure replay. Historical clr.dll failure evidence is kept separate from the reproduced apartment defect.
- Qualified on SOLIDWORKS2024 using a single-hole plate and a three-hole plate with through, counterbore and blind features, including the packaged Windows natural-language/upload path. Private keys, credentials and local CAD files are excluded from releases. 2026 remains unqualified.
- Output is an editable nominal drawing. Tolerances, GD&T, processes, offset sections, assembly drawings and multiple sheets require separate work; automatic drawing checks are not manufacturing certification.

## 0.14.0-rc11

- Adds Part.material with actual installed-library grades for6061/6061-T6,316 sheet/annealed bar, plain carbon steel and ABS, without density-only substitutions. Explicit custom density requires a label and kg/m3 and currently a single-configuration part.
- Verifies native maximum-accuracy mass/volume and material identity after save/reopen. Assembly BOM counts actual resolved instances and compares their known masses with the native total. Unknown engineering mass stays unknown; native defaults remain separate.
- Makes generic read-only mass queries use actual component materials and explicit custom density consistently with BOM. Rejects density-changing query arguments. Nested/unresolved components or differing referenced configurations remain unqualified.
- Repairs stock dimensions locked solely by downstream Hole Wizard dependencies while protecting standard features, consumed profiles, thread carriers and patterns. A separate-copy6061 plate edit verifies holes, other dimensions, mass and source hashes.
- Keeps Sol MAX planning/review and Terra MAX execution, separating reasoning effort from response capacity. Planning/review start at16384 tokens, configurable from1024 to128000. Ordinary planning permits one bounded capacity/structure correction; the retry capacity is at most twice the initial value, capped at128000. Execution MAX capacity and the free pool independent verified limits remain intact. A measured128000-token all-reasoning/no-plan failure exposed the old MAX budget override; this release fixes it.
- Fresh-task structural repair retains original intent plus bounded redacted field errors, without repeating the invalid draft. Source/revision contexts remain intact. Logs concrete failures/actual usage and stops before CAD if the single correction fails.
- Task failures retain exception types and code locations without exception text, arguments or local variables.
- A four-component6061 M12 plate,316 shaft and two shared resin blocks exercises nine real mates, zero interference,1/1/2 BOM, native save/reopen, actual four-body STEP reimport, four views, packaged natural-language planning/execution/review, independent mass query and settings-budget roundtrips.
- Preserves engineering-intent review. Automated CAD/material/mate/delivery qualification does not certify manufacturing, loads or motion.2024 is tested;2026, manufacturing drawings, mechanisms and configurations remain separate work. STEP qualification is geometry-only.

## 0.13.0-rc7

- Adds native editable stadium slots and simple polygon pockets through natural-language plans, on the highest local +Z planar face. Supports true Through All and flat-bottom blind cuts; slots use actual lines and circular arcs at arbitrary in-plane angles.
- Fixes the rejected structured-output schema for pocket XY coordinates by using bounded numeric arrays rather than tuple prefixItems; exact two-coordinate validation is retained. The failed candidate remains unpublished.
- Increases the single MAX request timeout from 600 to 1800 seconds after a measured planning timeout, retaining zero automatic retries and the requested reasoning effort. Timed-out usage is unknown, not zero-cost.
- Fixes GPT-6 Chat Completions compatibility with max_completion_tokens and maps user-facing MAX to the endpoint-supported highest xhigh effort, retaining the 128000 output budget and recording actual effort/capacity. Planning/review use Chat and native tools use the model-required Responses route, with model roles unchanged.
- Uses a compact native parameter contract for fresh tasks without attachments/history, retaining the complete schema, essential limits and four views while the compiler handles deterministic constraints/topology. Existing parts, images and revisions keep full context. Highest effort and128000 capacity remain unchanged; one same-task read-only plan passed in38.34s, without a general latency guarantee.
- Selects the tool transport required by the actual API: Terra function tools with reasoning use Responses at MAX; Sol planning/review use Chat at highest xhigh. Keeps models, keys and128000 capacity, fixing execution HTTP400; preview repair uses the same effective tool route.
- Fixes real cuts rejected when Instant3D returns ICE from GetTypeName2: resolves the underlying type through official GetTypeName and records both names. Still requires a true Cut, correct geometry/depth, consumed sketch and zero Fix. Dimension-tree identity uses the underlying type as well.
- Distinguishes overall slot length from arc-center spacing: native center spacing is overall length minus width. Records exact entry Z and blind depth instead of using an oversized blind cut as a through cut.
- Requires fully defined driving sketches without Fix, with actual consumed-sketch linkage, native Cut end conditions and depth readback. Rejects self-intersections, degenerate slots, excessive blind depths and incorrect removal volume.
- Independently verifies top/bottom straight edges, arc centers/radii/midpoints/endpoints and actual depth, against analytic removal volumes. Repeats checks after save/reopen and actual STEP reimport.
- A 180x100x20 mount combines a through slot, a 30-degree 6mm-deep slot and a 5mm-deep pentagonal pocket, with zero-Fix sketches and independent exact-volume acceptance. The packaged app runs the same design from natural language through planning, execution and review.
- Curved/side entries, overlap with prior voids, edge breakouts, arbitrary rounded pockets, CAM toolpaths and SOLIDWORKS2026 are not qualified by this release.

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
