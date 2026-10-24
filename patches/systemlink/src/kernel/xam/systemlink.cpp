/**
 * System Link (Xbox 360 LAN play) support for the XAM network layer.
 *
 * Added by Souls of the Reaper. Lives in patches/systemlink and is copied into the
 * ReXGlue SDK by port/build.ps1; xam_net.cpp only calls into it.
 */

// Disable warnings about unused parameters for kernel functions
#pragma GCC diagnostic ignored "-Wunused-parameter"

#include <atomic>
#include <cerrno>
#include <cstring>
#include <mutex>
#include <random>
#include <string>
#include <unordered_map>
#include <vector>

#if REX_PLATFORM_MAC
#include <sys/select.h>
#endif

#include <rex/cvar.h>
#include <rex/hook.h>
#include <rex/kernel/xam/module.h>
#include <rex/kernel/xam/private.h>
#include <rex/kernel/xam/systemlink.h>
#include <rex/logging.h>
#include <rex/system/kernel_state.h>
#include <rex/system/xsocket.h>
#include <rex/system/xthread.h>
#include <rex/system/xtypes.h>
#include <rex/types.h>

#if REX_PLATFORM_WIN32
// NOTE: must be included last as it expects windows.h to already be included.
#define _WINSOCK_DEPRECATED_NO_WARNINGS
#include <winsock2.h>  // NOLINT(build/include_order)
#include <ws2tcpip.h>  // NOLINT(build/include_order)
#elif REX_PLATFORM_LINUX || REX_PLATFORM_MAC
#include <arpa/inet.h>
#include <ifaddrs.h>
#include <net/if.h>
#include <netinet/in.h>
#include <netinet/ip.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

REXCVAR_DEFINE_INT32(systemlink_instance, 0, "Kernel",
                     "Player number (0-65535) for System Link. 0 is the classic player id and name; "
                     "N gives this copy its own id and the name User<N>, so two machines that play "
                     "together are not the same player.");

REXCVAR_DEFINE_STRING(systemlink_address, "", "Kernel",
                      "IPv4 address this PC presents as its console address for System Link "
                      "(e.g. 192.168.1.20). Empty = the default-route interface. Set it on a PC that "
                      "is on several networks (Wi-Fi plus a VM switch) to the address the other "
                      "player can actually reach, so its replies come from the address it advertised.");

REXCVAR_DEFINE_BOOL(systemlink_trace, false, "Kernel",
                    "Log the guest's XAM app messages (XGI sessions, XLive, ...) and their results, to see what a title asks of System Link.");

