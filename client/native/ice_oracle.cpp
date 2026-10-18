// Test-only driver for Valve's published, public-domain IceKey implementation.
// verify_password.py supplies synthetic bytes only; never use credentials here.
#include <mathlib/IceKey.H>
#include <iostream>
#include <iomanip>
#include <string>
#include <vector>
#include <stdexcept>
std::vector<unsigned char> unhex(const std::string& text) {
  if (text.size() % 2) throw std::runtime_error("hex-boundary");
  std::vector<unsigned char> result;
  for (std::size_t i = 0; i < text.size(); i += 2) {
    const auto part = text.substr(i, 2);
    if (part.find_first_not_of("0123456789abcdef") != std::string::npos) throw std::runtime_error("hex-input");
    result.push_back(static_cast<unsigned char>(std::stoul(part, nullptr, 16)));
  }
  return result;
}
int main() {
  std::string key_text, plain_text;
  while (std::cin >> key_text >> plain_text) {
    auto key = unhex(key_text), plain = unhex(plain_text);
    if (key.size() != 8 || plain.empty() || plain.size() > 96 || plain.size() % 8) return 1;
    IceKey ice(1); ice.set(key.data());
    for (std::size_t i = 0; i < plain.size(); i += 8) ice.encrypt(plain.data() + i, plain.data() + i);
    for (auto byte : plain) std::cout << std::hex << std::setw(2) << std::setfill('0') << static_cast<unsigned>(byte);
    std::cout << '\n';
  }
}
