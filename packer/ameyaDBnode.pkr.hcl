packer {
  required_plugins {
    amazon = {
      source  = "github.com/hashicorp/amazon"
      version = "~> 1.3"
    }
  }
}

variable "region" {
  type    = string
  default = "us-east-1"
}

# Base AMI - Amazon Linux 2023, x86_64 (kernel 6.12+).
#
# IMPORTANT: this was AL2 (kernel 4.14) until we discovered live, on a running
# node, that clockbound's PHC sampling hard-depends on the PTP_SYS_OFFSET_EXTENDED2
# ioctl, which was only added to the kernel in 5.10. AL2's 4.14 kernel doesn't
# have it at all - every PHC sample call fails with ENOTTY ("Inappropriate ioctl
# for device"), permanently, no config or source patch can fix that. AL2023's
# kernel is 6.12+, well past 5.10, so this actually works there.
#
# Current AMI ID looked up via:
#   aws ec2 describe-images --owners amazon \
#     --filters "Name=name,Values=al2023-ami-2023.*-x86_64" "Name=state,Values=available" \
#     --query 'sort_by(Images, &CreationDate)[-1].[ImageId,Name,CreationDate]' \
#     --output table --region us-east-1
# Re-run that periodically to pick up a newer AL2023 AMI; AWS retires old ones.
variable "source_ami" {
  type    = string
  default = "ami-0db1c5c6dc64eb019" # al2023-ami-2023.12.20260817.0-kernel-6.12-x86_64
}

# clock-bound is pre-1.0 (alpha) - pin explicitly rather than tracking `main`,
# since the API/CLI surface can still change between alphas.
variable "clockbound_version" {
  type    = string
  default = "3.0.0-alpha.1"
}

# Build on an instance type from the SAME family you'll actually run on.
# This matters here specifically: configure_phc / the PHC refclock device
# depend on the ENA driver exposing a PTP hardware clock (confirmed live as
# /dev/ptp0, not the /dev/ptp_ena symlink AWS's docs imply - no such symlink
# actually exists), which is only present on Gen7+ Nitro instances with Time
# Sync Service support. Building the AMI on a non-PHC instance type (e.g.
# t3.micro) would let the daemon/chrony install succeed but skip PHC-specific
# setup silently. Build on m7i.large to match the target db_node instance
# type.
variable "build_instance_type" {
  type    = string
  default = "m7i.large"
}

source "amazon-ebs" "node" {
  region        = var.region
  source_ami    = var.source_ami
  instance_type = var.build_instance_type
  ssh_username  = "ec2-user"

  ami_name        = "ameyaDB-node-{{timestamp}}"
  ami_description = "Amazon Linux 2023 node image for ameyaDB db_node (m7i.large): gcc C++20 toolchain + chrony + PHC config + ClockBound ${var.clockbound_version} daemon/FFI"

  tags = {
    Name              = "ameyaDB-node"
    ClockBoundVersion = var.clockbound_version
    SourceAMI         = var.source_ami
    BuiltBy           = "packer"
  }
}

