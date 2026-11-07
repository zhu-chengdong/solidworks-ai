# Native manufacturing drawing route

This adapter uses only the local SOLIDWORKS COM APIs. It does not expose generated
code, mouse/keyboard events, window messages, or PDF reconstruction as a CAD path.
The qualification target is SOLIDWORKS 2024; other installed years are not implied.

The bounded first route is one solid SLDPRT, A3 landscape, first-angle
front/top/left views, associated overall and top-hole position dimensions, native
hole callouts, one straight full section, SLDDRW, native PDF, a PDF-rendered PNG,
and a package containing the drawing and its copied part. Original part bytes are
pinned and checked. Unsupported operations must stop rather than be omitted.

## API evidence and local compatibility

- `swDwgPaperA3size=8`, verified in the installed 2024 `swconst.tlb`. The adapter
  reads back paper dimensions and first-angle settings from `ISheet.GetProperties2`.
- `IDrawingDoc.Create1stAngleViews2` creates the actual front/top/left views.
  Their `IView.ModelToViewTransform` rotations are matched to
  `IModelDoc2.GetStandardViewRotation(1/5/3)`; localized names or enumeration order
  do not decide orientation. Top is below front; left is to its right.
- Model-name lookup must be exact. The tested Chinese document uses localized
  names. Its built-in names return all-zero arrays from `GetNamedViewRotation`,
  so that method is not used as the identity proof for this route.
- Visible native vertices and circular edges are selected with `ISelectData.View`.
  Horizontal/vertical dimensions must return the measured value and attached
  entities. `IAnnotation.SetPosition2` and readback place their text in sheet space.
- Hole positions use the native `IDimension.SetArcEndCondition`: endpoints are
  numbered 1/2, center is 1, and success is 0. The adapter never sets a fabricated
  measured value or uses a Note in place of a dimension.
- `IDrawingDoc.AddHoleCallout2`, `IDisplayDimension.IsHoleCallout`, and real
  `GetHoleCalloutVariables` establish native hole-callout identity/specification.
  This 2024 installation needs the official dual-interface vtables for variable
  getters. Standard COM stream marshaling bridges the already connected pointer
  to the installed `comtypes` interfaces; it does not create another CAD instance.
- `IView.GetDisplayDimensions` is checked against `GetDisplayDimensionCount`.
  All values, references and hole variables are read again after save/reopen.
- A real drawing-view sketch supplies the selected cut line to
  `CreateSectionViewAt5`. Section type, parent, label, line/arrow data and actual
  face hatches are inspected. Arrow starts are checked against the intended cut.
- PDF export uses `IExportPdfData.SetSheets(3, actual BSTR sheet-name array)` and
  `IModelDocExtension.SaveAs`. The saved file remains a native drawing. PDFium
  inspects the actual exported values/character boxes and renders the PDF.

## Primary references

- [Create drawing view](https://help.solidworks.com/2021/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~CreateDrawViewFromModelView3.html)
- [Standard view IDs](https://help.solidworks.com/2024/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swStandardViews_e.html)
- [Native arc-end conditions](https://help.solidworks.com/2022/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDimension~SetArcEndCondition.html)
- [Native hole-callout variables](https://help.solidworks.com/2024/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ICalloutVariable.html)
- [Native section creation](https://help.solidworks.com/2018/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~CreateSectionViewAt5.html)
- [PDF sheet selection](https://help.solidworks.com/2025/English/api/sldworksapi/SolidWorks.interop.sldworks~SolidWorks.interop.sldworks.IExportPDFData~SetSheets.html)
- [PDF sheet constants](https://help.solidworks.com/2024/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swExportDataSheetsToExport_e.html)
- [COM interface marshaling](https://learn.microsoft.com/en-us/windows/win32/api/combaseapi/nf-combaseapi-comarshalinterface)

The installed official 2024 type library is the final signature/constant check
where online help redirects to another year. Native results and packaged-app
qualification are recorded separately; a documented API is not an acceptance.

The drawing carries nominal geometry. Unspecified tolerances, GD&T, loads,
processes and manufacturing certification are not inferred from a rendered PDF.
