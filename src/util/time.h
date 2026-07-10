#pragma once

#include <chrono>
#include <cstdint>

namespace util {

// Monotonic microsecond clock, used purely for measuring detection-to-parse
// (and later, detection-to-submission) latency. Not wall-clock time.
inline int64_t now_micros() {
    return std::chrono::duration_cast<std::chrono::microseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

} // namespace util
