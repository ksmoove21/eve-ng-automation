import unittest
from copy import deepcopy

from eve_lab.catalyst_center import (
    CatalystCenterClient, CatalystCenterError, CatalystCenterTaskError, TaskStatus,
)
from eve_lab.catalyst_center_anycast import AnycastGateway, AnycastGatewayAdapter

PATH = "/dna/intent/api/v1/sda/anycastGateways"


def desired(**overrides):
    values = dict(fabric_id="fabric-a", virtual_network_name="USER", ip_pool_name="pool-a", vlan_id=10, vlan_name="VLAN-A")
    values.update(overrides)
    return AnycastGateway(**values)


def record(gateway=None, identity="gateway-a", **overrides):
    result = {"id": identity, **(gateway or desired()).payload()}
    # 2.3.7.9 GET does not advertise this POST-only option.
    result.pop("autoGenerateVlanName")
    result.update(overrides)
    return result


class Client:
    def __init__(self, records=(), *, apply=True, task=True, task_error=False, after_write=None):
        self.records = deepcopy(list(records))
        self.apply, self.task, self.task_error, self.after_write = apply, task, task_error, after_write
        self.requests, self.reads, self.waits = [], [], []
        self.status = TaskStatus("task-a", True, True, False, 1)
        self.ignore_filter = False

    def list_all(self, path, *, query, limit, operation):
        self.reads.append((path, dict(query), limit))
        return tuple(deepcopy(item) for item in self.records if self.ignore_filter or item.get("fabricId") == query["fabricId"])

    def request(self, method, path, *, body, operation):
        self.requests.append((method, path, deepcopy(body)))
        if self.apply:
            for index, item in enumerate(body):
                created = {"id": f"created-{index}", **deepcopy(item)}
                created.pop("autoGenerateVlanName")
                self.records.append(created)
        if self.after_write:
            self.after_write(self.records)
        return {"response": {"taskId": "task-a"}} if self.task else {}

    task_reference = staticmethod(CatalystCenterClient.task_reference)

    def wait_task(self, task):
        self.waits.append(task.task_id)
        if self.task_error:
            raise CatalystCenterTaskError("task failed")
        return self.status


