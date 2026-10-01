# Valid sibling fixture: analysis must continue after the malformed file.
resource "aws_security_group" "valid" {
  name = "valid-sibling"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
