resource "aws_lb" "this" {
  name               = local.name
  load_balancer_type = "application"
  internal           = false
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  drop_invalid_header_fields = true
  # A request that outlives the 30s Anthropic timeout has already failed inside the app.
  idle_timeout = 60
}

resource "aws_lb_target_group" "app" {
  name        = local.name
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip" # awsvpc networking: targets are task addresses, not instances
  vpc_id      = aws_vpc.this.id

  # /api/health is the same check the container's own HEALTHCHECK runs; it reports the
  # dependencies rather than just that the process is up.
  health_check {
    path                = "/api/health"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  # Enough for `alembic upgrade head` plus RDKit's import on a cold task.
  deregistration_delay = 20
}

resource "aws_acm_certificate" "this" {
  domain_name       = var.hostname
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# With a hosted zone, validation is Terraform's job and the apply waits for the certificate.
# Without one, `terraform output certificate_validation_record` prints what to add by hand.
resource "aws_route53_record" "validation" {
  for_each = var.route53_zone_id == "" ? {} : {
    for option in aws_acm_certificate.this.domain_validation_options :
    option.domain_name => option
  }

  zone_id         = var.route53_zone_id
  name            = each.value.resource_record_name
  type            = each.value.resource_record_type
  records         = [each.value.resource_record_value]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "this" {
  count                   = var.route53_zone_id == "" ? 0 : 1
  certificate_arn         = aws_acm_certificate.this.arn
  validation_record_fqdns = [for record in aws_route53_record.validation : record.fqdn]
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn = (
    var.route53_zone_id == ""
    ? aws_acm_certificate.this.arn
    : aws_acm_certificate_validation.this[0].certificate_arn
  )

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

# Plain HTTP exists only to send a browser to HTTPS; nothing is served over it.
resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      protocol    = "HTTPS"
      port        = "443"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_route53_record" "app" {
  count   = var.route53_zone_id == "" ? 0 : 1
  zone_id = var.route53_zone_id
  name    = var.hostname
  type    = "A"

  alias {
    name                   = aws_lb.this.dns_name
    zone_id                = aws_lb.this.zone_id
    evaluate_target_health = true
  }
}
