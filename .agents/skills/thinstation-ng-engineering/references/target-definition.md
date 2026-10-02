# Target definition to ThinStation configuration

A target definition may arrive as prose, a checklist, an existing build profile, or structured data. Normalize it before editing source.

## Required target fields

Capture only what affects the image:

- **Purpose**: desktop, kiosk, terminal, server, container appliance, Kubernetes appliance, recovery/tooling image, etc.
- **Platform**: physical hardware family or generic virtual platform; BIOS/UEFI/Secure Boot requirements.
- **CPU/architecture**: supported architecture and any required virtualization features.
- **Drivers/modules**: machine profile, storage, network, GPU, input, filesystem, special kernel modules.
- **Runtime packages**: applications, daemons, clients, utilities, authentication/networking components.
- **UI/session**: headless, console, Xorg/XFCE, browser/kiosk, remote desktop, display manager.
- **Networking**: DHCP/static capability, NetworkManager/autonet choice, Wi-Fi, DNS/search behavior, firewall-owned service ports.
- **Persistence**: files/directories or dedicated filesystems that must survive reboot/image replacement.
- **Storage**: local disk/data-disk expectations, LVM/filesystem requirements, minimum capacity.
- **Security**: audit, SSH/debug policy, SELinux/container policy, Secure Boot expectations.
- **Output**: ISO, EFI image, PXE tree, fastboot image, or another existing ThinStation build target.
- **Qualification**: boot modes, services, UI behavior, persistence, networking, and application health that must be proven.

Do not add deployment-environment inventory or topology unless it directly changes the image contract.

## Translate target to repository changes

Prefer this order:

1. Reuse an existing `ts/build/conf/<profile>/` profile if it already represents the target class.
2. Adjust package selection in the profile.
3. Add a reusable package if behavior belongs to a component rather than one profile.
4. Add machine-specific modules through machine/kernel dependency mechanisms rather than globally bloating all images.
5. Put immutable package-owned runtime files under the package source tree, normally `build/extra` when the package population path uses it.
6. Use finalizers only for behavior that must be materialized in the final image and cannot be represented as ordinary package-owned files.
7. Keep credentials, site names, addresses, and deployment-specific values outside committed reusable defaults.

## Configuration output

Before building, be able to state:

- selected profile,
- packages enabled/disabled,
- machine profile/modules,
- build parameters,
- expected boot artifact,
- required persistent data,
- local qualification matrix.

If the target definition is underspecified, derive conservative defaults from existing repository profiles and keep the result generic.
