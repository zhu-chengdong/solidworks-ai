# Third-party notices

The desktop integration is distributed under the root MIT license.
The vendored automation engine originates from
https://github.com/wzyn20051216/solidworks-automation-skill and retains
Copyright (c) 2026 SolidWorks Automation Skill Contributors and its MIT license.
See vendor/source-manifest.json and PATCHES.md for provenance and local changes.

The Windows distribution includes Python and installed runtime dependencies.
Their distribution metadata and available license files are copied into licenses/;
DEPENDENCIES.json records the installed versions and license expressions.
These notices do not replace third-party license terms.

The selected reference geometry compiler originates from
https://github.com/czuryk/SolidworksMCP at the pinned commit in
integrations/czuryk/provenance.json. Copyright (c) 2026 Samsaam Ali Baig.
Its MIT license is retained at integrations/czuryk/source/LICENSE.
The original upstream source is unchanged. The local adapter restricts control to
native SolidWorks 2024 COM and exposes bounded prism/revolve specifications.
The local dimensioned adapter replaces equation-curve/fixed-point construction
with native line/circle profiles, geometric relations and driving dimensions;
it also supports explicitly specified circular through holes in prism profiles.
NumPy, SciPy, OpenCV headless, scikit-image, Shapely and SymPy support this compiler;
their notices and dependency metadata are included in the desktop distribution.

The independent local loft adapter also references native API patterns from
hjbaard/SolidWorks-MCP (a7fd83cba7f8970926a677bdf5a22c30e280690f),
Copyright (c) 2026 Henk Jan Baard, and
HarrierPigeon/Solidworks-MCP-Server (60c11fe45b6cfc60c4e2da8ad41fc725a48bf8ea),
Copyright (c) 2026 Joseph Robertson. Both use MIT; their full notices are retained
in release_tools/licenses and the Windows licenses/ directory. See
integrations/czuryk/LOFT_REFERENCES.md for the local implementation and scope.

PyMuPDF / MuPDF, OCCT, neural model weights and external solvers are not
included in this basic desktop bundle. Optional PDF text-layout review is unavailable
in this bundle. PyMuPDF has separate AGPL/commercial licensing; adding it to a
future distribution requires a separate distribution decision.

No SolidWorks executable, installer, SDK/PIA DLL, CAD project, account credential,
personal task history or model-service credit is distributed. SolidWorks and all
model-service accounts are supplied by the end user.
