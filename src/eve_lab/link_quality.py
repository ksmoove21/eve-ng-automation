"""Persist fixed native EVE cable delays without changing topology or styling."""
from .connection_styles import connection_key

SIDES = ("source", "destination")
QUALITY = tuple(side + "_" + field for side in SIDES for field in ("delay", "jitter", "loss", "bandwidth"))


def _index(rows):
    if not isinstance(rows, list):
        raise ValueError("Expected native EVE topology connection list")
    result = {}
    for row in rows:
        key = connection_key(row)
        if key in result:
            raise ValueError("Ambiguous native connection: " + str(key))
        result[key] = row
    return result


def reconcile_fixed_delays(client, lab_path, desired, *, enabled=True, apply=False):
    """Plan or apply symmetric per-side delays through EVE's native quality API.

    Entries contain two semantic node endpoints and integer delay_ms (0..30000).
    Disabled profiles set only those delays to zero. Jitter, loss and bandwidth
    are preserved. All bindings are checked before writes. Save persists native
    settings; running-node behavior must be field-qualified on the target EVE.
    Returns semantic keys needing changes; apply=False performs no writes.
    """
    if type(enabled) is not bool or type(apply) is not bool:
        raise ValueError("enabled and apply must be booleans")
    before = _index(client.request("GET", lab_path + "/topology"))
    plans = []; seen = set()
    for entry in desired:
        if not isinstance(entry, dict) or set(entry) != {"endpoints", "delay_ms"}:
            raise ValueError("Fixed delay requires endpoints and delay_ms")
        endpoints = entry["endpoints"]
        if not isinstance(endpoints, (list, tuple)) or len(endpoints) != 2:
            raise ValueError("Exactly two node endpoints required")
        for endpoint in endpoints:
            if not isinstance(endpoint, (list, tuple)) or len(endpoint) != 3 or endpoint[0] != "node" or not all(isinstance(x, str) and x for x in endpoint):
                raise ValueError("Expected node, name and interface endpoint")
        key = tuple(sorted(tuple(x) for x in endpoints))
        if key in seen or key not in before:
            raise ValueError("Duplicate or absent connection: " + str(key))
        seen.add(key)
        delay = entry["delay_ms"]
        if type(delay) is not int or not 0 <= delay <= 30000:
            raise ValueError("delay_ms must be an integer from 0 to 30000")
        row = before[key]; payload = {}
        if row.get("type") != "ethernet" or any(row.get(side + "_type") != "node" for side in SIDES):
            raise ValueError("Fixed delay requires a direct Ethernet cable")
        for side in SIDES:
            node = str(row[side]).removeprefix("node")
            iface = str(row[side + "_interfaceId"])
            if not node.isdigit() or not iface.isdigit():
                raise ValueError("Invalid native endpoint identity")
            payload[side] = node
            payload[side + "_interfaceId"] = row[side + "_interfaceId"]
            payload[side + "_label"] = row[side + "_label"]
            for field in ("delay", "jitter", "loss", "bandwidth"):
                name = side + "_" + field
                if name not in row:
                    raise ValueError("Missing native quality field: " + name)
                payload[name] = (delay if enabled else 0) if field == "delay" else row[name]
        payload["save"] = 1
        if any(str(row[name]) != str(payload[name]) for name in QUALITY):
            plans.append((key, payload))
    if not apply:
        return [key for key, _ in plans]
    for key, payload in plans:
        current = _index(client.request("GET", lab_path + "/topology"))
        if current != before:
            raise RuntimeError("Native topology changed before quality mutation")
        client.request("PUT", lab_path + "/quality", payload)
        after = _index(client.request("GET", lab_path + "/topology"))
        expected = {k: dict(v) for k, v in before.items()}
        expected[key].update({name: payload[name] for name in QUALITY})
        # Native backends may stringify numbers; normalize quality fields only.
        def normalized(index):
            return {k: {name: str(value) if name in QUALITY else value for name, value in row.items()} for k, row in index.items()}
        if normalized(after) != normalized(expected):
            raise RuntimeError("Native quality readback mismatch or unrelated topology/style change")
        before = after
    return [key for key, _ in plans]
