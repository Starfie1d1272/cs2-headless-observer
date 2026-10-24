#pragma once
// Compile against locally obtained Valve SDK headers. No SDK binaries are vendored.
// Host must supply legitimate, initialized App 730 user interfaces and keep them alive.
#include "session.hpp"
#include <steam_api.h>
#include <steam_api_flat.h>
#include <functional>

namespace cs2::observer {
class SteamBridge final : private Port {
 public:
  SteamBridge(ISteamUser& user, ISteamUtils& utils, ISteamNetworkingSockets& sockets,
              const SteamNetworkingIPAddr& authorized_endpoint)
      : user_(user), utils_(utils), sockets_(sockets), endpoint_(authorized_endpoint), session_(*this),
        ticket_callback_(this, &SteamBridge::on_ticket),
        connection_callback_(this, &SteamBridge::on_connection) {}
  ~SteamBridge() { session_.close(); }
  SteamBridge(const SteamBridge&) = delete;
  SteamBridge& operator=(const SteamBridge&) = delete;

  Session& session() { return session_; }
  int remote_end_reason() const { return remote_end_reason_; }
  std::uint64_t remote_steam_id() {
    SteamNetConnectionInfo_t info{};
    return transport_ready() && sockets_.GetConnectionInfo(session_.connection(), &info) && trusted(info)
      ? SteamAPI_SteamNetworkingIdentity_GetSteamID64(&info.m_identityRemote) : 0;
  }
  std::uint64_t local_steam_id() { return remote_steam_id() && context_ready() ? own_steam_id() : 0; }
  // Single-threaded host calls at >10 Hz. Do not mix with ManualDispatch.
  void pump(std::uint64_t monotonic_ms) {
    // Expire before dispatch: an already queued success must not revive a timeout.
    if (!context_ready()) session_.close(Failure::context);
    session_.tick(monotonic_ms);
    SteamAPI_RunCallbacks();
    if (!context_ready()) session_.close(Failure::context);
    session_.tick(monotonic_ms);
  }
  // GNS owns message ACK/reassembly/encryption; this supplies complete GNS messages,
  // NOT decoded Source 2 netchannel data. The consumer must not retain the span.
  int receive(const std::function<void(std::span<const std::uint8_t>, bool)>& consume) {
    if (!transport_ready() && !(remote_end_reason_ == 1038 && session_.connection())) return 0;
    SteamNetworkingMessage_t* message = nullptr;
    const int count = sockets_.ReceiveMessagesOnConnection(session_.connection(), &message, 1);
    if (count < 0) { session_.close(Failure::disconnected); return count; }
    if (!message) return count;
    struct Release { SteamNetworkingMessage_t* p; ~Release() { SteamAPI_SteamNetworkingMessage_t_Release(p); } } release{message};
    if (message->m_cbSize < 0) { session_.close(Failure::disconnected); return -1; }
    try {
      consume({static_cast<const std::uint8_t*>(message->m_pData), static_cast<std::size_t>(message->m_cbSize)},
        (message->m_nFlags & k_nSteamNetworkingSend_Reliable) != 0);
    } catch (...) {
      session_.close(Failure::consumer);
      throw; // RAII releases this SDK message even when protocol processing fails.
    }
    return count;
  }
  EResult send(std::span<const std::uint8_t> bytes, int flags) {
    if (!transport_ready() || bytes.size() > 512 * 1024) return k_EResultInvalidState;
    return sockets_.SendMessageToConnection(session_.connection(), bytes.data(),
      static_cast<std::uint32_t>(bytes.size()), flags, nullptr);
  }
 private:
  bool transport_ready() const {
    const auto s = session_.state();
    return s == State::connected || s == State::ticket_pending || s == State::ready || s == State::ready_no_ticket;
  }
  bool context_ready() override { return utils_.GetAppID() == 730 && user_.BLoggedOn(); }
  void init_authentication() override { sockets_.InitAuthentication(); }
  Availability authentication() override {
    const auto status = sockets_.GetAuthenticationStatus(nullptr);
    if (status == k_ESteamNetworkingAvailability_Current) {
      SteamNetworkingIdentity identity{};
      return sockets_.GetIdentity(&identity) && SteamAPI_SteamNetworkingIdentity_GetSteamID64(&identity) == own_steam_id() && own_steam_id() != 0
        ? Availability::current : Availability::failed;
    }
    if (status == k_ESteamNetworkingAvailability_Failed || status == k_ESteamNetworkingAvailability_CannotTry)
      return Availability::failed;
    return Availability::waiting;
  }
  std::uint32_t connect() override { return sockets_.ConnectByIPAddress(endpoint_, 0, nullptr); }
  std::uint32_t request_ticket(std::span<std::uint8_t> bytes, std::uint32_t& size) override {
    SteamNetConnectionInfo_t info{};
    if (!sockets_.GetConnectionInfo(session_.connection(), &info) || !trusted(info)) return 0;
    return user_.GetAuthSessionTicket(bytes.data(), static_cast<int>(bytes.size()), &size, &info.m_identityRemote);
  }
  std::uint64_t own_steam_id() override { return user_.GetSteamID().ConvertToUint64(); }
  void cancel_ticket(std::uint32_t handle) noexcept override { user_.CancelAuthTicket(handle); }
  void close_connection(std::uint32_t handle) noexcept override {
    sockets_.CloseConnection(handle, 1000, "observer-session-ended", false);
  }
  static bool trusted(SteamNetConnectionInfo_t& info) {
    return info.m_eState == k_ESteamNetworkingConnectionState_Connected &&
      !(info.m_nFlags & (k_nSteamNetworkConnectionInfoFlags_Unauthenticated | k_nSteamNetworkConnectionInfoFlags_Unencrypted)) &&
      SteamAPI_SteamNetworkingIdentity_GetSteamID64(&info.m_identityRemote) != 0;
  }
  void on_ticket(GetAuthSessionTicketResponse_t* callback) {
    session_.ticket_callback(callback->m_hAuthTicket, static_cast<int>(callback->m_eResult));
  }
  void on_connection(SteamNetConnectionStatusChangedCallback_t* callback) {
    if (callback->m_hConn != session_.connection()) return;
    if (callback->m_info.m_eState == k_ESteamNetworkingConnectionState_Connected) {
      // Callback snapshots can already be stale; query current state before trusting.
      SteamNetConnectionInfo_t current{};
      session_.connected(callback->m_hConn,
        sockets_.GetConnectionInfo(callback->m_hConn, &current) && trusted(current));
    } else if (callback->m_info.m_eState == k_ESteamNetworkingConnectionState_ClosedByPeer ||
               callback->m_info.m_eState == k_ESteamNetworkingConnectionState_ProblemDetectedLocally) {
      remote_end_reason_ = callback->m_info.m_eEndReason;
      // Retain queued inbound messages on normal source completion; owner closes after drain.
      session_.disconnected(callback->m_hConn, remote_end_reason_ == 1038);
    }
  }
  ISteamUser& user_;
  ISteamUtils& utils_;
  ISteamNetworkingSockets& sockets_;
  SteamNetworkingIPAddr endpoint_;
  Session session_;
  int remote_end_reason_ = 0;
  CCallback<SteamBridge, GetAuthSessionTicketResponse_t> ticket_callback_;
  CCallback<SteamBridge, SteamNetConnectionStatusChangedCallback_t> connection_callback_;
};
} // namespace cs2::observer

