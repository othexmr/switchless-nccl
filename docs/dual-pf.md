# Four-PF (dual PCI-root) Ring profile

An opt-in NCCL build for a four-Spark switchless cycle where each Spark reaches
each neighbour through **two PCIe-root functions**. That gives four RoCE PFs per
node: two per cable, one on each PCI root.

The default two-device build, release, installer and packager are unchanged.
Nothing here takes effect unless you build this profile and set its environment.

## What it adds

The fourth patch, `patches/nccl-2.30.7-dual-pf.patch`, applies on top of the
existing three:

- **Extended listener advertisement** (`NCCL_IB_EXTENDED_IPV4_GIDS=1`). A listener
  can publish up to four IPv4-mapped GIDs.
  - The extension uses a tagged format field in padding that the existing
    producer already zeroes.
  - Every legacy offset is kept, and the handle stays at 112 bytes, below
    `NCCL_NET_HANDLE_MAXSIZE`.
  - Old and new peers interoperate: an all-zero tag keeps the two-GID path, and
    an unknown tag is an error.
- **PCI-root-preserving route selection** (`NCCL_IB_PRESERVE_PCI_DOMAIN=1`). When
  the topology-selected device can't reach the peer's subnet, a reachable device
  on the same PCI root is preferred before NCCL's global first match.
- **Strict listener admission** in switchless mode (`NCCL_SWITCHLESS_RING_ONLY=1`,
  or the legacy `NCCL_SKIP_TREE_CONNECT`).
  - **Two-PF mode:** exactly two cable /24 subnets.
  - **Four-PF mode:** the full two-cable × two-PCI-root cross product.
  - **Refused:** duplicates, truncated lists, more than four candidates, and
    network, broadcast, loopback, zero or multicast addresses.
  - **Fabric:** any unicast IPv4 fabric works. A cable is identified by the full
    /24 prefix, and no address range is hard-coded.
  - **Switchless and extended both off:** only the topology-selected device is
    published, as before.
- **Route diagnostics** (`NCCL_IB_ROUTE_DIAGNOSTICS=1`, INFO/NET). One line per
  final QP: side, HCA, port, local and remote GID.

SparkRing's [dual-domain patch](https://github.com/FujitsuPolycom/sparkring/blob/ae38b0f11df4dece04673ba8549befc7e527bdf5/spark_transport/nccl/nccl-2.30.7-dual-pci-domain.patch)
already provides four-GID encoding and PCI-root preference. This profile differs
in its stricter listener admission and its backward-compatible handle extension.
It does not claim a speed advantage over SparkRing.

## Build

Prepare the patched source from a local NCCL checkout that contains
`73cf112295c33aee2b895f329f592f2a9b4b0f97`:

```sh
python3 scripts/prepare_dual_pf.py --nccl-source /path/to/nccl --output /path/to/new-dir
```

The helper:
- checks every patch hash;
- applies the stack in a fresh clone;
- requires the Git tree pinned in `profiles/dual-pf.json`;
- writes `receipt.json` and `build-plan.json`.

It doesn't fetch, build or install anything, and it refuses an existing output
directory.

Build on Linux AArch64 with CUDA 13.0:

```sh
make -C /path/to/new-dir/source -j4 src.build CUDA_HOME=/usr/local/cuda-13.0 \
  NVCC_GENCODE='-gencode=arch=compute_121,code=sm_121'
```

Or build in the pinned CUDA container on any ARM64 Linux host with Docker:

```sh
./scripts/build-dual-pf-ci.sh /absolute/path/to/new-dir
```

Ship NCCL's `LICENSE.txt` and `ThirdPartyNotices.txt` with any library you
distribute. This profile has its own identity, so don't use the default
release packager, installer or binary verifier for it.

## Configure

Copy [`examples/dual-pf.json`](../examples/dual-pf.json), fill in one rank's
values and render the environment:

```sh
python3 scripts/render-dual-pf-env.py node.json > node.env && . ./node.env
```

| Field | Meaning |
|---|---|
| `hcas` | Four exact HCA names |
| `fabric_addresses` | The four local IPv4 addresses, in the same order as `hcas`. They must be two per cable /24, on two different /24s. |
| `fabric_cidr` | A CIDR containing all four addresses |
| `socket_ifname` | The management interface for NCCL and Gloo bootstrap |

The output sets `NCCL_IB_HCA`, `NCCL_IB_ADDR_RANGE`, `NCCL_SOCKET_IFNAME` and
`GLOO_SOCKET_IFNAME`, plus the profile's fixed settings:

- Ring only;
- no NIC merging;
- /24 subnet-aware routing;
- extended GIDs;
- PCI-root preference;
- diagnostics.

It also clears an inherited `NCCL_IB_GID_INDEX`. The renderer only validates what
you declare. Check on every rank that the addresses, HCAs and cabling really form
the two-root × two-cable layout.

## Verify before use

The repository tests are CPU-only:

```sh
NCCL_SOURCE=/path/to/nccl python3 -m unittest discover -s tests -p test_dual_pf.py -v
```

They cover:
- patch identity and the pinned tree;
- the handle codec and legacy compatibility;
- the listener policy and switchless alias;
- config rendering and refusal of bad input;
- the build wrapper's failure handling.

Before serving with a rebuilt library, run a four-rank collective test with
changing payloads (eager and CUDA graph). Confirm from the route diagnostics and
per-HCA counters that all four PFs carry traffic.

## Measured results

Measured on a four-Spark switchless cycle (DGX Spark, CUDA 13.0, NCCL 2.30.7). Each Spark is direct-cabled to its two
neighbours, with two PFs per cable on separate PCI roots. The library was built from this branch: patched tree
`3b71d59c`, aarch64 `libnccl.so.2.30.7`, SHA256 `7c76d65e…0fd3`. Every rank loaded identical bytes.

The run compared this profile (all four PFs) with this repository's default two-PF release. Both ran the same
four-rank BF16 all-reduce sweep, 4 KiB to 256 MiB, in interleaved rounds. The figures are pooled median bus bandwidth
over two rounds and four ranks:

| Message | Four-PF profile | Two-PF release | Gain |
|---|---:|---:|---:|
| 16 MiB | 22.50 GB/s | 13.46 GB/s | 1.67× |
| 64 MiB | 22.92 GB/s | 13.52 GB/s | 1.70× |
| 256 MiB | 23.23 GB/s | 13.79 GB/s | 1.68× |

The run also checked:

- **Correctness:** three changing payloads per size, eager and through a CUDA-graph replay, were bitwise exact on
  every rank and size.
- **Engagement:** per-HCA `port_xmit_data` counters show every used port splitting traffic 30–70 % across its two PFs.
  The route diagnostics show every rank connecting on all four HCAs, on both PCI roots.

Small messages (≤ 1 MiB) were within run-to-run noise of the two-PF release and are not claimed. This is a
collective benchmark on one fabric, not an end-to-end serving result.

## Limits

- Ring only. Tree, PAT, diagonal P2P, IPv6, generic InfiniBand and two-node
  setups are not covered.
- The cable identity rule assumes /24 subnets per cable.

## Attribution

NVIDIA owns NCCL and its subnet-aware routing. SparkRing published the original
skip-Tree/PAT and listener patches. Alex Ellis / OpenFaaS Ltd added the hardening
patch this builds on. The four-PF patch and tooling are Apache-2.0, and existing
notices are kept. See [PROVENANCE.md](../PROVENANCE.md).
