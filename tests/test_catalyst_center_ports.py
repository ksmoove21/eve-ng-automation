import unittest
from copy import deepcopy

from eve_lab.catalyst_center import CatalystCenterClient, CatalystCenterError, CatalystCenterTaskError, TaskStatus
from eve_lab.catalyst_center_ports import TrunkPortAssignment, TrunkPortAssignmentAdapter, normalize_vlan_ranges

PATH = "/dna/intent/api/v1/sda/portAssignments"


def desired(**overrides):
    values = dict(fabric_id="fabric-a", network_device_id="device-a", interface_name="GigabitEthernet1/0/24", native_vlan_id=1, allowed_vlan_ranges="10,20,30")
    values.update(overrides)
    return TrunkPortAssignment(**values)


def record(assignment=None, identity="port-a", **overrides):
    result = {"id": identity, **(assignment or desired()).payload()}
    result.update(overrides)
    return result


class Client:
    def __init__(self, records=(), *, apply=True, task=True, task_error=False, after_write=None):
        self.records = deepcopy(list(records))
        self.apply, self.task, self.task_error, self.after_write = apply, task, task_error, after_write
        self.reads, self.requests, self.waits = [], [], []
        self.ignore_filter = False
        self.status_override = None

    def list_all(self, path, *, query, limit, operation):
        self.reads.append((path, deepcopy(query), limit))
        return tuple(deepcopy(item) for item in self.records if self.ignore_filter or all(item.get(k) == v for k, v in query.items()))

    def request(self, method, path, *, body, operation):
        self.requests.append((method, path, deepcopy(body)))
        batch = len(self.requests)
        if self.apply:
            for index, item in enumerate(body):
                self.records.append({"id": f"created-{batch}-{index}", **deepcopy(item)})
        if self.after_write:
            self.after_write(self.records, batch)
        return {"response": {"taskId": f"task-{batch}"}} if self.task else {}

    task_reference = staticmethod(CatalystCenterClient.task_reference)

    def wait_task(self, task):
        self.waits.append(task.task_id)
        if self.task_error:
            raise CatalystCenterTaskError("failed")
        return self.status_override or TaskStatus(task.task_id, True, True, False, 1)


