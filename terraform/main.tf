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

# Persistent data volumes — survive EC2 termination for chaos testing
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

  user_data = <<-EOF
    #!/bin/bash
    if ! blkid /dev/xvdf; then
      mkfs -t ext4 /dev/xvdf
    fi
    mkdir -p /var/log/ameyaDB
    mount /dev/xvdf /var/log/ameyaDB
    echo "/dev/xvdf /var/log/ameyaDB ext4 defaults,nofail 0 2" >> /etc/fstab
  EOF

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

# Bastion
resource "aws_instance" "bastion" {
  ami                         = "ami-0e10497160c48e829"
  instance_type               = "t3.micro"
  subnet_id                   = aws_subnet.public.id
  key_name                    = aws_key_pair.ameyaDB.key_name
  associate_public_ip_address = true
  vpc_security_group_ids      = [aws_security_group.db_nodes.id]

  tags = { Name = "ameyaDB-bastion" }
}

output "bastion_ip" {
  value = aws_instance.bastion.public_ip
}