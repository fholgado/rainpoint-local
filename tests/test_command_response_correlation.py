"""Actual pending-command seams: wrong-phase replies must not consume reservations."""
import sys
from pathlib import Path
import json
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests import test_stock_sequence_regressions as positive
from tests import test_rainpoint_safety as safety
from tests import test_rainpointd as gateway_tests
from rainpointd.valve_protocol import decode_htv145_command_error


class Htv145NegativePhaseInvariant(unittest.TestCase):
    setUp = safety.Htv145RuntimeTest.setUp
    enroll = safety.Htv145RuntimeTest.enroll

    def test_opposite_sixth_bit_negative_must_not_fail_pending_open(self):
        self.enroll()
        self.coordinator.request_open(self.profile, duration_seconds=60,
            started_at='2026-09-05T12:02:00+00:00')
        before = self.store.htv145_control_states()[0]
        fixture = json.loads((ROOT / 'research/fixtures/htv145_partial_pairing_control_replies_20260905.json').read_text())
        frame = fixture['trials'][1]['valid_valve_frames'][0]['frame']
        changes = {13: 0x82, 14: 0x50}
        changes.update(enumerate(self.profile.link.valve_endpoint, 5))
        changes.update(enumerate(self.profile.link.controller_endpoint, 9))
        opposite = positive.mutate_frame(frame, changes)
        self.assertIsNotNone(decode_htv145_command_error(opposite, self.profile.link))
        self.assertEqual(4, positive.stock_payload(opposite.hex())[9] & 63)
        with self.assertRaisesRegex(ValueError, 'matching durable reservation'):
            self.coordinator.observe_frame(self.profile, opposite,
                observed_at='2026-09-05T12:02:01+00:00')
        after = self.store.htv145_control_states()[0]
        self.assertIsNotNone(after['pending_command_id'],
            'native phase 4 negative must not consume native phase 5 OPEN')


class Htv405NegativePhaseInvariant(unittest.TestCase):
    setUp = positive.Htv405SequenceRegressionTest.setUp

    def test_odd_negative_must_not_fail_even_pending_close(self):
        self.gateway.observe_valve_control_air_response(self.node, self.response,
            observed_at='2026-08-24T20:00:21+00:00')
        self.gateway.request_htv405_control(device_id='htv405-94a98013', action='close',
            zone=1, now=positive.datetime.fromisoformat('2026-08-24T20:00:40+00:00'))
        before = self.gateway._store.valve_registry()[0]
        self.assertEqual(7, before['control_pending_sequence'])
        negative = positive.mutate_frame(gateway_tests.GatewayTest.HTV405_REJECTION_SEQUENCE_6,
            {13: 0x87})
        self.assertEqual(15, positive.stock_payload(negative.hex())[9] & 63)
        self.gateway.observe_valve_control_air_rejection(self.node, negative.hex(),
            observed_at='2026-08-24T20:00:41+00:00')
        after = self.gateway._store.valve_registry()[0]
        self.assertIsNotNone(after['control_pending_command_id'],
            'native phase 15 negative must not consume native phase 14 CLOSE')

    def test_matching_odd_negative_still_fails_open(self):
        result = self.gateway.observe_valve_control_air_rejection(self.node,
            gateway_tests.GatewayTest.HTV405_REJECTION_SEQUENCE_6,
            observed_at='2026-08-24T20:00:21+00:00')
        self.assertIsNotNone(result)
        self.assertIsNone(result['control_pending_command_id'])


