variable "region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "ssh_cidr" {
  description = "Trusted office CIDR allowed to reach the app tier over SSH"
  type        = string
  default     = "203.0.113.0/24"
}

variable "ami_id" {
  description = "AMI used by the application launch template"
  type        = string
  default     = "ami-0123456789abcdef0"
}

variable "certificate_arn" {
  description = "ACM certificate ARN for the HTTPS listener"
  type        = string
  default     = "arn:aws:acm:us-east-1:123456789012:certificate/11111111-2222-3333-4444-555555555555"
}

variable "db_username" {
  description = "Master username for the application database"
  type        = string
  default     = "appuser"
}

variable "db_password" {
  description = "Master password for the application database"
  type        = string
  sensitive   = true
}

variable "bucket_name" {
  description = "Globally unique name for the application data bucket"
  type        = string
  default     = "terramind-app-data-secure"
}

variable "tags" {
  description = "Tags applied to every supported resource"
  type        = map(string)
  default = {
    Project     = "terramind"
    Environment = "production"
    ManagedBy   = "terraform"
  }
}
