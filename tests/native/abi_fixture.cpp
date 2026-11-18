// Synthetic ABI test DLL only. No SDK, sockets, authentication or usable tickets.
#include <cstdint>
#include <cstring>
#ifdef _WIN32
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C"
#endif
namespace {
void* const token = reinterpret_cast<void*>(std::uintptr_t{0x1234567887654321});
bool closed = false;
constexpr std::uint8_t auth[] = "SYNTHETIC-NOT-A-TICKET";
}
API int observer_abi_version() { return 4; }
API int observer_boot_failure() { return 0; }
API int observer_init_result() { return 0; }
API void* observer_create(const char* endpoint, std::uint64_t now) {
  closed = false;
  return !std::strcmp(endpoint, "127.0.0.1:27020") && now == 42 ? token : nullptr;
}
API int observer_state(void* handle) { return handle == token && !closed ? 5 : 6; }
API int observer_failure(void*) { return 0; }
API int observer_remote_end_reason(void* handle) { return handle == token ? 1234 : 0; }
API void observer_pump(void*, std::uint64_t) {}
API std::uint64_t observer_remote_id(void* handle) { return handle == token ? 76561198000000001ull : 0; }
API std::uint64_t observer_local_id(void* handle) { return handle == token && !closed ? 76561198000000042ull : 0; }
API int observer_accept_server_auth2(void* handle) { return handle == token && !closed; }
API int observer_request_ticket(void* handle) { return handle == token; }
API const std::uint8_t* observer_auth(void* handle, std::uint32_t* size) {
  *size = handle == token ? sizeof(auth) - 1 : 0; return auth;
}
API int observer_send(void* handle, const std::uint8_t* bytes, std::uint32_t size, int flags) {
  return handle == token && size == 3 && !std::memcmp(bytes, "a\0b", 3) && (flags == 1 || flags == 5);
}
struct Received {
  const std::uint8_t* data;
  std::int64_t sdk_queue_age_us;
  std::uint32_t size;
  std::int32_t reliable;
};
API int observer_receive_many(void* handle, Received* output, int capacity) {
  static constexpr std::uint8_t payload[] = {'a', 0, 'b'};
  if (handle != token || capacity < 2) return -1;
  output[0] = {payload, 730, 3, 1};
  output[1] = {payload, -1, 3, 0};
  return 2;
}
API void observer_release_received(void*) {}
API void observer_close(void* handle) { if (handle == token) closed = true; }