namespace rex {
namespace kernel {
namespace xam {
using namespace rex::system;

namespace systemlink {
namespace {

constexpr uint32_t kDefaultSystemLinkPort = 3074;

uint16_t g_system_link_port = kDefaultSystemLinkPort;

// A stable, non-zero fake console MAC: locally administered (0x02) so it can never collide with a
// real NIC, then the host's whole IPv4 address. Two PCs always report different consoles (they
// cannot share an IP), and a peer can rebuild it from the IP alone, which is all it sees on the wire.
void FakeConsoleMac(uint32_t ip_network_order, uint8_t out[6]) {
  out[0] = 0x02;
  std::memcpy(out + 1, &ip_network_order, 4);
  out[5] = 0;
}

// The XNADDR the game itself gave us for each peer address it asked us to convert. Returned as-is
// later, so a peer keeps one identity however it is looked up.
std::mutex g_peer_mutex;
std::unordered_map<uint32_t, XNADDR> g_peers;  // key: IN_ADDR as handed to the guest (network order)

}  // namespace

// The host's LAN IPv4 address (network byte order), found by asking the OS which interface it
// would route a packet to a LAN address through. A UDP connect() sends nothing; it only selects
// the route. 0 when the host has no usable network.
uint32_t HostLanAddress() {
#if REX_PLATFORM_WIN32
  WSADATA wsa;
  WSAStartup(MAKEWORD(2, 2), &wsa);  // reference counted; harmless if already started
#endif
  const std::string& pinned = REXCVAR_GET(systemlink_address);
  if (!pinned.empty()) {
    uint32_t address = inet_addr(pinned.c_str());
    if (address != INADDR_NONE && address != 0) {
      return address;
    }
  }
  uint32_t result = 0;
  auto sock = ::socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
#if REX_PLATFORM_WIN32
  if (sock == INVALID_SOCKET) {
    return 0;
  }
#else
  if (sock < 0) {
    return 0;
  }
#endif
  sockaddr_in route = {};
  route.sin_family = AF_INET;
  route.sin_port = htons(9);
  route.sin_addr.s_addr = htonl(0xC0000201);  // 192.0.2.1 (TEST-NET-1, never actually contacted)
  if (::connect(sock, reinterpret_cast<sockaddr*>(&route), sizeof(route)) == 0) {
    sockaddr_in local = {};
#if REX_PLATFORM_WIN32
    int len = sizeof(local);
#else
    socklen_t len = sizeof(local);
#endif
    if (::getsockname(sock, reinterpret_cast<sockaddr*>(&local), &len) == 0) {
      result = local.sin_addr.s_addr;
    }
  }
#if REX_PLATFORM_WIN32
  ::closesocket(sock);
#else
  ::close(sock);
#endif
  if (result == htonl(INADDR_LOOPBACK) || result == 0) {
    return 0;
  }
  return result;
}

uint32_t EthernetLinkStatus() {
  // Titles refuse System Link with "no network connection" unless the cable is "plugged in".
  if (!HostLanAddress()) {
    return 0;
  }
  constexpr uint32_t kLinkActive = 0x01, kLink100Mbps = 0x02, kFullDuplex = 0x08;
  return kLinkActive | kLink100Mbps | kFullDuplex;
}

uint32_t FillTitleXnAddr(XNADDR* out) {
  uint32_t lan = HostLanAddress();
  out->inaOnline.addr = 0;
  out->wPortOnline = 0;
  std::memset(out->abOnline, 0, sizeof(out->abOnline));
  if (!lan) {
    out->ina.addr = 0;
    std::memset(out->abEnet, 0, sizeof(out->abEnet));
    return kXnAddrNone;
  }
  out->ina.addr = lan;
  // RakNet's 360 version appears to depend on abEnet to create "random" 64-bit numbers. A zero
  // value would make RakPeer::Startup fail.
  FakeConsoleMac(lan, out->abEnet);
  return kXnAddrStatic | kXnAddrEthernet;
}

uint32_t XnAddrToInAddr(const XNADDR* xn_addr, uint8_t* in_addr_out) {
  if (!xn_addr || !in_addr_out) {
    return 0x2726;  // WSAEINVAL
  }
  const uint32_t out_network = xn_addr->ina.addr;
  std::memcpy(in_addr_out, &out_network, 4);
  {
    std::lock_guard<std::mutex> lock(g_peer_mutex);
    g_peers[out_network] = *xn_addr;
  }
  REXKRNL_DEBUG("SystemLink: XnAddrToInAddr {:08X} -> {:08X}", ntohl(xn_addr->ina.addr),
                ntohl(out_network));
  return 0;
}

uint32_t InAddrToXnAddr(uint32_t in_addr, XNADDR* out) {
  if (!out) {
    return 0x2726;  // WSAEINVAL
  }
  // in_addr is the IN_ADDR passed by value: as a guest integer it is the host-order address.
  {
    std::lock_guard<std::mutex> lock(g_peer_mutex);
    auto known = g_peers.find(htonl(in_addr));
    if (known != g_peers.end()) {
      *out = known->second;
      return 0;
    }
  }
  // An address the game never converted from an XNADDR (a packet from a console we have not
  // heard advertise): describe it the way a console with that IP would describe itself.
  std::memset(out, 0, sizeof(*out));
  const uint32_t ip_network = htonl(in_addr);
  out->ina.addr = ip_network;
  FakeConsoleMac(ip_network, out->abEnet);
  REXKRNL_DEBUG("SystemLink: InAddrToXnAddr {:08X} -> synthesized", in_addr);
  return 0;
}

bool PrepareSocketOption(uint32_t& level, uint32_t& optname, void*& optval, uint32_t optlen,
                         int32_t& scratch) {
  // Integer-valued options: the guest stores the value big-endian.
  const bool sol_socket = level == 0xFFFF;
  bool integer_option = false;
  if (sol_socket) {
    switch (optname) {
      case 0x0004:  // SO_REUSEADDR
      case 0x0008:  // SO_KEEPALIVE
      case 0x0020:  // SO_BROADCAST
      case 0x1001:  // SO_SNDBUF
      case 0x1002:  // SO_RCVBUF
        integer_option = true;
        break;
      default:
        break;
    }
  } else if (level == 6 && optname == 1) {  // IPPROTO_TCP / TCP_NODELAY
    integer_option = true;
  }
  if (integer_option && optval && optlen == 4) {
    const uint8_t* b = static_cast<const uint8_t*>(optval);
    scratch = static_cast<int32_t>((uint32_t(b[0]) << 24) | (uint32_t(b[1]) << 16) |
                                   (uint32_t(b[2]) << 8) | uint32_t(b[3]));
    optval = &scratch;
  }
#if !REX_PLATFORM_WIN32
  if (sol_socket) {
    switch (optname) {
      case 0x0004:
        optname = SO_REUSEADDR;
        break;
      case 0x0008:
        optname = SO_KEEPALIVE;
        break;
      case 0x0020:
        optname = SO_BROADCAST;
        break;
      case 0x1001:
        optname = SO_SNDBUF;
        break;
      case 0x1002:
        optname = SO_RCVBUF;
        break;
      case 0x5801:
      case 0x5802:
        return true;  // console-only "disable encryption": handled by XSocket itself
      default:
        return false;  // unsupported WinSock option: accept it rather than fail socket setup
    }
    level = SOL_SOCKET;
  }
#endif
  return true;
}

uint32_t HostErrorToWsa(int host_error) {
#if REX_PLATFORM_WIN32
  return static_cast<uint32_t>(host_error);
#else
  switch (host_error) {
    case EWOULDBLOCK: return 10035;  // WSAEWOULDBLOCK (== EAGAIN on these hosts)
    case EINPROGRESS: return 10036;
    case EALREADY: return 10037;
    case ENOTSOCK: return 10038;
    case EMSGSIZE: return 10040;
    case EPROTOTYPE: return 10041;
    case ENOPROTOOPT: return 10042;
    case EPROTONOSUPPORT: return 10043;
    case EOPNOTSUPP: return 10045;
    case EAFNOSUPPORT: return 10047;
    case EADDRINUSE: return 10048;
    case EADDRNOTAVAIL: return 10049;
    case ENETDOWN: return 10050;
    case ENETUNREACH: return 10051;
    case ECONNABORTED: return 10053;
    case ECONNRESET: return 10054;
    case ENOBUFS: return 10055;
    case EISCONN: return 10056;
    case ENOTCONN: return 10057;
    case ETIMEDOUT: return 10060;
    case ECONNREFUSED: return 10061;
    case EHOSTUNREACH: return 10065;
    case EINTR: return 10004;
    default: return 10022;  // WSAEINVAL
  }
#endif
}

int SelectNfds(int guest_nfds) {
#if REX_PLATFORM_WIN32
  return guest_nfds;  // ignored by winsock
#else
  (void)guest_nfds;
  return FD_SETSIZE;
#endif
}

uint32_t XnAddrToMachineId(const XNADDR* addr, uint8_t* machine_id_out) {
  if (!addr || !machine_id_out) {
    return 0x2726;  // WSAEINVAL
  }
  // 64-bit id, big-endian for the guest: two zero bytes then the console MAC.
  machine_id_out[0] = 0;
  machine_id_out[1] = 0;
  std::memcpy(machine_id_out + 2, addr->abEnet, 6);
  return 0;
}

void TraceAppMessage(uint32_t app_id, uint32_t message, uint32_t arg1, uint32_t arg2,
                     uint32_t result, bool app_found) {
  if (!REXCVAR_GET(systemlink_trace)) {
    return;
  }
  static std::mutex mutex;
  static std::unordered_map<uint64_t, uint32_t> seen;
  uint32_t count;
  {
    std::lock_guard<std::mutex> lock(mutex);
    count = ++seen[(uint64_t(app_id) << 32) | message];
  }
  if (count <= 8 || count % 1000000 == 0) {
    REXKRNL_INFO("SystemLink: app {:02X} msg {:08X} arg1={:08X} arg2={:08X} -> {:08X}{} (#{})", app_id,
                 message, arg1, arg2, result, app_found ? "" : " [APP NOT REGISTERED]", count);
  }
}

void TraceNetCall(const char* name, uint32_t a, uint32_t b) {
  if (!REXCVAR_GET(systemlink_trace)) {
    return;
  }
  static std::mutex mutex;
  static std::unordered_map<std::string, uint32_t> seen;
  uint32_t count;
  {
    std::lock_guard<std::mutex> lock(mutex);
    count = ++seen[name];
  }
  if (count <= 6 || count % 10000 == 0) {
    REXKRNL_INFO("SystemLink: {} ({:X}, {:X}) (#{})", name, a, b, count);
  }
}

void LogSocketFailure(const char* name, uint32_t a, uint32_t b) {
#if REX_PLATFORM_WIN32
  int native_error = WSAGetLastError();
#else
  int native_error = errno;
#endif
  REXKRNL_INFO("SystemLink: {} FAILED ({:X}, {:X}) host error {}", name, a, b, native_error);
}

bool ShouldLogPacket() {
  static std::atomic<int> logged{0};
  return logged.fetch_add(1, std::memory_order_relaxed) < 500;
}

struct InterfaceAddress {
  uint32_t address;    // network byte order
  uint32_t broadcast;  // directed-broadcast address, network byte order
};

// Every up, non-loopback IPv4 interface. A limited broadcast (255.255.255.255) only leaves through
// the default-route interface, which would hide a console on any other network of a multi-homed PC
// (Wi-Fi plus a VM switch, say).
std::vector<InterfaceAddress> Interfaces() {
  std::vector<InterfaceAddress> result;
#if REX_PLATFORM_WIN32
  WSADATA wsa;
  WSAStartup(MAKEWORD(2, 2), &wsa);
  SOCKET probe = ::socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
  if (probe == INVALID_SOCKET) {
    return result;
  }
  INTERFACE_INFO info[32];
  DWORD bytes = 0;
  if (WSAIoctl(probe, SIO_GET_INTERFACE_LIST, nullptr, 0, info, sizeof(info), &bytes, nullptr,
               nullptr) == 0) {
    for (DWORD i = 0; i < bytes / sizeof(INTERFACE_INFO); ++i) {
      const u_long flags = info[i].iiFlags;
      if (!(flags & IFF_UP) || (flags & IFF_LOOPBACK) || !(flags & IFF_BROADCAST) ||
          info[i].iiAddress.Address.sa_family != AF_INET) {
        continue;
      }
      uint32_t address = info[i].iiAddress.AddressIn.sin_addr.s_addr;
      uint32_t mask = info[i].iiNetmask.AddressIn.sin_addr.s_addr;
      result.push_back({address, address | ~mask});
    }
  }
  ::closesocket(probe);
#else
  ifaddrs* list = nullptr;
  if (getifaddrs(&list) == 0) {
    for (ifaddrs* it = list; it; it = it->ifa_next) {
      if (!it->ifa_addr || it->ifa_addr->sa_family != AF_INET || !it->ifa_netmask ||
          !(it->ifa_flags & IFF_UP) || (it->ifa_flags & IFF_LOOPBACK) ||
          !(it->ifa_flags & IFF_BROADCAST)) {
        continue;
      }
      uint32_t address = reinterpret_cast<sockaddr_in*>(it->ifa_addr)->sin_addr.s_addr;
      uint32_t mask = reinterpret_cast<sockaddr_in*>(it->ifa_netmask)->sin_addr.s_addr;
      result.push_back({address, address | ~mask});
    }
    freeifaddrs(list);
  }
#endif
  return result;
}

std::vector<uint32_t> InterfaceBroadcastAddresses() {
  std::vector<uint32_t> result;
  for (const InterfaceAddress& iface : Interfaces()) {
    result.push_back(iface.broadcast);
  }
  return result;
}

bool IsOwnPacket(const N_XSOCKADDR_IN& from) {
  const uint32_t source = htonl(static_cast<uint32_t>(from.sin_addr));
  for (const InterfaceAddress& iface : Interfaces()) {
    if (iface.address == source) {
      return true;
    }
  }
  return false;
}

uint32_t SetPort(uint32_t port) {
  g_system_link_port = static_cast<uint16_t>(port);
  REXKRNL_INFO("SystemLink: XNetSetSystemLinkPort({})", g_system_link_port);
  return 0;
}

int SendTo(XSocket* socket, uint8_t* buf, uint32_t len, uint32_t flags, N_XSOCKADDR_IN to,
           uint32_t to_len) {
  if (static_cast<uint32_t>(to.sin_addr) == 0xFFFFFFFF) {
    // Limited broadcast: send it out of every network the PC is on.
    std::vector<uint32_t> targets = InterfaceBroadcastAddresses();
    if (!targets.empty()) {
      int result = -1;
      for (uint32_t target : targets) {
        N_XSOCKADDR_IN copy = to;
        copy.sin_addr = ntohl(target);
        if (ShouldLogPacket()) {
          REXKRNL_INFO("SystemLink: broadcast to {:08X}:{}", ntohl(target),
                       static_cast<uint16_t>(to.sin_port));
        }
        int r = socket->SendTo(buf, len, flags, &copy, to_len);
        if (r >= 0) {
          result = static_cast<int>(len);
        }
      }
      return result;
    }
  }
  return socket->SendTo(buf, len, flags, &to, to_len);
}

}  // namespace systemlink

// ---- XNet exports that were stubs -----------------------------------------------------------

// Session keys. System Link keys carry no flag bits in the top nibble of the key id.
u32 NetDll_XNetCreateKey_entry(u32 caller, mapped_void xnkid, mapped_void xnkey) {
  static std::mt19937_64 rng{std::random_device{}()};
  if (!xnkid || !xnkey) {
    return 0x2726;  // WSAEINVAL
  }
  uint8_t* id_bytes = xnkid;
  uint8_t* key_bytes = xnkey;
  uint64_t id = rng();
  std::memcpy(id_bytes, &id, 8);
  id_bytes[0] &= 0x0F;
  for (int i = 0; i < 16; i += 8) {
    uint64_t part = rng();
    std::memcpy(key_bytes + i, &part, 8);
  }
  REXKRNL_INFO("SystemLink: XNetCreateKey -> id {:02X}{:02X}{:02X}{:02X}{:02X}{:02X}{:02X}{:02X}",
               id_bytes[0], id_bytes[1], id_bytes[2], id_bytes[3], id_bytes[4], id_bytes[5],
               id_bytes[6], id_bytes[7]);
  return 0;
}

u32 NetDll_XNetRegisterKey_entry(u32 caller, mapped_void xnkid, mapped_void xnkey) {
  REXKRNL_INFO("SystemLink: XNetRegisterKey");
  return 0;
}

u32 NetDll_XNetUnregisterKey_entry(u32 caller, mapped_void xnkid) {
  REXKRNL_INFO("SystemLink: XNetUnregisterKey");
  return 0;
}

u32 NetDll_XNetReplaceKey_entry(u32 caller, mapped_void xnkid_unregister,
                                mapped_void xnkid_replace) {
  REXKRNL_INFO("SystemLink: XNetReplaceKey");
  return 0;
}

u32 NetDll_XNetGetSystemLinkPort_entry(u32 caller, mapped_void port_out) {
  if (!port_out) {
    return 0x2726;  // WSAEINVAL
  }
  memory::store_and_swap<uint16_t>(port_out, systemlink::g_system_link_port);
  REXKRNL_INFO("SystemLink: XNetGetSystemLinkPort -> {}", systemlink::g_system_link_port);
  return 0;
}

u32 NetDll_getsockname_entry(u32 caller, u32 socket_handle, ppc_ptr_t<XSOCKADDR_IN> name,
                             mapped_u32 namelen) {
  systemlink::TraceNetCall("getsockname", socket_handle, 0);
  auto socket = REX_KERNEL_OBJECTS()->LookupObject<XSocket>(systemlink::SockFromGuest(socket_handle));
  if (!socket) {
    XThread::SetLastError(0x2736);  // WSAENOTSOCK
    return -1;
  }
  if (!name) {
    XThread::SetLastError(0x2726);  // WSAEINVAL
    return -1;
  }
  sockaddr_in native = {};
#if REX_PLATFORM_WIN32
  int native_len = sizeof(native);
  int rc = ::getsockname(static_cast<SOCKET>(socket->native_handle()),
                         reinterpret_cast<sockaddr*>(&native), &native_len);
#else
  socklen_t native_len = sizeof(native);
  int rc = ::getsockname(static_cast<int>(socket->native_handle()),
                         reinterpret_cast<sockaddr*>(&native), &native_len);
#endif
  if (rc != 0) {
    XThread::SetLastError(0x2726);
    return -1;
  }
  name->sin_family = 2;
  name->sin_port = ntohs(native.sin_port);
  name->sin_addr = ntohl(native.sin_addr.s_addr);
  std::memset(name->x_sin_zero, 0, sizeof(name->x_sin_zero));
  if (namelen) {
    *namelen = 16;
  }
  return 0;
}

// XNetConnect starts the secure association with a peer and XNetGetConnectStatus is polled until it
// reads CONNECTED before the title sends anything. System Link runs with security bypassed
// (XNetStartup cfgFlags & 1), so there is nothing to negotiate: succeed and report connected.
u32 NetDll_XNetConnect_entry(u32 caller, u32 in_addr) {
  REXKRNL_INFO("SystemLink: XNetConnect({:08X})", in_addr);
  return 0;
}

u32 NetDll_XNetGetConnectStatus_entry(u32 caller, u32 in_addr) {
  systemlink::TraceNetCall("XNetGetConnectStatus", in_addr, 0);
  return 2;  // XNET_CONNECT_STATUS_CONNECTED
}

u32 NetDll_XNetUnregisterInAddr_entry(u32 caller, u32 in_addr) {
  systemlink::TraceNetCall("XNetUnregisterInAddr", in_addr, 0);
  return 0;
}

}  // namespace xam
}  // namespace kernel
}  // namespace rex

