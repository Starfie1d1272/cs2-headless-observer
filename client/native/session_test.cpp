// Synthetic SDK boundary, not a Steam/GNS session or valid ticket.
#include "session.hpp"
#include <cassert>
#include <iostream>
using namespace mizar::observer;
struct FakePort final : Port {
  bool context = true;
  Availability availability = Availability::current;
  std::uint32_t ticket_size = 3;
  int connects = 0, requests = 0, cancels = 0, closes = 0;
  bool context_ready() override { return context; }
  void init_authentication() override {}
  Availability authentication() override { return availability; }
  std::uint32_t connect() override { ++connects; return 11; }
  std::uint32_t request_ticket(std::span<std::uint8_t> data, std::uint32_t& size) override {
    ++requests; data[0] = 0x75; data[1] = 0x6e; data[2] = 0x69; size = ticket_size; return 17;
  }
  std::uint64_t own_steam_id() override { return 42; }
  void cancel_ticket(std::uint32_t handle) noexcept override { assert(handle == 17); ++cancels; }
  void close_connection(std::uint32_t handle) noexcept override { assert(handle == 11); ++closes; }
};
void connect(Session& session) {
  session.start(100);
  session.tick(100);
  assert(session.state() == State::connecting);
  session.connected(11, true);
  assert(session.state() == State::connected);
}
void not_ready(Session& session) {
  bool rejected = false;
  try { (void)session.auth_steam(); } catch (const std::logic_error&) { rejected = true; }
  assert(rejected);
}
int main() {
  {
    FakePort port;
    { Session session(port); connect(session);
      assert(port.requests == 0); // GNS Connected alone does not request a ticket.
      session.request_ticket(); not_ready(session);
      session.ticket_callback(999, 1); not_ready(session);
      session.ticket_callback(17, 1);
      const auto borrowed = session.auth_steam();
      assert(borrowed.size() == 11 && borrowed[0] == 42 && borrowed[8] == 0x75);
      session.disconnected(999); assert(session.state() == State::ready);
      session.disconnected(11); not_ready(session);
      for (auto byte : borrowed) assert(byte == 0);
      session.ticket_callback(17, 1); not_ready(session);
      session.close();
    }
    assert(port.cancels == 1 && port.closes == 1);
  }
  {
    FakePort port; Session session(port); connect(session); session.request_ticket();
    session.ticket_callback(17, 2);
    assert(session.failure() == Failure::ticket && port.cancels == 1 && port.closes == 1);
    not_ready(session);
  }
  {
    FakePort port; Session session(port); connect(session); session.request_ticket();
    session.tick(30100);
    assert(session.failure() == Failure::timeout && port.cancels == 1 && port.closes == 1);
    session.ticket_callback(17, 1); not_ready(session);
  }
  {
    FakePort port; port.availability = Availability::waiting; Session session(port);
    session.start(0); session.tick(29999); assert(port.connects == 0);
    session.tick(30000); assert(session.failure() == Failure::timeout && port.closes == 0);
  }
  {
    FakePort port; Session session(port); session.start(0); session.tick(0);
    session.connected(11, false);
    assert(session.failure() == Failure::untrusted_peer && port.requests == 0 && port.closes == 1);
  }
  {
    FakePort port; port.ticket_size = 2041; Session session(port); connect(session); session.request_ticket();
    assert(session.failure() == Failure::ticket && port.cancels == 1 && port.closes == 1);
  }
  {
    FakePort port; port.context = false; Session session(port); session.start(0);
    assert(session.failure() == Failure::context && port.connects == 0);
  }
  {
    FakePort port;
    { Session session(port); connect(session); session.request_ticket(); }
    assert(port.cancels == 1 && port.closes == 1);
  }
  std::cout << "8 lifecycle cases passed; synthetic port, no Steam login/network.\n";
}
