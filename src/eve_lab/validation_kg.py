"""Read-only acceptance of the IOS-XE KG boundary, with layer-specific evidence."""
from ipaddress import IPv4Address, IPv4Network
import re

FIELDS = {"kg-boundary": {"ct_interface", "ct_peer", "ct_prefix", "pt_interface", "tunnel", "remote_prefixes", "local_prefixes", "pt_destination", "pt_source"}}


def validate_check(c):
    for key in ("ct_interface", "pt_interface", "tunnel"):
        if not isinstance(c.get(key), str) or not re.fullmatch(r"(?:GigabitEthernet[1-9][0-9]*|Loopback[0-9]+|Tunnel[0-9]+)", c[key]):
            raise ValueError("KG check requires a valid " + key)
    for key in ("ct_peer", "pt_destination", "pt_source"): IPv4Address(c.get(key))
    IPv4Network(c.get("ct_prefix"), strict=True)
    for key in ("remote_prefixes", "local_prefixes"):
        if not isinstance(c.get(key), list) or not c[key]: raise ValueError("KG check requires " + key)
        for prefix in c[key]: IPv4Network(prefix, strict=True)


def evaluate(console, c):
    from .validation_iosxe import parse_ping, parse_route
    validate_check(c)
    stages = {}
    def run(layer, probe):
        try:
            passed, observed = probe()
            stages[layer] = {"pass": bool(passed), "observed": observed}
        except RuntimeError as error:
            stages[layer] = {"pass": False, "reason": str(error)}
    def ping(vrf, address):
        from .reachability import retry_ping
        command = "ping " + ("vrf Red " if vrf else "") + address + (" source " + c["pt_source"] if vrf else "") + " repeat 5 timeout 2"
        passed, best, attempts = retry_ping(
            lambda: parse_ping(console.command(command, timeout=30)))
        return passed, {**attempts[-1], "success_rate": best, "attempts": attempts}
    run("ct-underlay", lambda: ping(False,c["ct_peer"]))
    def vrf():
        text=console.command("show ip vrf interfaces")
        if not re.search(r"Interface\s+IP-Address\s+VRF",text): raise RuntimeError("Unrecognized VRF interface table")
        members=re.findall(r"^\s*(\S+)\s+\S+\s+Red\s+",text,re.M)
        normalize=lambda x: re.sub(r"^Gi(?=\d)","GigabitEthernet",re.sub(r"^Tu(?=\d)","Tunnel",re.sub(r"^Lo(?=\d)","Loopback",x)))
        members=[normalize(x) for x in members]
        ct=console.command("show running-config interface "+c["ct_interface"])
        if "interface "+c["ct_interface"] not in ct: raise RuntimeError("Missing CT interface configuration")
        return c["pt_interface"] in members and c["tunnel"] in members and not re.search(r"(?:ip )?vrf forwarding",ct), {"Red_interfaces":members,"CT_global":not bool(re.search(r"(?:ip )?vrf forwarding",ct))}
    run("vrf-isolation-interfaces",vrf)
    def vti():
        text=console.command("show interface "+c["tunnel"])
        state=re.search(r"^"+re.escape(c["tunnel"])+r" is (up|down|administratively down), line protocol is (up|down)",text,re.M)
        cfg=console.command("show running-config interface "+c["tunnel"])
        if not state: raise RuntimeError("Unrecognized tunnel state")
        good=state[1]==state[2]=="up" and "vrf forwarding Red" in cfg and "tunnel mode ipsec ipv4" in cfg and "tunnel protection ipsec profile " in cfg and "tunnel vrf " not in cfg
        return good,{"status":state[1],"protocol":state[2],"Red": "vrf forwarding Red" in cfg,"ipsec_protected":"tunnel protection ipsec profile " in cfg}
    run("vti",vti)
    def ike():
        text=console.command("show crypto ikev2 sa")
        if "Tunnel-id" not in text or "Status" not in text: raise RuntimeError("Unrecognized IKEv2 SA table")
        rows=[line for line in text.splitlines() if re.search(r"\b"+re.escape(c["ct_peer"])+r"(?:/|\s)",line)]
        return any(re.search(r"\bREADY\b",line) for line in rows),{"peer":c["ct_peer"],"ready":any(re.search(r"\bREADY\b",line) for line in rows)}
    run("ike",ike)
    def ipsec():
        text=console.command("show crypto ipsec sa peer "+c["ct_peer"])
        enc=re.findall(r"#pkts encaps: (\d+)",text);dec=re.findall(r"#pkts decaps: (\d+)",text)
        inbound="inbound esp sas:" in text;outbound="outbound esp sas:" in text
        active=len(re.findall(r"Status: ACTIVE",text))
        if not enc or not dec: raise RuntimeError("Missing IPsec counters")
        return inbound and outbound and active>=2 and sum(map(int,enc))>0 and sum(map(int,dec))>0,{"encapsulated":sum(map(int,enc)),"decapsulated":sum(map(int,dec)),"active_sas":active}
    # Trigger protected traffic before inspecting security associations/counters.
    run("pt-reachability",lambda:ping(True,c["pt_destination"]))
    run("ipsec",ipsec)
    def rip():
        cfg=console.command("show running-config | section ^router rip")
        af=re.search(r"address-family ipv4 vrf Red\n(.*?)exit-address-family",cfg,re.S)
        if not cfg.strip().startswith("router rip") or not af: raise RuntimeError("Missing protected RIP address family")
        global_cfg=cfg[:af.start()]
        protected=af[1]
        okay=not re.search(r"^\s*(?:network|redistribute|neighbor) ",global_cfg,re.M) and "version 2" in protected and "passive-interface default" in global_cfg
        active=re.findall(r"no passive-interface (\S+)",global_cfg)
        okay=okay and active==[c["tunnel"]]
        protocol=console.command("show ip protocols vrf Red")
        okay=okay and bool(re.search(r'Routing Protocol is "rip"',protocol))
        operational=re.findall(r"(?m)^\s*(\S+)\s+2\s+2\s+(?:No|Yes)\s+",protocol)
        okay=okay and operational==[c["tunnel"]]
        routes=[]
        for prefix in c["remote_prefixes"]:
            net=IPv4Network(prefix)
            output=console.command(f"show ip route vrf Red {net.network_address} {net.netmask}")
            seen=parse_route(output)
            learned=seen["present"] and seen["prefix"]==prefix and bool(re.search(r'Known via "rip"',output))
            routes.append({"prefix":prefix,"learned_by_rip":learned});okay=okay and learned
        return okay,{"active_interfaces":active,"remote_routes":routes,"global_rip_networks":bool(re.search(r"^\s*network ",global_cfg,re.M))}
    run("rip",rip)
    def isolation():
        seen=[]
        for prefix,red in [(p,False) for p in c["local_prefixes"]+c["remote_prefixes"]]+[(c["ct_prefix"],True)]:
            net=IPv4Network(prefix);scope=" vrf Red" if red else ""
            route=parse_route(console.command(f"show ip route{scope} {net.network_address} {net.netmask}"))
            absent=not route["present"]
            seen.append({"prefix":prefix,"table":"Red" if red else "global","absent":absent})
        return all(item["absent"] for item in seen),seen
    run("vrf-isolation-routes",isolation)
    failed=[name for name,value in stages.items() if not value["pass"]]
    return not failed,{"stages":stages,"failed_layers":failed}
