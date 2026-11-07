# Native assembly drawings / 原生装配工程图

The workbench module **装配工程图** accepts a local ZIP with one SLDASM and all referenced SLDPRT files. CAD bytes stay local. The configured planner describes the bounded drawing request; the execution model invokes one fixed tool, and the planner visually reviews the actual native PDF render.

## Qualified scope

- SOLIDWORKS2024, one flat, resolved assembly and active referenced configurations; installed GB A3 and native BOM templates.
- A3 landscape, first-angle aligned front/top views, isometric view and native view labels.
- Genuine parts-only BOM with native item numbers, quantities, component identities and a linked source-name property on independent part copies.
- One native circular BOM balloon per instance, including repeated instances, with attached edge/component and numbering-source readback after reopening.
- Native PDF export, actual BOM cell and balloon-number matching, rendered preview, CSV and checksummed drawing/assembly/part dependency package.

The local fixture has seven instances and five part kinds: a base plate, two brackets, an upper plate, a shaft and two guide blocks. The tested quantities are1/2/1/1/2. Schema limits (up to12 part kinds and24 instances) are bounds, not a claim that every possible assembly within them has been qualified. Unsupported geometry/layouts stop explicitly.

Nested, unresolved, excluded-from-BOM, external-reference leaf parts, multiple referenced configurations, exploded/assembly-section/multiple-sheet drawings and manufacturing tolerances require separate work. This release does not infer material density or certify engineering use.

## Native interfaces and evidence

`solidworks_assembly_drawing` accepts a task-pinned `assembly-drawing-spec.json` and stage0-3. Calls run serially on the registered native STA. It uses `GetDocumentDependencies2` and `ReplaceReferencedDocument` only on independent copies, `IView.InsertBomTable4`, `IBomTableAnnotation.GetComponents2`, `IModelDocExtension.InsertBOMBalloon2`, and actual note attachment and numbering properties. A general table or custom-text note is not accepted as a BOM/balloon substitute.

Each stage checks immutable input hashes and checkpoint/attempt markers. A failed accepted write is not replayed. Native view rotation, BOM rows, component geometry/poses, balloons and source hashes are checked after save/reopen; the PDF is read using bundled PDFium. The package contains every copied CAD dependency and SHA256 evidence. Original files remain unchanged.

Before opening CAD, Windows available commit is checked independently from free physical RAM. References are saved through the active assembly without creating a graphics window for every child. After successful delivery, only this task's saved, identity-checked documents are closed. Other user documents are preserved. Leader assignment uses pure Python and does not load new scientific DLLs on the native STA.

Official method references: [InsertBomTable4](https://help.solidworks.com/2023/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~InsertBomTable4.html), [InsertBOMBalloon2](https://help.solidworks.com/2024/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IModelDocExtension~InsertBOMBalloon2.html), [GetBomBalloonText](https://help.solidworks.com/2024/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.INote~GetBomBalloonText.html).
## Balloon attachment clarity

Visible curve coordinates are part-local. Compose the component-instance
transform with the actual drawing-view transform, sample the native curves,
and use interior-point clearance from neighbouring outlines to select an
edge. Keep SW's persistent native attachment on that edge, then read back
the actual leader geometry before and after saving/reopening. SW2024 testing
showed that manually setting a leader point can drift after reopening; those
unqualified iterations were retained. Native component
association alone does not prove a visually unambiguous leader; Sol visual
review can still reject an occluded or misleading arrow.

Official API: [SetLeaderAttachmentPointAtIndex](https://help.solidworks.com/2023/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IAnnotation~SetLeaderAttachmentPointAtIndex.html),
[drawing views and visible model entities](https://help.solidworks.com/2021/english/api/sldworksapiprogguide/Overview/Drawing_Views_and_Model_Entities.htm).

