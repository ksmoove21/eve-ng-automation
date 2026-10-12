import unittest

from eve_lab.catalyst_center import CatalystCenterError, CatalystCenterTaskError, TaskReference
from eve_lab.catalyst_center_ipam import IPv4Reservation, IPv4ReservationAdapter


class Client:
    def __init__(self, records, *, apply=True, task_fails=False, task=True, change_name=False):
        self.records = [dict(record) for record in records]
        self.apply, self.task_fails, self.task, self.change_name = apply, task_fails, task, change_name
        self.requests = []

    def list_all(self, *_args, **_kwargs):
        return tuple(dict(record) for record in self.records)

    def request(self, _method, _path, *, body, **_kwargs):
        self.requests.append(body)
        if self.apply:
            self.records.append({"id": "new-id", **body, **({"name": "unexpected-name"} if self.change_name else {})})
        return {"response": {"taskId": "task-1", "url": "/task"}} if self.task else {}

    @staticmethod
    def task_reference(response):
        task = response.get("response", {}).get("taskId")
        return TaskReference(task) if task else None

    def wait_task(self, _task):
        if self.task_fails:
            raise CatalystCenterTaskError("failed")


def record(identity, name="existing", site="site-a", subnet="10.0.0.0", prefix=24, global_pool="global-a", gateway="10.0.0.1"):
    return {"id": identity, "name": name, "poolType": "Generic", "siteId": site, "ipV4AddressSpace": {"subnet": subnet, "prefixLength": prefix, "globalPoolId": global_pool, "gatewayIpAddress": gateway}}


class IPv4ReservationAdapterTests(unittest.TestCase):
    def desired(self, **kwargs):
        values = {"name": "wanted", "pool_type": "Generic", "site_id": "site-a", "subnet": "10.0.0.0", "prefix_length": 24, "global_pool_id": "global-a", "gateway_ip_address": "10.0.0.1"}
        values.update(kwargs)
        return IPv4Reservation(**values)

    def test_idempotent_and_preserves_existing_id_and_display_name(self):
        client = Client([record("existing-id", name="owner-name")])
        plan = IPv4ReservationAdapter(client).reconcile([self.desired()])[0]
        self.assertEqual(plan.action, "noop")
        self.assertEqual(plan.observed_id, "existing-id")
        self.assertEqual(plan.expected_name, "owner-name")
        self.assertEqual(client.requests, [])

    def test_dry_run_and_create_task_readback(self):
        client = Client([])
        adapter = IPv4ReservationAdapter(client)
        self.assertEqual(adapter.reconcile([self.desired()], dry_run=True)[0].action, "create")
        self.assertEqual(client.requests, [])
        self.assertEqual(adapter.reconcile([self.desired()])[0].action, "create")
        self.assertEqual(client.requests[0]["ipV4AddressSpace"]["globalPoolId"], "global-a")

    def test_rejects_immutable_gateway_name_and_overlap_conflicts(self):
        with self.assertRaisesRegex(CatalystCenterError, "gateway conflict"):
            IPv4ReservationAdapter(Client([record("id")])).plan([self.desired(gateway_ip_address="10.0.0.2")])
        with self.assertRaisesRegex(ValueError, "names must be unique"):
            IPv4ReservationAdapter(Client([])).plan([self.desired(), self.desired(subnet="10.0.1.0", gateway_ip_address="10.0.1.1")])
        with self.assertRaisesRegex(CatalystCenterError, "overlaps"):
            IPv4ReservationAdapter(Client([record("id")])).plan([self.desired(subnet="10.0.0.128", prefix_length=25, gateway_ip_address="10.0.0.129")])

        with self.assertRaisesRegex(CatalystCenterError, "already belongs"):
            IPv4ReservationAdapter(Client([record("id", name="wanted")])).plan([self.desired(subnet="10.0.1.0", gateway_ip_address="10.0.1.1")])

    def test_requires_task_and_exact_readback(self):
        with self.assertRaises(CatalystCenterTaskError):
            IPv4ReservationAdapter(Client([], task_fails=True)).reconcile([self.desired()])
        with self.assertRaisesRegex(CatalystCenterTaskError, "no task ID"):
            IPv4ReservationAdapter(Client([], task=False)).reconcile([self.desired()])
        with self.assertRaisesRegex(CatalystCenterError, "did not converge"):
            IPv4ReservationAdapter(Client([], apply=False)).reconcile([self.desired()])
        with self.assertRaisesRegex(CatalystCenterError, "changed display name"):
            IPv4ReservationAdapter(Client([], change_name=True)).reconcile([self.desired()])

    def test_validates_ipv4_network_and_gateway(self):
        with self.assertRaises(ValueError):
            self.desired(subnet="10.0.0.1")
        with self.assertRaises(ValueError):
            self.desired(gateway_ip_address="10.0.1.1")


if __name__ == "__main__":
    unittest.main()
