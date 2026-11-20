# RadioKubeNDT

> Last reviewed: 20 Nov 2026

**RadioKubeNDT** emulates a 5G radio access network over a real area of the world, on Kubernetes.

You pick an area on a map, place the radio sites and the terminals, and RadioKubeNDT generates a namespace with a working 5G system: an Open5GS core, one gNB per site, one UE per terminal and a data network for your servers. While the terminals move through the streets of that area, their radio links follow a ray-traced model of its buildings, and every link of the namespace is shaped to match, step by step.

Under the radio side runs a full network emulation platform. Every namespace is a live topology that you can extend with routers, switches, servers and links, configure through declarative actions, inspect and measure from the dashboard or the REST API.

It is a research prototype, developed and tested on one machine (NVIDIA DGX Spark, arm64, single-node kind cluster).

## What it does

### Radio zones

The **Radio zones** page (`/radio`, also reachable from the home page and from every namespace) is an OpenStreetMap map where you:

1. draw the area (up to 3000 m per side); its buildings and roads are downloaded from OpenStreetMap;
2. place the sites by clicking, by importing the telephony masts mapped in OpenStreetMap, by importing a CSV, or automatically, and set their height, sector azimuths, downtilt and power;
3. build the scenario: a 3D scene of the buildings for Sionna RT, a SUMO road network with background traffic, and a ray-traced coverage map per sector, drawn over the map;
4. define the UEs: cars or persons, each one **mobile** (moves on its own along the streets), **fixed**, or on a **route** (a start point and one or more destinations visited in order, then stop or loop). UEs are always on a street;
5. create the namespace, choose whether handovers are emulated, and start or stop the emulation, watching every UE move with its trail, its planned route and its link figures.

### The generated namespace

An Open5GS core, one UERANSIM gNB per site, one UERANSIM UE per terminal (each UE wired to every gNB), and a data network behind the UPF with a switch (`dn-0`) and a first server (`server-0`, `10.45.0.10`). From there it is an ordinary namespace: add servers, routers or links with the usual tools.

### The emulation loop

Every 0.5 s:

- SUMO moves the UEs and the background traffic;
- Sionna RT gives the path gain from every UE to every sector, with the vehicles as moving objects;
- an A3 rule (TS 38.331: L3 filter, offset, hysteresis, time to trigger) picks the serving cell, and radio link failure follows the serving SINR against Qout and Qin with T310;
- the serving link is shaped to the rate its SINR allows (curves from Sionna SYS) and the links to the other gNBs are cut, through the platform's own API.

### Emulated Handover

A switch on the Radio zones page, per zone, used at the next Start:

- **Off**: a handover is an instant switch between gNBs.
- **On**: each handover goes through random access to the target cell, and its cost reaches the shaped links:
  - preamble power from the path loss with ramping, capped at the UE's maximum power (TS 38.213 7.4, TS 38.321 5.1);
  - detection by the target gNB from the preamble SNR on the uplink (99 % at −6 dB, TS 38.104 format 0);
  - the random access response, which the UE has to decode on the downlink;
  - contention with other UEs that picked the same preamble in the same occasion, from the emulated UEs and a background access rate;
  - at most `preambleTransMax` attempts, bounded by T304; a failed access is a handover failure followed by re-establishment;
  - a successful handover costs the RRC procedure delay plus the TS 38.133 6.1.1.2 interruption (T_search + T_IU + 20 ms + T_Δ), about 60 ms, taken from the throughput of that step.

The live table shows handover failures and the gap. In a 10-minute test on a 1.2 km zone with 32 UEs, the gap averaged 60 ms (95th percentile 64 ms) and 2 % of handovers failed, mostly because the target's downlink was too weak to decode the random access response.

Every value is a setting of [`radio/rach_lite.py`](radio/rach_lite.py) with its source and status: CONFIG (a network setting), DERIVED, ASSUMPTION or UNVERIFIED. The detection point, the RRC procedure delay and the background access rate are UNVERIFIED or ASSUMPTION. To change them for a zone, set `"emulation_params": {"access": {...}}` in its `zone.json`, with any field of `AccessConfig`.

### What changes in the platform

- **Node types `ue` and `gnb`**: hosts to the platform, drawn with their own icons in the graph.
- **`in_place` shaping**: `tcparams.in_place: true` updates a netem or tbf without emptying its queue, for links whose state changes every step.
- **One exec per pod for shaping**: the tc actions of a pod in a configure request share one `tc -b` batch.
- **`handover` action**: moves a route to another interface, make-before-break, for nodes wired to several attachment points.
- **`/radio/*` routes**: forwarded to the radio service when `KUBENDT_RADIO_URL` is set, behind the same authentication as the rest of the API.
- **arm64**: the backend image builds for the host architecture, and `deploy/others/meshnet-multiarch` installs Meshnet on workers that are not amd64.

