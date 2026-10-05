import copy
import unittest
from eve_lab.connection_styles import connection_key,reconcile_connection_styles

class Fake:
    def __init__(self, network=False):
        self.running=False;self.writes=[]
        self.links=[{'source_type':'node','source':'node8','source_node_name':'B','source_label':'Gi1','source_interfaceId':0,
                     'destination_type':'network' if network else 'node','destination':'network4' if network else 'node2',
                     'destination_node_name':'A','destination_label':'port_2048' if network else 'Gi2',
                     'destination_interfaceId':'network' if network else 1,'network_id':4,'type':'ethernet'}]
    def request(self,method,path,payload=None):
        if method=='GET':
            if path.endswith('/topology'):return copy.deepcopy(self.links)
            if path.endswith('/networks'):return {'4':{'id':4,'name':'Services'}}
            if path.endswith('/nodes'):return {'8':{'status':int(self.running)}}
        self.writes.append((method,path,payload))
        assert path.endswith('/nodes/8/style')
        self.links[0].update({k:v for k,v in payload.items() if k not in ('id','node','interface_id','type')})

class ConnectionStyleTests(unittest.TestCase):
    def desired(self, fake):
        return [{'endpoints':connection_key(fake.links[0],{'4':{'name':'Services'}}),
                 'style':{'color':'rgba(174, 174, 12, 1)','label':'10.1.1.0/30','linkstyle':'StateMachine'}}]
    def test_direct_native_payload_and_idempotence(self):
        f=Fake();want=self.desired(f)
        self.assertEqual(len(reconcile_connection_styles(f,'labs/test.unl',want)),1)
        self.assertEqual(f.writes[0][2]['id'],'network_id:4')
        self.assertEqual(f.writes[0][2]['interface_id'],'0')
        self.assertEqual(reconcile_connection_styles(f,'labs/test.unl',want),[])
        self.assertEqual(len(f.writes),1)
    def test_infrastructure_uses_name_and_native_interface_identity(self):
        f=Fake(True);want=self.desired(f)
        self.assertIn(('network','Services',''),want[0]['endpoints'])
        reconcile_connection_styles(f,'labs/test.unl',want)
        self.assertEqual(f.writes[0][2]['id'],'iface:node8:0')
    def test_missing_connection_preflight_prevents_partial_mutation(self):
        f=Fake();want=self.desired(f)
        want.append({'endpoints':[('node','Missing','Gi1'),('node','A','Gi2')],'style':{}})
        with self.assertRaises(ValueError):reconcile_connection_styles(f,'labs/test.unl',want)
        self.assertEqual(f.writes,[])
    def test_running_node_blocks_styles(self):
        f=Fake();f.running=True
        with self.assertRaises(ValueError):reconcile_connection_styles(f,'labs/test.unl',self.desired(f))
        self.assertEqual(f.writes,[])
    def test_payload_cannot_change_attachment(self):
        f=Fake();want=self.desired(f);want[0]['style']['network_id']=99
        with self.assertRaises(ValueError):reconcile_connection_styles(f,'labs/test.unl',want)
        self.assertEqual(f.writes,[])
    def test_endpoint_order_does_not_change_binding(self):
        f=Fake();want=self.desired(f);want[0]['endpoints']=list(reversed(want[0]['endpoints']))
        reconcile_connection_styles(f,'labs/test.unl',want)
        self.assertEqual(f.writes[0][2]['node'],'8')
