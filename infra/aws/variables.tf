variable "name" {
  description = "Prefix for every resource name."
  type        = string
  default     = "askgrey"
}

variable "region" {
  description = "Region. Must be the region the documents bucket and its KMS key already live in."
  type        = string
  default     = "us-east-2"
}

variable "hostname" {
  description = "Public hostname the certificate is issued for, e.g. app.askgrey.ai."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9.-]+\\.[a-z]{2,}$", var.hostname))
    error_message = "hostname must be a bare domain name, without a scheme or path."
  }
}

variable "route53_zone_id" {
  description = <<-EOT
    Hosted zone for `hostname`. Given one, Terraform writes both the certificate validation
    record and the alias to the load balancer, and the apply blocks until the certificate is
    issued. Left empty, it prints the records for you to add at your registrar instead, and the
    HTTPS listener is created in a second apply once the certificate validates.
  EOT
  type        = string
  default     = ""
}

variable "documents_bucket" {
  description = "Existing bucket holding the encrypted papers. Created by hand; not managed here."
  type        = string
  default     = "askgrey-documents-prod"
}

variable "documents_kms_key_arn" {
  description = "ARN of the existing askgrey-documents KMS key."
  type        = string
}

variable "private_tasks_with_nat" {
  description = <<-EOT
    false (default): the task runs in a public subnet with a public address and a security group
    that allows inbound from the load balancer only, and reaches PubMed/Anthropic/S3 directly.
    true: the task runs in a private subnet behind a NAT gateway — no public address at all,
    which is the shape a diligence conversation expects, for about $33/month more.
  EOT
  type        = bool
  default     = false
}

variable "task_cpu" {
  description = "Fargate CPU units. RDKit and pdfplumber are the memory-hungry parts, not the CPU."
  type        = number
  default     = 512
}

variable "task_memory" {
  description = "Fargate memory (MiB). Below 1024 RDKit's import alone risks the OOM killer."
  type        = number
  default     = 2048
}

variable "desired_count" {
  description = "Task count. 1 means a deploy has a gap; 2 costs twice and rolls without one."
  type        = number
  default     = 1
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  description = "RDS storage (GiB). Stored papers are in S3, so this holds rows and audit events."
  type        = number
  default     = 20
}

variable "db_backup_retention_days" {
  description = "Automated backup retention. 0 disables backups and is not a production value."
  type        = number
  default     = 7
}

variable "log_retention_days" {
  description = "CloudWatch retention for the task's logs."
  type        = number
  default     = 30
}

variable "image_tag" {
  description = "Tag in the ECR repository to run. The deploy workflow overrides this per commit."
  type        = string
  default     = "latest"
}

variable "llm_daily_call_budget" {
  description = "Hard ceiling on Claude calls per account per day."
  type        = number
  default     = 250
}

variable "llm_daily_cost_alert_usd" {
  description = "Metered spend that logs one warning per day. 0 disables the alert."
  type        = number
  default     = 25
}

variable "invite_email_sender" {
  description = "SES-verified From address for workspace invitations. Blank mails nothing."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags applied to everything, so the bill can be read by app."
  type        = map(string)
  default     = { app = "askgrey" }
}
