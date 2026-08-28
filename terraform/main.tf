terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_vpc" "geochron" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags = { Name = "ameyaDB-vpc" }
}

resource "aws_internet_gateway" "geochron" {
  vpc_id = aws_vpc.geochron.id
  tags   = { Name = "ameyaDB-igw" }
}

resource "aws_subnet" "private" {
  count             = 5
  vpc_id            = aws_vpc.geochron.id
  cidr_block        = "10.0.${count.index}.0/24"
  availability_zone = "us-east-1${["a", "b", "c", "d", "f"][count.index]}"
  tags = { Name = "ameyaDB-private-${count.index}" }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.geochron.id
  cidr_block              = "10.0.100.0/24"
  availability_zone       = "us-east-1a"
  map_public_ip_on_launch = true
  tags = { Name = "ameyaDB-public" }
}

resource "aws_eip" "nat" {
  domain = "vpc"
}

resource "aws_nat_gateway" "geochron" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public.id
  tags          = { Name = "ameyaDB-nat" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.geochron.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.geochron.id
  }
  tags = { Name = "ameyaDB-public-rt" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.geochron.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.geochron.id
  }
  tags = { Name = "ameyaDB-private-rt" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = 5
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_key_pair" "ameyaDB" {
  key_name   = "ameyaDB-key"
  public_key = file("~/.ssh/ameyaDB.pub")
}