class Htv145NativeCorrelationTest(unittest.TestCase):
    setUp = safety.Htv145RuntimeTest.setUp

    def test_actual_handler_ignores_stale_replies_and_preserves_matched_outcomes(self):
        main = (ROOT / 'firmware/rainpoint_bridge/src/main.cpp').read_text()
        function = 'void observeHtv145CandidateFrame(' + main.split(
            'void observeHtv145CandidateFrame(', 1)[1].split('\nvoid pollHtv145Candidate()', 1)[0]
        fixture = json.loads((ROOT / 'research/fixtures/htv145_partial_pairing_control_replies_20260905.json').read_text())
        negative = fixture['trials'][1]['valid_valve_frames'][0]['frame']
        route = dict(enumerate(self.profile.link.valve_endpoint, 5))
        route.update(enumerate(self.profile.link.controller_endpoint, 9))
        correct = positive.mutate_frame(self.response, {13: 0x82})
        cases = [
            (positive.mutate_frame(correct, {14: 0x50}), True, ''),
            (positive.mutate_frame(correct, {13: 0x81}), True, ''),
            (positive.mutate_frame(negative, {**route, 13: 0x82, 14: 0x50}), True, ''),
            (positive.mutate_frame(negative, {**route, 13: 0x82, 14: 0xd0}), False, 'failed'),
            (correct, False, 'confirmed'),
        ]
        prefix = r'''
#include "rainpoint_htv145_control.h"
#include <string>
struct Owner {
 bool configured=true, pending=true, idleAnchor=false, stateObserved=false, observedWatering=false;
 bool commandMarkerInverted=true, commandWatering=true;
 unsigned stateObservedAtMs=0, burstStartedAtMs=0;
 unsigned observedFrames=0, matchingRouteFrames=0, invalidTrailerFrames=0;
 unsigned classifiedResponseFrames=0, classifiedStateFrames=0, conflictingStateFrames=0;
 unsigned char transmittedSequence=0x82;
 rainpoint::Htv145Link link{};
 std::array<std::uint8_t,rainpoint::kFrameBytes> commandFrame{};
} owner;
Owner& htv145Owner() { return owner; }
unsigned millis() { return 1000; }
std::string outcome;
void failHtv145Candidate(const char*, const std::array<std::uint8_t,rainpoint::kFrameBytes>* = nullptr) {
 owner.pending=false; outcome="failed";
}
void confirmHtv145Candidate(const char*, const std::array<std::uint8_t,rainpoint::kFrameBytes>&) {
 owner.pending=false; outcome="confirmed";
}
'''
        # Reuse the real signature so fake I/O cannot conceal a bad call site.
        status_signature = 'void reportHtv145CandidateStatus(' + main.split(
            'void reportHtv145CandidateStatus(', 1)[1].split(') {', 1)[0] + ') {}\n'
        prefix += status_signature
        array = lambda data: '{' + ','.join(str(b) for b in data) + '}'
        code = prefix + function + '\nint main() {\n'
        for index, (frame, pending, expected) in enumerate(cases):
            code += 'owner=Owner{}; outcome.clear();\n'
            code += 'owner.link={' + array(self.profile.link.controller_endpoint) + ',' + array(self.profile.link.valve_endpoint) + '};\n'
            code += 'if (!rainpoint::buildHtv145OpenFrame(owner.link,0x82,60,0x4f03,owner.commandFrame,true)) return 99;\n'
            code += 'observeHtv145CandidateFrame(' + array(frame) + ');\n'
            code += f'if (owner.pending != {int(pending)} || outcome != "{expected}") return {index + 1};\n'
        code += 'return 0;\n}\n'
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / 'htv145-handler')
            compiled = subprocess.run(['c++', '-std=c++17', '-x', 'c++', '-',
                '-I' + str(ROOT / 'firmware/rainpoint_bridge/include'), '-o', executable],
                input=code, capture_output=True, text=True)
            self.assertEqual(0, compiled.returncode, compiled.stderr)
            result = subprocess.run([executable], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, f'failed native case {result.returncode}: {result.stderr}')


