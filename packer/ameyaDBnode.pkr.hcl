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

variable "source_ami" {
  type    = string
  default = "ami-0db1c5c6dc64eb019"
}

variable "clockbound_version" {
  type    = string
  default = "3.0.0-alpha.1"
}

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

  provisioner "shell" {
    inline = [
      "set -eux",
      "sudo dnf update -y",
      "sudo dnf install -y chrony gcc gcc-c++ git make lsof",
    ]
  }

  provisioner "shell" {
    inline = [
      "set -eux",
      "g++ --version",
      "echo '#include <ranges>' | g++ -std=c++20 -x c++ -E - > /dev/null && echo 'C++20 <ranges> OK'",
    ]
  }

  provisioner "shell" {
    inline = [
      "set -eux",
      "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable",
      "echo 'source $HOME/.cargo/env' >> $HOME/.bash_profile",
    ]
  }

  provisioner "shell" {
    inline = [
      "set -eux",
      "git clone --depth 1 --branch ${var.clockbound_version} https://github.com/aws/clock-bound.git /home/ec2-user/clock-bound",
    ]
  }

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

  provisioner "shell" {
    inline = [
      "set -eux",
      "source $HOME/.cargo/env",
      "cd /home/ec2-user/clock-bound",
      "cargo build --release --bin clockbound",
      "sudo cp target/release/clockbound /usr/bin/clockbound",
      "cd /home/ec2-user/clock-bound/clock-bound-ffi",
      "cargo build --release",
      "sudo cp include/clockbound.h /usr/include/clockbound.h",
      "sudo cp ../target/release/libclockbound.a ../target/release/libclockbound.so /usr/lib/",
      "sudo ldconfig",
    ]
  }

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

  provisioner "shell" {
    inline = [
      "set -eux",
      "echo 'refclock PHC /dev/ptp0 poll 0 delay 0.000010 prefer' | sudo tee -a /etc/chrony.conf",
      "sudo systemctl enable chronyd",
    ]
  }

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

  provisioner "shell" {
    inline = [
      "set -eux",
      "sudo dnf clean all",
    ]
  }
}