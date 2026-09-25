# Fabric runbook

Each Spark in a four-node cycle has two fabric NICs, one for each direct
neighbour. Give each physical link its own IPv4 `/24`. Keep rendezvous and NCCL
bootstrap on the ordinary management LAN.

## Physical wiring: four Sparks, four cables

This is the four-Spark layout we have used. Node numbers follow the cycle
`node0 -> node1 -> node2 -> node3 -> node0`. The drawing shows cable endpoints,
not the left/right position of sockets when looking at the chassis.

```text
                  Cable D: cross link, 10.20.40.0/24
          +------------------------------------------------+
          | f0: 10.20.40.1                  f0: 10.20.40.4 |
     +----+-------------+                    +-------------+----+
     | node0 / rank 0   |                    | node3 / rank 3   |
     | spark-1c24       |                    | spark-22d0       |
     +----+-------------+                    +-------------+----+
          | f1: 10.20.10.1                  f1: 10.20.30.4 |
          |                                                |
          | Cable A: pair                    Cable C: pair |
          | 10.20.10.0/24                    10.20.30.0/24 |
          |                                                |
          | f1: 10.20.10.2                  f1: 10.20.30.3 |
     +----+-------------+                    +-------------+----+
     | node1 / rank 1   |                    | node2 / rank 2   |
     | spark-d475       |                    | spark-3d5b       |
     +----+-------------+                    +-------------+----+
          | f0: 10.20.20.2                  f0: 10.20.20.3 |
          +------------------------------------------------+
                  Cable B: cross link, 10.20.20.0/24
```

There are no diagonal cables. Each node uses both fabric ports, one to each
neighbour. The `spark-*` names identify our machines; substitute your own host
names. The addresses below are a complete example: keep one distinct subnet
per cable if changing them.

| Cable | Endpoint A | Endpoint B | Role |
|---|---|---|---|
| A | node0 `enp1s0f1np1`, `10.20.10.1/24` | node1 `enp1s0f1np1`, `10.20.10.2/24` | Pair link |
| B | node1 `enp1s0f0np0`, `10.20.20.2/24` | node2 `enp1s0f0np0`, `10.20.20.3/24` | Cross link |
| C | node2 `enp1s0f1np1`, `10.20.30.3/24` | node3 `enp1s0f1np1`, `10.20.30.4/24` | Pair link |
| D | node3 `enp1s0f0np0`, `10.20.40.4/24` | node0 `enp1s0f0np0`, `10.20.40.1/24` | Cross link, closes the cycle |

### Cables we used

The ring uses **four Amphenol direct-attach copper (DAC) cables**, one per
edge. **We have used and tested both cable variants below on our Sparks.**
No separate optical transceivers or fabric switch are needed.

| Tested Amphenol part | Length | Identification |
|---|---|---|
| `NJAAKK-N911` | 0.4 m | Packaging label: `AHSP P/N NJAAKK-N911`, `QSFP/QSFP`, `0.4M` |
| `NJAAKK-0006` / `NJAAKK0006` | 0.5 m | Recorded supplier part: `SF-NJAAKK0006-000.5M` |

