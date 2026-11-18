"""Opt-in managed writes; existing read-only adapters remain the default."""
import re
import shlex
from devices.ssh_adapter import SSHAdapter
from core.exceptions import DeviceCommandError, DeviceRestoreError, DeviceWriteError
from netmiko.exceptions import ReadTimeout, NetmikoTimeoutException

NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,62}\Z')


class WriteSSHAdapter(SSHAdapter):
    """Explicit opt-in: MikroTik identity or FRR existing interface descriptions.

    Full snapshots are accepted only if every unmanaged setting is unchanged.
    No routing, management IP, daemon hostname or startup file writes.
    """
    @property
    def write_scopes(self):
        return ('identity',) if self.info.platform == 'mikrotik' else ('interface-description',)

    @property
    def write_scope(self):
        return self.write_scopes[0]

    def get_running_config(self):
        # Stable output lets the existing TV5 hash verifier compare real state.
        # Raw snapshot integrity is still checked separately by RestoreManager.
        content = super().get_running_config()
        if self.info.platform == 'mikrotik':
            content = re.sub(r'(?m)^# \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} by RouterOS (\S+)\s*$',
                             r'# RouterOS \1', content)
        return content

    def normalize_config_for_verification(self, content):
        lines = [line.rstrip() for line in content.splitlines() if line.strip()]
        if self.info.platform == 'mikrotik':
            # RouterOS exports include the current time; this is not configuration.
            lines = [re.sub(r'^# \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} by RouterOS (\S+)$', r'# RouterOS \1', line) for line in lines]
        else:
            lines = [line for line in lines if line not in
                     ('Building configuration...', 'Current configuration:')]
        return '\n'.join(lines)

    def _identity(self, content):
        if not isinstance(content, str) or not content.strip():
            raise DeviceCommandError('Empty configuration')
        lines = self.normalize_config_for_verification(content).splitlines()
        if self.info.platform == 'mikrotik':
            if not re.search(r'(?m)^#.*RouterOS', content):
                raise DeviceCommandError('Expected RouterOS export')
            entries = [x for x in lines if x.startswith('/system identity ')]
            if len(entries) != 1:
                raise DeviceCommandError('Expected one explicit RouterOS identity')
            tokens = shlex.split(entries[0])
            if len(tokens) != 4 or tokens[:3] != ['/system','identity','set'] or not tokens[3].startswith('name='):
                raise DeviceCommandError('Unsupported identity syntax')
            name = tokens[3][5:]
        else:
            if not any(x.startswith('frr version ') for x in lines) or lines[-1] != 'end':
                raise DeviceCommandError('Expected complete FRR configuration')
            entries = [x for x in lines if x.startswith('hostname ')]
            if len(entries) != 1:
                raise DeviceCommandError('Expected one FRR hostname')
            name = entries[0][9:]
        if not NAME.fullmatch(name):
            raise DeviceCommandError('Unsupported hostname')
        return name, '\n'.join(x for x in lines if x != entries[0])

    def _requested_identity(self, commands):
        if self.info.platform != "mikrotik":
            raise DeviceCommandError("FRR identity restore is unsupported: vtysh hostname is session-local")
        if not isinstance(commands, list) or len(commands) != 1 or not isinstance(commands[0], str):
            raise DeviceCommandError('Identity scope requires exactly one command')
        prefix = '/system identity set name=' if self.info.platform == 'mikrotik' else 'hostname '
        if not commands[0].startswith(prefix):
            raise DeviceCommandError('Command outside supported identity scope')
        name = commands[0][len(prefix):]
        if not NAME.fullmatch(name):
            raise DeviceCommandError('Invalid hostname or command separator')
        if self.info.platform == 'frr' and self.frr_shell != 'linux':
            raise DeviceCommandError('FRR writes require explicit frr_shell=linux')
        return name

    def validate_config_commands(self, commands):
        if self.info.platform == 'frr':
            self._description_request(commands)
        else:
            self._requested_identity(commands)

    def _description_request(self, commands):
        if self.frr_shell != 'linux':
            raise DeviceCommandError('FRR writes require explicit frr_shell=linux')
        if (not isinstance(commands, list) or len(commands) != 3
                or not all(isinstance(x, str) for x in commands)
                or not re.fullmatch(r'interface [A-Za-z][A-Za-z0-9_.-]{0,31}', commands[0])
                or commands[2] != 'exit'):
            raise DeviceCommandError('Expected interface, description/no description, exit')
        value = commands[1]
        if value == 'no description':
            description = None
        elif re.fullmatch(r'description [A-Za-z0-9][A-Za-z0-9 _.-]{0,79}', value):
            description = value[len('description '):]
            if description != description.strip():
                raise DeviceCommandError('Description must not have trailing spaces')
        else:
            raise DeviceCommandError('Unsupported description or command separator')
        return commands[0][len('interface '):], description

    def _descriptions(self, content):
        lines = self.normalize_config_for_verification(content).splitlines()
        if not lines or lines[-1] != 'end' or not any(x.startswith('frr version ') for x in lines):
            raise DeviceCommandError('Expected complete FRR configuration')
        values, remainder, current = {}, [], None
        for raw in lines:
            line = raw.strip()
            if line.startswith('interface '):
                name = line[len('interface '):]
                if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,31}', name) or name in values:
                    raise DeviceCommandError('Unsupported or duplicate FRR interface block')
                current = name
                values[name] = None
            elif line in ('exit', '!', 'end'):
                current = None
            elif current and line.startswith('description '):
                if values[current] is not None:
                    raise DeviceCommandError('Duplicate interface description')
                _, value = self._description_request(['interface '+current, line, 'exit'])
                values[current] = value
                continue
            remainder.append(raw)
        return values, '\n'.join(remainder)

    def _write_descriptions(self, changes):
        if self._connection is None:
            raise DeviceCommandError('Device is not connected')
        commands = ['configure terminal']
        for name, description in changes.items():
            fragment = ['interface '+name,
                        'no description' if description is None else 'description '+description, 'exit']
            self._description_request(fragment)
            commands.extend(fragment)
        commands.append('end')
        command = 'vtysh ' + ' '.join('-c '+shlex.quote(x) for x in commands)
        self._send_write(command)

    def _send_write(self, command, **options):
        try:
            output = self._connection.send_command(command, read_timeout=self.timeout, **options)
        except (TimeoutError, ReadTimeout, NetmikoTimeoutException):
            raise DeviceWriteError('WRITE_TIMEOUT') from None
        except (OSError, EOFError):
            raise DeviceWriteError('WRITE_CONNECTION_LOST') from None
        except Exception:
            raise DeviceWriteError('WRITE_TRANSPORT_ERROR') from None
        if not isinstance(output, str):
            raise DeviceWriteError('WRITE_INVALID_RESPONSE')
        if re.search(r'(?i)permission denied|not permitted|not enough permissions', output):
            raise DeviceWriteError('WRITE_PERMISSION_DENIED')
        if self._has_error(output) or re.search(r'(?mi)^\s*%|error:', output):
            raise DeviceWriteError('WRITE_REJECTED')
        return output

    def _write_identity(self, name):
        if self._connection is None:
            raise DeviceCommandError('Device is not connected')
        if self.info.platform != 'mikrotik':
            raise DeviceCommandError('FRR hostname writes are unsupported')
        self._send_write('/system identity set name=' + name, expect_string=r'\]\s*>\s*$')
        if self.info.platform == 'mikrotik':
            # RouterOS changes the CLI prompt with the system identity. Netmiko
            # otherwise leaves the new prompt at the end of subsequent exports.
            try:
                self._connection.set_base_prompt()
            except Exception:
                raise DeviceCommandError('Identity changed but SSH prompt refresh failed') from None

    def push_config(self, commands):
        if self.info.platform == 'frr':
            name, value = self._description_request(commands)
            values, remainder = self._descriptions(self.get_running_config())
            if name not in values:
                raise DeviceCommandError('Only existing configured interfaces may be changed')
            expected = dict(values, **{name: value})
            self._write_descriptions({name: value})
            actual, after_remainder = self._descriptions(self.get_running_config())
            if actual != expected or after_remainder != remainder:
                raise DeviceCommandError('Description change did not verify or unmanaged configuration changed')
            return 'Interface description updated and verified; running configuration only'
        name = self._requested_identity(commands)
        before = self.get_running_config()
        _, remainder = self._identity(before)
        self._write_identity(name)
        actual, after_remainder = self._identity(self.get_running_config())
        if actual != name or after_remainder != remainder:
            raise DeviceCommandError('Identity change did not verify or unrelated configuration changed')
        return 'RouterOS identity updated and verified'

    def verify_config_commands(self, commands):
        if self.info.platform == 'frr':
            name, value = self._description_request(commands)
            values, _ = self._descriptions(self.get_running_config())
            return {'device_name':self.info.name, 'passed':name in values and values[name] == value,
                    'verification_mode':'platform-interface-description', 'scope':self.write_scope}
        name = self._requested_identity(commands)
        actual, _ = self._identity(self.get_running_config())
        return {'device_name':self.info.name, 'passed':actual == name,
                'verification_mode':'platform-identity', 'expected_identity':name,
                'actual_identity':actual, 'scope':self.write_scope}

    def restore_config(self, backup):
        if self.info.platform == 'frr':
            if self.frr_shell != 'linux':
                raise DeviceRestoreError('FRR restore requires explicit frr_shell=linux')
            expected, remainder = self._descriptions(backup)
            if self._connection is None:
                self.connect()
            current, current_remainder = self._descriptions(self.get_running_config())
            if remainder != current_remainder or expected.keys() != current.keys():
                raise DeviceRestoreError('Changes outside interface-description scope; refusing partial restore')
            changes = {k:v for k,v in expected.items() if current[k] != v}
            if changes:
                self._write_descriptions(changes)
            if self.normalize_config_for_verification(self.get_running_config()) != self.normalize_config_for_verification(backup):
                raise DeviceRestoreError('Restored configuration did not match snapshot')
            return True
        name, expected_remainder = self._identity(backup)
        self._requested_identity([('/system identity set name=' if self.info.platform == 'mikrotik' else 'hostname ')+name])
        if self._connection is None:
            self.connect()
        if self.info.platform == 'mikrotik':
            # A timed-out write may have changed the remote prompt already.
            self._connection.set_base_prompt()
        current_name, current_remainder = self._identity(self.get_running_config())
        if current_remainder != expected_remainder:
            raise DeviceRestoreError('Changes outside identity scope; refusing partial restore')
        if current_name != name:
            self._write_identity(name)
        actual = self.normalize_config_for_verification(self.get_running_config())
        expected = self.normalize_config_for_verification(backup)
        if actual != expected:
            raise DeviceRestoreError('Restored configuration did not match snapshot')
        return True
