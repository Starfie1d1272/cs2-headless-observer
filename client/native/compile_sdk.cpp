// Compile-only integration check; there is no login/connection executable.
#include "steam_bridge.hpp"
#include <cstddef>
#include <memory>
static_assert(GetAuthSessionTicketResponse_t::k_iCallback == 163);
static_assert(k_nSteamNetworkingSend_UnreliableNoDelay == 5);
static_assert(k_nSteamNetworkingSend_UnreliableNoNagle == 1);
static_assert(k_nSteamNetworkingSend_Reliable == 8);
static_assert(offsetof(SteamNetworkingMessage_t, m_nFlags) == 0xc4);
static_assert(offsetof(SteamNetworkingMessage_t, m_conn) == 0xc);

// Emit actual SDK callback/pump references in the object, without linking/running.
std::unique_ptr<mizar::observer::SteamBridge> compile_checked_bridge(
    ISteamUser& user, ISteamUtils& utils, ISteamNetworkingSockets& sockets,
    const SteamNetworkingIPAddr& endpoint) {
  return std::make_unique<mizar::observer::SteamBridge>(user, utils, sockets, endpoint);
}
void compile_checked_pump(mizar::observer::SteamBridge& bridge, std::uint64_t now_ms) {
  bridge.pump(now_ms);
}

