"""Actual RMT stream construction must include the native CRC's final bit."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Htv213ControlTailTest(unittest.TestCase):
    def test_actual_rmt_stream_adds_one_explicit_symbol_and_preserves_legacy_default(self):
        compiler = shutil.which("c++")
        if not compiler: self.skipTest("native compiler unavailable")
        source = (ROOT / "firmware/rainpoint_bridge/src/cc1101.cpp").read_text()
        block = source.split("    const std::size_t symbolCount = rainpointSymbolCount(", 1)[1]
        block = "    const std::size_t symbolCount = rainpointSymbolCount(" + block.split("    bool sent = prepareTransmit();", 1)[0]
        harness = '''
#include <vector>
#include <iostream>
#include "rainpoint_pairing.h"
using namespace rainpoint;
struct rmt_item32_t { unsigned level0,duration0,level1,duration1; };
int main() {
    constexpr unsigned kSymbolMicros=50;
    const std::uint16_t wakeSymbols=2400;
    std::array<std::uint8_t,kFrameBytes> frame{};
    for (const bool invert:{false,true}) for (const std::int8_t finalSymbol:{-1,0,1}) {
''' + block + '''
        const unsigned expected=2400+304+(finalSymbol>=0);
        if (symbolCount!=expected) {
            std::cerr << "Expected " << expected << " symbols, generated " << symbolCount; return 1;
        }
        if (finalSymbol>=0 && symbolAt(symbolCount-1)!=(finalSymbol^invert)) return 2;
        for (unsigned i=0;i<2400+304;++i)
            if (symbolAt(i)!=rainpointSymbol(frame,wakeSymbols,i,invert)) return 3;
        const auto last=items.back();
        if (finalSymbol>=0 && (last.level0!=(unsigned(finalSymbol)^invert) || last.duration0!=50)) return 4;
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            exe = str(Path(directory) / "tail")
            result = subprocess.run([compiler,"-std=c++17","-DRAINPOINT_HTV213_CONTROL_EXPERIMENT",
                "-I"+str(ROOT/"firmware/rainpoint_bridge/include"),"-x","c++","-","-o",exe],
                input=harness,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result = subprocess.run([exe],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
