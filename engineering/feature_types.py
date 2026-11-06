"""Resolve Instant3D wrappers using the official underlying feature API.

IFeature.GetTypeName2 documents ICE -> GetTypeName (also verified on 2024).
https://help.solidworks.com/2022/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IFeature~GetTypeName2.html
"""
def canonical_type(raw,legacy=None):
    if not isinstance(raw,str) or not raw:raise RuntimeError('Native feature type is unavailable')
    if raw!='ICE':return raw
    if not isinstance(legacy,str) or not legacy or legacy=='ICE':raise RuntimeError('Instant3D underlying feature type is unavailable')
    return legacy

def feature_type(feature):
    from scripts.sw_connect import get_com_member as get
    raw=get(feature,'GetTypeName2')
    legacy=get(feature,'GetTypeName') if raw=='ICE' else None
    return canonical_type(raw,legacy),raw
