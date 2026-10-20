/**
 * System Link (Xbox 360 LAN play) support for the XAM network layer.
 *
 * Added by Souls of the Reaper. Lives in patches/systemlink and is copied into the
 * ReXGlue SDK by port/build.ps1; xam_net.cpp only calls into it.
 */
#pragma once

#include <cstdint>

#include <rex/system/xsocket.h>
#include <rex/types.h>

namespace rex::kernel::xam {

// Layout of the guest's XNADDR. IPv4 values are stored in network byte order.
// (Not named s_addr: winsock defines that as a macro.)
struct XnIn4 {
  uint32_t addr;
};

struct XNADDR {
  XnIn4 ina;                      // IP address (zero if not static/DHCP)
  XnIn4 inaOnline;                // Online IP address (zero if not online)
  rex::be<uint16_t> wPortOnline;  // Online port
  uint8_t abEnet[6];              // Ethernet MAC address
  uint8_t abOnline[20];           // Online identification
};

namespace systemlink {

// XNetGetTitleXnAddr status bits (XNET_GET_XNADDR_*).
constexpr uint32_t kXnAddrNone = 0x01;
constexpr uint32_t kXnAddrEthernet = 0x02;
constexpr uint32_t kXnAddrStatic = 0x04;

// The host's LAN IPv4 address in network byte order, or 0 when there is no usable network.
uint32_t HostLanAddress();

// XNetGetEthernetLinkStatus: "cable plugged in" bits when the host has a network.
uint32_t EthernetLinkStatus();

// XNetGetTitleXnAddr: fills *out with the host's address and a per-instance console MAC and
// returns the XNET_GET_XNADDR_* status.
uint32_t FillTitleXnAddr(XNADDR* out);

// XNetXnAddrToInAddr / XNetInAddrToXnAddr. in_addr_out points at 4 guest bytes.
uint32_t XnAddrToInAddr(const XNADDR* xn_addr, uint8_t* in_addr_out);
uint32_t InAddrToXnAddr(uint32_t in_addr_host_order, XNADDR* out);

// XNetGet/SetSystemLinkPort.
uint32_t SetPort(uint32_t port);

// Guest socket descriptors must be small non-negative ints: titles test `socket() >= 0` as a signed
// value, and raw kernel handles (0xF8xxxxxx) read as negative. Map handle <-> descriptor.
inline uint32_t SockToGuest(uint32_t handle) {
  return handle == 0xFFFFFFFFu ? handle : (handle & 0x07FFFFFFu);
}
inline uint32_t SockFromGuest(uint32_t sock) {
  return sock == 0xFFFFFFFFu ? sock : (sock | 0xF8000000u);
}

// The console uses winsock option numbers (SOL_SOCKET = 0xFFFF, SO_BROADCAST = 0x20, ...) and
// big-endian integer option values. Converts them for this host: on other hosts the common options
// are renumbered too. Returns false when the option is unsupported on this host and should just be
// accepted. `scratch` holds the converted value that `optval` may be pointed at.
bool PrepareSocketOption(uint32_t& level, uint32_t& optname, void*& optval, uint32_t optlen,
                         int32_t& scratch);

// Winsock error code for a host socket error (errno on Linux/macOS; already a WSA code on Windows).
uint32_t HostErrorToWsa(int host_error);

// First argument for the host select(): guest descriptor numbers mean nothing to the host.
int SelectNfds(int guest_nfds);

// XNetXnAddrToMachineId: a stable per-console id derived from the console MAC.
uint32_t XnAddrToMachineId(const XNADDR* addr, uint8_t* machine_id_out);

// Logs a guest -> XAM app message and its result (cvar systemlink_trace). Every distinct
// (app, message) is logged for its first occurrences, then only now and then, so polling
// does not flood the log. Pass result = 0x80070490 style codes as the app returned them.
void TraceAppMessage(uint32_t app_id, uint32_t message, uint32_t arg1, uint32_t arg2,
                     uint32_t result, bool app_found);

// Logs a NetDll_* call by name (cvar systemlink_trace), bounded like TraceAppMessage.
void TraceNetCall(const char* name, uint32_t a = 0, uint32_t b = 0);

// Logs a failed socket call with the host's error code (always on: failures are rare).
void LogSocketFailure(const char* name, uint32_t a, uint32_t b);

// True when a received datagram came from one of this PC's own addresses. A console never hears
// its own broadcasts, but a PC does, so the game would list itself as a joinable session.
bool IsOwnPacket(const rex::system::N_XSOCKADDR_IN& from);

// True for the first few hundred socket packets of a run, so the discovery protocol shows up in
// the normal (info) log without flooding it.
bool ShouldLogPacket();

// sendto(): a limited broadcast (255.255.255.255) is sent out of every active IPv4 network, not just
// the default-route one, so a console on any of them can hear it.
int SendTo(rex::system::XSocket* socket, uint8_t* buf, uint32_t len, uint32_t flags,
           rex::system::N_XSOCKADDR_IN to, uint32_t to_len);

}  // namespace systemlink
}  // namespace rex::kernel::xam
