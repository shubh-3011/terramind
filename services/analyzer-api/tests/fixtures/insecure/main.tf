# Security Group
resource "aws_security_group" "main" {
  name        = "${var.name_prefix}-sg"
  description = var.description

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port       = 22
    to_port         = 22
    protocol        = "tcp"
    cidr_blocks     = ["10.0.0.0/16"] # Assuming this is the allowed IP range for SSH access
  }
}

variable "description" {
  description = "Auto-declared by TerraMind because the draft referenced var.description without declaring it; review the type and value."
  default     = null
}

variable "name_prefix" {
  description = "Auto-declared by TerraMind because the draft referenced var.name_prefix without declaring it; review the type and value."
  default     = null
}
