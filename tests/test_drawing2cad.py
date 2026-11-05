import io,json,math,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
import ezdxf
from drawing2cad.parser import inspect_dxf,options,select_spec,DrawingError,exact_bounds
from workbench.drawing_inputs import DrawingStore,pin_drawings
from workbench.reference_inputs import ReferenceStore
from workbench.settings import UserFacingError
from drawing_fixtures import plate


class DrawingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def test_exact_arcs_slot_holes_and_area(self):
        path=self.root/'plate.dxf';plate(path);data=inspect_dxf(path)
        self.assertEqual(len(data['views']),1);view=data['views'][0]
        self.assertEqual(view['bounds_mm'],[-60,-40,60,40]);self.assertEqual(len(view['inner']),5)
        expected=120*80-(4-math.pi)*100-18*12-math.pi*36-4*math.pi*16
        self.assertAlmostEqual(view['area_mm2'],expected,places=7)
        self.assertEqual(data['dimension_conflicts'],0)
        spec,q=select_spec(data,options('厚度8毫米，所有内轮廓均为通孔'))
        self.assertIsNone(q);self.assertEqual(spec['thickness_mm'],8)
    def test_multiview_never_extrudes_all_views(self):
        path=self.root/'views.dxf';plate(path,multi=True);data=inspect_dxf(path)
        self.assertEqual(len(data['views']),3)
        spec,q=select_spec(data,options('厚度8mm，通孔'))
        self.assertIsNone(spec);self.assertIn('视图1',q)
        self.assertEqual(select_spec(data,options('视图1，厚度8mm，通孔'))[0]['id'],1)
    def test_missing_depth_and_through_intent(self):
        path=self.root/'plate.dxf';plate(path)
        spec,q=select_spec(inspect_dxf(path),options('做三维'))
        self.assertIsNone(spec);self.assertIn('厚度',q);self.assertIn('贯穿',q)
    def test_dimension_override_blocks(self):
        path=self.root/'conflict.dxf';plate(path,conflict=True);data=inspect_dxf(path)
        self.assertEqual(data['dimension_conflicts'],1)
        self.assertIsNone(select_spec(data,options('厚度8，通孔'))[0])
        self.assertEqual(select_spec(data,options('厚度8，通孔，忽略标注'))[0]['dimension_policy'],'ignored_by_user')
    def test_units_and_conflicts(self):
        path=self.root/'inch.dxf';plate(path,unit=1);data=inspect_dxf(path)
        self.assertAlmostEqual(data['views'][0]['bounds_mm'][2],60*25.4)
        with self.assertRaises(DrawingError):inspect_dxf(path,'mm')
        d=ezdxf.readfile(path);d.units=0;d.saveas(path)
        with self.assertRaisesRegex(DrawingError,'单位'):inspect_dxf(path)
        self.assertEqual(inspect_dxf(path,'mm')['mm_per_unit'],1)
    def test_open_gap_rejected(self):
        d=ezdxf.new();d.units=4;m=d.modelspace();m.add_line((0,0),(20,0));m.add_line((20,0),(20,20));m.add_line((20,20),(0,20));m.add_line((0,20),(0,.1));path=self.root/'gap.dxf';d.saveas(path)
        with self.assertRaisesRegex(DrawingError,'闭合'):inspect_dxf(path)
    def test_rotated_block_preserves_geometry(self):
        d=ezdxf.new();d.units=4;b=d.blocks.new('PART');b.add_lwpolyline([(0,0),(20,0),(20,10),(0,10)],close=True);d.modelspace().add_blockref('PART',(30,40),dxfattribs={'rotation':90});path=self.root/'block.dxf';d.saveas(path)
        self.assertAlmostEqual(inspect_dxf(path,'mm')['views'][0]['area_mm2'],200)
    def test_spline_and_nonplanar_rejected(self):
        d=ezdxf.new();d.units=4;d.modelspace().add_circle((0,0,1),10);path=self.root/'z.dxf';d.saveas(path)
        with self.assertRaisesRegex(DrawingError,'平面'):inspect_dxf(path)
        d=ezdxf.new();d.units=4;d.modelspace().add_spline([(0,0),(1,2),(2,0)]);d.saveas(path)
        with self.assertRaisesRegex(DrawingError,'SPLINE'):inspect_dxf(path)
    def test_upload_hash_and_pinning(self):
        path=self.root/'plate.dxf';plate(path);refs=ReferenceStore(self.root/'refs');store=DrawingStore(self.root/'drawings',refs)
        data=store.add(path.read_bytes(),'零件.dxf');files=store.resolve([data['id']]);job=Mock();job.output_dir=self.root/'task';job.drawing_inputs=[]
        pin_drawings(job,files);self.assertTrue((job.output_dir/job.drawing_inputs[0]['file']).exists())
        files[0][0].write_bytes(b'changed')
        with self.assertRaisesRegex(UserFacingError,'图纸'):store.resolve([data['id']])
    def test_invalid_container_rejected(self):
        store=DrawingStore(self.root,ReferenceStore(self.root/'refs'))
        for suffix in ['.dwg','.dxf','.pdf']:
            with self.assertRaises(UserFacingError):store.add(b'fake','fake'+suffix)
    def test_exact_circle_bounds(self):
        self.assertEqual(exact_bounds([{'kind':'circle','center':[10,20],'radius':30}]),[-20,-10,40,50])
    def test_pdf_pages_render_locally(self):
        import pypdfium2 as pdfium
        pdf=pdfium.PdfDocument.new();pdf.new_page(100,160);raw=io.BytesIO();pdf.save(raw);pdf.close()
        refs=ReferenceStore(self.root/'refs');store=DrawingStore(self.root/'drawings',refs)
        meta=store.add(raw.getvalue(),'drawing.pdf')
        self.assertEqual(meta['kind'],'pdf_image');self.assertEqual(len(meta['references']),1)
        self.assertTrue(refs.get(meta['references'][0]['id'])[0].exists())
        self.assertEqual(len(store.resolve([meta['id']])),1)
    def test_pdf_many_pages_rejected_before_render(self):
        import pypdfium2 as pdfium
        pdf=pdfium.PdfDocument.new()
        for _ in range(5):pdf.new_page(100,100)
        raw=io.BytesIO();pdf.save(raw);pdf.close()
        with self.assertRaisesRegex(UserFacingError,'4页'):DrawingStore(self.root/'drawings',ReferenceStore(self.root/'refs')).add(raw.getvalue(),'too-many.pdf')
    def test_unsupported_3d_intent_not_silently_omitted(self):
        for text in ['M6螺纹孔','建模并装配','创建曲面']:
            with self.assertRaises(DrawingError):options(text)
    def test_classic_2d_polyline(self):
        d=ezdxf.new('R12');d.units=4;d.modelspace().add_polyline2d([(0,0),(20,0),(20,10),(0,10)],close=True);path=self.root/'r12.dxf';d.saveas(path)
        self.assertAlmostEqual(inspect_dxf(path,'mm')['views'][0]['area_mm2'],200)
    def test_no_credentials_required_and_no_model_called_for_clarification(self):
        import time
        from workbench.jobs import JobManager
        from workbench.engine import WorkbenchEngine
        from workbench.settings import SettingsStore
        from workbench_support import MemoryVault
        store=SettingsStore(self.root/'settings',MemoryVault());engine=WorkbenchEngine(store)
        engine.settings.role=Mock(side_effect=AssertionError('Vector jobs must not resolve a paid model'))
        path=self.root/'plate.dxf';plate(path)
        drawings=DrawingStore(self.root/'drawings',ReferenceStore(self.root/'refs'));meta=drawings.add(path.read_bytes(),'plate.dxf')
        manager=JobManager(engine,self.root/'jobs')
        try:
            job=manager.submit('按图建模',drawing_inputs=drawings.resolve([meta['id']]))
            for _ in range(100):
                if not manager.active:break
                time.sleep(.02)
            result=manager.get(job['id']);self.assertEqual(result['phase'],'clarify');self.assertEqual(result['usage']['input_tokens'],0)
            self.assertEqual(result['routing']['mode'],'local_vector');engine.settings.role.assert_not_called()
            self.assertFalse(list(Path(result['output_dir']).rglob('*.SLDPRT')))
        finally:manager.pool.shutdown(wait=True)


if __name__=='__main__':unittest.main()
