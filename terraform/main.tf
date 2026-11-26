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

variable "nat_enabled" {
  type    = bool
  default = true
}

resource "aws_eip" "nat" {
  count  = var.nat_enabled ? 1 : 0
  domain = "vpc"
}

resource "aws_nat_gateway" "geochron" {
  count         = var.nat_enabled ? 1 : 0
  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public.id
  tags          = { Name = "ameyaDB-nat" }
}

moved {
  from = aws_eip.nat
  to   = aws_eip.nat[0]
}

moved {
  from = aws_nat_gateway.geochron
  to   = aws_nat_gateway.geochron[0]
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
  dynamic "route" {
    for_each = aws_nat_gateway.geochron[*].id
    content {
      cidr_block     = "0.0.0.0/0"
      nat_gateway_id = route.value
    }
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

  ingress {
    from_port   = 8080
    to_port     = 8084
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  ingress {
    from_port   = 7000
    to_port     = 7000
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  ingress {
    from_port   = 9000
    to_port     = 9001
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

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

  depends_on = [aws_route_table.private]

  user_data = <<-EOF
#!/bin/bash
set -x
exec >> /var/log/user-data.log 2>&1

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

VOL_UUID=$(blkid -s UUID -o value "$DEV")
if ! grep -q "$VOL_UUID" /etc/fstab; then
  echo "UUID=$VOL_UUID /var/log/ameyaDB ext4 defaults,nofail 0 2" >> /etc/fstab
fi

mkdir -p /var/log/ameyaDB/server
chown -R ec2-user:ec2-user /var/log/ameyaDB

command -v iptables >/dev/null 2>&1 || dnf install -y iptables || yum install -y iptables

if [ ! -e /dev/ptp_ena ]; then
  sed -i 's|^refclock PHC|#refclock PHC|' /etc/chrony.conf
  if ! grep -q '169.254.169.123' /etc/chrony.conf; then
    echo 'server 169.254.169.123 prefer iburst minpoll 4 maxpoll 4' >> /etc/chrony.conf
  fi
  systemctl restart chronyd
fi

mkdir -p /var/log/clockbound
sed -i 's|^ExecStart=.*|ExecStart=/usr/bin/clockbound|' /etc/systemd/system/clockbound.service
systemctl daemon-reload

if ! grep -q 'ConditionPathExists=/dev/vmclock0' /etc/systemd/system/clockbound.service; then
  sed -i '/^\[Unit\]/a ConditionPathExists=/dev/vmclock0' /etc/systemd/system/clockbound.service
fi
systemctl daemon-reload
systemctl enable --now clockbound.service || true

cat > /usr/local/bin/build_ameyaDB.sh << 'SCRIPT'
#!/bin/bash
set -e
rm -rf /home/ec2-user/ameyaDB
for i in $(seq 1 30); do
  git clone --depth 1 https://github.com/uhhmeya/ameyaDB.git /home/ec2-user/ameyaDB && break
  rm -rf /home/ec2-user/ameyaDB
  sleep 5
done
test -d /home/ec2-user/ameyaDB/.git
mkdir -p /home/ec2-user/ameyaDB/engine/src/output/EXEC
cd /home/ec2-user/ameyaDB/engine/src/server
g++ -std=c++20 -O2 -pthread -o /home/ec2-user/ameyaDB/engine/src/output/EXEC/server main.cpp handlers.cpp walsnap.cpp threads.cpp raft.cpp -lclockbound || {
  echo '{"node":${count.index},"type":"compile","msg":"failed"}' > /dev/tcp/10.0.100.70/9001
  exit 1
}

install -m 0755 /home/ec2-user/ameyaDB/engine/src/scripts/ameyaDB-allow.sh /usr/local/bin/ameyaDB-allow.sh
install -m 0755 /home/ec2-user/ameyaDB/engine/src/scripts/ameyaDB-crash.sh /usr/local/bin/ameyaDB-crash.sh

echo 'ec2-user ALL=(root) NOPASSWD: /usr/local/bin/ameyaDB-allow.sh, /usr/local/bin/ameyaDB-crash.sh, /usr/bin/systemd-run' > /etc/sudoers.d/ameyaDB-net
chmod 0440 /etc/sudoers.d/ameyaDB-net
SCRIPT
chmod +x /usr/local/bin/build_ameyaDB.sh

cat > /etc/systemd/system/ameyaDB-build.service << 'UNIT'
[Unit]
Description=ameyaDB build (once per boot)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/build_ameyaDB.sh

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/ameyaDB.service << 'UNIT'
[Unit]
Description=ameyaDB node
After=network-online.target clockbound.service ameyaDB-build.service
Wants=network-online.target
Wants=clockbound.service
Requires=ameyaDB-build.service
RequiresMountsFor=/var/log/ameyaDB
StartLimitIntervalSec=0

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/var/log/ameyaDB/server
ExecStartPre=+/usr/local/bin/ameyaDB-allow.sh ${count.index} all
ExecStart=/home/ec2-user/ameyaDB/engine/src/output/EXEC/server ${count.index}
Restart=always
RestartSec=1

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now ameyaDB-build.service ameyaDB.service
  EOF

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

output "bastion_instance_id" {
  value = aws_instance.bastion.id
}