# Transport contribution assessment

This assessment separates source changes that fit this NCCL integration from
runtime work that needs another package. It makes no new performance claim.
The four-PF repair and configuration renderer are implemented; the runtime
candidates below are not included or enabled by this branch.

| Item | Contribution boundary | Decision |
| --- | --- | --- |
| Deployment-owned addressing and device selection | NCCL source profile and CPU renderer | Included: full /24 cable identity, operator-supplied CIDR, four exact HCA names and a management interface. |
| Listener admission and compatibility | NCCL listener patch | Included: both switchless flags enforce admission; option-off publication uses the selected device; original wire layout remains intact. |
| Lean TP4 all-reduce | Separate CuTe/PyTorch/libibverbs runtime | Prepare a separately versioned adapter, with an explicit numerical and failure contract. It is not a drop-in NCCL source patch. |
| Small rank-major all-gather | Separate runtime using the lean transport | Needs changing-payload eager and graph gates, size routing and a serving result. Small graph timings alone do not qualify eager or serving behavior. |
| Huge-page-backed registered buffers | Allocation and GPU/NIC lifetime changes | Keep experimental. Prove actual page backing, GPU ATS access, NIC registration, fences and safe reclamation before timing. No global host settings. |
| Raw relay / fewer proxy threads | A different transport schedule | Keep separately registered. Prior component improvement did not establish serving improvement; do not ship a relay as an automatic speed upgrade. |
| KDA/FP8 prefill handoff gathers | Model-specific producer/consumer boundary | Belongs to the serving runtime and prefill ring, with bit-exact gather and integration gates. No implicit NCCL replacement. |
| Inline CTS work requests | Optional NCCL verbs patch | Needs negotiated device capability, message-size guards, a build and a matched runtime result. Do not add an unconditional inline flag. |

## Lean all-reduce port requirements

The reviewed lean design uses two direct-neighbor pair exchanges and a GPU
reducer. BF16 rounds each rank pair before the final pair addition. That order
is part of the implementation's numerical contract; replacing it with a CPU
sum or NCCL's ring order can change bytes. A portable adapter must declare its
supported types, alignment, sizes and four-rank topology explicitly.

The runtime currently depends on PyTorch process-group bootstrap, CuTe JIT,
host-memory staging and resident libibverbs proxies. NCCL's source patch and
C ABI do not supply those components. A separate adapter can use NCCL as the
control and fallback for unsupported operations, but it must agree that choice
on every rank before enqueue. After an operation starts, a timeout or poisoned
rank must stop the whole step before tokens are released. A delayed watchdog
alone cannot establish that boundary.

Before publication of a runnable adapter, require:

1. A deployment-owned rank/cable/PF map, with no embedded host addresses or
   device numbering. Validate direct neighbors and both cable/root pairings.
2. Preserved upstream licenses and notices for every reused proxy/kernel;
   no source copied from repositories without a reuse license.
3. A declared reduction order, byte checks across all ranks, changing inputs,
   slot reuse, signed-zero coverage and eager/CUDA-graph replay checks.
4. Coordinated construction failure, stream ordering, sequence/epoch handling,
   cleanup and a tested fail-stop gate before any output release.
5. A measured size cutoff with the fallback control unchanged. Report eager,
   graph and serving results separately; use matched prompts and protocols for
   comparisons. A new library or adapter needs its own qualification.

Configuration is therefore the immediate reusable contribution. The lean
adapter, buffer allocation changes and prefill handoffs remain separate
implementation candidates rather than unverified switches in this release.

## Public reference points

- [NVIDIA NCCL environment-variable documentation](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/env.html)
  defines exact interface/HCA selection and dynamic IPv4 GID filtering. The
  pinned source, rather than later documentation, controls this profile.
- [Pinned NCCL transport source](https://github.com/NVIDIA/nccl/tree/73cf112295c33aee2b895f329f592f2a9b4b0f97/src/transport)
  identifies the existing NCCL network/proxy integration boundary.
- [SparkRing four-PF prior art](https://github.com/FujitsuPolycom/sparkring/blob/ae38b0f11df4dece04673ba8549befc7e527bdf5/spark_transport/nccl/nccl-2.30.7-dual-pci-domain.patch)
  already covers four-GID encoding and PCI-root preference. Preserve that credit.