[NVIDIA's ConnectX-7 networking guide](https://docs.nvidia.com/dgx/dgx-spark/spark-clustering.html)
lists NJAAKK0006 as the 0.5 m version of the approved NJAAKK-N911 cable
(QSFP to QSFP112). Use the exact part number when sourcing the cable, rather
than treating any cable advertised as "100G QSFP28" as equivalent.

Our 24 September 2026 four-node capture reported `Speed: 200000Mb/s` on both
fabric interfaces of every node. That is the negotiated link rate, not a
claim of 200 Gb/s application throughput or a separate measurement for each
cable variant. The tested 0.4 m and 0.5 m lengths suit our adjacent nodes; check
the actual cable path and connector clearance in your layout.

### Port names and per-node configuration

| Drawing label | Linux interface used | RDMA device used |
|---|---|---|
| `f0` (cross) | `enp1s0f0np0` | `rocep1s0f0` |
| `f1` (pair) | `enp1s0f1np1` | `rocep1s0f1` |

These are the interface names on our systems. Verify your own mapping with
`ibdev2netdev` and the permanent MAC addresses before applying configuration;
do not infer a physical socket's identity from its position in the drawing.

| Node | `FABRIC0_ADDRESS` (`f0`) | `FABRIC1_ADDRESS` (`f1`) |
|---|---|---|
| node0 | `10.20.40.1/24` | `10.20.10.1/24` |
| node1 | `10.20.20.2/24` | `10.20.10.2/24` |
| node2 | `10.20.20.3/24` | `10.20.30.3/24` |
| node3 | `10.20.40.4/24` | `10.20.30.4/24` |

[`examples/fabric.env`](../examples/fabric.env) starts with node0's addresses
and placeholder MACs. Create a separate file for each node, replacing both
MACs and using that node's row above. MTU is 9000 on all eight fabric ports.

### Management wiring is separate

Each Spark also has an ordinary Ethernet connection to our management LAN.
This carries SSH, rendezvous, and NCCL bootstrap. The switchless description
applies to the four RoCE cables above.

```text
 node0 management ----+
 node1 management ----+---- management Ethernet switch ---- LAN / operator
 node2 management ----+
 node3 management ----+

 4 ordinary Ethernet patch leads, separate from the 4 fabric DACs
 Management interface on our Sparks: enP7s7
```

Use the management interface for bootstrap and both fabric RDMA devices for
NCCL data transport, following [the runtime contract](runtime.md). Do not put
management addresses on the fabric interfaces. This four-node wiring does
not include our separate two-Spark cluster.

## Why stale addresses break GID selection

The mlx5 driver creates GID table entries as addresses appear. A node converted
from a TP2 setup can retain an older global address, so its intended RoCEv2 GID
lands above index 3. NCCL accepts one rank-wide `NCCL_IB_GID_INDEX`; if the two
ports settle on different indices, selecting a correct cable becomes brittle.

Netplan describes the desired persistent state, but it does not guarantee that
manually added live addresses disappear in the order needed to normalise the
GID table. NCCL 2.21 and later can select the address dynamically, but stale
addresses still make that selection and listener advertisement ambiguous.
`fabric-apply.sh` therefore performs one bounded reset:

1. render and validate the complete Netplan file without touching live state;
2. prove each named interface has the expected permanent MAC;
3. refuse the default-route and current SSH interfaces;
4. flush global IPv4 addresses only from the two fabric interfaces;
5. apply Netplan; and
6. wait for exactly the configured IPv4 RoCEv2 GID on each port.

It prints the common legacy index and fails if the two indices differ. New
NCCL 2.30.7 profiles should normally leave `NCCL_IB_GID_INDEX` unset, per
NVIDIA's guidance, and select IPv4 RoCEv2 dynamically. On the validated DGX
Spark layout, link-local v1/v2 occupy
indices 0 and 1, IPv4 RoCEv1 occupies 2, and IPv4 RoCEv2 occupies 3. The script
discovers and verifies that result instead of blindly assuming it.

## Apply per node

Copy and edit the example outside the checkout:

```bash
cp examples/fabric.env ./fabric.env
sudo ./scripts/fabric-apply.sh ./fabric.env
```

Run it locally on each node. Do not use one node's MAC addresses or fabric
addresses on another. The generated file uses NetworkManager, disables DHCP,
IPv6 router advertisements, and link-local addressing on the fabric ports,
sets MTU 9000, and matches each port by its permanent MAC before restoring its
normal interface name.

After applying all four nodes, verify every directly cabled peer with a jumbo
ping, then run a real NCCL collective. If Docker is used for routed traffic,
restore and verify the deployment's `DOCKER-USER` forwarding rules after any
Docker restart; those policy rules are intentionally outside this repository.

## Safety boundary

The apply command changes network state and requires root. Its scope is the two
interfaces named in `fabric.env` and one explicit Netplan file. It will not
flush the default-route interface or the interface carrying the current SSH
connection. Review the rendered file before first use:

```bash
./scripts/render-netplan.sh ./fabric.env
```
