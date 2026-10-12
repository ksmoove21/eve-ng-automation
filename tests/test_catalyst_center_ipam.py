import unittest

from eve_lab.catalyst_center import CatalystCenterError, CatalystCenterTaskError, TaskReference
from eve_lab.catalyst_center_ipam import GlobalIPv4Pool, GlobalIPv4PoolAdapter, IPv4Reservation, IPv4ReservationAdapter


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



class GlobalClient:
    def __init__(self, records, *, apply=True, task=True, task_fails=False, add_metadata=False):
        self.records = [dict(record, addressSpace=dict(record["addressSpace"])) for record in records]
        self.apply, self.task, self.task_fails, self.add_metadata = apply, task, task_fails, add_metadata
        self.requests = []

    def list_all(self, *_args, **_kwargs):
        return tuple(dict(record, addressSpace=dict(record["addressSpace"])) for record in self.records)

    def request(self, _method, _path, *, body, **_kwargs):
        self.requests.append(body)
        if self.apply:
            address = dict(body["addressSpace"])
            if self.add_metadata:
                address["dnsServers"] = ["resolver"]
            self.records.append({"id": "new-" + body["name"], "name": body["name"], "poolType": body["poolType"], "addressSpace": address})
        return {"response": {"taskId": "task-1", "url": "/task"}} if self.task else {}

    @staticmethod
    def task_reference(response):
        task = response.get("response", {}).get("taskId")
        return TaskReference(task) if task else None

    def wait_task(self, _task):
        if self.task_fails:
            raise CatalystCenterTaskError("failed")


def global_record(identity="global-id", name="global-existing", subnet="192.0.2.0", prefix=24, pool_type="Generic", **metadata):
    address = {"subnet": subnet, "prefixLength": prefix, **metadata}
    return {"id": identity, "name": name, "poolType": pool_type, "addressSpace": address}


class GlobalIPv4PoolAdapterTests(unittest.TestCase):
    def desired(self, **kwargs):
        values = {"name": "global-wanted", "pool_type": "Generic", "subnet": "192.0.2.0", "prefix_length": 24}
        values.update(kwargs)
        return GlobalIPv4Pool(**values)

    def test_exact_existing_pool_is_noop_and_preserves_id_and_metadata(self):
        client = GlobalClient([global_record(name="global-wanted", dnsServers=["resolver"], dhcpServers=[])])
        plan = GlobalIPv4PoolAdapter(client).reconcile([self.desired()])[0]
        self.assertEqual((plan.action, plan.observed_id, plan.expected_dns_servers, client.requests), ("noop", "global-id", ("resolver",), []))

    def test_dry_run_and_minimal_create_payload(self):
        client = GlobalClient([])
        adapter = GlobalIPv4PoolAdapter(client)
        self.assertEqual(adapter.reconcile([self.desired()], dry_run=True)[0].action, "create")
        self.assertEqual(client.requests, [])
        self.assertEqual(adapter.reconcile([self.desired()])[0].action, "create")
        self.assertEqual(client.requests, [{"name": "global-wanted", "poolType": "Generic", "addressSpace": {"subnet": "192.0.2.0", "prefixLength": 24}}])

    def test_rejects_duplicate_identity_name_and_overlap_without_post(self):
        adapter = GlobalIPv4PoolAdapter(GlobalClient([]))
        with self.assertRaisesRegex(ValueError, "names"):
            adapter.reconcile([self.desired(), self.desired(subnet="198.51.100.0")])
        with self.assertRaisesRegex(ValueError, "prefixes"):
            adapter.plan([self.desired(), self.desired(name="other")])
        with self.assertRaisesRegex(CatalystCenterError, "overlaps"):
            GlobalIPv4PoolAdapter(GlobalClient([global_record(subnet="192.0.2.0")])).plan([self.desired(subnet="192.0.2.128", prefix_length=25)])
        with self.assertRaisesRegex(CatalystCenterError, "already belongs"):
            GlobalIPv4PoolAdapter(GlobalClient([global_record(name="global-wanted")])).plan([self.desired(subnet="198.51.100.0")])
        self.assertEqual(adapter._client.requests, [])

    def test_rejects_immutable_existing_and_duplicate_controller_records(self):
        with self.assertRaisesRegex(CatalystCenterError, "immutable"):
            GlobalIPv4PoolAdapter(GlobalClient([global_record(name="other")])).plan([self.desired()])
        with self.assertRaisesRegex(CatalystCenterError, "duplicate"):
            GlobalIPv4PoolAdapter(GlobalClient([global_record(), global_record(identity="other", name="other")])).plan([self.desired()])

    def test_requires_task_and_exact_readback_metadata(self):
        with self.assertRaises(CatalystCenterTaskError):
            GlobalIPv4PoolAdapter(GlobalClient([], task_fails=True)).reconcile([self.desired()])
        with self.assertRaisesRegex(CatalystCenterTaskError, "no task ID"):
            GlobalIPv4PoolAdapter(GlobalClient([], task=False)).reconcile([self.desired()])
        with self.assertRaisesRegex(CatalystCenterError, "did not converge"):
            GlobalIPv4PoolAdapter(GlobalClient([], apply=False)).reconcile([self.desired()])
        with self.assertRaisesRegex(CatalystCenterError, "metadata"):
            GlobalIPv4PoolAdapter(GlobalClient([], add_metadata=True)).reconcile([self.desired()])

    def test_validates_ipv4_and_pool_type(self):
        with self.assertRaises(ValueError):
            self.desired(subnet="192.0.2.1")
        with self.assertRaises(ValueError):
            self.desired(pool_type="generic")
if __name__ == "__main__":
    unittest.main()
