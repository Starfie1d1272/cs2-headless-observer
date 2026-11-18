#pragma once
// Compile against locally obtained Valve SDK headers. No SDK binaries are vendored.
// Host must supply legitimate, initialized App 730 user interfaces and keep them alive.
#include "session.hpp"
#include <steam_api.h>
#include <steam_api_flat.h>
#include <isteamnetworkingutils.h>
#include <array>

namespace cs2::observer {
class SteamBridge final : private Port {
 public:
  SteamBridge(ISteamUser& user, ISteamUtils& utils, ISteamNetworkingSockets& sockets,
              ISteamNetworkingUtils* networking_utils,
              const SteamNetworkingIPAddr& authorized_endpoint)
      : user_(user), utils_(utils), sockets_(sockets), networking_utils_(networking_utils), endpoint_(authorized_endpoint), session_(*this),
        ticket_callback_(this, &SteamBridge::on_ticket),
        connection_callback_(this, &SteamBridge::on_connection) {}
  ~SteamBridge() { release_received(); session_.close(); }
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
  struct Received {
    const std::uint8_t* data;
    std::int64_t sdk_queue_age_us;
    std::uint32_t size;
    std::int32_t reliable;
  };
  static constexpr int receive_limit = 8;
  // Borrowed payloads remain valid until the next receive call or destruction.
  // The SDK owns these allocations; Python copies only the envelopes it consumes.
  int receive(Received* output, int capacity) {
    release_received();
    if (!transport_ready() && !(remote_end_reason_ == 1038 && session_.connection())) return 0;
    const int count = sockets_.ReceiveMessagesOnConnection(session_.connection(), received_.data(), capacity);
    if (count < 0) { session_.close(Failure::disconnected); return count; }
    if (!count) return 0;
    const auto now = networking_utils_ ? networking_utils_->GetLocalTimestamp() : 0;
    for (int i = 0; i < count; ++i) {
      const auto* message = received_[i];
      if (!message || !message->m_pData || message->m_cbSize <= 0 || message->m_cbSize > 4 * 1024 * 1024) {
        release_received();
        session_.close(Failure::consumer);
        return -1;
      }
      const auto received = message->m_usecTimeReceived;
      const auto elapsed = received > 0 && received <= now ? now - received : -1;
      const auto age = elapsed <= 9007199254740991LL ? elapsed : -1;
      output[i] = {
        static_cast<const std::uint8_t*>(message->m_pData), age,
        static_cast<std::uint32_t>(message->m_cbSize),
        (message->m_nFlags & k_nSteamNetworkingSend_Reliable) != 0,
      };
    }
    return count;
  }
  void release_received() noexcept {
    for (auto& message : received_) {
      if (message) SteamAPI_SteamNetworkingMessage_t_Release(message);
      message = nullptr;
    }
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
  ISteamNetworkingUtils* networking_utils_;
  std::array<SteamNetworkingMessage_t*, receive_limit> received_{};
  SteamNetworkingIPAddr endpoint_;
  Session session_;
  int remote_end_reason_ = 0;
  CCallback<SteamBridge, GetAuthSessionTicketResponse_t> ticket_callback_;
  CCallback<SteamBridge, SteamNetConnectionStatusChangedCallback_t> connection_callback_;
};
} // namespace cs2::observer

