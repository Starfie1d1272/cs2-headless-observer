#pragma once
// Research-only lifecycle. No SDK login, ticket fabrication, network framing or logging.
#include <array>
#include <cstdint>
#include <span>
#include <stdexcept>

namespace mizar::observer {
enum class State { idle, authenticating, connecting, connected, ticket_pending, ready, closed };
enum class Failure { none, context, authentication, connect, untrusted_peer, ticket, timeout, disconnected, consumer, cancelled };
enum class Availability { waiting, current, failed };

struct Port {
  virtual ~Port() = default;
  virtual bool context_ready() = 0;
  virtual void init_authentication() = 0;
  virtual Availability authentication() = 0;
  virtual std::uint32_t connect() = 0;
  // Writes only a genuine SDK result bound to the authenticated remote identity.
  virtual std::uint32_t request_ticket(std::span<std::uint8_t> bytes, std::uint32_t& size) = 0;
  virtual std::uint64_t own_steam_id() = 0;
  virtual void cancel_ticket(std::uint32_t handle) noexcept = 0;
  virtual void close_connection(std::uint32_t handle) noexcept = 0;
};

class Session {
 public:
  explicit Session(Port& port) : port_(port) {}
  ~Session() { close(Failure::cancelled); }
  Session(const Session&) = delete;
  Session& operator=(const Session&) = delete;

  State state() const { return state_; }
  Failure failure() const { return failure_; }
  std::uint32_t connection() const { return connection_; }

  // now_ms must be a monotonic host clock. One instance owns one connection only.
  void start(std::uint64_t now_ms) {
    if (state_ != State::idle) throw std::logic_error("session-reuse-forbidden");
    if (!port_.context_ready()) { close(Failure::context); return; }
    state_ = State::authenticating;
    deadline_ = now_ms + 30000;
    port_.init_authentication();
  }
  void tick(std::uint64_t now_ms) {
    if (state_ == State::idle || state_ == State::closed || state_ == State::ready) return;
    if (now_ms >= deadline_) { close(Failure::timeout); return; }
    if (state_ != State::authenticating) return;
    const auto availability = port_.authentication();
    if (availability == Availability::failed) { close(Failure::authentication); return; }
    if (availability != Availability::current) return;
    connection_ = port_.connect();
    if (!connection_) { close(Failure::connect); return; }
    state_ = State::connecting;
  }
  void connected(std::uint32_t handle, bool authenticated_and_encrypted) {
    if (state_ != State::connecting || handle != connection_) return;
    if (!authenticated_and_encrypted) { close(Failure::untrusted_peer); return; }
    state_ = State::connected;
  }
  // Protocol caller invokes only after validating the actual Source 2 challenge.
  void request_ticket() {
    if (state_ != State::connected) throw std::logic_error("ticket-phase-invalid");
    ticket_ = port_.request_ticket(std::span(bytes_).subspan(8), ticket_size_);
    if (!ticket_ || ticket_size_ == 0 || ticket_size_ > bytes_.size() - 8) {
      close(Failure::ticket); return;
    }
    const auto own_id = port_.own_steam_id();
    if (!own_id) { close(Failure::context); return; }
    for (unsigned i = 0; i < 8; ++i) bytes_[i] = static_cast<std::uint8_t>(own_id >> (8 * i));
    state_ = State::ticket_pending;
  }
  void ticket_callback(std::uint32_t handle, int result) {
    if (state_ != State::ticket_pending || handle != ticket_) return;
    if (result != 1) { close(Failure::ticket); return; } // k_EResultOK
    state_ = State::ready;
  }
  std::span<const std::uint8_t> auth_steam() const {
    if (state_ != State::ready) throw std::logic_error("ticket-not-ready");
    // Borrowed sensitive bytes: never persist/log; invalid after close/destruction.
    return std::span(bytes_).first(ticket_size_ + 8);
  }
  void disconnected(std::uint32_t handle) {
    if (handle && handle == connection_) close(Failure::disconnected);
  }
  void close(Failure reason = Failure::cancelled) noexcept {
    if (state_ == State::closed) return;
    state_ = State::closed;
    failure_ = reason;
    // Invalidate before SDK calls, so reentrant/late callbacks cannot release bytes.
    const auto ticket = ticket_; ticket_ = 0;
    const auto connection = connection_; connection_ = 0;
    volatile std::uint8_t* data = bytes_.data();
    for (std::size_t i = 0; i < bytes_.size(); ++i) data[i] = 0;
    ticket_size_ = 0;
    if (ticket) port_.cancel_ticket(ticket);
    if (connection) port_.close_connection(connection);
  }
 private:
  Port& port_;
  State state_ = State::idle;
  Failure failure_ = Failure::none;
  std::uint32_t connection_ = 0, ticket_ = 0, ticket_size_ = 0;
  std::uint64_t deadline_ = 0;
  std::array<std::uint8_t, 2048> bytes_{};
};
} // namespace mizar::observer
