import unittest
import sys
from types import SimpleNamespace as Obj
from unittest.mock import patch
from workbench.manufacturing_runner import run_manufacturing
from engineering.manufacturing_pdf import numeric_runs


class DrawingInputGate(unittest.IsolatedAsyncioTestCase):
    async def test_missing_source_clarifies_before_models_or_CAD(self):
        finished=[]
        job=Obj(cad_inputs=[],references=[],drawing_inputs=[],finish=lambda *args:finished.append(args))
        await run_manufacturing(None,job)
        self.assertEqual(finished[0][0],'clarify')

    async def test_multiple_sources_do_not_silently_pick_one_part(self):
        finished=[]
        job=Obj(cad_inputs=[{},{}],references=[],drawing_inputs=[],finish=lambda *args:finished.append(args))
        await run_manufacturing(None,job)
        self.assertEqual(finished[0][0],'clarify')

    async def test_nonvisual_reviewer_stops_before_native_drawing_or_model_call(self):
        finished=[]
        job=Obj(cad_inputs=[{}],references=[],drawing_inputs=[],finish=lambda *args:finished.append(args))
        profile={'provider':'deepseek','api_style':'chat_completions','vision':False,'model':'test'}
        engine=Obj(settings=Obj(read=lambda:{},role=lambda *args:dict(profile)))
        with patch('workbench.magpie.route_profiles',return_value=None):await run_manufacturing(engine,job)
        self.assertEqual(finished[0][0],'clarify')


class PDFTextRuns(unittest.TestCase):
    def test_native_hole_symbol_does_not_corrupt_diameter_or_depth(self):
        chars=[{'char':c,'index':i,'box_pt':[i,0,i+.8,1]} for i,c in enumerate('⌀13.50 DEPTH 12.00') if not c.isspace()]
        runs=numeric_runs(chars)
        self.assertEqual([r['value'] for r in runs],[13.5,12.])

    def test_separate_PDF_text_runs_do_not_merge_identical_numbers(self):
        chars=[{'char':'8','index':0,'box_pt':[0,0,1,1]},{'char':'0','index':1,'box_pt':[1,0,2,1]},
            {'char':'8','index':4,'box_pt':[10,0,11,1]},{'char':'0','index':5,'box_pt':[11,0,12,1]}]
        self.assertEqual([r['value'] for r in numeric_runs(chars)],[80.,80.])


@unittest.skipUnless(sys.platform=='win32','Native COM bridge test requires Windows')
class COMBridgeIdentity(unittest.TestCase):
    def test_marshaling_reuses_the_same_COM_object(self):
        import win32com.client
        from comtypes.client.dynamic import Dispatch
        from engineering.manufacturing_callouts import bridge_dispatch
        dictionary=win32com.client.Dispatch('Scripting.Dictionary')
        dictionary.Add('first',17)
        same=Dispatch(bridge_dispatch(dictionary))
        self.assertEqual(same.Count,1)
        dictionary.Add('second',19)
        self.assertEqual(same.Count,2)
