# Lab Validation and Debugging

## Canonical repo and workspace

- GitLab project: `davinci/thinstation-ng`, project ID 6.
- Canonical branch: `7.4-Stable`.
- Fedora build host alias: `fedora`, workspace `/thinstation-ng`.
- Fedora checkout may lag GitLab and may contain deliberate active build edits. Do not broad-reset it.

## PVE lab

Cluster nodes: `pve1`, `pve2`, `pve3`.

Shared ISO storage: `cephfs`, typically visible as `/mnt/pve/cephfs/template/iso`.
VM disks commonly use `Ceph_Datastore`.
Appliance VMs normally use q35, OVMF, host CPU, virtio-scsi-single, virtio NIC, and VLAN 2 on `vmbr0` in this lab.

Use PVE direct tools for VM lifecycle/configuration whenever possible. Use SSH to a PVE node for gaps such as `qm guest exec`, checksums, or file transfer.

## Pipeline-to-VM validation workflow

1. Trigger pipeline on current `7.4-Stable` with the desired appliance variable.
2. Manual appliance build jobs must be explicitly played.
3. Watch the build job until success; inspect trace on failure rather than launching duplicate pipelines.
4. Verify deploy/publish succeeds.
5. Determine the exact published ISO filename from deploy trace or distro index.
6. Download the ISO directly from `distro.thinstation.org` to shared CephFS from a PVE node.
7. Verify the published `.sha256` before use.
8. Stop the disposable test VM, attach the new ISO, and start it.
9. Verify runtime through QGA and/or SSH.

## QGA

QEMU Guest Agent is a preferred validation path because it avoids fragile serial-console assumptions.

Useful checks through a PVE node:

```bash
qm guest cmd <vmid> network-get-interfaces
qm guest exec <vmid> -- sh -lc 'systemctl --failed --no-pager'
qm guest exec <vmid> -- sh -lc 'systemctl is-active docker sshd'
```

Use QGA to inspect the guest before assuming SSH/network behavior.

## SSH debugging

The GitLab appliance CI can enable OpenSSH specifically for lab debugging. The MCP public key is supplied through CI; the private key must remain only on the MCP host.

Current successful test pattern used root key-only access. Verify in the guest:

- `sshd` active
- port 22 listening for appliance/MCP SSH
- `/root/.ssh/authorized_keys` exists with mode 0600

Then test the real MCP-side key login, not only the presence of the file. For the GitLab appliance, repository SSH should be published separately on host TCP 2222.

## Current disposable GitLab test VM pattern

A recent test used VM 106 on `pve3`, name `gitlab-ee-lab-test`, with 4 vCPU, 8 GiB RAM, 32 GiB Ceph disk, q35/OVMF, VLAN 2, ISO first in boot order. DHCP assigned `192.168.22.124` during validation.

Treat IDs/IPs as lab observations, not reusable source defaults.

## Debugging discipline

- Prefer the real live guest over reasoning from source alone once an ISO is available.
- Confirm package payloads actually exist in the runtime filesystem.
- Inspect `tmp-tree` and `fastboot-tmp` for fastboot issues.
- Use exact PIDs for QEMU cleanup; avoid broad `pkill -f`.
- Do not launch duplicate builds just because connector calls time out; first inspect pipeline/job/process state.

## Web-service validation

When a Docker-backed service is unreachable, isolate layers in this order:

1. Confirm the VM address with QGA.
2. Confirm Docker container state and published ports.
3. Confirm host listeners with `ss -lntp`.
4. Confirm package firewall fragments and effective firewalld zone state.
5. Confirm the service inside the container is actually listening/ready.
6. Test from a PVE node to the guest IP.

Do not assume `docker ps ... healthy` means GitLab Rails is ready. For GitLab, confirm the Puma Rails socket before treating 502 responses as a network problem.

For firewalld validation, inspect both declarative package fragments and effective state:

```bash
cat /etc/firewall.d/<fragment>
firewall-cmd --get-active-zones
firewall-cmd --zone=public --list-services
firewall-cmd --zone=public --list-ports
nft list ruleset
```


## Appliance management services

For appliance images, prefer the normal `sshd.service` ordered with `tsinit` over per-connection socket activation when early boot/persistent state is still settling. In validation, socket-activated SSH accepted TCP and then closed sessions before a usable daemon environment was ready.

For QEMU Guest Agent, avoid a brittle hard `BindsTo=` on the virtio-port device unit. The validated appliance override starts after `tsinit.target` and `fastboot.service` and uses restart-on-failure, while the package still provides its normal device integration.
