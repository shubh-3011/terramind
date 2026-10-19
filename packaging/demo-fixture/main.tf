terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "eu-west-1"
}

# --- Deliberately insecure demo: TerraMind should flag every one of these ---

resource "aws_security_group" "web" {
  name        = "terramind-demo-web"
  description = "Demo group with a world-open SSH port"

  ingress {
    description = "SSH from anywhere (BAD)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "web" {
  instance_type          = "t3.large"
  ami                    = "ami-0123456789abcdef0"
  vpc_security_group_ids = [aws_security_group.web.id]

  metadata_options {
    http_tokens = "optional" # IMDSv1 still allowed (BAD)
  }
}
