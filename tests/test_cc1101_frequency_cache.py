"""Exercise the real driver's cache API when carrier profiles change."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from tests.test_htv213_runtime import function

ROOT = Path(__file__).resolve().parents[1]


class FrequencyCacheTest(unittest.TestCase):
    def test_repeated_profile_changes_do_not_require_a_radio_reboot(self):
        compiler = shutil.which("c++")
        if not compiler:
            self.skipTest("native compiler unavailable")
        driver = (ROOT / "firmware/rainpoint_bridge/src/cc1101.cpp").read_text()
        header = (ROOT / "firmware/rainpoint_bridge/src/cc1101.h").read_text()
        capacity = re.search(r"kMaximumCachedTransmitFrequencies = (\d+)", header).group(1)
        harness = '''
#include <array>
#include <cstdint>
#include <cstddef>
#include <iostream>
namespace rainpoint {
constexpr unsigned kChannelNumber=0,kCalibrate=1,kMainStateIdle=2;
constexpr unsigned kFrequencyCalibration3=3,kFrequencyCalibration2=4,kFrequencyCalibration1=5;
class Cc1101 {
public:
    struct CachedFrequencyCalibration {
        std::uint32_t centerFrequencyHz=0;
        std::uint8_t frequencyCalibration3=0,frequencyCalibration2=0,frequencyCalibration1=0;
        bool valid=false;
    };
    static constexpr std::size_t kMaximumCachedTransmitFrequencies=CAPACITY;
    std::array<CachedFrequencyCalibration,kMaximumCachedTransmitFrequencies> cachedTransmitFrequencies_{};
    std::size_t nextCachedTransmitFrequency_=0;
    unsigned channel_=0,restores=0;
    bool fail=false;
    bool enterIdle() {return true;}
    void writeRegister(unsigned,unsigned) {}
    void setFrequency(unsigned) {}
    unsigned strobe(unsigned) {return fail ? 0xff : 0;}
    bool waitForMainState(unsigned,unsigned) {return true;}
    std::uint8_t readRegister(unsigned) {return 0x11;}
    bool restoreReceiveConfiguration(unsigned) {++restores;return true;}
    bool cacheTransmitFrequency(std::uint32_t);
};
ACTUAL_METHOD
}
int main() {
    rainpoint::Cc1101 radio;
    // More than one radio's original pair of frequencies: overrides, other
    // associations and repeated re-enrollment all use this same public API.
    for(unsigned index=0;index<24;++index) {
        const unsigned hz=433100000+index*50000;
        if(!radio.cacheTransmitFrequency(hz)) {
            std::cerr << "Valid carrier rejected after profile " << index; return 1;
        }
    }
    if(radio.restores!=24) return 2;
    if(radio.cacheTransmitFrequency(432999999) || radio.cacheTransmitFrequency(435000001)) return 3;
    radio.fail=true;
    if(radio.cacheTransmitFrequency(434241500)) return 4;
}
'''.replace("CAPACITY", capacity).replace("ACTUAL_METHOD", function(driver, "bool Cc1101::cacheTransmitFrequency("))
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "cache")
            built = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-x", "c++", "-", "-o", executable], input=harness, text=True, capture_output=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([executable], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
