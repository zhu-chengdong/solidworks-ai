import sys,unittest
from types import SimpleNamespace as Obj,ModuleType
from unittest.mock import patch
from engineering.dimensions import catalog

class Feature:
    def __init__(self,name,kind):self.Name=name;self.kind=kind;self.owner=None;self.children=[];self.sub=None;self.next=None;self.display=None
    def GetTypeName2(self):return self.kind
    def GetOwnerFeature(self):return self.owner
    def GetChildren(self):return self.children
    def GetFirstDisplayDimension(self):return self.display
    def GetNextDisplayDimension(self,_):return None
    def GetFirstSubFeature(self):return self.sub
    def GetNextSubFeature(self):return None
    def GetNextFeature(self):return self.next
    def dimension(self):
        value=Obj(FullName='D1@'+self.Name,SystemValue=.01,DrivenState=2)
        self.display=Obj(Type2=2,GetDimension2=lambda _:value)

class DimensionOwnership(unittest.TestCase):
    def test_downstream_wizard_does_not_own_stock_but_its_sketch_stays_protected(self):
        stock=Feature('Stock','Extrusion');stock.dimension();profile=Feature('StockSketch','ProfileFeature');profile.dimension()
        wizard=Feature('Wizard','HoleWzd');position=Feature('WizardPosition','ProfileFeature');position.dimension()
        stock.sub=profile;profile.owner=stock;stock.children=[wizard];stock.next=wizard
        wizard.sub=position;position.owner=wizard
        connector=ModuleType('scripts.sw_connect')
        def get(obj,name,*args,default=None):
            value=getattr(obj,name,default)
            return value(*args) if callable(value) else value
        connector.get_com_member=get
        with patch.dict(sys.modules,{'scripts':ModuleType('scripts'),'scripts.sw_connect':connector}):
            data=catalog(Obj(FirstFeature=lambda:stock))
            carrier=Feature('ThreadCarrier','Extrusion');carrier.dimension();thread=Feature('Thread','SweepThread');carrier.children=[thread]
            protected=catalog(Obj(FirstFeature=lambda:carrier))
        rows={r['feature']:r for r in data['dimensions']}
        self.assertTrue(rows['Stock']['editable']);self.assertTrue(rows['StockSketch']['editable'])
        self.assertFalse(rows['WizardPosition']['editable']);self.assertTrue(rows['WizardPosition']['native_standard_managed'])
        self.assertFalse(protected['dimensions'][0]['editable'])

if __name__=='__main__':unittest.main()
