# Intentionally insecure fixture: public RDP and unrestricted egress.
resource "aws_security_group" "insecure_app" {
  name        = "insecure-app"
  description = "Deliberately insecure security group for integration tests"

  ingress {
    description = "RDP open to the public internet"
    from_port   = 3389
    to_port     = 3389
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Unrestricted egress to the public internet"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
