import unittest

from eve_lab.catalyst_center import CatalystCenterError, CatalystCenterTaskError, TaskReference
from eve_lab.catalyst_center_sda import Layer2VirtualNetwork, Layer2VirtualNetworkAdapter


class Client:
    def __init__(self, records, *, layer3_names=("L3-A",), apply=True, task=True, task_fails=False):
        self.records = [dict(record) for record in records]
        self.layer3_names, self.apply, self.task, self.task_fails = layer3_names, apply, task, task_fails
        self.requests = []

    def list_all(self, path, *, query=None, **_kwargs):
        if path.endswith("layer3VirtualNetworks"):
            return tuple({"virtualNetworkName": name} for name in self.layer3_names)
        return tuple(dict(record) for record in self.records if record["fabricId"] == query["fabricId"])

    def request(self, _method, _path, *, body, **_kwargs):
        self.requests.append(body)
        if self.apply:
            for payload in body:
                self.records.append({"id": "new-" + payload["vlanName"], **payload})
        return {"response": {"taskId": "task", "url": "/task"}} if self.task else {}

    @staticmethod
    def task_reference(response):
        task = response.get("response", {}).get("taskId")
        return TaskReference(task) if task else None

    def wait_task(self, _task):
        if self.task_fails:
            raise CatalystCenterTaskError("failed")


def record(identity="id-a", name="VLAN-A", vlan=109, traffic="DATA", association="L3-A"):
    return {"id": identity, "fabricId": "fabric-a", "vlanName": name, "vlanId": vlan, "trafficType": traffic, "associatedLayer3VirtualNetworkName": association}


class Layer2VirtualNetworkAdapterTests(unittest.TestCase):
    def desired(self, **kwargs):
        values = {"fabric_id": "fabric-a", "vlan_name": "VLAN-A", "traffic_type": "DATA", "vlan_id": 109, "associated_layer3_virtual_network_name": "L3-A"}
        values.update(kwargs)
        return Layer2VirtualNetwork(**values)

    def test_existing_exact_identity_is_noop(self):
        client = Client([record()])
        plan = Layer2VirtualNetworkAdapter(client).reconcile([self.desired()])[0]
        self.assertEqual((plan.action, plan.observed_id, client.requests), ("noop", "id-a", []))

    def test_create_uses_only_requested_documented_fields(self):
        client = Client([])
        plan = Layer2VirtualNetworkAdapter(client).reconcile([self.desired()])[0]
        self.assertEqual(plan.action, "create")
        self.assertEqual(client.requests, [[{"fabricId": "fabric-a", "vlanName": "VLAN-A", "trafficType": "DATA", "vlanId": 109, "associatedLayer3VirtualNetworkName": "L3-A"}]])

    def test_rejects_missing_l3_existing_association_and_duplicate_conflicts(self):
        with self.assertRaisesRegex(CatalystCenterError, "not present"):
            Layer2VirtualNetworkAdapter(Client([], layer3_names=())).plan([self.desired()])
        with self.assertRaisesRegex(CatalystCenterError, "immutable"):
            Layer2VirtualNetworkAdapter(Client([record(association=None)])).plan([self.desired()])
        with self.assertRaisesRegex(CatalystCenterError, "duplicate"):
            Layer2VirtualNetworkAdapter(Client([record(), record(identity="id-b")])).plan([self.desired()])

    def test_requires_task_and_readback(self):
        with self.assertRaises(CatalystCenterTaskError):
            Layer2VirtualNetworkAdapter(Client([], task_fails=True)).reconcile([self.desired()])
        with self.assertRaisesRegex(CatalystCenterTaskError, "no task ID"):
            Layer2VirtualNetworkAdapter(Client([], task=False)).reconcile([self.desired()])
        with self.assertRaisesRegex(CatalystCenterError, "did not converge"):
            Layer2VirtualNetworkAdapter(Client([], apply=False)).reconcile([self.desired()])

    def test_rejects_conflicting_desired_name_or_explicit_vlan_without_post(self):
        client = Client([])
        adapter = Layer2VirtualNetworkAdapter(client)
        with self.assertRaisesRegex(ValueError, "names"):
            adapter.reconcile([self.desired(), self.desired(vlan_id=110)])
        self.assertEqual(client.requests, [])
        with self.assertRaisesRegex(ValueError, "VLAN"):
            adapter.reconcile([self.desired(), self.desired(vlan_name="VLAN-B")])
        self.assertEqual(client.requests, [])

    def test_rejects_existing_duplicate_name_or_explicit_vlan(self):
        with self.assertRaisesRegex(CatalystCenterError, "duplicate"):
            Layer2VirtualNetworkAdapter(Client([record(), record(identity="id-b", name="VLAN-B")])).plan([self.desired()])
        with self.assertRaisesRegex(CatalystCenterError, "duplicate"):
            Layer2VirtualNetworkAdapter(Client([record(), record(identity="id-b", vlan=110)])).plan([self.desired()])
    def test_validates_vlan_range_and_traffic(self):
        with self.assertRaises(ValueError): self.desired(vlan_id=1002)
        with self.assertRaises(ValueError): self.desired(traffic_type="data")


if __name__ == "__main__": unittest.main()
