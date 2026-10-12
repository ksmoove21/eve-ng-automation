import unittest

from eve_lab.catalyst_center import CatalystCenterError, CatalystCenterTaskError, TaskReference
from eve_lab.catalyst_center_sda import Layer3VirtualNetwork, Layer3VirtualNetworkAdapter


class Client:
    def __init__(self, records, *, apply=True, task_fails=False, returns_task=True, changes_id=False, detaches_fabric=False, adds_fabric=False, reorder_readback=False):
        self.records = [dict(record) for record in records]
        self.apply = apply
        self.task_fails = task_fails
        self.returns_task = returns_task
        self.changes_id = changes_id
        self.detaches_fabric = detaches_fabric
        self.adds_fabric = adds_fabric
        self.reorder_readback = reorder_readback
        self.reads = 0
        self.requests = []

    def list_all(self, *_args, **_kwargs):
        self.reads += 1
        result = []
        for record in self.records:
            copy = dict(record)
            if self.reorder_readback and self.reads > 1:
                copy["fabricIds"] = list(reversed(copy["fabricIds"]))
            result.append(copy)
        return tuple(result)


    def request(self, method, _path, *, body, **_kwargs):
        self.requests.append((method, body))
        if self.apply:
            for payload in body:
                if method == "POST":
                    self.records.append({"id": f"id-{payload['virtualNetworkName']}", **payload})
                else:
                    for record in self.records:
                        if record["id"] == payload["id"]:
                            record.update(payload)
                            if self.changes_id:
                                record["id"] = "unexpected-id"
                            if self.detaches_fabric:
                                record["fabricIds"] = [payload["fabricIds"][-1]]
                            if self.adds_fabric:
                                record["fabricIds"].append("fabric-unexpected")
        return {"response": {"taskId": "task-1", "url": "/task"}} if self.returns_task else {}

    @staticmethod
    def task_reference(response):
        task = response.get("response", {}).get("taskId")
        return TaskReference(task, response["response"].get("url")) if task else None

    def wait_task(self, _task):
        if self.task_fails:
            raise CatalystCenterTaskError("failed")


