cmake_minimum_required(VERSION 3.21)
project(solana_copy_trader CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(Protobuf CONFIG REQUIRED)
find_package(gRPC CONFIG REQUIRED)
find_package(nlohmann_json CONFIG REQUIRED)
find_package(CURL REQUIRED)

# --- Protobuf/gRPC codegen (manual add_custom_command, not protobuf_generate(),
# so this doesn't depend on which CMake helper macros a given vcpkg protobuf/grpc
# version happens to ship) ---------------------------------------------------

set(PROTO_DIR ${CMAKE_SOURCE_DIR}/proto)
set(PROTO_GEN_DIR ${CMAKE_BINARY_DIR}/generated)
file(MAKE_DIRECTORY ${PROTO_GEN_DIR})

# solana-storage.proto has no local imports.
set(STORAGE_PB_H ${PROTO_GEN_DIR}/solana-storage.pb.h)
set(STORAGE_PB_CC ${PROTO_GEN_DIR}/solana-storage.pb.cc)
add_custom_command(
    OUTPUT ${STORAGE_PB_H} ${STORAGE_PB_CC}
    COMMAND protobuf::protoc
    ARGS --cpp_out=${PROTO_GEN_DIR}
         -I ${PROTO_DIR}
         ${PROTO_DIR}/solana-storage.proto
    DEPENDS ${PROTO_DIR}/solana-storage.proto
    COMMENT "Generating C++ for solana-storage.proto"
    VERBATIM
)

# geyser.proto imports solana-storage.proto and needs gRPC service codegen too.
# It explicitly DEPENDS on solana-storage's generated header/source so the
# build system generates that first -- geyser.pb.cc #includes
# solana-storage.pb.h, and that dependency can't be discovered from a fresh
# tree until after the first successful compile, so it must be stated here.
set(GEYSER_PB_H ${PROTO_GEN_DIR}/geyser.pb.h)
set(GEYSER_PB_CC ${PROTO_GEN_DIR}/geyser.pb.cc)
set(GEYSER_GRPC_H ${PROTO_GEN_DIR}/geyser.grpc.pb.h)
set(GEYSER_GRPC_CC ${PROTO_GEN_DIR}/geyser.grpc.pb.cc)
add_custom_command(
    OUTPUT ${GEYSER_PB_H} ${GEYSER_PB_CC} ${GEYSER_GRPC_H} ${GEYSER_GRPC_CC}
    COMMAND protobuf::protoc
    ARGS --cpp_out=${PROTO_GEN_DIR}
         --grpc_out=${PROTO_GEN_DIR}
         --plugin=protoc-gen-grpc=$<TARGET_FILE:gRPC::grpc_cpp_plugin>
         -I ${PROTO_DIR}
         ${PROTO_DIR}/geyser.proto
    DEPENDS ${PROTO_DIR}/geyser.proto ${STORAGE_PB_H} ${STORAGE_PB_CC}
    COMMENT "Generating C++/gRPC for geyser.proto"
    VERBATIM
)

add_library(geyser_proto STATIC ${STORAGE_PB_CC} ${GEYSER_PB_CC} ${GEYSER_GRPC_CC})
target_link_libraries(geyser_proto PUBLIC protobuf::libprotobuf gRPC::grpc++)
target_include_directories(geyser_proto PUBLIC ${PROTO_GEN_DIR})

# --- Shared code, linked into every executable below --------------------------

add_library(core STATIC
    src/config.cpp
    src/util/logging.cpp
    src/solana/base58.cpp
    src/solana/base64.cpp
    src/solana/pubkey.cpp
    src/parsing/trade_event.cpp
    src/parsing/venue_pumpfun.cpp
    src/parsing/tx_parser.cpp
    src/parsing/tx_parser_json.cpp
    src/parsing/debug_utils.cpp
    src/geyser/geyser_client.cpp
    src/rpc/rpc_client.cpp
    src/rpc/poll_client.cpp
)

target_include_directories(core PUBLIC src)
target_link_libraries(core PUBLIC geyser_proto nlohmann_json::nlohmann_json CURL::libcurl)

# --- Executables ---------------------------------------------------------------

add_executable(copytrader src/main.cpp)
target_link_libraries(copytrader PRIVATE core)

# Standalone research tool: measures real price decay at simulated execution
# lags across the same tracked wallets, to estimate copy-trade viability
# before paying for the geyser engine or risking capital on live execution.
add_executable(lag_experiment src/main_lag_experiment.cpp)
target_link_libraries(lag_experiment PRIVATE core)

# Standalone research tool: tracks tracked wallets' real buy/sell round trips
# and computes both their real P&L and our simulated copy-trade P&L at an
# assumed execution lag -- answers "is this wallet even profitable" and
# "would copying it still be profitable after lag" with real on-chain data.
add_executable(paper_trade src/main_paper_trade.cpp)
target_link_libraries(paper_trade PRIVATE core)
