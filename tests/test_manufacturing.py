import unittest
from types import SimpleNamespace as Obj
from unittest.mock import patch
from engineering.manufacturing_spec import ManufacturingRequest


class NativeViewNames(unittest.TestCase):
    def test_localized_names_are_matched_by_native_rotation_not_list_order(self):
        from engineering.manufacturing import resolve_standard_names
        names=['*正视于','*后视','*上视','*前视','*左视']
        matrices={'*后视':[2.]*9,'*上视':[5.]*9,'*前视':[1.]*9,'*左视':[3.]*9}
        self.assertEqual(resolve_standard_names(names,lambda n:matrices.get(n),lambda i:[float(i)]*9),
            {'front':'*前视','top':'*上视','left':'*左视'})

    def test_missing_native_orientation_is_not_silently_guessed(self):
        from engineering.manufacturing import resolve_standard_names
        with self.assertRaises(ValueError):resolve_standard_names(['*前视'],lambda n:[1.]*9,lambda i:[float(i)]*9)

    def test_drawing_view_names_need_no_english_or_chinese_model_alias(self):
        from engineering.manufacturing import resolve_standard_names
        values={'工程图视图3':[3.]*9,'工程图视图1':[1.]*9,'工程图视图2':[5.]*9}
        result=resolve_standard_names(list(values),values.get,lambda i:[float(i)]*9)
        self.assertEqual(result['front'],'工程图视图1')

    def test_request_rejects_unsupported_projection_and_nonfinite_scale(self):
        for data in ({'projection':'third_angle'},{'scale':float('nan')},{'section':{'axis':'offset'}}):
            with self.assertRaises(ValueError):ManufacturingRequest.model_validate(data)


class DynamicSelection(unittest.TestCase):
    def test_auto_returned_select_data_is_not_called_twice(self):
        from engineering.manufacturing import select_entities
        class AutoReturned:
            def __call__(self):raise RuntimeError('COM DISPID_VALUE member not found')
        selection=AutoReturned();manager=Obj(CreateSelectData=selection)
        view=object();calls=[]
        doc=Obj(ClearSelection2=lambda all:None)
        drawing=Obj(ActivateView=lambda name:True)
        entities=[Obj(Select4=lambda append,data:calls.append((append,data)) or True) for _ in range(2)]
        def native_get(obj,name,*args):
            if obj is doc and name=='SelectionManager':return manager
            if obj is manager and name=='CreateSelectData':return selection
            raise AssertionError(name)
        with patch('engineering.manufacturing.get',side_effect=native_get),patch('engineering.manufacturing.view_name',return_value='view1'),patch('engineering.manufacturing.typed',side_effect=lambda value,kind:value):
            select_entities(doc,drawing,view,entities)
        self.assertIs(selection.View,view)
        self.assertEqual([row[0] for row in calls],[False,True])

    def test_hole_position_uses_native_arc_center_instead_of_nearest_rim(self):
        from engineering.manufacturing import center_arc_endpoints
        class Dimension:
            ends={1:0,2:2}
            measured_mm=23.25
            def GetArcEndCondition(self,index):return self.ends[index]
            def SetArcEndCondition(self,index,condition):
                self.ends[index]=condition;self.measured_mm=30.;return 0
        dimension=Dimension();display=Obj(GetDimension2=lambda index:dimension)
        def native_get(obj,name,*args):return getattr(obj,name)(*args)
        with patch('engineering.manufacturing.typed',side_effect=lambda value,kind:value),patch('engineering.manufacturing.get',side_effect=native_get):
            result=center_arc_endpoints(display)
        self.assertEqual(result,[0,1]);self.assertEqual(dimension.measured_mm,30.)


class HoleCoverage(unittest.TestCase):
    def check_scope(self,axis,span,entries):
        from engineering.manufacturing import validate_hole_scope
        surface=Obj(IsCylinder=lambda:True,CylinderParams=lambda:[0,0,0,*axis,.003])
        face=Obj(GetSurface=lambda:surface,FaceInSurfaceSense=lambda:True,GetUVBounds=lambda:[0,span,0,.02])
        body=Obj(GetFaces=lambda:[face]);doc=Obj(GetBodies2=lambda *args:[body])
        def native_get(obj,name,*args):return getattr(obj,name)(*args)
        with patch('engineering.manufacturing.get',side_effect=native_get):validate_hole_scope(doc,entries)

    def test_side_entry_full_hole_is_not_silently_omitted(self):
        import math
        with self.assertRaisesRegex(ValueError,'Side/bottom-entry'):
            self.check_scope([1,0,0],2*math.pi,[{'center_mm':[0,0,20]}])

    def test_bottom_entry_with_no_top_rim_is_not_silently_omitted(self):
        import math
        with self.assertRaises(ValueError):self.check_scope([0,0,1],2*math.pi,[])

    def test_partial_cylindrical_fillet_is_not_mistaken_for_full_hole(self):
        import math
        self.check_scope([1,0,0],math.pi/2,[])


class LeaderRouting(unittest.TestCase):
    def holes(self):
        return [{'sheet_center_m':[x,.205,0.],'radius_mm':r} for x,r in ((.136,3.3),(.160,5.5),(.184,2.75))]

    def test_reproduces_counterbore_leader_crossing_the_next_blind_hole(self):
        from engineering.manufacturing_layout import clear_other_holes
        holes=self.holes()
        self.assertFalse(clear_other_holes([[.160,.205],[.22594,.20894]],holes[1],holes,1.))

    def test_three_real_test_holes_get_non_crossing_callout_placements(self):
        from engineering.manufacturing_layout import callout_anchor,clear_other_holes,intersects
        holes=self.holes();used=[];outline=[.11406,.16906,.20594,.24094]
        anchors=[callout_anchor(hole,holes,outline,used,i,1.) for i,hole in enumerate(holes)]
        for hole,anchor in zip(holes,anchors):self.assertTrue(clear_other_holes([hole['sheet_center_m'],anchor],hole,holes,1.))
        for i,a in enumerate(used):
            for b in used[i+1:]:self.assertFalse(intersects(*a['line'],*b['line']))
        self.assertLess(anchors[0][0],.11406);self.assertGreater(anchors[1][1],.24094)

    def test_single_hole_keeps_its_already_qualified_anchor(self):
        from engineering.manufacturing_layout import callout_anchor
        hole={'sheet_center_m':[.160,.205,0.],'radius_mm':6.75}
        self.assertEqual(callout_anchor(hole,[hole],[.11406,.16906,.20594,.24094],[],0,1.),[.22594,.22893999999999998])

    def test_overall_text_moves_away_from_three_hole_extension_lines(self):
        from engineering.manufacturing_layout import free_text_coordinate
        x=free_text_coordinate(.160,.120,.200,[.136,.160,.184])
        self.assertTrue(all(abs(x-line)>.005 for line in (.136,.160,.184)))

    def test_vertical_text_moves_away_from_shared_hole_row(self):
        from engineering.manufacturing_layout import free_text_coordinate
        self.assertGreater(abs(free_text_coordinate(.205,.175,.235,[.205])-.205),.005)

    def test_too_narrow_dimension_span_stops_instead_of_hiding_collisions(self):
        from engineering.manufacturing_layout import free_text_coordinate
        with self.assertRaises(ValueError):free_text_coordinate(.1,.099,.101,[.1])
