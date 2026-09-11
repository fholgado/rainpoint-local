#pragma once
#include <array>
#include <cstddef>

namespace rainpoint {
// Slots retain independent counters; selecting one never changes its contents.
template <class State, std::size_t N, class Link>
std::size_t associationSlot(const std::array<State, N>& slots, const Link& link,
                            bool allowEmpty) {
    std::size_t empty = N;
    for (std::size_t i = 0; i < N; ++i) {
        if (!slots[i].configured) {
            if (empty == N) empty = i;
        } else if (slots[i].link.controllerEndpoint == link.controllerEndpoint &&
                   slots[i].link.valveEndpoint == link.valveEndpoint) {
            return i;
        }
    }
    return allowEmpty ? empty : N;
}
} // namespace rainpoint
