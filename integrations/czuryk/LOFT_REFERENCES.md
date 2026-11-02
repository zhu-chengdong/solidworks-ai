# Native smooth-body integration

The local loft_spec.py and loft_native.py add bounded ellipse-section lofts and a
parameterized cartoon-aircraft recipe. They do not start another MCP server or
execute generated scripts. The original czuryk snapshot remains unchanged.

Native API patterns were cross-checked against these MIT projects on 2026-11-01:

- hjbaard/SolidWorks-MCP, commit a7fd83cba7f8970926a677bdf5a22c30e280690f,
  Docs/PROGRESS.md: offset planes, selecting actual plane features, stacked
  profiles with mark 1, and consistent loft seams. Copyright 2026 Henk Jan Baard.
- HarrierPigeon/Solidworks-MCP-Server, commit
  60c11fe45b6cfc60c4e2da8ad41fc725a48bf8ea, solidworks/features.py:
  InsertProtrusionBlend2 native feature creation. Copyright 2026 Joseph Robertson.

Full MIT notices are retained in release_tools/licenses and Windows licenses/.
These are API references, not a claim that either project supplies this complete
image-to-airplane workflow. The SolidWorks 2024 API signature is authoritative.

Each local ellipse exposes its axes through native construction lines,
coincidence and horizontal/vertical relations. The existing constraint checker
remains unchanged and requires status 3, driving dimensions and zero Fix.
Each component is one independently colored solid. Two components are built per
native call, with a saved checkpoint and a stop check between calls. A failed
batch is preserved for diagnosis; it is not automatically replayed.

Aircraft coordinates are X nose-to-tail, Y span and Z up. Hidden wings, tailplanes
and windows are mirrored by an explicit recipe. Image-derived proportions and
the demonstration scale are estimates. Separate solids overlap at their joints
and glass overlays. Their summed volumes are not the union volume or a reliable
mass of a manufactured airplane. This is an editable visual approximation.
Use SLDPRT for editable native features; STEP transfers solid geometry.
Native output titles include the task identifier: duplicate open titles were
observed to yield a successful STEP SaveAs of a different document on SW2024.
The local step_export.py adapter temporarily selects AP214 solid output, restores
the user's original preferences and compares exported B-Rep records with the
native part's actual solid count. Final delivery also reimports the STEP.
