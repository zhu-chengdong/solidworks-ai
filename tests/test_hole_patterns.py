import unittest,math
from pydantic import ValidationError
from engineering.patterns import HolePattern,validate_patterns
from engineering.standard_holes import StandardHole

class PatternSafety(unittest.TestCase):
    def test_grid_counts_seed_once_and_respects_negative_directions(self):
        op=HolePattern(kind='linear',seed_hole_index=0,count=3,direction='-x',spacing_mm=20,second_direction='+y',second_count=2,second_spacing_mm=12)
        self.assertEqual(op.points([30,-6,8]),[[30,-6,8],[10,-6,8],[-10,-6,8],[30,6,8],[10,6,8],[-10,6,8]])
    def test_circular_radius_and_instance_count(self):
        points=HolePattern(kind='circular',seed_hole_index=0,count=6,center_mm=[5,7]).points([35,7,12])
        self.assertEqual(len(points),6)
        self.assertTrue(all(math.isclose(math.dist(p[:2],[5,7]),30,abs_tol=1e-9) for p in points))
    def test_mirror_on_seed_and_duplicate_target_are_rejected(self):
        for holes,op in [([StandardHole(kind='clearance',size='M6',point_mm=[0,10,8])],HolePattern(kind='mirror',seed_hole_index=0)),
          ([StandardHole(kind='clearance',size='M6',point_mm=[-10,0,8]),StandardHole(kind='clearance',size='M6',point_mm=[10,0,8])],HolePattern(kind='linear',seed_hole_index=0,spacing_mm=20))]:
            with self.assertRaises(ValueError):validate_patterns(holes,[op])
    def test_unqualified_thread_seed_and_invalid_grid_stop_before_native_write(self):
        with self.assertRaises(ValueError):validate_patterns([StandardHole(kind='tapped',size='M6',point_mm=[10,10,8])],[HolePattern(kind='mirror',seed_hole_index=0)])
        with self.assertRaises(ValidationError):HolePattern(kind='linear',seed_hole_index=0,spacing_mm=10,second_count=2,second_direction='-x',second_spacing_mm=10)
        with self.assertRaises(ValidationError):HolePattern(kind='linear',seed_hole_index=0,spacing_mm=10,count=32,second_count=3,second_direction='+y',second_spacing_mm=10)
