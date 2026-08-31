output "hostname" {
  description = "Where the app will answer once DNS points at the load balancer."
  value       = "https://${var.hostname}"
}

output "load_balancer_dns_name" {
  description = "Target for the CNAME (or the alias, if Terraform owns the zone)."
  value       = aws_lb.this.dns_name
}

output "certificate_validation_record" {
  description = "Add this at your registrar when Terraform does not own the zone."
  value = var.route53_zone_id != "" ? {} : {
    for option in aws_acm_certificate.this.domain_validation_options :
    option.domain_name => {
      name  = option.resource_record_name
      type  = option.resource_record_type
      value = option.resource_record_value
    }
  }
}

output "ecr_repository_url" {
  description = "Push the image here; the deploy workflow reads this from the same name."
  value       = aws_ecr_repository.app.repository_url
}

output "ecs_cluster" {
  value = aws_ecs_cluster.this.name
}

output "ecs_service" {
  value = aws_ecs_service.app.name
}

output "database_endpoint" {
  description = "Reachable from the tasks only; there is no public route to it."
  value       = aws_db_instance.this.address
}

output "secrets_to_fill_in" {
  description = "Created empty on purpose: paste the values, then redeploy."
  value = {
    anthropic_api_key = aws_secretsmanager_secret.anthropic_api_key.name
    uspto_odp_api_key = aws_secretsmanager_secret.uspto_api_key.name
  }
}

output "monthly_cost_note" {
  description = "What the shape of this deployment costs, so a change of mind is priced."
  value       = var.private_tasks_with_nat ? "private tasks behind a NAT gateway: about $33/month more than the public-subnet shape" : "public-subnet tasks, inbound from the load balancer only: no NAT gateway to pay for"
}
