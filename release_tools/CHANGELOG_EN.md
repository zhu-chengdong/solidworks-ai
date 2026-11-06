# Changelog

English | [简体中文](CHANGELOG.md)

Published tags, their original notes and downloads remain in [GitHub Releases](https://github.com/zhu-chengdong/solidworks-ai/releases). Unpublished local candidates are not listed as public releases. All current releases are Windows x64 prereleases; native CAD acceptance targets SOLIDWORKS 2024.

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
