// SPDX-License-Identifier: Apache-2.0
// CPU-only validation of the exact qualified source's listener contract.
#include "tp4_listener_contract.h"
#include <algorithm>
#include <cassert>
#include <cstdio>

static void valid(uint8_t gids[4][16], char roots[4][11]) {
  std::memset(gids, 0, 4 * 16);
  for (int i = 0; i < 4; ++i) {
    gids[i][10] = gids[i][11] = 0xff;
    gids[i][12] = 10; gids[i][13] = 100;
    gids[i][14] = uint8_t(224 + i / 2);
    gids[i][15] = uint8_t(1 + i % 2);
    std::memcpy(roots[i], i % 2 ? "pci0002:00" : "pci0000:00", 11);
  }
}

int main() {
  uint8_t gids[4][16], orderedGids[4][16];
  char roots[4][11], orderedRoots[4][11];
  valid(gids, roots);
  int order[] = {0, 1, 2, 3}, permutations = 0;
  do {
    for (int i = 0; i < 4; ++i) {
      std::memcpy(orderedGids[i], gids[order[i]], 16);
      std::memcpy(orderedRoots[i], roots[order[i]], 11);
    }
    assert(tp4ValidateListener(orderedGids, orderedRoots, 4, true) == nullptr);
    ++permutations;
  } while (std::next_permutation(order, order + 4));
  assert(permutations == 24);

  for (int count : {0, 1, 2, 3, 5}) {
    assert(tp4ValidateListener(gids, roots, count, true) != nullptr);
  }
  std::memcpy(orderedGids[0], gids[0], 16);
  std::memcpy(orderedGids[1], gids[2], 16);
  assert(tp4ValidateListener(orderedGids, roots, 2, false) == nullptr);
  std::memcpy(orderedGids[1], gids[1], 16);
  assert(tp4ValidateListener(orderedGids, roots, 2, false) != nullptr);

  std::memcpy(gids[3], gids[0], 16);
  assert(tp4ValidateListener(gids, roots, 4, true) != nullptr);
  valid(gids, roots); gids[0][0] = 0x20;
  assert(tp4ValidateListener(gids, roots, 4, true) != nullptr);
  valid(gids, roots); gids[0][14] = 223;
  assert(tp4ValidateListener(gids, roots, 4, true) != nullptr);
  valid(gids, roots); gids[0][15] = 0;
  assert(tp4ValidateListener(gids, roots, 4, true) != nullptr);
  valid(gids, roots); gids[0][15] = 255;
  assert(tp4ValidateListener(gids, roots, 4, true) != nullptr);
  valid(gids, roots); std::memcpy(roots[1], roots[0], 11);
  assert(tp4ValidateListener(gids, roots, 4, true) != nullptr);
  valid(gids, roots); roots[0][0] = 0;
  assert(tp4ValidateListener(gids, roots, 4, true) != nullptr);
  valid(gids, roots); roots[0][10] = 'x';
  assert(tp4ValidateListener(gids, roots, 4, true) != nullptr);
  valid(gids, roots); std::memcpy(roots[3], "pci0003:00", 11);
  assert(tp4ValidateListener(gids, roots, 4, true) != nullptr);
  std::puts("listener contract: 24 dual-PF permutations, two-PF and invalid cases passed");
}
