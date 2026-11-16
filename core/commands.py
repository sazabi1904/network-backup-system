"""Read-only collection commands shared by TV2 adapters and TV3 Collector."""

COLLECTION_COMMANDS = {
    "mikrotik": {
        "system": "/system resource print",
        "serial": "/system routerboard print",
        "interfaces": "/interface print terse without-paging",
        "routes": "/ip route print terse without-paging",
        "arp": "/ip arp print terse without-paging",
        "mac_table": "/interface bridge host print terse without-paging",
        "discovery": "/ip neighbor print terse without-paging",
        "ospf": "/routing ospf neighbor print terse without-paging",
    },
    "frr": {
        "system": "show version",
        "serial": None,
        "interfaces": "show interface json",
        "routes": "show ip route json",
        "arp": None,
        "mac_table": None,
        "discovery": None,
        "ospf": "show ip ospf neighbor json",
    },
}
