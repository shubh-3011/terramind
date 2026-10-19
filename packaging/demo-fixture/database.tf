# Demo database: unencrypted, publicly reachable, no backups, no deletion protection.
resource "aws_db_instance" "orders" {
  identifier             = "terramind-demo-orders"
  engine                 = "postgres"
  engine_version         = "16"
  instance_class         = "db.m5.large"
  allocated_storage      = 100
  storage_encrypted      = false # BAD
  publicly_accessible    = true  # BAD
  backup_retention_period = 0    # BAD
  deletion_protection    = false
  skip_final_snapshot    = true
  username               = "demo"
  password               = "demo-not-a-real-password" # BAD: literal secret
}
