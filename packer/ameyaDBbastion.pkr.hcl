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
  default = "ami-0db1c5c6dc64eb019" # al2023-ami-2023.12.20260817.0-kernel-6.12-x86_64
}

variable "build_instance_type" {
  type    = string
  default = "t3.micro" # matches the actual bastion instance type - no reason to build bigger
}

variable "repo_url" {
  type    = string
  default = "https://github.com/uhhmeya/ameyaDB.git"
}

source "amazon-ebs" "bastion" {
  region        = var.region
  source_ami    = var.source_ami
  instance_type = var.build_instance_type
  ssh_username  = "ec2-user"

  ami_name        = "ameyaDB-bastion-{{timestamp}}"
  ami_description = "Amazon Linux 2023 image for ameyaDB bastion: git + python3/pip + websockets + relay.py checked out, ready to run the relay"

  tags = {
    Name      = "ameyaDB-bastion"
    SourceAMI = var.source_ami
    BuiltBy   = "packer"
  }
}

build {
  name    = "ameyaDB-bastion"
  sources = ["source.amazon-ebs.bastion"]

  provisioner "shell" {
    inline = [
      "set -eux",
      "sudo dnf update -y",
      "sudo dnf install -y git python3 python3-pip",
    ]
  }

  provisioner "shell" {
    inline = [
      "set -eux",
      "pip3 install --user websockets",
    ]
  }

  provisioner "shell" {
    inline = [
      "set -eux",
      "rm -rf /home/ec2-user/ameyaDB",
      "git clone --depth 1 ${var.repo_url} /home/ec2-user/ameyaDB",
      "sudo chown -R ec2-user:ec2-user /home/ec2-user/ameyaDB",
    ]
  }

  # --- Cleanup ---
  provisioner "shell" {
    inline = [
      "set -eux",
      "sudo dnf clean all",
    ]
  }
}