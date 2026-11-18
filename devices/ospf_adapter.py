"""Opt-in OSPFv2 backbone writes; unsupported existing OSPF blocks writes.

Manages the default FRR process or named RouterOS tv2-ospf objects.
No interface/IP, filters, authentication, redistribution or startup writes.
"""
import ipaddress
import json
import re
import shlex

from core.commands import COLLECTION_COMMANDS
from core.exceptions import DeviceCommandError, DeviceRestoreError
from devices.write_adapter import WriteSSHAdapter


def ipv4(value):
    try:
        address = ipaddress.IPv4Address(value)
        if address.is_multicast or address.is_unspecified or int(address) == 0xffffffff:
            raise ValueError()
        return str(address)
    except (ValueError, TypeError):
        raise DeviceCommandError('Invalid OSPF router ID') from None


def prefix(value):
    try:
        network = ipaddress.IPv4Network(value, strict=True)
        if str(network) != value:
            raise ValueError()
        return str(network)
    except (ValueError, TypeError):
        raise DeviceCommandError('Expected a canonical IPv4 network prefix') from None


def validate_variables(variables):
    if set(variables) - {'router_id', 'networks'} or 'router_id' not in variables:
        raise DeviceCommandError('OSPF requires explicit router_id and networks; only backbone is supported')
    ipv4(variables['router_id'])
    networks = variables.get('networks')
    if not isinstance(networks, list) or len(networks) > 64:
        raise DeviceCommandError('OSPF requires at most 64 network prefixes')
    seen = set()
    for item in networks:
        if (not isinstance(item, dict) or set(item) - {'prefix', 'area_id'}
                or item.get('area_id', '0.0.0.0') != '0.0.0.0'):
            raise DeviceCommandError('Only OSPFv2 area 0.0.0.0 is supported')
        value = prefix(item.get('prefix'))
        if value in seen:
            raise DeviceCommandError('Duplicate OSPF network')
        seen.add(value)