class Htv405NativePositiveInvariant(unittest.TestCase):
    def test_actual_positive_handler_must_not_consume_opposite_action(self):
        opposite = positive.mutate_frame(gateway_tests.GatewayTest.HTV405_OPEN_RESPONSE_SEQUENCE_6,
            {14: 0x50, 18: 0x4f})
        self.check_handler(opposite, watering=True, pending=True, authenticated=False)

    def test_actual_handler_confirms_matching_open(self):
        self.check_handler(bytes.fromhex(gateway_tests.GatewayTest.HTV405_OPEN_RESPONSE_SEQUENCE_6),
                           watering=True, pending=False, authenticated=True)

    def test_actual_handler_confirms_matching_close(self):
        close = positive.mutate_frame(gateway_tests.GatewayTest.HTV405_OPEN_RESPONSE_SEQUENCE_6,
            {14: 0x50, 18: 0x4f})
        self.check_handler(close, watering=False, pending=False, authenticated=True)

    def test_actual_negative_handler_preserves_even_close(self):
        self.check_handler(bytes.fromhex(gateway_tests.GatewayTest.HTV405_REJECTION_SEQUENCE_6),
                           watering=False, pending=True, authenticated=False)

    def test_actual_negative_handler_rejects_matching_open_without_authentication(self):
        self.check_handler(bytes.fromhex(gateway_tests.GatewayTest.HTV405_REJECTION_SEQUENCE_6),
                           watering=True, pending=False, authenticated=False)

    def check_handler(self, raw, *, watering, pending, authenticated):
        # Compile the actual production response branches and real decoders.
        # Only link acceptance, radio receive restore, and status sinks are fakes.
        main = (ROOT / 'firmware/rainpoint_bridge/src/main.cpp').read_text()
        handler = main.split('bool observeValveProbeFrame(', 1)[1].split(
            '    rainpoint::Htv405Phase nextPhase{};', 1)[0]
        handler = 'bool observeValveProbeFrame(' + handler + '\nreturn false;\n}\n'
        prefix = r'''
#include "rainpoint_valve_control.h"
#include <string>
#include <iostream>
namespace rainpoint { struct Cc1101 { bool restoreReceiveChannel(int) { return true; } }; }
struct Probe {
 bool commandPendingConfirmation=true, responseListenActive=true;
 rainpoint::Htv405Phase transmittedPhase{6,false};
 unsigned char transmittedZone=1;
 bool transmittedIdleSyncAnchor=false;
 unsigned char commandSequence=6;
 bool commandRepeat=false, counterConfigured=false, commandCounterAuthenticated=false;
 bool confirmedStateValid=false, confirmedWatering=false;
 unsigned char confirmedActiveZone=0, lastConfirmedSequence=0;
 bool openSent=true, closeSent=false;
 std::array<std::uint8_t,rainpoint::kFrameBytes> commandFrame{};
 std::string commandId="pending-open";
} valveControlProbe;
constexpr int kHcs026TelemetryChannel=0;
bool valveProbeMatchesLink(const std::array<std::uint8_t,rainpoint::kFrameBytes>&) { return true; }
void reportValveProbeStatus(const char*, const std::array<std::uint8_t,rainpoint::kFrameBytes>* = nullptr) {}
void reportValveProbeError(const char*) {}
'''
        suffix = '''
int main() {
 rainpoint::Htv405GatewayControlLink link{{0xb9,0xc4,0x02,0x80},{0x39,0x84,0x02,0x80}};
 bool built = %s ? rainpoint::buildHtv405GatewayOpenFrame(link,valveControlProbe.transmittedPhase,
       1,5,60,0x4f03,valveControlProbe.commandFrame)
       : rainpoint::buildHtv405GatewayCloseFrame(link,valveControlProbe.transmittedPhase,
       1,5,0x4f03,valveControlProbe.commandFrame);
 if (!built) return 2;
 std::array<std::uint8_t,rainpoint::kFrameBytes> frame={%s};
 rainpoint::Cc1101 radio;
 observeValveProbeFrame(frame,radio,0);
 std::cout << "pending=" << valveControlProbe.commandPendingConfirmation
           << " counter_authenticated=" << valveControlProbe.commandCounterAuthenticated
           << " confirmed_watering=" << valveControlProbe.confirmedWatering << "\\n";
 return valveControlProbe.commandPendingConfirmation == %s &&
        valveControlProbe.commandCounterAuthenticated == %s ? 0 : 1;
}
''' % (int(watering), ','.join(str(b) for b in raw), int(pending), int(authenticated))
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / 'positive-handler')
            compiled = subprocess.run(['c++','-std=c++17','-x','c++','-',
                '-I' + str(ROOT / 'firmware/rainpoint_bridge/include'), '-o', executable],
                input=prefix+handler+suffix, text=True, capture_output=True)
            self.assertEqual(0, compiled.returncode, compiled.stderr)
            result = subprocess.run([executable], text=True, capture_output=True)
            self.assertEqual(0, result.returncode,
                'native handler disagreed with correlated transaction state: ' + result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
