import unittest

from eve_lab.catalyst_center import CatalystCenterError, CatalystCenterTaskError, TaskReference
from eve_lab.catalyst_center_sda import Layer2Handoff, Layer2HandoffAdapter


class Client:
    def __init__(self, records, *, apply=True, task=True, task_fails=False, change_external=False):
        self.records = [dict(record) for record in records]
        self.apply, self.task, self.task_fails, self.change_external = apply, task, task_fails, change_external
        self.requests = []

    def list_all(self, _path, *, query, **_kwargs):
        return tuple(dict(record) for record in self.records if record["fabricId"] == query["fabricId"])

    def request(self, _method, _path, *, body, **_kwargs):
        self.requests.append(body)
        if self.apply:
            for payload in body:
                external = payload["externalVlanId"] + 1 if self.change_external else payload["externalVlanId"]
                self.records.append({"id": "new-" + payload["interfaceName"], **payload, "externalVlanId": external})
        return {"response": {"taskId": "task", "url": "/task"}} if self.task else {}

    @staticmethod
    def task_reference(response):
        value = response.get("response", {}).get("taskId")
        return TaskReference(value) if value else None

    def wait_task(self, _task):
        if self.task_fails:
            raise CatalystCenterTaskError("failed")


def record(identity="handoff-id", **overrides):
    value = {
        "id": identity,
        "networkDeviceId": "device-a",
        "fabricId": "fabric-a",
        "interfaceName": "GigabitEthernet1/0/1",
        "internalVlanId": 208,
        "externalVlanId": 208,
    }
    value.update(overrides)
    return value


class Layer2HandoffAdapterTests(unittest.TestCase):
    def desired(self, **overrides):
        value = {
            "network_device_id": "device-a",
            "fabric_id": "fabric-a",
            "interface_name": "GigabitEthernet1/0/1",
            "internal_vlan_id": 208,
            "external_vlan_id": 208,
        }
        value.update(overrides)
        return Layer2Handoff(**value)

    def test_matching_existing_handoff_is_noop_and_preserves_id(self):
        client = Client([record()])
        plan = Layer2HandoffAdapter(client).reconcile([self.desired()])[0]
        self.assertEqual((plan.action, plan.observed_id, client.requests), ("noop", "handoff-id", []))

    def test_create_uses_documented_batch_fields_and_dry_run_does_not_mutate(self):
        client = Client([])
        adapter = Layer2HandoffAdapter(client)
        self.assertEqual(adapter.reconcile([self.desired()], dry_run=True)[0].action, "create")
        self.assertEqual(client.requests, [])
        self.assertEqual(adapter.reconcile([self.desired()])[0].action, "create")
        self.assertEqual(client.requests, [[{
            "networkDeviceId": "device-a", "fabricId": "fabric-a", "interfaceName": "GigabitEthernet1/0/1",
            "internalVlanId": 208, "externalVlanId": 208,
        }]])

    def test_rejects_desired_controller_and_external_vlan_conflicts_without_post(self):
        client = Client([])
        adapter = Layer2HandoffAdapter(client)
        with self.assertRaisesRegex(ValueError, "endpoints"):
            adapter.reconcile([self.desired(), self.desired(external_vlan_id=209)])
        self.assertEqual(client.requests, [])
        with self.assertRaisesRegex(CatalystCenterError, "immutable"):
            Layer2HandoffAdapter(Client([record(externalVlanId=209)])).plan([self.desired()])
        with self.assertRaisesRegex(CatalystCenterError, "duplicate"):
            Layer2HandoffAdapter(Client([record(), record(identity="other", externalVlanId=209)])).plan([self.desired()])

    def test_requires_task_and_exact_readback(self):
        with self.assertRaises(CatalystCenterTaskError):
            Layer2HandoffAdapter(Client([], task_fails=True)).reconcile([self.desired()])
        with self.assertRaisesRegex(CatalystCenterTaskError, "no task ID"):
            Layer2HandoffAdapter(Client([], task=False)).reconcile([self.desired()])
        with self.assertRaisesRegex(CatalystCenterError, "did not converge"):
            Layer2HandoffAdapter(Client([], apply=False)).reconcile([self.desired()])
        with self.assertRaisesRegex(CatalystCenterError, "immutable"):
            Layer2HandoffAdapter(Client([], change_external=True)).reconcile([self.desired()])

    def test_validates_reserved_vlans_and_required_identity(self):
        with self.assertRaises(ValueError):
            self.desired(internal_vlan_id=1002)
        with self.assertRaises(ValueError):
            self.desired(external_vlan_id=2046)
        with self.assertRaises(ValueError):
            self.desired(interface_name="")


if __name__ == "__main__":
    unittest.main()