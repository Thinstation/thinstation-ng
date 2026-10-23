
# ThinStation

[**Join the ThinStation Discord community**](https://discord.gg/FVhXJgNZEE) — get help, discuss development, and follow project announcements. Choose a general channel in your language; messages translate to and from the English hub.

## Support ThinStation development

ThinStation is free and open source, but AI time and compute resources are not free. Donations help fund AI-assisted development, builds, and testing so we can finish features and deliver releases.

If ThinStation is useful to you, please consider supporting its development. Any amount helps, and donating is entirely optional.

[**Donate via PayPal on thinstation.org**](https://thinstation.org/) — click the **Donate** button on the official website.

README - Displaying this file can be disabled by touching `/ts/etc/READ`

Visit the ThinStation [Wiki](https://github.com/Thinstation/thinstation-ng/wiki/Getting-Started-with-ThinStation)

ThinStation is a small, yet powerful, Open Source thin client operating system supporting:
Citrix ICA, Redhat Spice, NoMachine NX, Microsoft Windows terminal services (RDP, via FreeRDP), VMware Horizon View, Cendio ThinLinc, X and SSH.

This environment was created for you by Donald A. Cupp Jr. from Fedora and ThinStation.

ThinStation itself has many contributors, with special thanks to:
- Mike Eriksen
- Trevor Batley
- Miles Roper
- Marcos Amorim

## NEWS

- ThinStation now uses **Fedora** binaries and the **DNF** package manager for improved compatibility and maintainability.
- A utility has been added to configure `dnsmasq` as a DHCP/DNS/Router to DevStation.
- All boot images except GRUB have been deprecated.

## System Requirements

ThinStation now requires either:
1. A **Fedora-based** host environment.
2. The preconfigured **DevStation** Installer to set up the development environment.
3. **WSL** and the minimal ThinStation root fs

### Using a Fedora Host

- Minimum system requirements:
    - **8 GB of RAM**
    - **30 GB of free disk space**
    - Administrative privileges (root or sudo).

- Install required dependencies:

   ```bash
   sudo dnf install dnf chroot git
   ```

- Clone the ThinStation repository:

   ```bash
   git clone https://github.com/Thinstation/thinstation-ng.git
   cd thinstation-ng
   ```

### Using the DevStation Installer

The **DevStation** image is installed through the DevStation **Installer**, which will:
- Create the necessary partitions on your target disk.
- Download and place the DevStation image on the system.

#### Steps to Use the DevStation Installer:

1. Download the DevStation Installer from the ThinStation [Website](https://www.thinstation.org/TS-7.2.0-Installer-0701.iso)
2. Boot the installer on your system.
3. Follow the prompts to:
    - Collect credentials.
    - Partition the disk.
    - Download the DevStation image.
    - Install the image to the appropriate partitions.
    - Setup the build environment.
5. Once installed, reboot into the DevStation environment.

### Importing ThinStation into WSL and Setting Up the Development Environment

To get started with ThinStation on a Windows system using Windows Subsystem for Linux (WSL), follow these steps to download the distribution tarball, import it into WSL, and prepare your development environment.

#### Step 1: Download the ThinStation Tarball

1. Download a root fs from the official ThinStation website [here](https://www.thinstation.org/thinstation.tar.xz).
2. Once downloaded, expand the archive to for example `Downloads/thinstation.tar`.

#### Step 2: Import ThinStation into WSL

1. Open Windows Terminal or your preferred PowerShell or Command Prompt interface.
2. Ensure WSL is installed on your system. If not, you can install it by following the official Microsoft guide.
3. Use the following command to import ThinStation into WSL:

   ```bash
   wsl --import ThinStation $HOME\WSL\ThinStation $HOME\Downloads\thinstation.tar
   ```

#### Step 3: Clone the thinstation-ng Repository

1. Launch the ThinStation distribution in WSL by typing:

   ```bash
   wsl -d ThinStation
   ```
2. Clone the thinstation-ng repository:

   ```bash
   git clone https://www.github.com/thinstation/thinstation-ng.git
   cd thinstation-ng
   ```

## Notes

- Ensure that you have sufficient disk space and permissions to perform these operations.
- For detailed build instructions and options, refer to the ThinStation Wiki and the README files within the repository.

## Getting Started

1. **Prepare the Development Environment**

   - On a Fedora host or DevStation or WSL, ensure you have access to the `setup-chroot` script located in the ThinStation repository.
   - Run the script to initialize the development environment:

   ```bash
   ./setup-chroot
   ```

   - This will:
      - Populate necessary directories and dependencies.
      - Set up the chroot environment for building ThinStation images.

2. **Build ThinStation Images**

   - Enter the chroot environment:

   ```bash
   ./setup-chroot
   ```

   - Navigate to the build directory:

   ```bash
   cd /build
   ```

   - Configure your build by editing the following files:
      - `build.conf`: Defines the overall build configuration.
      - `thinstation.conf.buildtime`: Customizes runtime settings for ThinStation.

   - Run the build process:

   ```bash
   ./build
   ```

3. **Deploy ThinStation**

   - Once the build completes, your ThinStation images will be ready in /build/boot-images/grub of the chroot.
   - Follow the [deployment](https://github.com/Thinstation/thinstation-ng/wiki/Deployment) guide on the ThinStation Wiki for details on deploying ThinStation to your environment.

## Notes for End Users

### Running ThinStation

- ThinStation is designed to run as a thin client, requiring minimal hardware resources.
- Ensure that the target hardware supports PXE boot or has a method to boot the ThinStation image (e.g., USB, CD/DVD, or network boot).

### Basic Requirements

- **Client Hardware:**
    - CPU: x86-64 architecture.
    - RAM: Minimum 2 GB (8 GB recommended).
    - Network: Wired or wireless network interface.

- **Server Environment:**
    - Ensure compatibility with your backend systems (e.g., RDP, Citrix, VMware Horizon).
    - Configure servers to allow client connections according to your chosen protocol.

## Support and Documentation

For detailed instructions, troubleshooting, and additional resources, visit the ThinStation Wiki.

If you encounter issues or require assistance:
- Open an issue on the [ThinStation GitHub repository](https://github.com/Thinstation/thinstation-ng/issues).
- Join the [ThinStation Discord community](https://discord.gg/FVhXJgNZEE) for troubleshooting, development discussions, and project announcements. Start in `#welcome`, read `#rules`, then choose your language's general channel.
- Use GitHub issues for reproducible bugs and tracked development work.

