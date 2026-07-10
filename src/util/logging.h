#pragma once

#include <string>

namespace util {

enum class LogLevel { Debug, Info, Warn, Error };

void log(LogLevel level, const std::string& msg);

} // namespace util

#define LOG_DEBUG(msg) ::util::log(::util::LogLevel::Debug, (msg))
#define LOG_INFO(msg) ::util::log(::util::LogLevel::Info, (msg))
#define LOG_WARN(msg) ::util::log(::util::LogLevel::Warn, (msg))
#define LOG_ERROR(msg) ::util::log(::util::LogLevel::Error, (msg))
