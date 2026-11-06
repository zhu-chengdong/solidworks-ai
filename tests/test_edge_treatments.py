import unittest
from unittest.mock import patch
from pydantic import ValidationError
from engineering.finishing import EdgeTreatment
from engineering.spec import PartSpec
from engineering.dimensions import verify

class EdgeTreatmentTests(unittest.TestCase):
    def test_ambiguous_or_nonfinite_selection_is_rejected(self):
        for item in [dict(kind='fillet',target='vertical_edges',size_mm=4),dict(kind='chamfer',target='hole_mouth',size_mm=1,expected_edges=1),dict(kind='fillet',target='top_outer',size_mm=float('inf'),expected_edges=4),dict(kind='chamfer',target='top_outer',size_mm=1,angle_deg=90,expected_edges=4)]:
            with self.assertRaises(ValidationError):EdgeTreatment(**item)
    def test_recipe_validation_is_retained_before_finishing(self):
        p=PartSpec(id='a',shape='plate',length_mm=100,width_mm=60,thickness_mm=8,edge_treatments=[dict(kind='fillet',target='vertical_edges',size_mm=4,expected_edges=4)])
        self.assertIsNone(p.expected_volume());self.assertEqual(p.expected_volume(include_treatments=False),48000)
    def test_new_features_do_not_hide_unrequested_dimension_changes(self):
        old={'name':'D1@Sketch','value':100,'unit':'mm'};changed={**old,'value':90}
        evidence={'before':{'features':{'Sketch':'ProfileFeature'},'dimensions':[old]},'changes':[],
            'after_operations':{'features':{'Sketch':'ProfileFeature','Fillet':'Fillet'},'dimensions':[changed]}}
        with patch('engineering.dimensions.catalog',return_value=evidence['after_operations']):
            result=verify(None,evidence)
        self.assertFalse(result['passed']);self.assertIn('D1@Sketch',result['issues'][0])
