"""Physical pin oracle, independent of the carrier generator's numbering.

Top view, USB down, radio antenna right: the photographed V2.0 module has
1/2 at its top and 7/8 at its bottom. Test the delivered KiCad artifact, not
just a second copy of the generator's coordinate table. No KiCad install needed.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "hardware/rainpoint_carrier/kicad/rainpoint_carrier.kicad_pcb"


def parse_sexpr(text):
    stack = [[]]
    for token in re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', text):
        if token == "(":
            child = []
            stack[-1].append(child)
            stack.append(child)
        elif token == ")":
            stack.pop()
        else:
            stack[-1].append(token[1:-1] if token.startswith('"') else token)
    return stack[0][0]


def children(node, name):
    return [item for item in node if isinstance(item, list) and item[0] == name]


def value(node, name):
    return children(node, name)[0]


class CarrierPinOrientationTests(unittest.TestCase):
    def setUp(self):
        self.board = parse_sexpr(BOARD.read_text())
        self.headers = {}
        for fp in children(self.board, "footprint"):
            ref = next(p[2] for p in children(fp, "property") if p[1] == "Reference")
            self.headers[ref] = fp

    def test_physical_radio_rows_match_module_not_reversed_carrier(self):
        radio = self.headers["J3"]
        # KiCad Y increases downward. Sorting by Y then X reconstructs what
        # the user sees without trusting the pad numbers printed by our tool.
        pads = sorted(children(radio, "pad"), key=lambda p: (
            float(value(p, "at")[2]), float(value(p, "at")[1])))
        expected = [("1", "/GND"), ("2", "/3V3"),
                    ("3", "/RADIO_GDO0"), ("4", "/RADIO_CSN"),
                    ("5", "/RADIO_SCK"), ("6", "/RADIO_MOSI"),
                    ("7", "/RADIO_MISO"), ("8", "/RADIO_GDO2")]
        actual = [(p[1], value(p, "net")[-1]) for p in pads]
        self.assertEqual(actual, expected)
        self.assertEqual(pads[0][3], "rect", "mark physical pin 1")
        self.assertEqual(float(value(radio, "at")[3]) if len(value(radio, "at")) > 3 else 0, 0)

    def test_esp32_connections_match_firmware_and_photographed_board(self):
        for ref, expected in {
            "J1": {"2": "/GND", "6": "/RADIO_CSN", "7": "/RADIO_GDO0", "8": "/RADIO_GDO2"},
            "J2": {"1": "/3V3", "9": "/RADIO_SCK", "10": "/RADIO_MISO", "15": "/RADIO_MOSI"},
        }.items():
            pads = {p[1]: p for p in children(self.headers[ref], "pad")}
            for number, net in expected.items():
                self.assertEqual(value(pads[number], "net")[-1], net)
        firmware = (ROOT / "firmware/rainpoint_bridge/src/main.cpp").read_text()
        for symbol, pin in {"kSpiSckPin": 18, "kSpiMisoPin": 19,
                            "kSpiMosiPin": 23, "kPrimaryChipSelectPin": 27}.items():
            self.assertRegex(firmware, rf"{symbol}\s*=\s*{pin};")

    def test_fabrication_netlist_physical_order_matches_module(self):
        # IPC-D-356 exported by KiCad uses upward Y (unlike pcbnew's page Y).
        text = (ROOT / "hardware/rainpoint_carrier/fabrication/rainpoint_carrier.d356").read_text()
        radio = []
        for line in text.splitlines():
            if not re.search(r"\bJ3\s+-\d", line):
                continue
            match = re.search(r"X([+-]\d+)Y([+-]\d+)", line)
            self.assertIsNotNone(match)
            radio.append((int(match[2]), int(match[1]), line[3:17].strip()))
        self.assertEqual([p[2] for p in sorted(radio, key=lambda p: (-p[0], p[1]))],
                         ["/GND", "/3V3", "/RADIO_GDO0", "/RADIO_CSN",
                          "/RADIO_SCK", "/RADIO_MOSI", "/RADIO_MISO", "/RADIO_GDO2"])

    def test_library_rows_and_board_rows_agree(self):
        fp = parse_sexpr((ROOT / "hardware/rainpoint_carrier/kicad/RainPoint_Carrier.pretty/CC1101_2x4.kicad_mod").read_text())
        library = {p[1]: tuple(map(float, value(p, "at")[1:3])) for p in children(fp, "pad")}
        board = {p[1]: tuple(map(float, value(p, "at")[1:3])) for p in children(self.headers["J3"], "pad")}
        self.assertEqual(library, board)


if __name__ == "__main__":
    unittest.main()
