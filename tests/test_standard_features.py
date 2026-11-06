import unittest
from pydantic import ValidationError
from engineering.standard_holes import StandardHole
from engineering.threads import MetricThread
from engineering.spec import PartSpec
from engineering.feature_quality import classify

class StandardFeatures(unittest.TestCase):
    def test_modeled_thread_depth_is_explicit_and_bounded_by_drill(self):
        for opts in [dict(thread_representation='modeled'),dict(thread_representation='modeled',thread_depth_mm=13),dict(thread_representation='modeled',thread_depth_mm=8,outward='+y')]:
            with self.assertRaises(ValidationError):StandardHole(kind='tapped',size='M6',point_mm=[20,10,20],depth_mm=12,**opts)
    def test_bad_hole_family_or_nonfinite_entry_is_rejected(self):
        for opts in [dict(point_mm=[0,float('nan'),20]),dict(point_mm=[20,10,20],thread_representation='modeled',thread_depth_mm=8)]:
            with self.assertRaises(ValidationError):StandardHole(kind='clearance',size='M6',**opts)
    def test_duplicate_standard_entry_and_wrong_shaft_nominal_are_rejected(self):
        hole=dict(kind='clearance',size='M6',point_mm=[20,10,20])
        with self.assertRaises(ValidationError):PartSpec(id='a',shape='existing',source_id='a'*32,standard_holes=[hole,hole])
        with self.assertRaises(ValidationError):PartSpec(id='a',shape='shaft',diameter_mm=6,length_mm=20,metric_threads=[dict(size='M8',internal=False,point_mm=[0,0,20],length_mm=8)])
    def test_thread_kernel_counts_stay_visible(self):
        base=dict(constrained_status=3,dimension_count=2,fix_count=0,dangling=False,status='pass',consumed_by=['Base'])
        raw={'status':'review_required','sketches':[{**base,'name':'stock'},{**base,'name':'pos','consumed_by':['Hole']},{**base,'name':'kernel','fix_count':1,'status':'review_required','consumed_by':['Hole']}]}
        holes=[{'native':{'feature':'Hole','passed':True,'position':{'sketch_name':'pos'}}}]
        result=classify(raw,holes,[])
        self.assertEqual(result['status'],'native_standard_profiles_verified');self.assertEqual(result['native_managed_profile_fix_count'],1)
        self.assertEqual(result['sketches'][2]['fix_count'],1);self.assertEqual(result['sketches'][2]['raw_status'],'review_required')
    def test_free_sketch_fix_cannot_be_hidden_by_native_profile(self):
        raw={'status':'review_required','sketches':[dict(name='stock',constrained_status=3,dimension_count=2,fix_count=1,dangling=False,status='review_required',consumed_by=['Base'])]}
        result=classify(raw,[],[])
        self.assertEqual(result['status'],'review_required');self.assertFalse(result['application_sketches_pass'])