### The network platform underneath

- Topologies as JSON (nodes, links, images, replicas) deployed on Kubernetes with the Meshnet CNI, shown as a live graph with annotations and exported as JSON or as a picture.
- A driver and capability system: the same declarative actions on hosts, Linux routers and switches, FRR, VyOS, Open vSwitch, Faucet, P4 (BMv2) and EXOS nodes.
- Layer 2 (bridges, VLANs, spanning tree), layer 3 (addresses, routes, ARP and NDP), routing protocols (OSPFv2 and v3, RIP, BGP, IS-IS), NAT and NAT64, traffic control, OpenFlow and P4.
- Shells, live packet capture, traceroute shown on the graph, iperf3 throughput tests, interface and per-protocol inspections, a file manager for what the nodes mount.
- Authentication with sessions and API tokens, and a REST API documented with Swagger.

## Quick start

### Requirements

- **Kubernetes 1.25+ with the Meshnet CNI** (1.30 or newer recommended). The kubelet must allow the `net.ipv4.ip_forward` and `net.ipv6.conf.all.forwarding` sysctls. See [doc/How-to-deploy-a-K8s-cluster.md](doc/How-to-deploy-a-K8s-cluster.md).
- **Docker and Docker Compose** for the dashboard and the API.
- **A host with an NVIDIA GPU** for the radio service, with a Python environment holding Sionna 2.2 (Sionna RT and Sionna SYS, with PyTorch), Eclipse SUMO 1.28 (`eclipse-sumo`, `libsumo`, `sumolib`, `traci`), `aiohttp`, `mapbox-earcut`, `pyproj`, `scipy`, `matplotlib` and `Pillow`, and `kubectl` with a kubeconfig for the cluster.
- **Container images for the 5G system**, available to the cluster: Open5GS built from [herlesupreeth/docker_open5gs](https://github.com/herlesupreeth/docker_open5gs) and UERANSIM. On arm64, Open5GS and the toolbox image have to be built locally.

### 1. Run the dashboard and the API

```bash
git clone https://github.com/alejandrocalvillo/radio-kubendt.git
cd radio-kubendt
docker compose up --build
```

Then open http://localhost. The compose file ships the admin password `admin123`: change it with `KUBENDT_ADMIN_PASSWORD` before any real use. On the backend, also set:

- `KUBENDT_RADIO_URL`: where the radio service listens (step 2);
- `KUBENDT_K8S_QPS` and `KUBENDT_K8S_BURST`: raise them (2000 and 4000 were used) so that shaping many links per step is not throttled.

All the other settings are in [doc/DEPLOYMENT.md](doc/DEPLOYMENT.md).

### 2. Run the radio service

Create an API token in the dashboard (profile menu, API tokens) and save it in a file. Then, on the GPU host:

```bash
python radio/radio_service.py --host 172.17.0.1 --port 8770 --kubendt-url http://localhost:8080 --home ~/kubendt-radio
```

and point the backend to it with `KUBENDT_RADIO_URL=http://172.17.0.1:8770`. `172.17.0.1` is only an example (the default Docker bridge gateway): use an address of the GPU host that the backend container reaches and that is not public, because the service has no authentication of its own.

| Setting | Command line | Environment | Default |
| --- | --- | --- | --- |
| Address and port the service listens on | `--host`, `--port` | `KUBENDT_RADIO_HOST`, `KUBENDT_RADIO_PORT` | `127.0.0.1`, `8770` |
| Base URL of the platform's API | `--kubendt-url` | `KUBENDT_URL` | `http://localhost:8080` |
| Working folder (zones, cache, generated files) | `--home` | `KUBENDT_RADIO_HOME` | `~/kubendt-radio` |
| API token | `--token-file` | `KUBENDT_TOKEN_FILE`, or the token itself in `KUBENDT_TOKEN` | `<home>/.kubendt_token` |
| Open5GS image | | `KUBENDT_RADIO_OPEN5GS_IMAGE` | `docker_open5gs:latest` |
| UERANSIM image | | `KUBENDT_RADIO_UERANSIM_IMAGE` | `gradiant/ueransim:3.2.6` |
| Image of `server-0` | | `KUBENDT_RADIO_TOOLBOX_IMAGE` | `ghcr.io/emigcm98/kubendt-toolbox:latest` |

### 3. Emulate an area

Open **Radio zones** from the home page and follow its five steps. The guide is in [doc/RADIO_ZONES.md](doc/RADIO_ZONES.md).

## The radio scripts

| Script | |
| --- | --- |
| [`radio_service.py`](radio/radio_service.py) | the HTTP service behind `/radio/*`: zones, sites, UEs, namespaces, emulation |
| [`zone.py`](radio/zone.py) | a zone from OpenStreetMap: 3D scene, road network, coverage maps, UEs on the streets |
| [`emulator.py`](radio/emulator.py) | the namespace of a zone and the loop that drives its radio links |
| [`mobility_sys.py`](radio/mobility_sys.py) | SUMO mobility, the Sionna RT link model, the A3 rule and radio link failure |
| [`rach_lite.py`](radio/rach_lite.py) | random access and the handover gap of Emulated Handover |
| [`g5_stack.py`](radio/g5_stack.py) | the Open5GS and UERANSIM topology of a zone |
| [`radio_maps.py`](radio/radio_maps.py), [`link_rate.py`](radio/link_rate.py) | coverage map container; SINR to rate curves from Sionna SYS |
| [`config.py`](radio/config.py) | the settings of the table above |

## Limits

- Building heights come from OpenStreetMap where mapped and from a default by building type elsewhere; roofs and terrain are flat; every building is concrete.
- The radio channel is one path gain per UE and sector every 0.5 s: there is no fast fading, Doppler or multipath delay in the shaped links.
- UERANSIM has no handover between gNBs: on a change of gNB the UE reselects the cell and its 5G stack takes a few seconds to carry traffic again. Emulated Handover models the cost a real handover would have; it does not make UERANSIM perform one. The emulator keeps the serving link at a 50 kbit/s floor during fades and restarts the 5G stack of a UE whose user plane does not come back.
- The cell-edge SINR is pessimistic (neighbours at heavy load, one antenna element, no beamforming), which raises radio link failures and failed random access responses.
- One emulation at a time per GPU. With about a dozen UEs and five sites, a 0.5 s step runs in real time.
- The radio service has no authentication of its own: it must listen only where the backend reaches it.

## Documentation

- Radio zones: [doc/RADIO_ZONES.md](doc/RADIO_ZONES.md)
- Architecture and execution model: [doc/ARCHITECTURE.md](doc/ARCHITECTURE.md)
- Drivers and node images: [doc/DRIVERS.md](doc/DRIVERS.md)
- Deployment and environment variables: [doc/DEPLOYMENT.md](doc/DEPLOYMENT.md)
- Files the nodes mount: [doc/FILE_MANAGER.md](doc/FILE_MANAGER.md)
- What survives a failure: [doc/FAILURE_MODEL.md](doc/FAILURE_MODEL.md)
- Troubleshooting: [doc/TROUBLESHOOTING.md](doc/TROUBLESHOOTING.md)

[`deploy/examples/`](deploy/examples/) holds 11 reference topologies of the network platform, from a five-node lab to OSPF, BGP, SDN and P4 scenarios and a full Open5GS core, each with a README.

## Security

The radio service trusts whoever reaches it: keep it on an address only the backend reaches. For the platform's security model and deployment hardening, see [SECURITY.md](SECURITY.md).

## Based on KubeNDT

RadioKubeNDT is a modified version of [KubeNDT](https://github.com/emigcm98/kubendt), Copyright (C) 2026 Emilio García de la Calera Molina, licensed under the GNU Affero General Public License v3.0 or later. It is based on KubeNDT v1.11.0 and was modified by Alejandro Calvillo; last modified on 20 November 2026. The modifications are the radio emulation described above and the platform changes listed under "What changes in the platform"; the history of this repository has the detail. If you use the network platform in research, KubeNDT's citation is in [CITATION.cff](CITATION.cff).

## License

Copyright (C) 2026 Alejandro Calvillo (RadioKubeNDT: the radio emulation and the changes to the platform)<br>
Copyright (C) 2026 Emilio García de la Calera Molina (KubeNDT)

RadioKubeNDT is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the [LICENSE](LICENSE) file for the full text.

Anyone who runs a modified version of RadioKubeNDT as a service that others use over a network must offer those users its source code.

Third-party assets bundled in the dashboard (icons, Leaflet) are listed with their licenses in [ATTRIBUTION.md](ATTRIBUTION.md).
