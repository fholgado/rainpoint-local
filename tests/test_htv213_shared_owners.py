"""Normal shared-radio enrollment preserves each valve's durable state."""
import copy
import unittest

from tests import test_htv213_enrollment_journal as fixtures
from tests.test_valve_configuration import alter
from tests.test_htv213_pairing_gateway import NODE
from rainpointd import htv213_owner as owner, htv213_control_transport as transport
from rainpointd.htv213_control import ControlJournal


class SharedOwnersTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.EnrollmentFlowTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.gateway = self.fixture.gateway
        self.gateway.update_node(NODE, capabilities=self.fixture.capabilities +
            [transport.SHARED_RADIO_CAPABILITY, transport.NORMAL_CONTROL_CAPABILITY])

    def enroll(self, number):
        started = self.fixture.start()
        factory = f'{0x11556677 + number:08x}'
        paired = f'{int(factory,16) | 0x80000000:08x}'
        proof = {**self.fixture.proof, 'command_id':started['command_id'], 'factory_endpoint':factory}
        for field in ('notification_ack_frame','completion_frame'):
            raw = bytearray.fromhex(proof[field])
            raw[5:9] = bytes.fromhex(self.gateway.rf_identity.controller_endpoint)
            raw[9:13] = bytes.fromhex(paired)
            proof[field] = alter(raw.hex())
        self.assertTrue(fixtures.flow.observe(self.gateway,NODE,proof))
        result = self.gateway.complete_pairing(endpoint=paired,name=f'Valve {number}')
        for record in owner.records(self.gateway).values():
            owner.observe(self.gateway,NODE,dict(command_id=record['command']['command_id'],enabled=True,
                retained_rejoin_enabled=True,configuration_revision=2))
        return result

    def test_eight_enrollments_keep_independent_readiness_and_counter_records(self):
        first = self.enroll(0)
        journal = ControlJournal(self.gateway._store)
        key = self.gateway.rf_identity.controller_endpoint + ':91556677'
        journal.reserve(key,action='open',port=1,seconds=60)
        original = journal.snapshot(key)
        identifiers = [first['device_id']]
        for number in range(1,8):
            identifiers.append(self.enroll(number)['device_id'])
            self.assertEqual(journal.snapshot(key),original)
        devices = self.gateway.devices()
        self.assertEqual({d['device_id'] for d in devices},set(identifiers))
        self.assertTrue(all(d['available'] for d in devices))
        self.assertEqual(len(self.gateway._nodes[NODE]['htv213_owners']),8)
        with self.assertRaisesRegex(ValueError,'capacity'):
            self.fixture.start()
        self.assertEqual(journal.snapshot(key),original)

    def test_control_receipts_for_two_associations_do_not_use_last_dispatch_only(self):
        self.enroll(0); self.enroll(1)
        keys = list(owner.records(self.gateway))
        journal = ControlJournal(self.gateway._store)
        transactions = []
        for key in keys:
            tx = journal.reserve(key,action='open',port=1,seconds=60)
            journal.dispatch(key,tx,lambda *_:None)
            transport.remember(self.gateway,NODE,tx['command_id'],key)
            transactions.append(tx)
        before = [copy.deepcopy(journal.snapshot(key)) for key in keys]
        transport.observe(self.gateway,NODE,dict(command_id=transactions[0]['command_id'],
            state='awaiting_response',tx_armed=True))
        self.assertEqual(self.gateway._nodes[NODE]['htv213_control']['command_id'],transactions[0]['command_id'])
        self.assertTrue(self.gateway._nodes[NODE]['tx_armed'])
        self.assertEqual([journal.snapshot(key) for key in keys],before)
        self.assertFalse(transport.observe_error(self.gateway,'rp-aabbccddeeff',
            dict(command_id=transactions[0]['command_id'])))

    def test_downgrade_before_save_cannot_commit_shared_enrollment(self):
        started = self.fixture.start()
        proof = {**self.fixture.proof,'command_id':started['command_id']}
        for field in ('notification_ack_frame','completion_frame'):
            raw = bytearray.fromhex(proof[field]);raw[5:9]=bytes.fromhex(self.gateway.rf_identity.controller_endpoint)
            proof[field]=alter(raw.hex())
        self.assertTrue(fixtures.flow.observe(self.gateway,NODE,proof))
        self.gateway.update_node(NODE,capabilities=self.fixture.capabilities)
        with self.assertRaisesRegex(ValueError,'shared-radio firmware'):
            self.gateway.complete_pairing(endpoint='91556677',name='No downgrade')
        self.assertEqual(owner.records(self.gateway),{})
