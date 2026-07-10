#include "util/logging.h"

#include <chrono>
#include <ctime>
#include <iomanip>
#include <iostream>
#include <mutex>

namespace util {

namespace {

std::mutex g_log_mutex;

const char* level_name(LogLevel level) {
    switch (level) {
        case LogLevel::Debug: return "DEBUG";
        case LogLevel::Info: return "INFO";
        case LogLevel::Warn: return "WARN";
        case LogLevel::Error: return "ERROR";
    }
    return "?";
}

} // namespace

void log(LogLevel level, const std::string& msg) {
    auto now = std::chrono::system_clock::now();
    auto now_time_t = std::chrono::system_clock::to_time_t(now);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()) % 1000;

    std::tm tm_buf{};
#if defined(_WIN32)
    gmtime_s(&tm_buf, &now_time_t);
#else
    gmtime_r(&now_time_t, &tm_buf);
#endif

    std::lock_guard<std::mutex> lock(g_log_mutex);
    auto& out = (level == LogLevel::Error || level == LogLevel::Warn) ? std::cerr : std::cout;
    out << std::put_time(&tm_buf, "%Y-%m-%dT%H:%M:%S") << '.' << std::setfill('0') << std::setw(3)
        << ms.count() << "Z [" << level_name(level) << "] " << msg << '\n';
}

} // namespace util
