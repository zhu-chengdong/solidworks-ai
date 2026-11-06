import unittest
from engineering.feature_types import canonical_type
class Instant3DTypes(unittest.TestCase):
    def test_underlying_cut_is_distinguished_from_a_boss_and_unresolved_wrapper(self):
        self.assertEqual(canonical_type('ICE','Cut'),'Cut')
        self.assertEqual(canonical_type('ICE','Extrusion'),'Extrusion')
        self.assertNotEqual(canonical_type('ICE','Extrusion'),'Cut')
        self.assertEqual(canonical_type('HoleWzd'),'HoleWzd')
        with self.assertRaises(RuntimeError):canonical_type('ICE','ICE')
        with self.assertRaises(RuntimeError):canonical_type('ICE')
if __name__=='__main__':unittest.main()
