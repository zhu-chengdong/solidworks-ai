import unittest
from pydantic import ValidationError
from engineering.spec import PartSpec
from engineering.dimensions import DimensionChange

class DimensionChanges(unittest.TestCase):
    def test_forbid_unbounded_or_stale_intent(self):
        for item in [dict(name='D1@Sketch1',before_value=8,value=float('nan')),dict(name='D1@Sketch1',before_value=8,value=8),dict(name='../file@Sketch',before_value=8,value=12)]:
            with self.assertRaises(ValidationError):DimensionChange(**item)
    def test_native_edit_requires_existing_source(self):
        change=dict(name='D1@Boss',before_value=8,value=12)
        with self.assertRaises(ValidationError):PartSpec(id='a',shape='plate',length_mm=100,width_mm=60,thickness_mm=8,dimension_changes=[change])
        part=PartSpec(id='a',shape='existing',source_id='a'*32,dimension_changes=[change])
        self.assertEqual(part.dimension_changes[0].unit,'mm')
        with self.assertRaises(ValidationError):PartSpec(id='a',shape='existing',source_id='a'*32,dimension_changes=[change,change])
