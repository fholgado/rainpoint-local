"""Offline native terminal-command comparisons against retained RF evidence."""
import unittest

from tests.test_stock_valve_frame_reference import load_fixture, stock_payload


def body(payload: bytes) -> bytes:
    return payload[12:12 + (payload[11] & 31)]


class StockTerminalPairingReferenceTests(unittest.TestCase):
    def assert_terminal_exchange(self, request: bytes, reply: bytes):
        self.assertEqual(request[10], 0x59)
        self.assertEqual(reply[10], 0xD9)
        self.assertEqual(request[9] & 63, reply[9] & 63)
        self.assertEqual(len(body(request)), 1)
        self.assertEqual(body(reply)[:2], b"\x00" + body(request))

    def test_single_zone_stock_terminal_parameter_read_across_two_profiles(self):
        counter2 = load_fixture("htv145_counter2_stock_enrollment_20260901.json")
        row = next(row for row in counter2["exchanges"] if row["stage"] == 5)
        first = (stock_payload(row["request_frame"]), stock_payload(row["reply_frame"]))
        selector2 = load_fixture("htv145_selector2_stock_pairing_control_20260905.json")
        frames = selector2["pairing"]["frames"]
        second = (stock_payload(frames[10]["frame"]), stock_payload(frames[11]["frame"]))
        for request, reply in (first, second):
            with self.subTest(phase=request[9] & 63):
                self.assert_terminal_exchange(request, reply)
                self.assertEqual(body(request), bytes.fromhex("32"))
                self.assertEqual(body(reply), bytes.fromhex("003200"))
        self.assertEqual([first[0][9] & 63, second[0][9] & 63], [8, 5])

    def test_four_zone_uses_same_command_but_different_parameter_values(self):
        fixture = load_fixture("htv405_gateway_pairing_replies.json")
        ids = []
        for row in fixture["exchanges"]:
            request = stock_payload(row["request_frame"])
            if request[10] != 0x59:
                continue
            reply = stock_payload(row["reply_frame"])
            self.assert_terminal_exchange(request, reply)
            parameter_id = body(request)[0]
            ids.append(parameter_id)
            # Native length prefix 12, followed by twelve captured 100 values.
            self.assertEqual(body(reply), bytes((0, parameter_id, 12)) + bytes([100]) * 12)
        self.assertEqual(ids, [0x32, 0x33, 0x34, 0x35])

    def test_failed_local_progress_repeats_plan_read_not_terminal_request(self):
        for name in (
            "htv145_receive_edge_terminal_retry_20260905.json",
            "htv145_low_gain_terminal_retry_20260905.json",
            "htv145_calibrated_tail_terminal_retry_20260905.json",
        ):
            with self.subTest(fixture=name):
                fixture = load_fixture(name)
                requests = [stock_payload(row["frame"]) for row in fixture["requests"]]
                self.assertNotIn(0x59, [request[10] for request in requests])
                plan_reads = [request for request in requests if request[10] == 0x06]
                self.assertEqual([request[9] & 63 for request in plan_reads], [7, 8, 9, 10, 11])
                self.assertEqual([body(request) for request in plan_reads], [bytes.fromhex("0c0100")] * 5)
                replies = [stock_payload(row["frame"]) for row in fixture["replies"]]
                matching = [reply for reply in replies if reply[10] == 0x86]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0][9] & 63, 7)
                self.assertEqual(body(matching[0]), b"\x00")


if __name__ == "__main__":
    unittest.main()