class OSPFSSHAdapter(WriteSSHAdapter):
    write_scopes = ('ospf-backbone',)
    write_scope = 'ospf-backbone'
    MT = '/routing ospf '

    @staticmethod
    def _tag(network):
        return 'tv2-ospf-' + network.replace('.', '-').replace('/', '-')

    def _mt_entry(self, line):
        try:
            tokens = shlex.split(line)
            if tokens[:2] != ['/routing', 'ospf'] or tokens[3] != 'add':
                raise ValueError()
            kind = tokens[2]
            pairs = [token.split('=', 1) for token in tokens[4:]]
            props = dict(pairs)
            if len(props) != len(pairs):
                raise ValueError()
            if props.get('disabled') == 'no':
                props.pop('disabled')
            if kind == 'instance':
                if props.get('version') == '2':
                    props.pop('version')
                if set(props) != {'name', 'router-id'} or props['name'] != 'tv2-ospf':
                    raise ValueError()
                props['router-id'] = ipv4(props['router-id'])
            elif kind == 'area':
                # RouterOS omits the default backbone area ID from /export.
                props.setdefault('area-id', '0.0.0.0')
                if props != {'name': 'tv2-backbone', 'instance': 'tv2-ospf', 'area-id': '0.0.0.0'}:
                    raise ValueError()
            elif kind == 'interface-template':
                if set(props) != {'area', 'networks', 'comment'} or props['area'] != 'tv2-backbone':
                    raise ValueError()
                network = prefix(props['networks'])
                if props['comment'] != self._tag(network):
                    raise ValueError()
            else:
                raise ValueError()
            return kind, props
        except (ValueError, IndexError, TypeError):
            raise DeviceCommandError('Unsupported or unowned RouterOS OSPF configuration') from None

    def _split(self, content):
        normalized = super().normalize_config_for_verification(content)
        lines = normalized.splitlines()
        if self.info.platform == 'mikrotik':
            if not any(line.startswith('# RouterOS 7.') for line in lines):
                raise DeviceCommandError('OSPF writes require RouterOS 7')
            entries, rest = [], []
            for line in lines:
                if line.startswith(self.MT):
                    entries.append(self._mt_entry(line))
                else:
                    rest.append(line)
            keys = [(kind, props.get('comment', props.get('name'))) for kind, props in entries]
            if len(keys) != len(set(keys)):
                raise DeviceCommandError('Duplicate OSPF objects')
            return self._sort(entries), '\n'.join(rest)
        if not lines or lines[-1] != 'end' or not any(line.startswith('frr version ') for line in lines):
            raise DeviceCommandError('Expected a complete FRR configuration')
        rest, ospf, in_ospf = [], [], False
        for line in lines:
            stripped = line.strip()
            if stripped == '!':
                continue
            if stripped.startswith('router ospf'):
                if stripped != 'router ospf' or ospf or in_ospf:
                    raise DeviceCommandError('Only one default FRR OSPF process is supported')
                in_ospf = True
                ospf.append('router ospf')
            elif in_ospf:
                if stripped == 'exit':
                    in_ospf = False
                ospf.append(stripped)
            else:
                if re.match(r'(?:no )?ip ospf\b', stripped):
                    raise DeviceCommandError('Interface OSPF settings are outside this scope')
                rest.append(line)
        if in_ospf:
            raise DeviceCommandError('Incomplete FRR OSPF block')
        return self._frr_state(ospf, partial=True), '\n'.join(rest)

    @staticmethod
    def _sort(entries):
        return sorted(entries, key=lambda entry: (entry[0], json.dumps(entry[1], sort_keys=True)))

    @staticmethod
    def _frr_state(commands, partial=False):
        if commands == []:
            return None
        if commands[0] != 'router ospf' or commands[-1] != 'exit':
            raise DeviceCommandError('Expected router ospf ... exit')
        rid, networks = None, []
        for command in commands[1:-1]:
            if command.startswith('ospf router-id ') and rid is None:
                rid = ipv4(command[len('ospf router-id '):])
            else:
                match = re.fullmatch(r'network (\S+) area 0.0.0.0', command)
                if not match:
                    raise DeviceCommandError('Unsupported FRR OSPF setting')
                networks.append(prefix(match[1]))
        if (not partial and rid is None) or len(set(networks)) != len(networks) or len(networks) > 64:
            raise DeviceCommandError('Explicit router ID and unique networks are required')
        return {'router_id': rid, 'networks': sorted(networks)}

    def _requested(self, commands):
        if not isinstance(commands, list) or not commands or not all(isinstance(x, str) for x in commands):
            raise DeviceCommandError('Expected nonempty OSPF command list')
        if self.info.platform == 'frr':
            if self.frr_shell != 'linux':
                raise DeviceCommandError('FRR writes require frr_shell=linux')
            return self._frr_state(commands)
        entries = [self._mt_entry(command) for command in commands]
        kinds = [kind for kind, _ in entries]
        if kinds[:2] != ['instance', 'area'] or any(kind != 'interface-template' for kind in kinds[2:]):
            raise DeviceCommandError('Expected one instance, one backbone area, then interface templates')
        networks = [props['networks'] for kind, props in entries if kind == 'interface-template']
        if len(set(networks)) != len(networks) or len(networks) > 64:
            raise DeviceCommandError('Duplicate or excessive OSPF networks')
        return self._sort(entries)

    def validate_config_commands(self, commands):
        self._requested(commands)
        if self._connection is not None:
            self._split(self.get_running_config())

    def normalize_config_for_verification(self, content):
        state, rest = self._split(content)
        return rest + '\n# managed OSPF state\n' + json.dumps(state, sort_keys=True)

    def _replace(self, current, desired):
        if current == desired:
            return
        if self.info.platform == 'frr':
            commands = ['configure terminal']
            if current is not None:
                commands.append('no router ospf')
            if desired is not None:
                commands.append('router ospf')
                if desired['router_id'] is not None:
                    commands.append('ospf router-id ' + desired['router_id'])
                commands += ['network ' + net + ' area 0.0.0.0' for net in desired['networks']]
                commands.append('exit')
            commands.append('end')
            self._send_write('vtysh ' + ' '.join('-c ' + shlex.quote(command) for command in commands))
            return
        for kind in ('interface-template', 'area', 'instance'):
            for entry_kind, props in current:
                if kind == entry_kind:
                    field = 'comment' if kind == 'interface-template' else 'name'
                    self._send_write(self.MT + kind + ' remove [find where ' + field + '=' + props[field] + ']')
        for kind in ('instance', 'area', 'interface-template'):
            for entry_kind, props in desired:
                if kind == entry_kind:
                    self._send_write(self.MT + kind + ' add ' + ' '.join(key + '=' + value for key, value in props.items()))

    def push_config(self, commands):
        desired = self._requested(commands)
        current, rest = self._split(self.get_running_config())
        self._replace(current, desired)
        actual, after_rest = self._split(self.get_running_config())
        if actual != desired or after_rest != rest:
            raise DeviceCommandError('OSPF read-back failed or unrelated configuration changed')
        return 'OSPF backbone running configuration applied and verified'

    def verify_config_commands(self, commands):
        desired = self._requested(commands)
        actual, _ = self._split(self.get_running_config())
        return {'device_name': self.info.name, 'passed': actual == desired,
                'scope': self.write_scope, 'verification_mode': 'ospf-configuration',
                'neighbor_convergence_checked': False}

    def restore_config(self, backup):
        desired, rest = self._split(backup)
        if self._connection is None:
            self.connect()
        current, current_rest = self._split(self.get_running_config())
        if current_rest != rest:
            raise DeviceRestoreError('Unmanaged configuration changed; refusing partial OSPF restore')
        self._replace(current, desired)
        if self.normalize_config_for_verification(self.get_running_config()) != self.normalize_config_for_verification(backup):
            raise DeviceRestoreError('OSPF restore did not match the complete snapshot')
        return True

    def ospf_neighbors(self):
        output = self.send_command(COLLECTION_COMMANDS[self.info.platform]['ospf'])
        neighbors = {}
        if self.info.platform == 'frr':
            data = json.loads(output)
            table = data.get('neighbors', data)
            for rid, entries in table.items():
                ipv4(rid)
                if not isinstance(entries, list):
                    raise DeviceCommandError('Invalid FRR neighbor table')
                for item in entries:
                    neighbors.setdefault(rid, []).append(item.get('state', item.get('nbrState', '')))
        else:
            for line in output.splitlines():
                rid = re.search(r'(?:^|\s)router-id=(\S+)', line)
                state = re.search(r'(?:^|\s)state=(\S+)', line)
                if rid and state:
                    neighbors.setdefault(rid[1], []).append(state[1])
        return neighbors

    def ospf_routes(self):
        output = self.send_command(COLLECTION_COMMANDS[self.info.platform]['routes'])
        if self.info.platform == 'frr':
            return sorted(net for net, paths in json.loads(output).items()
                          if any(path.get('protocol') == 'ospf' and path.get('selected') for path in paths))
        routes = []
        for line in output.splitlines():
            match = re.search(r'\bdst-address=(\S+)', line)
            flags = re.split(r'\b[\w-]+=', line, maxsplit=1)[0] if match else ''
            if match and 'A' in flags and 'o' in flags:
                routes.append(match[1])
        return sorted(routes)

    def ping_ospf_target(self, address):
        """Bounded data-plane probe to an explicitly supplied IPv4 address."""
        address = ipv4(address)
        if self.info.platform == 'mikrotik':
            output = self._read('/ping address=' + address + ' count=3')
            match = re.search(r'sent=(\d+)\s+received=(\d+)', output)
        else:
            output = self._read('ping -n -c 3 -W 2 ' + address)
            match = re.search(r'(\d+) packets transmitted, (\d+) (?:packets )?received', output)
        return {'target': address, 'passed': bool(match and match[1] == '3' and match[2] == '3')}
