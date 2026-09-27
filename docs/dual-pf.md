# Opt-in four-PF source preparation

This source profile reconstructs a measured NCCL 2.30.7 Ring
implementation for four DGX Sparks, with two PCIe-root functions on each of two
neighbor-facing ports. It does not replace this repository's two-device default,
release package, installer or fabric tools. A rebuilt library is unqualified.

SparkRing already publishes four-GID encoding and PCI-root preference in its
[dual-domain patch](https://github.com/FujitsuPolycom/sparkring/blob/ae38b0f11df4dece04673ba8549befc7e527bdf5/spark_transport/nccl/nccl-2.30.7-dual-pci-domain.patch).
Those capabilities are not claimed as a new invention here. This profile
preserves a different measured composition with stricter listener admission;
no speed advantage over SparkRing has been established.

The first three patches remain unchanged. The fourth,
`patches/nccl-2.30.7-dual-pf.patch`, is generated from the exact difference between
NCCL source commits `6c04592a62c684695b6bc5755cb25c5d74ab93fe` and
`cbd2a32d17592d6480a781d06630c6a3325ea8d2` in the retained source
snapshot, with the predecessor's listener-hardening credit comment restored.
Those commits describe historical source snapshots; the current reconstruction
is pinned by its patch hashes and final tree. The patch
adds bounded four-IPv4-GID encoding, PCI-root-preserving route preference, strict listener
validation and final-QP diagnostics. Route preference can fall back globally;
HCA discovery alone does not prove useful traffic on each root.

## Prepare and build

Supply an existing local NCCL Git checkout containing revision
`73cf112295c33aee2b895f329f592f2a9b4b0f97`. The helper does not fetch from the
network, use the input's working-tree changes, or modify the input checkout.

```sh
python3 scripts/prepare_dual_pf.py --nccl-source /path/to/nccl --output /path/to/fresh-output
```

The helper verifies all four patch hashes, applies them to the pinned clean base
in a new checkout, then requires Git tree
`6373893a20a873aec89c88b6a57b5df8142d6888`. It writes `receipt.json` and a
`build-plan.json` containing a command argument list and its working directory.
Existing outputs are refused. Failed preparation leaves a receipt and retained
files for diagnosis. No automatic retry, build, installation or service action.

Run the build plan in Linux AArch64 with CUDA 13.0 and NCCL's build dependencies:

```sh
make -C /path/to/fresh-output/source -j4 src.build CUDA_HOME=/usr/local/cuda-13.0 \
  NVCC_GENCODE='-gencode=arch=compute_121,code=sm_121'
```

Record compiler/toolkit versions, the source tree and the produced library
SHA256. Keep NCCL LICENSE.txt and ThirdPartyNotices.txt with any distributed
library. Do not use this repository's existing two-device release packager or
installer for this profile: it has different markers and identity. No binary is
included here. The [profile](../profiles/dual-pf.json) identifies a historical
CUDA13.0 library; its hash is not an expected reproducible-build result.

## Configuration and limits

`profiles/dual-pf.json` records the canonical environment. It requires explicit
`NCCL_SWITCHLESS_RING_ONLY=1`, `NCCL_ALGO=Ring`, four exact HCA selections,
no NIC merging, extended IPv4 GIDs, and subnet-aware routing. Supply the actual
four PF names at deployment; no site hosts or device names are supplied here.
The listener implementation recognizes the four cable subnets
`10.100.224.0/24` through `10.100.227.0/24`. These literals are restrictions of
this source profile, not a network configuration to apply automatically.
Different addressing requires a source change and its own validation.

The exact measured source retains known limitations: alias-only
`NCCL_SKIP_TREE_CONNECT` bypasses strict listener admission; opting out of both
canonical switchless and extended advertisement does not recover stock
selected-device-only publication. Use only the explicit canonical environment.
Fixes need separate commits and qualification; this profile does not claim to
solve those bugs. Tree/PAT, diagonal P2P, generic IPv6/InfiniBand and TP2 are not
qualified by this profile. Existing release defaults remain unchanged.

## Offline verification and hardware gates

```sh
NCCL_SOURCE=/path/to/nccl python3 -m unittest discover -s tests -p test_dual_pf.py -v
```

The test applies the entire stack to the real base, verifies the final tree,
compiles/runs the codec and listener tests, and rejects a corrupt patch or reused
output. Without NCCL_SOURCE the real-source test is explicitly skipped.
The existing `scripts/check.sh` CI entry point also runs these gates against
its pinned NCCL checkout. These tests do not exercise CUDA or RDMA. Before serving, require all-rank loaded
library hashes, changing-payload eager/graph collective checks, final connected
QP/root evidence and per-HCA traffic, followed by a matched serving comparison.

## Attribution

NVIDIA owns the base NCCL code and subnet routing. SparkRing published the
original skip-Tree/PAT and listener patches; Alex Ellis / OpenFaaS Ltd added the
hardening predecessor. This repository contributes the optional source integration
and measured dual-PF delta under Apache-2.0, retaining existing notices.
The verified public origin chain is recorded in [PROVENANCE.md](../PROVENANCE.md).
No source is copied from the unlicensed Joseph Rose repository; that work remains
conceptual prior art.

## Hosted validation

`.github/workflows/dual-pf.yml` runs the default source gates and four-PF CPU
contracts on GitHub-hosted Ubuntu 24.04, then compiles the opt-in library on
`ubuntu-24.04-arm`. No custom runner registration, GPU, node credentials or
repository secrets are needed. Permissions are read-only; no package or release
is published. The existing default build and release workflows are unchanged.

The native job uses the CUDA image digest in `scripts/versions.sh`, the profile's
exact source tree, CUDA 13.0 and SM121. It records the actual invocation (`-j2`
to bound hosted-runner memory), toolchain output, image ID, ELF architecture,
SONAME, version/patch markers and library hash. Logs and the resulting library
are retained as Actions artifacts for 30 days, including failure logs when
available. A failure requires diagnosis before a manual rerun; no retry loop.
Hosted-runner disk or memory exhaustion is a failed build, never a validation
pass. Build containers are retained until the ephemeral runner expires.

`PASS_NATIVE_COMPILE_ONLY` does not establish collective correctness or runtime
qualification. The rebuilt library needs the all-rank payload and routing gates
before installation in a serving recipe. It is not required to reproduce the
historical binary hash. The default two-GID binary verifier must not be used to
judge the four-PF candidate. To reproduce on a Linux ARM64 CPU host with Docker:

```sh
./scripts/build-dual-pf-ci.sh /absolute/path/to/fresh-output
```