class AnycastGatewayTests(unittest.TestCase):
    def test_defaults_are_explicit_and_voice_is_supported(self):
        data = desired().payload()
        self.assertEqual(set(data), {
            "fabricId", "virtualNetworkName", "ipPoolName", "vlanId", "vlanName", "trafficType",
            "isCriticalPool", "isLayer2FloodingEnabled", "isWirelessPool", "isIpDirectedBroadcast",
            "isIntraSubnetRoutingEnabled", "isMultipleIpToMacAddresses", "autoGenerateVlanName",
        })
        self.assertTrue(data["isIntraSubnetRoutingEnabled"])
        self.assertFalse(any(value for key, value in data.items() if (key.startswith("is") and key != "isIntraSubnetRoutingEnabled") or key == "autoGenerateVlanName"))
        self.assertEqual(desired(traffic_type="VOICE").payload()["trafficType"], "VOICE")

    def test_invalid_or_unsupported_intent_fails_before_requests(self):
        for override in [
            {"vlan_id": True}, {"vlan_id": 1}, {"vlan_id": 1002}, {"vlan_id": 1005},
            {"vlan_id": 2046}, {"vlan_id": 4094}, {"vlan_id": "10"},
            {"fabric_id": ""}, {"ip_pool_name": "pool\nname"}, {"vlan_name": " name"},
            {"traffic_type": "OTHER"}, {"is_wireless_pool": "false"},
            {"auto_generate_vlan_name": True}, {"is_critical_pool": True}, {"virtual_network_name": "INFRA_VN"},
        ]:
            with self.subTest(override=override), self.assertRaises(ValueError):
                desired(**override)

    def test_empty_input_makes_no_requests(self):
        client = Client()
        self.assertEqual(AnycastGatewayAdapter(client).reconcile([]), ())
        self.assertEqual((client.reads, client.requests), ([], []))

    def test_dry_run_reads_scoped_list_and_does_not_write_or_wait(self):
        client = Client()
        plans = AnycastGatewayAdapter(client).reconcile([desired()], dry_run=True)
        self.assertEqual(plans[0].action, "create")
        self.assertEqual(plans[0].payload, desired().payload())
        self.assertEqual(client.reads, [(PATH, {"fabricId": "fabric-a"}, 500)])
        self.assertEqual((client.requests, client.waits), ([], []))

    def test_matching_existing_preserves_id_and_omitted_request_only_flag(self):
        client = Client([record()])
        plan = AnycastGatewayAdapter(client).reconcile([desired()])[0]
        self.assertEqual((plan.action, plan.payload, plan.observed_id), ("noop", None, "gateway-a"))
        self.assertEqual(client.requests, [])

    def test_existing_conflicts_never_mutate(self):
        for override in [
            {"virtualNetworkName": "VOICE"}, {"ipPoolName": "other-pool"}, {"vlanId": 20},
            {"vlanName": "OTHER"}, {"trafficType": "VOICE"}, {"isLayer2FloodingEnabled": True},
            {"isIntraSubnetRoutingEnabled": False}, {"autoGenerateVlanName": True},
        ]:
            client = Client([record(**override)])
            with self.subTest(override=override), self.assertRaisesRegex(CatalystCenterError, "conflict"):
                AnycastGatewayAdapter(client).reconcile([desired()])
            self.assertEqual(client.requests, [])

    def test_missing_or_non_boolean_option_is_not_assumed_false(self):
        for mode in ("missing", "string", "integer"):
            raw = record()
            if mode == "missing":
                raw.pop("isWirelessPool")
            else:
                raw["isWirelessPool"] = "false" if mode == "string" else 0
            client = Client([raw])
            with self.subTest(mode=mode), self.assertRaises(CatalystCenterError):
                AnycastGatewayAdapter(client).reconcile([desired()])
            self.assertEqual(client.requests, [])

    def test_duplicate_controller_identity_fails_closed(self):
        other = desired(ip_pool_name="pool-b", vlan_id=20, vlan_name="VLAN-B")
        for duplicate in [
            record(other, "gateway-a"), record(other, "gateway-b", ipPoolName="pool-a"),
            record(other, "gateway-b", vlanId=10), record(other, "gateway-b", vlanName="VLAN-A"),
        ]:
            client = Client([record(), duplicate])
            with self.subTest(duplicate=duplicate), self.assertRaisesRegex(CatalystCenterError, "duplicate"):
                AnycastGatewayAdapter(client).plan([desired()])
            self.assertEqual(client.requests, [])

    def test_split_identity_conflict_is_not_created(self):
        client = Client([
            record(vlanId=20, vlanName="VLAN-B"),
            record(identity="gateway-b", ipPoolName="pool-b"),
        ])
        with self.assertRaisesRegex(CatalystCenterError, "conflicting existing identities"):
            AnycastGatewayAdapter(client).reconcile([desired()])
        self.assertEqual(client.requests, [])

    def test_duplicate_desired_identity_is_rejected_before_read(self):
        for other in [
            desired(vlan_id=20, vlan_name="VLAN-B"),
            desired(ip_pool_name="pool-b", vlan_name="VLAN-B"),
            desired(ip_pool_name="pool-b", vlan_id=20),
        ]:
            client = Client()
            with self.subTest(other=other), self.assertRaises(ValueError):
                AnycastGatewayAdapter(client).reconcile([desired(), other])
            self.assertEqual((client.requests, client.reads), ([], []))

    def test_complete_preflight_detects_late_batch_conflict_before_any_write(self):
        other = desired(ip_pool_name="pool-b", vlan_id=20, vlan_name="VLAN-B")
        client = Client([record(other, "gateway-b", trafficType="VOICE")])
        with self.assertRaises(CatalystCenterError):
            AnycastGatewayAdapter(client).reconcile([desired(), other])
        self.assertEqual(client.requests, [])

    def test_batch_create_skips_noops_waits_once_and_is_idempotent(self):
        existing = desired(ip_pool_name="pool-existing", vlan_id=30, vlan_name="VLAN-EXISTING")
        voice = desired(ip_pool_name="pool-voice", vlan_id=90, vlan_name="VLAN-VOICE", traffic_type="VOICE")
        client = Client([record(existing, "existing-id")])
        adapter = AnycastGatewayAdapter(client)
        plans = adapter.reconcile([desired(), existing, voice])
        self.assertEqual([item.action for item in plans], ["create", "noop", "create"])
        self.assertEqual(plans[1].observed_id, "existing-id")
        self.assertEqual(client.requests, [("POST", PATH, [desired().payload(), voice.payload()])])
        self.assertEqual(client.waits, ["task-a"])
        self.assertEqual(len(client.reads), 2)
        self.assertEqual([item.action for item in adapter.reconcile([desired(), existing, voice])], ["noop"] * 3)
        self.assertEqual(len(client.requests), 1)

    def test_same_vlan_pool_and_name_across_fabrics_are_independent(self):
        other = desired(fabric_id="fabric-b")
        client = Client([record()])
        plans = AnycastGatewayAdapter(client).reconcile([desired(), other])
        self.assertEqual([item.action for item in plans], ["noop", "create"])
        self.assertEqual({tuple(query.items()) for _, query, _ in client.reads}, {
            (("fabricId", "fabric-a"),), (("fabricId", "fabric-b"),),
        })

    def test_unfiltered_or_duplicate_cross_fabric_response_fails(self):
        other = desired(fabric_id="fabric-b")
        for ignore_filter in (False, True):
            client = Client([record(), record(other)])
            client.ignore_filter = ignore_filter
            with self.subTest(ignore_filter=ignore_filter), self.assertRaises(CatalystCenterError):
                AnycastGatewayAdapter(client).reconcile([desired(), other])
            self.assertEqual(client.requests, [])

    def test_missing_failed_or_unsuccessful_task_does_not_claim_convergence(self):
        clients = [Client(task=False), Client(task_error=True)]
        for status in [None, TaskStatus("other", True, True, False, 1), TaskStatus("task-a", False, False, False, None), TaskStatus("task-a", True, False, True, 1)]:
            client = Client()
            client.status = status
            clients.append(client)
        for client in clients:
            with self.subTest(client=client), self.assertRaises(CatalystCenterTaskError):
                AnycastGatewayAdapter(client).reconcile([desired()])
            self.assertEqual(len(client.requests), 1)
            self.assertEqual(len(client.reads), 1)

    def test_successful_task_without_actual_gateway_fails(self):
        client = Client(apply=False)
        with self.assertRaisesRegex(CatalystCenterError, "did not converge"):
            AnycastGatewayAdapter(client).reconcile([desired()])
        self.assertEqual(client.waits, ["task-a"])

    def test_readback_must_match_requested_configuration(self):
        for key, value in [("virtualNetworkName", "OTHER"), ("vlanId", 20), ("isLayer2FloodingEnabled", True)]:
            client = Client(after_write=lambda rows, k=key, v=value: rows[-1].update({k: v}))
            with self.subTest(key=key), self.assertRaises(CatalystCenterError):
                AnycastGatewayAdapter(client).reconcile([desired()])

    def test_unrequested_existing_objects_and_options_remain_stable(self):
        other = record(desired(ip_pool_name="pool-b", vlan_id=20, vlan_name="VLAN-B"), "gateway-b", securityGroupName="group-a")
        for mutate in [
            lambda rows: rows.pop(0),
            lambda rows: rows[0].update(id="replacement-id"),
            lambda rows: rows[0].update(securityGroupName="group-b"),
        ]:
            client = Client([other], after_write=mutate)
            with self.subTest(mutate=mutate), self.assertRaisesRegex(CatalystCenterError, "changed an existing"):
                AnycastGatewayAdapter(client).reconcile([desired()])

    def test_unexpected_extra_object_after_create_fails(self):
        extra = record(desired(ip_pool_name="pool-extra", vlan_id=30, vlan_name="VLAN-EXTRA"), "extra-id")
        client = Client(after_write=lambda rows: rows.append(extra))
        with self.assertRaisesRegex(CatalystCenterError, "unexpected additional objects"):
            AnycastGatewayAdapter(client).reconcile([desired()])

    def test_duplicate_id_across_fabrics_in_final_readback_fails(self):
        other = desired(fabric_id="fabric-b")
        client = Client(after_write=lambda rows: rows[-1].update(id=rows[0]["id"]))
        with self.assertRaisesRegex(CatalystCenterError, "duplicate ID across fabrics"):
            AnycastGatewayAdapter(client).reconcile([desired(), other])

    def test_noop_object_id_cannot_change_during_another_creation(self):
        other = desired(ip_pool_name="pool-b", vlan_id=20, vlan_name="VLAN-B")
        client = Client([record()], after_write=lambda rows: rows[0].update(id="replacement-id"))
        with self.assertRaisesRegex(CatalystCenterError, "changed an existing"):
            AnycastGatewayAdapter(client).reconcile([desired(), other])


if __name__ == "__main__":
    unittest.main()
