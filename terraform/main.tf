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
  count             = 3
  vpc_id            = aws_vpc.geochron.id
  cidr_block        = "10.0.${count.index}.0/24"
  availability_zone = "us-east-1${["a", "b", "c"][count.index]}"
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
  count          = 3
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
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  ingress {
    from_port   = 8081
    to_port     = 8081
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

resource "aws_iam_role_policy_attachment" "s3_access" {
  role       = aws_iam_role.db_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}

resource "aws_iam_role_policy_attachment" "sqs_access" {
  role       = aws_iam_role.db_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSQSFullAccess"
}

resource "aws_iam_role_policy_attachment" "sns_access" {
  role       = aws_iam_role.db_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSNSFullAccess"
}

resource "aws_iam_instance_profile" "db_node" {
  name = "ameyaDB-node-profile"
  role = aws_iam_role.db_node.name
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "ameyaDB" {
  bucket        = "ameyadb-storage-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
  tags          = { Name = "ameyaDB-storage" }
}

resource "aws_sns_topic" "replication" {
  name = "ameyaDB-replication"
  tags = { Name = "ameyaDB-replication" }
}

resource "aws_sqs_queue" "replication" {
  count                      = 3
  name                       = "ameyaDB-replication-node-${count.index}"
  visibility_timeout_seconds = 30
  tags                       = { Name = "ameyaDB-replication-node-${count.index}" }
}

resource "aws_sqs_queue_policy" "replication" {
  count     = 3
  queue_url = aws_sqs_queue.replication[count.index].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.replication[count.index].arn
      Condition = {
        ArnEquals = {
          "aws:SourceArn" = aws_sns_topic.replication.arn
        }
      }
    }]
  })
}

resource "aws_sns_topic_subscription" "replication" {
  count     = 3
  topic_arn = aws_sns_topic.replication.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.replication[count.index].arn
}

resource "aws_instance" "db_node" {
  count                  = 3
  ami                    = "ami-0c4d8a7fe320af2e0"
  instance_type          = "t3.micro"
  subnet_id              = aws_subnet.private[count.index].id
  key_name               = aws_key_pair.ameyaDB.key_name
  iam_instance_profile   = aws_iam_instance_profile.db_node.name
  vpc_security_group_ids = [aws_security_group.db_nodes.id]

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  tags = { Name = "ameyaDB-node-${count.index}" }
}

resource "aws_lb" "internal" {
  name               = "ameyaDB-internal-nlb"
  internal           = true
  load_balancer_type = "network"
  subnets            = aws_subnet.private[*].id
  tags               = { Name = "ameyaDB-internal-nlb" }
}

resource "aws_route53_zone" "private" {
  name = "ameyadb.internal"
  vpc {
    vpc_id = aws_vpc.geochron.id
  }
}

resource "aws_route53_record" "db_node" {
  count   = 3
  zone_id = aws_route53_zone.private.zone_id
  name    = "node-${count.index}.ameyadb.internal"
  type    = "A"
  ttl     = 60
  records = [aws_instance.db_node[count.index].private_ip]
}

output "node_ips" {
  value = aws_instance.db_node[*].private_ip
}

output "sns_topic_arn" {
  value = aws_sns_topic.replication.arn
}

output "replication_queue_urls" {
  value = aws_sqs_queue.replication[*].url
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