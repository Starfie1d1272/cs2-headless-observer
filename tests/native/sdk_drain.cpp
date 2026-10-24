// Local SDK queue semantics only: no GOTV handshake, match data or real spectator endpoint.
#include <steam_api.h>
#include <steam_api_flat.h>
#include <chrono>
#include <thread>
#include <cstring>
#include <iostream>
int main() {
  SteamErrMsg diagnostic{};
  const auto result = SteamAPI_InitEx(&diagnostic);
  if (result != k_ESteamAPIInitResult_OK) {
    std::cout << "{\"passed\":false,\"stage\":\"steam-init\",\"code\":" << int(result) << "}";
    return 1;
  }
  struct Shutdown { ~Shutdown() { SteamAPI_Shutdown(); } } shutdown;
  if (!SteamUser() || !SteamUser()->BLoggedOn() || SteamUtils()->GetAppID() != 730) return 2;
  auto* sockets = SteamNetworkingSockets();
  HSteamNetConnection first = 0, second = 0;
  struct Pair {
    ISteamNetworkingSockets* sockets; HSteamNetConnection& first; HSteamNetConnection& second;
    ~Pair() { if (first) sockets->CloseConnection(first, 0, nullptr, false);
              if (second) sockets->CloseConnection(second, 0, nullptr, false); }
  } cleanup{sockets, first, second};
  if (!sockets->CreateSocketPair(&first, &second, false, nullptr, nullptr)) return 3;
  constexpr char payload[] = "synthetic-sdk-tail";
  if (sockets->SendMessageToConnection(first, payload, sizeof(payload), k_nSteamNetworkingSend_Reliable, nullptr) != k_EResultOK) return 4;
  sockets->FlushMessagesOnConnection(first);
  for (int i = 0; i < 20; ++i) { SteamAPI_RunCallbacks(); std::this_thread::sleep_for(std::chrono::milliseconds(5)); }
  sockets->CloseConnection(first, 1038, "synthetic-source-end", false); first = 0;
  SteamNetConnectionInfo_t info{};
  for (int i = 0; i < 200; ++i) {
    SteamAPI_RunCallbacks();
    if (sockets->GetConnectionInfo(second, &info) && info.m_eState == k_ESteamNetworkingConnectionState_ClosedByPeer) break;
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
  SteamNetworkingMessage_t* message = nullptr;
  const auto count = sockets->ReceiveMessagesOnConnection(second, &message, 1);
  const bool passed = info.m_eState == k_ESteamNetworkingConnectionState_ClosedByPeer && count == 1 &&
    message && message->m_cbSize == sizeof(payload) && std::memcmp(message->m_pData, payload, sizeof(payload)) == 0;
  if (message) SteamAPI_SteamNetworkingMessage_t_Release(message);
  std::cout << "{\"passed\":" << (passed ? "true" : "false") << ",\"state\":" << int(info.m_eState)
    << ",\"receivedMessages\":" << count << ",\"scope\":\"local-SDK-socket-pair-only\"}";
  return passed ? 0 : 5;
}
