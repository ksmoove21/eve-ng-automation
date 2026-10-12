import unittest

from eve_lab.catalyst_center import CatalystCenterError, CatalystCenterTaskError, TaskReference
from eve_lab.catalyst_center_sda import Layer3IPTransitHandoff, Layer3IPTransitHandoffAdapter


class Client:
    def __init__(self, records, *, apply=True, task=True, task_fails=False, invalid_assignment=False):
        self.records = [dict(record) for record in records]
        self.apply, self.task, self.task_fails, self.invalid_assignment = apply, task, task_fails, invalid_assignment
        self.requests = []

    def list_all(self, _path, *, query, **_kwargs):
        return tuple(dict(record) for record in self.records if record["fabricId"] == query["fabricId"])

    def request(self, _method, _path, *, body, **_kwargs):
        self.requests.append(body)
        if self.apply:
            for payload in body:
                assignment = {"localIpAddress": "198.51.100.1/30", "remoteIpAddress": "198.51.100.2/30"}
                if self.invalid_assignment:
                    assignment = {"localIpAddress": "198.51.100.1/24", "remoteIpAddress": "198.51.100.2/24"}
                self.records.append({"id": "new-" + payload["interfaceName"], **payload, **assignment})
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
        "transitNetworkId": "transit-a",
        "interfaceName": "GigabitEthernet1/0/1",
        "virtualNetworkName": "DEFAULT_VN",
        "vlanId": 300,
        "externalConnectivityIpPoolName": "pool-a",
        "localIpAddress": "198.51.100.1/30",
        "remoteIpAddress": "198.51.100.2/30",
    }
    value.update(overrides)
    return value


class Layer3IPTransitHandoffAdapterTests(unittest.TestCase):
    def desired(self, **overrides):
        value = {
            "network_device_id": "device-a",
            "fabric_id": "fabric-a",
            "transit_network_id": "transit-a",
            "interface_name": "GigabitEthernet1/0/1",
            "virtual_network_name": "DEFAULT_VN",
            "vlan_id": 300,
            "external_connectivity_ip_pool_name": "pool-a",
        }
        value.update(overrides)
        return Layer3IPTransitHandoff(**value)

    def test_matching_existing_handoff_is_noop_and_preserves_id(self):
        client = Client([record()])
        plan = Layer3IPTransitHandoffAdapter(client).reconcile([self.desired()])[0]
        self.assertEqual((plan.action, plan.observed_id, client.requests), ("noop", "handoff-id", []))

    def test_create_posts_only_controller_allocated_minimum_fields(self):
        client = Client([])
        plan = Layer3IPTransitHandoffAdapter(client).reconcile([self.desired()])[0]
        self.assertEqual(plan.action, "create")
        self.assertEqual(client.requests, [[{
            "networkDeviceId": "device-a", "fabricId": "fabric-a", "transitNetworkId": "transit-a",
            "interfaceName": "GigabitEthernet1/0/1", "virtualNetworkName": "DEFAULT_VN", "vlanId": 300,
            "externalConnectivityIpPoolName": "pool-a",
        }]])
        self.assertNotIn("localIpAddress", client.requests[0][0])
        self.assertNotIn("remoteIpAddress", client.requests[0][0])

    def test_rejects_desired_and_controller_identity_conflicts_without_post(self):
        client = Client([])
        adapter = Layer3IPTransitHandoffAdapter(client)
        with self.assertRaisesRegex(ValueError, "endpoints"):
            adapter.reconcile([self.desired(), self.desired(virtual_network_name="OTHER_VN")])
        self.assertEqual(client.requests, [])

        for field, value in (("virtualNetworkName", "OTHER_VN"), ("transitNetworkId", "other"), ("externalConnectivityIpPoolName", "other")):
            with self.subTest(field=field):
                with self.assertRaisesRegex(CatalystCenterError, "immutable"):
                    Layer3IPTransitHandoffAdapter(Client([record(**{field: value})])).plan([self.desired()])
        with self.assertRaisesRegex(CatalystCenterError, "duplicate"):
            Layer3IPTransitHandoffAdapter(Client([record(), record(identity="other", virtualNetworkName="OTHER_VN")])).plan([self.desired()])

    def test_requires_task_and_valid_controller_assigned_pair_and_readback(self):
        with self.assertRaises(CatalystCenterTaskError):
            Layer3IPTransitHandoffAdapter(Client([], task_fails=True)).reconcile([self.desired()])
        with self.assertRaisesRegex(CatalystCenterTaskError, "no task ID"):
            Layer3IPTransitHandoffAdapter(Client([], task=False)).reconcile([self.desired()])
        with self.assertRaisesRegex(CatalystCenterError, "did not converge"):
            Layer3IPTransitHandoffAdapter(Client([], apply=False)).reconcile([self.desired()])
        with self.assertRaisesRegex(CatalystCenterError, "IPv4 pair"):
            Layer3IPTransitHandoffAdapter(Client([], invalid_assignment=True)).reconcile([self.desired()])

    def test_validates_required_identity_and_vlan(self):
        with self.assertRaises(ValueError):
            self.desired(vlan_id=1002)
        with self.assertRaises(ValueError):
            self.desired(external_connectivity_ip_pool_name="")


if __name__ == "__main__":
    unittest.main()