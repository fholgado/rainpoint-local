"""Durable revoke-before-grant barrier for sensor and HTV405 ACK owners.

The caller serializes access with its gateway lock. Network delivery is never
confirmation. Journal entries survive deleted registry rows and process restarts;
only a correlated response from the current authenticated connection advances them.
"""
from __future__ import annotations

import copy
import json
import uuid


CAPABILITY = "correlated_ack_ownership"
METADATA_KEY = "ack_ownership_operations_v1"


class AckOwnership:
    def __init__(self, store, nodes, sender, commit):
        self.store = store
        self.nodes = nodes
        self.sender = sender
        self.commit = commit
        self.operations = json.loads(store.metadata_value(METADATA_KEY) or '{}')

    def _save(self):
        self.store.set_metadata_value(METADATA_KEY, json.dumps(self.operations))

    def pending(self, kind, endpoint):
        return f'{kind}:{endpoint}' in self.operations

    def snapshot(self):
        # Public diagnostics omit stored command bodies and control snapshots.
        fields = ('kind', 'endpoint', 'generation', 'old_node', 'new_node', 'stage', 'state')
        return [{**{key: operation[key] for key in fields}, 'confirmed_active_owner': None}
                for operation in self.operations.values()]

    def start(self, *, kind, endpoint, old_node, revoke, new_node=None,
              configure=None, target=None):
        key = f'{kind}:{endpoint}'
        if key in self.operations:
            raise RuntimeError('ACK ownership cleanup is pending; reconnect the old owner and retry')
        self.operations[key] = {
            'kind': kind, 'endpoint': endpoint, 'generation': uuid.uuid4().hex,
            'old_node': old_node, 'new_node': new_node, 'revoke': revoke,
            'configure': configure, 'target': target, 'stage': 'revoke',
            'state': 'pending', 'command_id': None, 'session': None,
        }
        # Write the tombstone before any packet can leave the gateway.
        self._save()
        self._dispatch(key)
        return self.snapshot()

    def resume(self, node_id):
        for key, operation in list(self.operations.items()):
            owner = operation['old_node'] if operation['stage'] == 'revoke' else operation['new_node']
            if owner == node_id:
                self._dispatch(key)

    def _dispatch(self, key):
        operation = self.operations[key]
        stage = operation['stage']
        owner = operation['old_node'] if stage == 'revoke' else operation['new_node']
        node = self.nodes.get(owner, {})
        if not (node.get('connected') is True and node.get('authenticated') is True):
            operation['state'] = 'owner_offline'
            self._save()
            return
        if CAPABILITY not in node.get('capabilities', []) or not node.get('connected_at'):
            operation['state'] = 'owner_firmware_upgrade_required'
            self._save()
            return
        # Repeated restore calls in one connection do not flood the node. A
        # reconnect invalidates this command and issues a fresh correlation ID.
        session = str(node['connected_at'])
        if operation['state'] == 'awaiting_confirmation' and operation['session'] == session:
            return
        command = copy.deepcopy(operation[stage])
        command.update(command_id=uuid.uuid4().hex,
                       ownership_generation=operation['generation'],
                       ownership_session=session)
        operation.update(command_id=command['command_id'], session=session,
                         state='awaiting_confirmation')
        self._save()
        diagnostic = 'routine_ack_command_id' if operation['kind'] == 'sensor' else 'htv405_routine_ack_command_id'
        node[diagnostic] = command['command_id']
        try:
            self.sender(owner, command)
        except (ConnectionError, KeyError, RuntimeError, ValueError):
            # A sender may deliver synchronously before throwing. Do not undo a
            # response which has already advanced/completed the operation.
            current = self.operations.get(key)
            if current and current['command_id'] == command['command_id']:
                current['state'] = 'delivery_failed'
                self._save()

    def observe(self, node_id, message):
        for key, operation in list(self.operations.items()):
            owner = operation['old_node'] if operation['stage'] == 'revoke' else operation['new_node']
            node = self.nodes.get(owner, {})
            if (node_id != owner or node.get('connected') is not True
                    or node.get('authenticated') is not True
                    or node.get('connected_at') != operation['session']
                    or not operation['command_id']
                    or message.get('command_id') != operation['command_id']):
                continue
            if message.get('type') == 'command_error':
                operation['state'] = 'command_failed'
                self._save()
                return True
            if (message.get('type') != 'ack_ownership_status'
                    or message.get('ownership_generation') != operation['generation']
                    or message.get('ownership_session') != operation['session']
                    or message.get('kind') != operation['kind']
                    or message.get('endpoint') != operation['endpoint']):
                continue
            state = message.get('state')
            if state == 'rejected':
                operation['state'] = 'command_failed'
                self._save()
            elif operation['stage'] == 'revoke' and state == 'revoked':
                if operation['new_node'] is None:
                    del self.operations[key]
                    self._save()
                else:
                    operation.update(stage='configure', state='pending', command_id=None, session=None)
                    self._save()
                    self._dispatch(key)
            elif operation['stage'] == 'configure' and state == 'configured':
                # Idempotent durable assignment first: a crash between these
                # commits leaves the barrier in place, never a second owner.
                self.commit(operation['kind'], copy.deepcopy(operation['target']))
                del self.operations[key]
                self._save()
            return True
        return False