class Layer3VirtualNetworkAdapterTests(unittest.TestCase):
    def test_idempotent_dry_run_and_reconcile_do_not_mutate(self):
        client = Client([{"id": "id-a", "virtualNetworkName": "VN-A", "fabricIds": ["fabric-a"]}])
        adapter = Layer3VirtualNetworkAdapter(client)
        desired = [Layer3VirtualNetwork("VN-A", ("fabric-a",))]

        self.assertEqual(adapter.plan(desired)[0].action, "noop")
        self.assertEqual(adapter.reconcile(desired, dry_run=True)[0].action, "noop")
        self.assertEqual(adapter.reconcile(desired)[0].action, "noop")
        self.assertEqual(client.requests, [])

    def test_update_preserves_id_extra_membership_and_anchor(self):
        client = Client(
            [{"id": "id-a", "virtualNetworkName": "VN-A", "fabricIds": ["fabric-existing"], "anchoredSiteId": "site-anchor"}]
        )

        plan = Layer3VirtualNetworkAdapter(client).reconcile(
            [Layer3VirtualNetwork("VN-A", ("fabric-requested",), "site-anchor")]
        )[0]

        self.assertEqual(plan.action, "update")
        self.assertEqual(client.requests[0][1][0]["id"], "id-a")
        self.assertEqual(plan.expected_fabric_ids, ("fabric-existing", "fabric-requested"))
        self.assertEqual(client.records[0]["fabricIds"], ["fabric-existing", "fabric-requested"])
        self.assertEqual(client.records[0]["anchoredSiteId"], "site-anchor")

    def test_greenfield_anchor_uses_minimal_documented_post(self):
        client = Client([])

        plan = Layer3VirtualNetworkAdapter(client).reconcile(
            [Layer3VirtualNetwork("VN-NEW", ("fabric-a",), "site-anchor")]
        )[0]

        self.assertEqual(plan.action, "create")
        self.assertEqual(
            client.requests[0],
            ("POST", [{"virtualNetworkName": "VN-NEW", "fabricIds": ["fabric-a"], "anchoredSiteId": "site-anchor"}]),
        )

    def test_rejects_ordinary_anchor_conversion(self):
        client = Client([{"id": "id-a", "virtualNetworkName": "VN-A", "fabricIds": []}])

        with self.assertRaisesRegex(CatalystCenterError, "cannot be converted"):
            Layer3VirtualNetworkAdapter(client).plan([Layer3VirtualNetwork("VN-A", (), "site-anchor")])

    def test_rejects_invalid_desired_identity_types(self):
        with self.assertRaises(ValueError):
            Layer3VirtualNetwork(1)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            Layer3VirtualNetwork("VN-A", "fabric-a")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            Layer3VirtualNetwork("VN-A", (), 1)  # type: ignore[arg-type]

    def test_rejects_duplicate_controller_identities(self):
        duplicate_names = Client(
            [
                {"id": "id-a", "virtualNetworkName": "VN-A", "fabricIds": []},
                {"id": "id-b", "virtualNetworkName": "VN-A", "fabricIds": []},
            ]
        )
        with self.assertRaisesRegex(CatalystCenterError, "duplicate"):
            Layer3VirtualNetworkAdapter(duplicate_names).plan([])

    def test_rejects_controller_id_rotation_or_membership_detach(self):
        desired = [Layer3VirtualNetwork("VN-A", ("fabric-requested",))]
        changed_id = Client(
            [{"id": "id-a", "virtualNetworkName": "VN-A", "fabricIds": ["fabric-existing"]}], changes_id=True
        )
        with self.assertRaisesRegex(CatalystCenterError, "changed controller ID"):
            Layer3VirtualNetworkAdapter(changed_id).reconcile(desired)

        detached = Client(
            [{"id": "id-a", "virtualNetworkName": "VN-A", "fabricIds": ["fabric-existing"]}], detaches_fabric=True
        )
        with self.assertRaisesRegex(CatalystCenterError, "changed fabric membership"):
            Layer3VirtualNetworkAdapter(detached).reconcile(desired)

    def test_treats_readback_membership_order_as_semantic(self):
        client = Client(
            [{"id": "id-a", "virtualNetworkName": "VN-A", "fabricIds": ["fabric-existing"]}],
            reorder_readback=True,
        )
        plan = Layer3VirtualNetworkAdapter(client).reconcile([Layer3VirtualNetwork("VN-A", ("fabric-requested",))])[0]
        self.assertEqual(plan.action, "update")
        self.assertEqual(client.requests[0][1][0]["fabricIds"], ["fabric-existing", "fabric-requested"])

    def test_rejects_readback_membership_addition(self):
        client = Client(
            [{"id": "id-a", "virtualNetworkName": "VN-A", "fabricIds": ["fabric-existing"]}],
            adds_fabric=True,
        )
        with self.assertRaisesRegex(CatalystCenterError, "changed fabric membership"):
            Layer3VirtualNetworkAdapter(client).reconcile([Layer3VirtualNetwork("VN-A", ("fabric-requested",))])


    def test_requires_task_and_readback_convergence(self):
        task_fails = Client([], task_fails=True)
        with self.assertRaises(CatalystCenterTaskError):
            Layer3VirtualNetworkAdapter(task_fails).reconcile([Layer3VirtualNetwork("VN-NEW")])

        no_task = Client([], returns_task=False)
        with self.assertRaisesRegex(CatalystCenterTaskError, "no task ID"):
            Layer3VirtualNetworkAdapter(no_task).reconcile([Layer3VirtualNetwork("VN-NEW")])

        no_readback = Client([], apply=False)
        with self.assertRaisesRegex(CatalystCenterError, "did not converge"):
            Layer3VirtualNetworkAdapter(no_readback).reconcile([Layer3VirtualNetwork("VN-NEW")])


if __name__ == "__main__":
    unittest.main()
