# Intentionally insecure fixture: public RDS with backups disabled.
resource "aws_db_instance" "insecure_db" {
  identifier              = "insecure-db"
  engine                  = "postgres"
  instance_class          = "db.t3.micro"
  allocated_storage       = 20
  username                = "appuser"
  password                = "CorrectHorseBatteryStaple123!"
  publicly_accessible     = true
  storage_encrypted       = false
  backup_retention_period = 0
  multi_az                = false
  deletion_protection     = false
  skip_final_snapshot     = true
}
