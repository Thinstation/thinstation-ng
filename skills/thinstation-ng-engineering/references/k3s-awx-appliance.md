# K3s / AWX Appliance Architecture

## Runtime model

Use upstream K3s as a matched runtime stack rather than mixing Fedora's standalone containerd with K3s.

K3s provides the Kubernetes server/agent plus its matched containerd, runc, CNI, kubectl, crictl, ctr, and bundled userspace tools. Fedora supplies host prerequisites and kernel support.

Pin the K3s release and verify its SHA256 during package population.

## Red Hat / SELinux integration

Follow Rancher's Red Hat ecosystem split:

- Fedora/ThinStation supplies the base SELinux stack and `container-selinux`.
- Rancher's official `k3s-selinux` RPM supplies K3s policy.
- K3s runtime remains the upstream K3s binary.

Keep `k3s-selinux` as a separate ThinStation package so policy updates are independent of the K3s runtime.

## Fastboot caveat

ThinStation fastboot presents a synthetic root filesystem that kubelet/cAdvisor cannot use for ordinary rootfs capacity accounting. K3s can still run by passing:

```yaml
kubelet-arg:
  - "local-storage-capacity-isolation=false"
```

This means workloads should not depend on kubelet enforcing ephemeral-storage requests/limits or `emptyDir.sizeLimit` on the synthetic root.

## Network/kernel requirements

K3s kube-proxy, flannel, and the network-policy controller need a broader netfilter set than a minimal Docker appliance. Include the relevant bridge/veth/vxlan, conntrack, iptables/nftables compatibility, ipset, multiport, comment, nfacct, REJECT, physdev, limit, NFLOG, and NAT modules.

When a K3s component reports an iptables extension failure, resolve the extension to the actual Fedora kernel module with `modinfo`/module aliases and add it to the package kernel dependency set rather than installing another userspace firewall stack.

## IPv4-only appliance behavior

A changing SLAAC IPv6 address can make K3s detect `NodeIPs changed` and intentionally restart.

For the IPv4-only appliance profile:

- set ThinStation networking to IPv6 disabled,
- use NetworkManager's real `ipv6.method=disabled`, not `ignore`,
- add `ipv6.disable=1` to the appliance kernel command line so IPv6 cannot initialize in the initramfs before NetworkManager,
- prefer kubelet IPv4 with `node-ip=0.0.0.0`.

A profile edit is not enough if the active `ts/build/build.conf` still has an older kernel command line. Verify the generated GRUB/iPXE files contain `ipv6.disable=1` before boot testing.

## Persistence and image preload

Persist `/var/lib/rancher/k3s` on a dedicated data filesystem. Do not duplicate it through ThinStation's persistence-copy mechanism.

K3s watches `/var/lib/rancher/k3s/agent/images` for OCI/Docker archives, which is useful for an immutable AWX appliance. Stage pinned K3s/AWX images there from ISO media and let bundled containerd import them.

## Validation contract

Before layering AWX itself, prove the K3s substrate:

1. fresh loop-backed persistent disk mounts correctly,
2. K3s reaches Ready,
3. bundled containerd initializes,
4. flannel writes `/run/flannel/subnet.env`,
5. network-policy controller starts,
6. no missing netfilter extension remains,
7. graceful poweroff/reboot preserves K3s DB, certificates, token, and node identity,
8. stable reboot produces one K3s start with no `NodeIPs changed` churn.