build {
  name    = "ameyaDB-node"
  sources = ["source.amazon-ebs.node"]

  # --- Base packages: chrony, build toolchain, git, rust toolchain deps ---
  # AL2023 uses dnf, not yum (yum is a symlink to dnf here, but use dnf
  # directly to avoid relying on that compat shim).
  provisioner "shell" {
    inline = [
      "set -eux",
      "sudo dnf update -y",
      "sudo dnf install -y chrony gcc gcc-c++ git make lsof",
    ]
  }

  # --- C++20 toolchain check ---
  # AL2023 ships gcc 11+ by default (unlike AL2's gcc 7.3), which fully
  # supports -std=c++20 (concepts, <ranges>, etc - walsnap.cpp uses
  # ranges::find_if, which needs GCC 10+). test.py invokes the compiler as
  # plain `g++` with no version suffix and we were asked not to edit test.py -
  # on AL2023 the default `g++` already satisfies that with zero extra setup,
  # so there's no update-alternatives dance needed here anymore (that was an
  # AL2-only workaround). Keep the version print + <ranges> compile check as
  # a build-time guardrail in case a future base-AMI bump changes the default
  # compiler version again.
  provisioner "shell" {
    inline = [
      "set -eux",
      "g++ --version",
      "echo '#include <ranges>' | g++ -std=c++20 -x c++ -E - > /dev/null && echo 'C++20 <ranges> OK'",
    ]
  }

  # --- Rust toolchain (for building clockbound + clock-bound-ffi from source) ---
  provisioner "shell" {
    inline = [
      "set -eux",
      "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable",
      "echo 'source $HOME/.cargo/env' >> $HOME/.bash_profile",
    ]
  }

  # --- Clone clock-bound at the pinned tag ---
  provisioner "shell" {
    inline = [
      "set -eux",
      "git clone --depth 1 --branch ${var.clockbound_version} https://github.com/aws/clock-bound.git /home/ec2-user/clock-bound",
    ]
  }

  # --- Patch: VMClock hard panic on instances without /dev/vmclock0 ---
  # Discovered live, on a running node: clock-bound 3.0.0-alpha.1 (the tip of
  # both its tags and `main` as of this writing - there is no upstream fix)
  # unconditionally tries to enable AWS's VMClock device on any non-metal EC2
  # instance, and *hard panics* (process exit 101) if that device isn't
  # present. VMClock is separate from PHC and isn't exposed on m7i.large /
  # this AMI - so without this patch, clockbound crash-loops immediately on
  # every boot.
  #
  # The fix mirrors the graceful-fallback pattern the same function already
  # uses for its other failure modes (IMDS failure, metal-instance detection):
  # turn the `.unwrap_or_else(|_| panic!(...))` on VMClock::construct() into a
  # match that logs a warning and returns instead of panicking. Verified this
  # compiles and the daemon stays up (no crash-loop) with this patch applied.
  #
  # The patch itself is a Python script (uploaded via the "file" provisioner
  # below, checked into packer/ alongside this template) so we can assert the
  # exact original string is present exactly once before rewriting it - if a
  # future clock-bound version changes this code, the build fails loudly
  # instead of silently no-op'ing or mismatching.
  provisioner "file" {
    source      = "patch_vmclock_panic.py"
    destination = "/tmp/patch_vmclock_panic.py"
  }

  provisioner "shell" {
    inline = [
      "set -eux",
      "python3 /tmp/patch_vmclock_panic.py",
    ]
  }

  # --- Build clockbound daemon + the FFI library ---
  provisioner "shell" {
    inline = [
      "set -eux",
      "source $HOME/.cargo/env",
      "cd /home/ec2-user/clock-bound",
      # Daemon binary
      "cargo build --release --bin clockbound",
      "sudo cp target/release/clockbound /usr/bin/clockbound",
      # FFI library + header, for the C/C++ client (threads.cpp links against these)
      "cd /home/ec2-user/clock-bound/clock-bound-ffi",
      "cargo build --release",
      "sudo cp include/clockbound.h /usr/include/clockbound.h",
      "sudo cp ../target/release/libclockbound.a ../target/release/libclockbound.so /usr/lib/",
      "sudo ldconfig",
    ]
  }

  # --- PHC configuration on the ENA NIC (Gen7+ Nitro instances only) ---
  # configure_phc wires up the PTP hardware clock exposed by the ENA driver
  # (requires ENA driver >= 2.10.0, already present on current AL2023 AMIs for
  # Gen7 instance families). `-c` persists the config for next boot rather
  # than reloading the ENA driver live during the Packer build, which is
  # safer inside a build session over SSH.
  #
  # NOTE: the exact path to this script inside the clock-bound repo isn't
  # documented anywhere I could verify externally (AWS's own docs just say
  # "see the assets directory" without a path, and GitHub blocks automated
  # fetches of the repo tree). So instead of hardcoding a guessed path, this
  # step searches the actual cloned repo for it and reports what it finds -
  # ground truth from the real checked-out source beats a guess.
  provisioner "shell" {
    inline = [
      "set -eux",
      "echo '--- searching cloned repo for configure_phc ---'",
      "find /home/ec2-user/clock-bound -iname '*configure_phc*' -o -iname '*phc*' 2>/dev/null || true",
      "echo '--- top-level repo contents ---'",
      "ls -la /home/ec2-user/clock-bound",
      "PHC_SCRIPT=$(find /home/ec2-user/clock-bound -iname 'configure_phc' -type f | head -n1)",
      "if [ -n \"$PHC_SCRIPT\" ]; then",
      "  echo \"Found configure_phc at: $PHC_SCRIPT\"",
      "  chmod +x \"$PHC_SCRIPT\"",
      "  sudo \"$PHC_SCRIPT\" -c",
      "else",
      "  echo 'WARNING: configure_phc script not found anywhere in the repo at this pinned version.'",
      "  echo 'Skipping PHC-specific configuration - chrony will still run, but without the PHC refclock boost.'",
      "  echo 'This needs manual follow-up: check the clock-bound repo for how PHC setup is meant to work at this version.'",
      "fi",
    ]
  }

  # --- chrony: point it at the PHC refclock ---
  # NOTE: AWS's docs suggest a stable `/dev/ptp_ena` symlink, but that doesn't
  # actually exist on this AMI/instance family - confirmed live (exhaustively:
  # checked /etc/modprobe.d/ena.conf, `lsmod | grep ena`, `ls /dev/ptp*`, and
  # searched for any udev rule that would create such a symlink - there isn't
  # one). The real device is /dev/ptp0. This is a single-PHC-device box (one
  # ENA NIC), so a fixed path is fine here; if a future instance type exposes
  # multiple PTP devices, this would need clockbound's own dynamic discovery
  # approach (see phc_path_locator in clock-bound's source) instead of a
  # hardcoded path.
  provisioner "shell" {
    inline = [
      "set -eux",
      "echo 'refclock PHC /dev/ptp0 poll 0 delay 0.000010 prefer' | sudo tee -a /etc/chrony.conf",
      "sudo systemctl enable chronyd",
    ]
  }

  # --- clockbound systemd service ---
  # No official systemd unit ships from a source build (only the RPM does),
  # so we write a minimal one. Verify at boot with `systemctl status clockbound`
  # and `clockbound_now` via threads.cpp's own fallback logging.
  provisioner "shell" {
    inline = [
      "set -eux",
      "cat <<'UNIT' | sudo tee /etc/systemd/system/clockbound.service",
      "[Unit]",
      "Description=ClockBound daemon",
      "After=chronyd.service",
      "Requires=chronyd.service",
      "",
      "[Service]",
      # This alpha's CLI only accepts --log-dir/-h - confirmed live via
      # `clockbound --help` - it does NOT accept --ip. Passing --ip crashes
      # the daemon immediately with "unexpected argument '--ip' found".
      "ExecStart=/usr/bin/clockbound",
      "Restart=on-failure",
      "RestartSec=2",
      "",
      "[Install]",
      "WantedBy=multi-user.target",
      "UNIT",
      "sudo systemctl daemon-reload",
      "sudo systemctl enable clockbound",
    ]
  }

  # --- Cleanup: remove build toolchain/source tree so the AMI stays lean ---
  # (kept minimal deliberately - rustup/cargo are left in place in case the
  # FFI library needs rebuilding in place later; remove manually if you want
  # a smaller image.)
  provisioner "shell" {
    inline = [
      "set -eux",
      "sudo dnf clean all",
    ]
  }
}