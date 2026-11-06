import sys, unittest
from types import SimpleNamespace as Obj, ModuleType
from unittest.mock import patch
from engineering.physical_query import report


class MaterialQuery(unittest.TestCase):
    def run_query(self, doc, physical, native=None):
        connect = ModuleType('scripts.sw_connect')
        connect.get_com_member = lambda obj, name, *args: getattr(obj, name)(*args) if callable(getattr(obj, name)) else getattr(obj, name)
        measurement = ModuleType('scripts.sw_measure')
        measurement.collect_mass_properties = lambda obj: {'errors':[], 'warnings':['legacy missing document material'], 'mass_g':1, 'surface_area_mm2':100}
        with patch.dict(sys.modules, {'scripts.sw_connect':connect, 'scripts.sw_measure':measurement}), patch('engineering.physical_query.measure', side_effect=lambda part: physical), patch('engineering.physical_query.native_values', return_value=native or {'mass_g':10., 'volume_mm3':1000., 'density_kg_m3':10000.}), patch('engineering.physical_query.config', return_value='Default'):
            return report(doc)

    def physical(self, known=True):
        return {'mass_known':known,'mass_g':10. if known else None,'volume_mm3':1000.,'density_kg_m3':10000. if known else None,'material':'resin' if known else None,'density_source':'explicit_custom_density' if known else 'unassigned_native_default','note':None if known else 'Unknown material'}

    def component(self, name='a', configuration='Default', kind=1):
        part=Obj(GetType=kind,GetPathName='part.SLDPRT')
        return Obj(Name2=name,ReferencedConfiguration=configuration,GetModelDoc2=part)

    def test_custom_density_is_known_without_library_name(self):
        result=self.run_query(Obj(GetType=1),self.physical())
        self.assertEqual(result['mass_g'],10);self.assertEqual(result['warnings'],[])
        self.assertTrue(result['read_only']);self.assertEqual(result['material'],'resin')

    def test_repeated_resolved_components_match_native_total(self):
        doc=Obj(GetType=2,GetComponents=lambda top:[self.component('a'),self.component('b')])
        result=self.run_query(doc,self.physical(),{'mass_g':20.,'volume_mm3':2000.,'density_kg_m3':10000.})
        self.assertEqual(result['mass_g'],20);self.assertTrue(result['physical_properties']['native_total_verified'])
        self.assertEqual(len(result['components']),2);self.assertEqual(result['warnings'],[])

    def test_unknown_part_mass_is_not_default_mass(self):
        result=self.run_query(Obj(GetType=1),self.physical(False))
        self.assertIsNone(result['mass_g']);self.assertIsNone(result['density_kg_m3'])
        self.assertEqual(result['native_default_or_assigned_mass_g'],10)
        self.assertEqual(result['status'],'warn')

    def test_unknown_component_keeps_assembly_mass_unknown(self):
        doc=Obj(GetType=2,GetComponents=lambda top:[self.component()])
        result=self.run_query(doc,self.physical(False))
        self.assertIsNone(result['mass_g']);self.assertFalse(result['physical_properties']['native_total_verified'])

    def test_inconsistent_native_assembly_total_is_rejected(self):
        doc=Obj(GetType=2,GetComponents=lambda top:[self.component()])
        with self.assertRaises(RuntimeError):self.run_query(doc,self.physical(),{'mass_g':11.,'volume_mm3':1000.,'density_kg_m3':11000.})

    def test_reference_configuration_is_never_switched(self):
        doc=Obj(GetType=2,GetComponents=lambda top:[self.component(configuration='Other')])
        with self.assertRaises(ValueError):self.run_query(doc,self.physical())

    def test_nested_or_unresolved_assemblies_are_rejected(self):
        for component in (self.component(kind=2),Obj(Name2='a',ReferencedConfiguration='Default',GetModelDoc2=None)):
            with self.assertRaises(ValueError):self.run_query(Obj(GetType=2,GetComponents=lambda top:[component]),self.physical())

    def test_density_argument_cannot_mutate_a_read_only_query(self):
        with self.assertRaises(ValueError):report(None,1234)


if __name__=='__main__':unittest.main()
