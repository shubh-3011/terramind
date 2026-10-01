output "alb_dns_name" {
  description = "Public DNS name of the application load balancer"
  value       = aws_lb.app.dns_name
}

output "db_endpoint" {
  description = "Connection endpoint of the application database"
  value       = aws_db_instance.main.endpoint
  sensitive   = true
}
