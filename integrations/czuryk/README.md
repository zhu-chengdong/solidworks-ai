# Selected SolidworksMCP integration

Upstream: https://github.com/czuryk/SolidworksMCP

Pinned commit: eccb8af4aa76416baf2a5ca99b256da19b73d9b6 (MIT).
The upstream source snapshot is unchanged; local adaptations are in native_only.py
reference_build.py and dimensioned.py. provenance.json records the downloaded archive hash.

Only validated prism/revolve profile data can reach the geometry compiler.
No upstream MCP server, execute_python tool, UI watchdog, window recovery or
window screenshot tools are started or exposed. The host supplies the existing
2024 COM connection on its one STA and serializes calls with the existing mutex.
Native SaveBMP/review exports provide visual evidence.

2026-11-01 local evidence:
- Cylinder creation, native parameter edit, save/reopen and STEP passed.
- L profile prism creation, 4800 mm3 volume and native preview passed.
- HTTP image upload -> OpenAI vision plan -> economical executor -> native MCP
  -> 40 x 30 x 8 mm L part, 4800 mm3, STEP and previews completed.
- The old parameter-carrier/equation-curve path produced real constraint warnings.
  The local dimensioned adapter now builds native line/circle profiles with
  explicit endpoint coincidence, horizontal/vertical relations and driving
  dimensions. The unmodified general checker confirms fully constrained status 3,
  zero Fix relations and consumption by a native feature for L profiles, cylinders
  and a stepped plate with three circular through holes.
- Radius/thickness driving edits, actual B-Rep volume changes, restoration and
  silent save/reopen checks passed. ForceRebuild3 is required after dimension edits
  on this installation; an EditRebuild3 success alone left stale body geometry.
- Native B-Rep checks verify all profile vertices and actual cylindrical hole
  centers/radii. Manual design/manufacturing review remains separate.
- Native-only audit: no UI recovery or window capture invoked.

The isolated qualification venv, downloaded ZIP, local CAD and API state are
excluded from public source and Windows bundles. NumPy and compiler modules are
loaded before worker startup to avoid a reproduced Windows DLL-load deadlock.

Scope: one prism with up to 12 circular through holes, solid axisymmetric
profiles, bounded elliptical multi-body lofts and a declared cartoon-aircraft
recipe. The local smooth-body implementation and pinned MIT API references are
documented in LOFT_REFERENCES.md. Arbitrary hidden structures and unrestricted
surface reconstruction are outside this implementation.
