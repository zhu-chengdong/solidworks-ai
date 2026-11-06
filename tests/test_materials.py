import unittest
from types import SimpleNamespace as Obj
from pydantic import ValidationError
from engineering.materials import MaterialSpec
from engineering.bom import summarize,rows

class PhysicalBOM(unittest.TestCase):
    def fixture(self):
        spec=Obj(parts=[Obj(id='plate',label='base')],instances=[Obj(id='a',part_id='plate'),Obj(id='b',part_id='plate')])
        physical={'mass_known':True,'mass_g':25.,'density_kg_m3':2700.,'material':'6061','density_source':'native_library_assignment'}
        components=[{'id':name,'part_id':'plate','physical_properties':dict(physical)} for name in ('a','b')]
        return spec,components
    def test_density_requires_explicit_units_and_label_and_cannot_override_grade(self):
        for values in ({'grade':'custom_density'},{'grade':'custom_density','label':'resin'},{'grade':'custom_density','label':'resin','density_kg_m3':float('nan')},
                {'grade':'aluminium_6061','density_kg_m3':1234}):
            with self.assertRaises(ValidationError):MaterialSpec(**values)
        self.assertEqual(MaterialSpec(grade='custom_density',label='resin',density_kg_m3=1234).density_kg_m3,1234)
    def test_repeated_instances_use_quantity_and_match_native_total(self):
        spec,components=self.fixture();summary=summarize(spec,components,50)
        self.assertTrue(summary['native_total_verified']);self.assertEqual(summary['mass_g'],50)
        bom=rows(spec,{'plate':{'path':'plate.SLDPRT'}},components)
        self.assertEqual(bom[0]['quantity'],2);self.assertEqual(bom[0]['total_mass_g'],50)
        with self.assertRaises(RuntimeError):summarize(spec,components,49)
    def test_unknown_material_keeps_total_unknown_and_bom_cells_empty(self):
        spec,components=self.fixture()
        components[1]['physical_properties'].update(mass_known=False,mass_g=None,density_kg_m3=None,material=None,density_source='unassigned_native_default')
        summary=summarize(spec,components,35)
        self.assertIsNone(summary['mass_g']);self.assertEqual(summary['known_subtotal_g'],25)
        self.assertEqual(summary['unknown_instances'],['b']);self.assertFalse(summary['native_total_verified'])
        # Separate configurations of a part cannot be silently merged.
        with self.assertRaises(RuntimeError):rows(spec,{'plate':{'path':'plate.SLDPRT'}},components)
        components[0]['physical_properties']=dict(components[1]['physical_properties'])
        row=rows(spec,{'plate':{'path':'plate.SLDPRT'}},components)[0]
        self.assertEqual(row['mass_state'],'unknown');self.assertEqual(row['unit_mass_g'],'');self.assertEqual(row['density_kg_m3'],'')
    def test_missing_or_duplicate_actual_instances_are_rejected(self):
        spec,components=self.fixture()
        with self.assertRaises(RuntimeError):summarize(spec,components[:1],25)
        components[1]['id']='a'
        with self.assertRaises(RuntimeError):summarize(spec,components,50)
    def test_planned_volume_change_keeps_material_and_final_saved_mass_checked(self):
        from unittest.mock import patch
        from engineering.materials import refresh,verify
        before={'mass_known':True,'material_name':'6061','material':'6061','database':'solidworks materials','configuration':'Default','density_source':'native_library_assignment','density_kg_m3':2700.,'mass_g':2.7,'volume_mm3':1000.}
        after={**before,'mass_g':1.35,'volume_mm3':500.}
        with patch('engineering.materials.measure',return_value=after):
            record=refresh(None,{'actual':before,'passed':True})
            self.assertEqual(record['assignment_actual_before_model_operations']['volume_mm3'],1000)
            self.assertEqual(record['actual']['volume_mm3'],500)
            self.assertTrue(verify(None,record)['passed'])
        with patch('engineering.materials.measure',return_value={**after,'density_kg_m3':1000.}):
            with self.assertRaises(RuntimeError):refresh(None,{'actual':before})
            with self.assertRaises(RuntimeError):verify(None,record)

if __name__=='__main__':unittest.main()