resource "aws_security_group" "db_nodes" {
  name   = "ameyaDB-nodes"
  vpc_id = aws_vpc.geochron.id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Raft peer mesh: node i listens on 8080 + i (nodes 0-4 -> 8080-8084).
  # All peer traffic (WRITE / READ / REQUEST_VOTE) is multiplexed over these.
  ingress {
    from_port   = 8080
    to_port     = 8084
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  # Relay: nodes dial out to relay.py (listening on the bastion, port 9000)
  # to report status. Only needs to allow traffic from inside the VPC.
  ingress {
    from_port   = 9000
    to_port     = 9000
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  # Relay WS: your browser connects here from anywhere to watch the cluster.
  # Open to the internet for now -- lock this down later (see notes).
  ingress {
    from_port   = 8765
    to_port     = 8765
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "ameyaDB-nodes-sg" }
}

resource "aws_iam_role" "db_node" {
  name = "ameyaDB-node-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_instance_profile" "db_node" {
  name = "ameyaDB-node-profile"
  role = aws_iam_role.db_node.name
}

# Persistent data volumes -- survive EC2 termination for chaos testing
resource "aws_ebs_volume" "db_node" {
  count             = 5
  availability_zone = "us-east-1${["a", "b", "c", "d", "f"][count.index]}"
  size              = 20
  type              = "gp3"
  tags = { Name = "ameyaDB-data-${count.index}" }
}

resource "aws_volume_attachment" "db_node" {
  count       = 5
  device_name = "/dev/xvdf"
  volume_id   = aws_ebs_volume.db_node[count.index].id
  instance_id = aws_instance.db_node[count.index].id

  # Never rip a mounted ext4 filesystem out from under a live instance.
  # Only matters when you run `dooby.sh --fresh`, which replaces the nodes.
  stop_instance_before_detaching = true
}

variable "db_node_ami" {
  type    = string
  default = "ami-0479cba6c062ea44e"
}

resource "aws_instance" "db_node" {
  count                  = 5
  ami                    = var.db_node_ami
  instance_type          = "m7i.large"
  subnet_id              = aws_subnet.private[count.index].id
  key_name               = aws_key_pair.ameyaDB.key_name
  iam_instance_profile   = aws_iam_instance_profile.db_node.name
  vpc_security_group_ids = [aws_security_group.db_nodes.id]

  # NOTE: every line below is flush at column 0 on purpose. Terraform's <<-
  # heredoc strips the SMALLEST indent found in the body, so a single flush
  # line (like `cat > ...`) makes the strip amount 0 and leaves the shebang
  # indented -- which stops cloud-init from recognising this as a script.
  user_data = <<-EOF
#!/bin/bash
set -x
exec >> /var/log/user-data.log 2>&1

# The EBS data volume is attached by a SEPARATE terraform resource, which
# lands ~20s AFTER this instance boots. Wait for the device instead of
# racing it. m7i is Nitro, so the kernel name is nvme1n1; /dev/xvdf only
# exists if the AMI ships the ec2-utils udev rules.
DEV=""
for i in $(seq 1 60); do
  for cand in /dev/xvdf /dev/sdf /dev/nvme1n1; do
    if [ -b "$cand" ]; then DEV="$cand"; break 2; fi
  done
  sleep 2
done
if [ -z "$DEV" ]; then
  echo "FATAL: data volume never appeared after 120s" >&2
  exit 1
fi

if ! blkid "$DEV"; then
  mkfs -t ext4 "$DEV"
fi

mkdir -p /var/log/ameyaDB
mount "$DEV" /var/log/ameyaDB

# fstab by UUID -- NVMe enumeration order is not stable across reboots.
VOL_UUID=$(blkid -s UUID -o value "$DEV")
if ! grep -q "$VOL_UUID" /etc/fstab; then
  echo "UUID=$VOL_UUID /var/log/ameyaDB ext4 defaults,nofail 0 2" >> /etc/fstab
fi

mkdir -p /var/log/ameyaDB/server
chown -R ec2-user:ec2-user /var/log/ameyaDB

# ---- time stack repair (all three are Amazon Linux 2 version skew) ----

# 1. chrony.conf points at the PTP hardware clock, but AL2's ENA driver has no
#    PTP support so /dev/ptp_ena never appears -- and chronyd treats that as
#    FATAL. Dead chronyd took clockbound down, which took ameyaDB down.
if [ ! -e /dev/ptp_ena ]; then
  sed -i 's|^refclock PHC|#refclock PHC|' /etc/chrony.conf
  if ! grep -q '169.254.169.123' /etc/chrony.conf; then
    echo 'server 169.254.169.123 prefer iburst minpoll 4 maxpoll 4' >> /etc/chrony.conf
  fi
  systemctl restart chronyd
fi

# 2. The clockbound unit baked into this AMI passes --ip, which ClockBound 1.x
#    removed when it moved from a UDP socket to shared memory (exit 2).
mkdir -p /var/log/clockbound
sed -i 's|^ExecStart=.*|ExecStart=/usr/bin/clockbound|' /etc/systemd/system/clockbound.service
systemctl daemon-reload

# 3. ClockBound 1.x enables VMClock on every non-metal EC2 instance and panics
#    (exit 101) when /dev/vmclock0 is missing. That device needs the
#    ptp_vmclock driver, absent from AL2's 4.14 kernel. `disable` alone is NOT
#    enough: ameyaDB's Wants= re-triggers a start whenever ameyaDB starts, and
#    clockbound's own Restart=on-failure then panic-loops it every 2s forever.
#    A start condition parks it quietly instead -- a failed condition is not a
#    unit failure, so no restart loop -- and it lights up automatically on an
#    AL2023 rebuild where the device exists. ameyaDB falls back to adjtimex
#    bounds either way.
if ! grep -q 'ConditionPathExists=/dev/vmclock0' /etc/systemd/system/clockbound.service; then
  sed -i '/^\[Unit\]/a ConditionPathExists=/dev/vmclock0' /etc/systemd/system/clockbound.service
fi
systemctl daemon-reload
systemctl enable --now clockbound.service || true

cat > /usr/local/bin/build_ameyaDB.sh << 'SCRIPT'
#!/bin/bash
set -e
rm -rf /home/ec2-user/ameyaDB
git clone --depth 1 https://github.com/uhhmeya/ameyaDB.git /home/ec2-user/ameyaDB
mkdir -p /home/ec2-user/ameyaDB/engine/src/output/EXEC
cd /home/ec2-user/ameyaDB/engine/src/server
g++ -std=c++20 -pthread -o /home/ec2-user/ameyaDB/engine/src/output/EXEC/server main.cpp handlers.cpp walsnap.cpp threads.cpp -lclockbound
SCRIPT
chmod +x /usr/local/bin/build_ameyaDB.sh
chown ec2-user:ec2-user /usr/local/bin/build_ameyaDB.sh

cat > /etc/systemd/system/ameyaDB.service << 'UNIT'
[Unit]
Description=ameyaDB node
After=network-online.target clockbound.service
Wants=network-online.target
# Wants=, NOT Requires=. Requires= propagates STOPS: every time clockbound
# hit its failed state systemd tore this service down with it, which is what
# the restart storm actually was. The server degrades to adjtimex bounds on
# its own when clockbound is absent.
Wants=clockbound.service
# Refuse to start if the data volume did not mount, instead of silently
# writing the WAL to the root disk (which dies with the instance).
RequiresMountsFor=/var/log/ameyaDB

[Service]
# ExecStartPre does a full git clone. Without a rate limit, a failing build
# re-clones GitHub every RestartSec forever and gets the host throttled.
# systemd 219 (Amazon Linux 2) spells this StartLimitInterval and wants it
# in [Service]; StartLimitIntervalSec in [Unit] is a systemd 230+ name and
# is silently ignored here.
StartLimitInterval=300
StartLimitBurst=5
Type=simple
User=ec2-user
WorkingDirectory=/var/log/ameyaDB/server
ExecStartPre=/usr/local/bin/build_ameyaDB.sh
ExecStart=/home/ec2-user/ameyaDB/engine/src/output/EXEC/server ${count.index}
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now ameyaDB.service
  EOF

  # Re-run user_data if the script itself changes (only takes effect on the
  # next replacement, but keeps the plan honest about drift).
  user_data_replace_on_change = false

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  tags = { Name = "ameyaDB-node-${count.index}" }
}

resource "aws_route53_zone" "private" {
  name = "ameyadb.internal"
  vpc {
    vpc_id = aws_vpc.geochron.id
  }
}

resource "aws_route53_record" "db_node" {
  count   = 5
  zone_id = aws_route53_zone.private.zone_id
  name    = "node-${count.index}.ameyadb.internal"
  type    = "A"
  ttl     = 60
  records = [aws_instance.db_node[count.index].private_ip]
}

output "node_ips" {
  value = aws_instance.db_node[*].private_ip
}

output "node_instance_ids" {
  value = join(" ", aws_instance.db_node[*].id)
}

variable "bastion_ami" {
  type    = string
  default = "ami-00bcfe7d433aa2c17"
}

resource "aws_instance" "bastion" {
  ami                    = var.bastion_ami
  instance_type          = "t3.micro"
  subnet_id              = aws_subnet.public.id
  key_name               = aws_key_pair.ameyaDB.key_name
  vpc_security_group_ids = [aws_security_group.db_nodes.id]

  tags = { Name = "ameyaDB-bastion" }
}

resource "aws_eip" "bastion" {
  domain   = "vpc"
  instance = aws_instance.bastion.id
  tags     = { Name = "ameyaDB-bastion-eip" }

  lifecycle {
    prevent_destroy = true
  }
}

output "bastion_ip" {
  value = aws_eip.bastion.public_ip
}

# dooby.sh needs this to start/stop the bastion. Without it the script has no
# way to bring the bastion back, which is exactly how it ended up stranded.
output "bastion_instance_id" {
  value = aws_instance.bastion.id
}