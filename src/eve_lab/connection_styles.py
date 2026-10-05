"""Reconcile native EVE cable presentation without changing attachments."""

FIELDS = {
    'style': 'Solid', 'color': '#3e7089', 'srcpos': '0.15',
    'dstpos': '0.85', 'linkstyle': 'Straight', 'width': '1',
    'label': '', 'labelpos': '0.5', 'stub': '0', 'curviness': '10',
    'beziercurviness': '150', 'round': '0', 'midpoint': '0.5',
}


def connection_key(connection, networks=None):
    """Order-independent semantic identity, independent of runtime EVE IDs."""
    endpoints = []
    for side in ('source', 'destination'):
        kind = connection[side + '_type']
        if kind == 'node':
            endpoints.append(('node', connection[side + '_node_name'], connection[side + '_label']))
        elif kind == 'network':
            ident = str(connection['network_id'])
            name = networks[ident]['name'] if networks is not None else connection[side + '_label']
            endpoints.append(('network', name, ''))
        else:
            raise ValueError(f'Unsupported connection endpoint type: {kind}')
    return tuple(sorted(endpoints))


def reconcile_connection_styles(client, lab_path, desired):
    """Apply exact native GUI styles to existing cables in a stopped lab.

    Each desired entry has two endpoints (kind, name, interface) and a style
    mapping. All identities and fields are checked before any writes. Node
    interface attachment APIs are deliberately never used.
    """
    rendered = client.request('GET', lab_path + '/topology')
    if not isinstance(rendered, list):
        raise ValueError('Expected a native EVE topology connection list')
    networks = client.request('GET', lab_path + '/networks')
    if isinstance(networks, list):
        networks = {str(item['id']): item for item in networks}
    by_key = {}
    for item in rendered:
        key = connection_key(item, networks)
        if key in by_key:
            raise ValueError(f'Ambiguous native connection: {key}')
        by_key[key] = item
    plans = []
    seen = set()
    for entry in desired:
        if set(entry) != {'endpoints', 'style'} or len(entry['endpoints']) != 2:
            raise ValueError('Connection style requires two endpoints and a style mapping')
        key = tuple(sorted(tuple(endpoint) for endpoint in entry['endpoints']))
        if key in seen or key not in by_key:
            raise ValueError(f'Duplicate or absent connection: {key}')
        seen.add(key)
        style = entry['style']
        if not isinstance(style, dict) or set(style) - set(FIELDS):
            raise ValueError('Unsupported native cable style field')
        wanted = {k: str(style.get(k, default)) for k, default in FIELDS.items()}
        actual = by_key[key]
        if all(str(actual.get(k, '')) == value for k, value in wanted.items()):
            continue
        if actual['source_type'] != 'node':
            raise ValueError('Native EVE cable style requires a node source')
        node = actual['source'].removeprefix('node')
        if not node.isdigit():
            raise ValueError('Invalid native source node identity')
        interface = str(actual['source_interfaceId'])
        ident = (f"network_id:{actual['network_id']}" if actual['destination_type'] == 'node'
                 else f"iface:{actual['source']}:{interface}")
        payload = {**wanted, 'id': ident, 'node': node,
                   'interface_id': interface, 'type': actual['type']}
        plans.append((key, node, payload))
    nodes = client.request('GET', lab_path + '/nodes')
    nodes = nodes.values() if isinstance(nodes, dict) else nodes
    if any(str(node.get('status')) != '0' for node in nodes):
        raise ValueError('Cable presentation requires all lab nodes stopped')
    changes = []
    for key, node, payload in plans:
        # Recheck the lifecycle guard immediately before each mutation.
        nodes = client.request('GET', lab_path + '/nodes')
        nodes = nodes.values() if isinstance(nodes, dict) else nodes
        if any(str(item.get('status')) != '0' for item in nodes):
            raise ValueError('A lab node started during cable presentation reconciliation')
        client.request('PUT', lab_path + '/nodes/' + node + '/style', payload)
        changes.append(key)
    final = {connection_key(item, networks): item for item in client.request('GET', lab_path + '/topology')}
    if set(final) != set(by_key):
        raise RuntimeError('Connection membership changed during style reconciliation')
    for entry in desired:
        key = tuple(sorted(tuple(endpoint) for endpoint in entry['endpoints']))
        wanted = {k: str(entry['style'].get(k, default)) for k, default in FIELDS.items()}
        if any(str(final[key].get(k, '')) != value for k, value in wanted.items()):
            raise RuntimeError(f'Cable presentation readback mismatch: {key}')
    return changes