REX_EXPORT(__imp__NetDll_XNetConnect, rex::kernel::xam::NetDll_XNetConnect_entry)
REX_EXPORT(__imp__NetDll_XNetGetConnectStatus, rex::kernel::xam::NetDll_XNetGetConnectStatus_entry)
REX_EXPORT(__imp__NetDll_XNetUnregisterInAddr, rex::kernel::xam::NetDll_XNetUnregisterInAddr_entry)
REX_EXPORT(__imp__NetDll_XNetCreateKey, rex::kernel::xam::NetDll_XNetCreateKey_entry)
REX_EXPORT(__imp__NetDll_XNetRegisterKey, rex::kernel::xam::NetDll_XNetRegisterKey_entry)
REX_EXPORT(__imp__NetDll_XNetUnregisterKey, rex::kernel::xam::NetDll_XNetUnregisterKey_entry)
REX_EXPORT(__imp__NetDll_XNetReplaceKey, rex::kernel::xam::NetDll_XNetReplaceKey_entry)
REX_EXPORT(__imp__NetDll_XNetGetSystemLinkPort,
           rex::kernel::xam::NetDll_XNetGetSystemLinkPort_entry)
REX_EXPORT(__imp__NetDll_getsockname, rex::kernel::xam::NetDll_getsockname_entry)
