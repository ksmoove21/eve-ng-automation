import copy
import unittest
from eve_lab.connection_styles import connection_key
from eve_lab.link_quality import reconcile_fixed_delays, QUALITY

class Fake:
    def __init__(self):
        self.links=[dict(source_type="node", source="node8", source_node_name="CE", source_label="Gi1", source_interfaceId=0,
                         destination_type="node", destination="node2", destination_node_name="PE", destination_label="Gi2", destination_interfaceId=1,
                         network_id=4,type="ethernet",color="yellow",label="192.0.2.0/30")]
        self.links[0].update({key:0 for key in QUALITY})
        self.links[0]["source_bandwidth"]=10000
        self.writes=[]; self.corrupt=None;self.stale=False; self.reads=0
    def request(self,method,path,payload=None):
        if method=="GET":
            self.reads+=1
            if self.stale and self.reads==2:self.links[0]["color"]="changed"
            return copy.deepcopy(self.links)
        self.writes.append((method,path,payload))
        self.links[0].update({key:payload[key] for key in QUALITY})
        if self.corrupt:self.links[0][self.corrupt]="changed"

class FixedDelayTests(unittest.TestCase):
    def desired(self,f):return [{"endpoints":connection_key(f.links[0]),"delay_ms":15}]
    def test_plan_is_read_only(self):
        f=Fake();self.assertEqual(len(reconcile_fixed_delays(f,"labs/test.unl",self.desired(f))),1);self.assertEqual(f.writes,[])
    def test_live_payload_persistence_preservation_and_idempotence(self):
        f=Fake();want=self.desired(f)
        self.assertEqual(len(reconcile_fixed_delays(f,"labs/test.unl",want,apply=True)),1)
        method,path,payload=f.writes[0]
        self.assertEqual((method,path),("PUT","labs/test.unl/quality"))
        self.assertEqual(payload["save"],1);self.assertEqual(payload["source"],"8")
        self.assertEqual(payload["source_bandwidth"],10000)
        self.assertEqual(payload["source_delay"],15);self.assertEqual(payload["destination_delay"],15)
        self.assertEqual(f.links[0]["network_id"],4);self.assertEqual(f.links[0]["color"],"yellow")
        self.assertEqual(reconcile_fixed_delays(f,"labs/test.unl",want,apply=True),[])
        reconcile_fixed_delays(f,"labs/test.unl",want,apply=True,enabled=False)
        self.assertEqual(f.links[0]["source_delay"],0);self.assertEqual(f.links[0]["source_bandwidth"],10000)
    def test_invalid_later_entry_prevents_all_writes(self):
        f=Fake();want=self.desired(f);want.append({"endpoints":[("node","Missing","Gi1"),("node","PE","Gi2")],"delay_ms":10})
        with self.assertRaises(ValueError):reconcile_fixed_delays(f,"labs/test.unl",want,apply=True)
        self.assertEqual(f.writes,[])
    def test_invalid_values(self):
        for value in (-1,30001,True,5.0,"5;reset"):
            f=Fake();want=self.desired(f);want[0]["delay_ms"]=value
            with self.assertRaises(ValueError):reconcile_fixed_delays(f,"labs/test.unl",want,apply=True)
            self.assertEqual(f.writes,[])
    def test_duplicate_and_ambiguous(self):
        for duplicate_native in (False,True):
            f=Fake();want=self.desired(f)
            if duplicate_native:f.links.append(copy.deepcopy(f.links[0]))
            else:want+=copy.deepcopy(want)
            with self.assertRaises(ValueError):reconcile_fixed_delays(f,"labs/test.unl",want,apply=True)
            self.assertEqual(f.writes,[])
    def test_missing_quality_and_invalid_native_id(self):
        for field,value in (("source","node8;reset"),("source_interfaceId","1;reset"),("type","serial")):
            f=Fake();want=self.desired(f);f.links[0][field]=value
            with self.assertRaises(ValueError):reconcile_fixed_delays(f,"labs/test.unl",want,apply=True)
            self.assertEqual(f.writes,[])
        f=Fake();want=self.desired(f);del f.links[0]["source_jitter"]
        with self.assertRaises(ValueError):reconcile_fixed_delays(f,"labs/test.unl",want,apply=True)
    def test_readback_detects_style_or_attachment_damage(self):
        for field in ("color","network_id","source_delay"):
            f=Fake();f.corrupt=field
            with self.assertRaises(RuntimeError):reconcile_fixed_delays(f,"labs/test.unl",self.desired(f),apply=True)
    def test_concurrent_change_prevents_write(self):
        f=Fake();f.stale=True
        with self.assertRaises(RuntimeError):reconcile_fixed_delays(f,"labs/test.unl",self.desired(f),apply=True)
        self.assertEqual(f.writes,[])
    def test_reversed_endpoints_bind_same_link(self):
        f=Fake();want=self.desired(f);want[0]["endpoints"]=list(reversed(want[0]["endpoints"]))
        reconcile_fixed_delays(f,"labs/test.unl",want,apply=True)
        self.assertEqual(f.writes[0][2]["source"],"8")