class VlanRangeTests(unittest.TestCase):
    def test_semantic_canonicalization_and_complete_vlan_range(self):
        for value, canonical in [
            ("30,10,20", "10,20,30"), ("3, 1-2,4,8-10,7", "1-4,7-10"),
            ("1002-1005,2046,4094", "1002-1005,2046,4094"),
            ("1-2000,2001-4094", "all"), ("all", "all"), ("001,002", "1-2"),
        ]:
            with self.subTest(value=value):
                self.assertEqual(normalize_vlan_ranges(value), canonical)
        self.assertEqual(desired(native_vlan_id=4094, allowed_vlan_ranges="1,4094").native_vlan_id, 4094)

    def test_invalid_ranges_types_and_overlaps(self):
        for value in [None, True, 10, [], "", " ", "ALL", "all,10", "1,,2", "1,", "0", "4095", "2-1", "1-2-3", "1.5", "-1", "one", "1,1", "1-3,3-4", "1-10,2-3"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_vlan_ranges(value)

    def test_invalid_identity_or_native_vlan(self):
        for changes in [{"native_vlan_id": True}, {"native_vlan_id": 0}, {"native_vlan_id": 4095}, {"native_vlan_id": "1"}, {"interface_name": ""}, {"fabric_id": "fabric\n"}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                desired(**changes)


class TrunkPortAssignmentTests(unittest.TestCase):
    def test_dry_run_and_empty_input_never_write(self):
        client = Client()
        adapter = TrunkPortAssignmentAdapter(client)
        self.assertEqual(adapter.reconcile([]), ())
        self.assertEqual(client.reads, [])
        plan = adapter.reconcile([desired()], dry_run=True)[0]
        self.assertEqual(plan.action, "create")
        self.assertEqual(plan.payload, {
            "fabricId": "fabric-a", "networkDeviceId": "device-a", "interfaceName": "GigabitEthernet1/0/24",
            "connectedDeviceType": "TRUNKING_DEVICE", "authenticateTemplateName": "No Authentication",
            "nativeVlanId": 1, "allowedVlanRanges": "10,20,30",
        })
        self.assertEqual(client.reads, [(PATH, {"fabricId": "fabric-a", "networkDeviceId": "device-a"}, 50)])
        self.assertEqual((client.requests, client.waits), ([], []))

    def test_semantically_matching_existing_trunk_preserves_id(self):
        client = Client([record(allowedVlanRanges="12,10,11,20")])
        plan = TrunkPortAssignmentAdapter(client).reconcile([desired(allowed_vlan_ranges="10-12,20")])[0]
        self.assertEqual((plan.action, plan.observed_id), ("noop", "port-a"))
        self.assertEqual(client.requests, [])
        client = Client([record(allowedVlanRanges="1-4094")])
        self.assertEqual(TrunkPortAssignmentAdapter(client).plan([desired(allowed_vlan_ranges="all")])[0].action, "noop")

    def test_conflicting_existing_assignment_is_never_replaced(self):
        for changes in [{"connectedDeviceType": "USER_DEVICE"}, {"authenticateTemplateName": "Closed Authentication"}, {"nativeVlanId": 20}, {"allowedVlanRanges": "10,20"}]:
            client = Client([record(**changes)])
            with self.subTest(changes=changes), self.assertRaisesRegex(CatalystCenterError, "conflict"):
                TrunkPortAssignmentAdapter(client).reconcile([desired()])
            self.assertEqual(client.requests, [])

    def test_missing_or_malformed_readback_never_assumes_defaults(self):
        for key, value in [("nativeVlanId", None), ("nativeVlanId", True), ("allowedVlanRanges", None), ("allowedVlanRanges", "1-10,10"), ("authenticateTemplateName", None)]:
            raw = record()
            if value is None:
                raw.pop(key)
            else:
                raw[key] = value
            client = Client([raw])
            with self.subTest(key=key, value=value), self.assertRaises(CatalystCenterError):
                TrunkPortAssignmentAdapter(client).reconcile([desired()])
            self.assertEqual(client.requests, [])

    def test_missing_trunk_state_uses_validated_observer_without_post(self):
        raw = record()
        raw.pop("nativeVlanId")
        raw.pop("allowedVlanRanges")
        calls = []

        def observer(fabric_id, network_device_id, interface_name):
            calls.append((fabric_id, network_device_id, interface_name))
            return {
                "fabricId": fabric_id, "networkDeviceId": network_device_id,
                "interfaceName": interface_name, "nativeVlanId": 1,
                "allowedVlanRanges": "30,10,20",
            }

        client = Client([raw])
        plan = TrunkPortAssignmentAdapter(client, trunk_observer=observer).reconcile([desired()])[0]
        self.assertEqual((plan.action, plan.observed_id), ("noop", "port-a"))
        self.assertEqual(calls, [("fabric-a", "device-a", "GigabitEthernet1/0/24")])
        self.assertEqual(client.requests, [])

    def test_complete_controller_readback_does_not_call_observer(self):
        client = Client([record()])
        adapter = TrunkPortAssignmentAdapter(client, trunk_observer=lambda *_: (_ for _ in ()).throw(AssertionError("unexpected observer call")))
        self.assertEqual(adapter.reconcile([desired()])[0].action, "noop")
        self.assertEqual(client.requests, [])

    def test_invalid_supplemental_observer_fails_closed(self):
        with self.assertRaises(TypeError):
            TrunkPortAssignmentAdapter(Client(), trunk_observer=object())
        raw = record()
        raw.pop("nativeVlanId")
        raw.pop("allowedVlanRanges")
        invalid = [
            [],
            {"fabricId": "fabric-b", "networkDeviceId": "device-a", "interfaceName": "GigabitEthernet1/0/24", "nativeVlanId": 1, "allowedVlanRanges": "10,20,30"},
            {"fabricId": "fabric-a", "networkDeviceId": "device-a", "interfaceName": "GigabitEthernet1/0/24", "allowedVlanRanges": "10,20,30"},
            {"fabricId": "fabric-a", "networkDeviceId": "device-a", "interfaceName": "GigabitEthernet1/0/24", "nativeVlanId": 1, "allowedVlanRanges": "10,10"},
        ]
        for response in invalid:
            client = Client([raw])
            with self.subTest(response=response), self.assertRaises(CatalystCenterError):
                TrunkPortAssignmentAdapter(client, trunk_observer=lambda *_, response=response: response).reconcile([desired()])
            self.assertEqual(client.requests, [])

    def test_supplemental_observer_cannot_override_present_controller_values(self):
        controller_native = record()
        controller_native.pop("allowedVlanRanges")
        client = Client([controller_native])
        with self.assertRaisesRegex(CatalystCenterError, "observer conflicts with controller native VLAN"):
            TrunkPortAssignmentAdapter(client, trunk_observer=lambda *identity: {
                "fabricId": identity[0], "networkDeviceId": identity[1], "interfaceName": identity[2],
                "nativeVlanId": 20, "allowedVlanRanges": "10,20,30",
            }).reconcile([desired()])
        self.assertEqual(client.requests, [])

        controller_allowed = record()
        controller_allowed.pop("nativeVlanId")
        client = Client([controller_allowed])
        with self.assertRaisesRegex(CatalystCenterError, "observer conflicts with controller allowed VLAN ranges"):
            TrunkPortAssignmentAdapter(client, trunk_observer=lambda *identity: {
                "fabricId": identity[0], "networkDeviceId": identity[1], "interfaceName": identity[2],
                "nativeVlanId": 1, "allowedVlanRanges": "20",
            }).reconcile([desired()])
        self.assertEqual(client.requests, [])

    def test_observed_all_ranges_conflict_with_narrow_trunk_intent(self):
        raw = record()
        raw.pop("nativeVlanId")
        raw.pop("allowedVlanRanges")
        client = Client([raw])
        with self.assertRaisesRegex(CatalystCenterError, "conflict"):
            TrunkPortAssignmentAdapter(client, trunk_observer=lambda *identity: {
                "fabricId": identity[0], "networkDeviceId": identity[1], "interfaceName": identity[2],
                "nativeVlanId": 1, "allowedVlanRanges": "all",
            }).reconcile([desired()])
        self.assertEqual(client.requests, [])

    def test_duplicate_desired_endpoints_fail_before_read(self):
        client = Client()
        with self.assertRaises(ValueError):
            TrunkPortAssignmentAdapter(client).plan([desired(), desired(allowed_vlan_ranges="20")])
        self.assertEqual(client.reads, [])

    def test_duplicate_controller_ids_or_interfaces_fail(self):
        for other in [record(identity="port-b"), record(interfaceName="GigabitEthernet1/0/23")]:
            client = Client([record(), other])
            with self.subTest(other=other), self.assertRaisesRegex(CatalystCenterError, "duplicate"):
                TrunkPortAssignmentAdapter(client).plan([desired()])

    def test_cross_device_ids_and_filter_leaks_fail_closed(self):
        other = desired(network_device_id="device-b")
        for ignore_filter in (False, True):
            client = Client([record(), record(other)])
            client.ignore_filter = ignore_filter
            with self.subTest(ignore_filter=ignore_filter), self.assertRaises(CatalystCenterError):
                TrunkPortAssignmentAdapter(client).reconcile([desired(), other])
            self.assertEqual(client.requests, [])

    def test_batching_never_mixes_devices_or_fabrics_and_is_idempotent(self):
        intents = [desired(), desired(interface_name="GigabitEthernet1/0/23"), desired(network_device_id="device-b"), desired(fabric_id="fabric-b", network_device_id="device-c")]
        client = Client()
        adapter = TrunkPortAssignmentAdapter(client)
        self.assertEqual([p.action for p in adapter.reconcile(intents)], ["create"] * 4)
        self.assertEqual([len(body) for _, _, body in client.requests], [2, 1, 1])
        for method, path, body in client.requests:
            self.assertEqual((method, path), ("POST", PATH))
            self.assertEqual(len({(r["fabricId"], r["networkDeviceId"]) for r in body}), 1)
        self.assertEqual(client.waits, ["task-1", "task-2", "task-3"])
        self.assertEqual([p.action for p in adapter.reconcile(intents)], ["noop"] * 4)
        self.assertEqual(len(client.requests), 3)

    def test_conflict_in_later_device_prevents_all_writes(self):
        other = desired(network_device_id="device-b")
        client = Client([record(other, allowedVlanRanges="all")])
        with self.assertRaises(CatalystCenterError):
            TrunkPortAssignmentAdapter(client).reconcile([desired(), other])
        self.assertEqual(client.requests, [])

    def test_noop_and_unrelated_ports_are_excluded_from_create_payload(self):
        existing = record(interfaceDescription="preserve")
        unrelated = record(desired(interface_name="GigabitEthernet1/0/22"), "user-port", connectedDeviceType="USER_DEVICE", dataVlanName="DATA-A")
        new = desired(interface_name="GigabitEthernet1/0/23")
        client = Client([existing, unrelated])
        plans = TrunkPortAssignmentAdapter(client).reconcile([desired(), new])
        self.assertEqual([p.action for p in plans], ["noop", "create"])
        self.assertEqual(client.requests[0][2], [new.payload()])
        self.assertEqual(client.records[:2], [existing, unrelated])

    def test_missing_failed_or_wrong_task_stops_before_later_batch(self):
        clients = [Client(task=False), Client(task_error=True)]
        for status in [TaskStatus("wrong", True, True, False, 1), TaskStatus("task-1", False, False, False, None), TaskStatus("task-1", True, False, True, 1)]:
            client = Client()
            client.status_override = status
            clients.append(client)
        for client in clients:
            with self.subTest(client=client), self.assertRaises(CatalystCenterTaskError):
                TrunkPortAssignmentAdapter(client).reconcile([desired(), desired(network_device_id="device-b")])
            self.assertEqual(len(client.requests), 1)
            self.assertEqual(len(client.reads), 2)

    def test_task_success_without_readback_stops_before_later_batch(self):
        client = Client(apply=False)
        with self.assertRaisesRegex(CatalystCenterError, "did not converge"):
            TrunkPortAssignmentAdapter(client).reconcile([desired(), desired(network_device_id="device-b")])
        self.assertEqual(len(client.requests), 1)

    def test_readback_compact_ranges_are_accepted_but_changed_vlan_is_not(self):
        client = Client(after_write=lambda rows, batch: rows[-1].update(allowedVlanRanges="10-12"))
        TrunkPortAssignmentAdapter(client).reconcile([desired(allowed_vlan_ranges="10,11,12")])
        client = Client(after_write=lambda rows, batch: rows[-1].update(nativeVlanId=20))
        with self.assertRaisesRegex(CatalystCenterError, "conflict"):
            TrunkPortAssignmentAdapter(client).reconcile([desired()])

    def test_existing_object_deletion_id_or_optional_metadata_change_fails(self):
        other = record(desired(interface_name="GigabitEthernet1/0/23"), "other-id", interfaceDescription="preserve")
        for mutation in [lambda rows, batch: rows.pop(0), lambda rows, batch: rows[0].update(id="replacement"), lambda rows, batch: rows[0].update(interfaceDescription="changed")]:
            client = Client([other], after_write=mutation)
            with self.subTest(mutation=mutation), self.assertRaisesRegex(CatalystCenterError, "changed an existing"):
                TrunkPortAssignmentAdapter(client).reconcile([desired()])

    def test_unexpected_new_object_fails_before_next_device(self):
        extra = record(desired(interface_name="GigabitEthernet1/0/22"), "extra")
        client = Client(after_write=lambda rows, batch: rows.append(extra))
        with self.assertRaisesRegex(CatalystCenterError, "unexpected additional"):
            TrunkPortAssignmentAdapter(client).reconcile([desired(), desired(network_device_id="device-b")])
        self.assertEqual(len(client.requests), 1)

    def test_partial_failure_replans_applied_batch_without_retrying_it(self):
        intents = [desired(), desired(network_device_id="device-b")]
        def partial(rows, batch):
            if batch == 2:
                rows.pop()
        client = Client(after_write=partial)
        adapter = TrunkPortAssignmentAdapter(client)
        with self.assertRaisesRegex(CatalystCenterError, "did not converge"):
            adapter.reconcile(intents)
        self.assertEqual(len(client.requests), 2)
        self.assertEqual([p.action for p in adapter.plan(intents)], ["noop", "create"])

    def test_later_batch_cannot_replace_id_created_by_earlier_batch(self):
        def replace_previous(rows, batch):
            if batch == 2:
                rows[0]["id"] = "replacement"
        client = Client(after_write=replace_previous)
        with self.assertRaisesRegex(CatalystCenterError, "changed an existing"):
            TrunkPortAssignmentAdapter(client).reconcile([desired(), desired(network_device_id="device-b")])


if __name__ == "__main__":
    unittest.main()
