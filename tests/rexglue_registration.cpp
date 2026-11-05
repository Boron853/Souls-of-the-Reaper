#include <algorithm>
#include <cstdio>
#include <rex/codegen/function_graph.h>

using namespace rex::codegen;

int main() {
  FunctionGraph ordinary, batched;
  for (auto *graph : {&ordinary, &batched}) {
    graph->addFunction(0x1000, 16, FunctionAuthority::PDATA);
    graph->addFunction(0x2000, 16, FunctionAuthority::PDATA);
    graph->addUnresolvedJumpToFunction(0x1000, 0x1004, 0x3000, false, false);
    graph->addUnresolvedJumpToFunction(0x1000, 0x1008, 0x4000, false, true);
    graph->addUnresolvedJumpToFunction(0x2000, 0x2004, 0x5000, false, false);
  }
  auto pending = batched.getPendingFunctions();
  std::erase_if(pending,
                [](auto *node) { return !node->hasUnresolvedJumps(); });
  for (unsigned address : {0x3000, 0x4000, 0x6000}) {
    ordinary.addFunction(address, 4, FunctionAuthority::GAP_FILL);
    auto *added = batched.addFunction(address, 4, FunctionAuthority::GAP_FILL,
                                      false, false);
    batched.notifyPendingFunctions(added, pending);
  }
  for (unsigned address : {0x1000, 0x2000}) {
    auto *expected = ordinary.getFunction(address);
    auto *actual = batched.getFunction(address);
    if (expected->unresolvedJumps().size() !=
            actual->unresolvedJumps().size() ||
        expected->tailCalls().size() != actual->tailCalls().size()) {
      std::fputs("FAIL: batched registration changed branch resolution\n",
                 stderr);
      return 1;
    }
  }
  if (batched.getFunction(0x1000)->hasUnresolvedJumps() ||
      batched.getFunction(0x1000)->tailCalls().size() != 2 ||
      batched.getFunction(0x2000)->unresolvedJumps().size() != 1) {
    return 2;
  }
  std::puts(
      "PASS: ordinary and batched registration resolve identical branches.");

  FunctionGraph coverage;
  coverage.addFunction(0x1000, 0x100, FunctionAuthority::PDATA);
  coverage.addBlockToFunction(0x1000, {0x1000, 4});
  coverage.addFunction(0x1020, 4, FunctionAuthority::GAP_FILL);
  coverage.addFunction(0x2000, 0x100, FunctionAuthority::GAP_FILL);
  coverage.addBlockToFunction(0x2000, {0x2000, 0x10});
  coverage.addBlockToFunction(0x2000, {0x2080, 0x10});
  coverage.addFunction(0x2040, 4, FunctionAuthority::GAP_FILL);
  coverage.addFunction(0x2080, 4, FunctionAuthority::GAP_FILL);
  coverage.addFunction(0x2100, 4, FunctionAuthority::GAP_FILL);
  coverage.addFunction(0x3000, 0x100, FunctionAuthority::GAP_FILL);
  coverage.addFunction(0x3080, 4, FunctionAuthority::GAP_FILL);
  coverage.addFunction(0x4000, 0x100, FunctionAuthority::HELPER);
  coverage.addBlockToFunction(0x4000, {0x4080, 0x10});
  coverage.addFunction(0x4040, 4, FunctionAuthority::GAP_FILL);
  coverage.addFunction(0x4080, 4, FunctionAuthority::GAP_FILL);
  std::vector<uint32_t> expected;
  for (const auto &[address, node] : coverage.functions()) {
    if (node->authority() != FunctionAuthority::GAP_FILL)
      continue;
    for (const auto &[otherAddress, other] : coverage.functions()) {
      if (otherAddress != address && other->containsAddress(address) &&
          (other->authority() != FunctionAuthority::GAP_FILL ||
           otherAddress < address)) {
        expected.push_back(address);
        break;
      }
    }
  }
  std::sort(expected.begin(), expected.end());
  if (expected != coverage.findAbsorbedGapFunctions() ||
      expected != std::vector<uint32_t>{0x1020, 0x2080, 0x3080, 0x4080})
    return 3;
  std::puts("PASS: interval cleanup matches full scans, including gaps and "
            "range boundaries.");
  uint32_t random = 0x394F07D4;
  auto next = [&] {
    random = random * 1664525u + 1013904223u;
    return random;
  };
  for (unsigned trial = 0; trial < 128; ++trial) {
    FunctionGraph graph;
    for (unsigned i = 0; i < 32; ++i) {
      const unsigned address = 0x10000 + i * 16;
      const auto authority = ((next() >> 16) & 1) ? FunctionAuthority::GAP_FILL
                                                  : FunctionAuthority::PDATA;
      graph.addFunction(address, 4 * (1 + next() % 32), authority);
      if ((next() >> 16) & 1) {
        graph.addBlockToFunction(address, {address, 4});
        graph.addBlockToFunction(address, {address + 4 * (next() % 24), 4});
      }
    }
    std::vector<uint32_t> original;
    for (const auto &[address, node] : graph.functions()) {
      if (node->authority() != FunctionAuthority::GAP_FILL)
        continue;
      for (const auto &[otherAddress, other] : graph.functions()) {
        if (otherAddress != address && other->containsAddress(address) &&
            (other->authority() != FunctionAuthority::GAP_FILL ||
             otherAddress < address)) {
          original.push_back(address);
          break;
        }
      }
    }
    std::sort(original.begin(), original.end());
    if (original != graph.findAbsorbedGapFunctions())
      return 4;
  }
  std::puts("PASS: interval cleanup matches original scans across 128 "
            "generated graphs.");
}
