resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.name}"
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_cluster" "this" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "disabled" # a paid metric stream; the log group and the ALB metrics are enough here
  }
}

locals {
  # Everything non-secret. Values that differ per environment are variables; the rest matches
  # backend/.env.example, which stays the list of record.
  task_environment = [
    { name = "ENVIRONMENT", value = "production" },
    { name = "PORT", value = "8000" },
    { name = "PUBLIC_APP_URL", value = "https://${var.hostname}" },
    # Empty is correct: the API serves the SPA, so every request is same-origin.
    { name = "CORS_ORIGINS", value = "" },
    { name = "FRONTEND_DIST_DIR", value = "/app/frontend-dist" },
    # One proxy in front of the app — the load balancer — so the per-address sign-in limit keys
    # on the visitor rather than on a single shared bucket.
    { name = "TRUSTED_PROXY_HOPS", value = "1" },
    { name = "AWS_REGION", value = var.region },
    { name = "DOCUMENT_S3_BUCKET", value = var.documents_bucket },
    { name = "DOCUMENT_KMS_KEY_ID", value = var.documents_kms_key_arn },
    { name = "LLM_DAILY_CALL_BUDGET", value = tostring(var.llm_daily_call_budget) },
    { name = "LLM_DAILY_COST_ALERT_USD", value = tostring(var.llm_daily_cost_alert_usd) },
    { name = "INVITE_EMAIL_SENDER", value = var.invite_email_sender },
    { name = "LOG_JSON", value = "true" },
    { name = "RELEASE", value = var.image_tag },
  ]

  task_secrets = [
    { name = "JWT_SECRET", valueFrom = aws_secretsmanager_secret.jwt_secret.arn },
    { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.database_url.arn },
    { name = "ANTHROPIC_API_KEY", valueFrom = aws_secretsmanager_secret.anthropic_api_key.arn },
    { name = "USPTO_ODP_API_KEY", valueFrom = aws_secretsmanager_secret.uspto_api_key.arn },
  ]
}

resource "aws_ecs_task_definition" "app" {
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.task_cpu)
  memory                   = tostring(var.task_memory)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name                   = "app"
      image                  = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
      essential              = true
      portMappings           = [{ containerPort = 8000, protocol = "tcp" }]
      environment            = local.task_environment
      secrets                = local.task_secrets
      readonlyRootFilesystem = false # pdfplumber writes temporary files while parsing
      linuxParameters = {
        initProcessEnabled = true # so a stopped task's uvicorn is reaped, not orphaned
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.app.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "app"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "curl -fsS http://127.0.0.1:8000/api/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ])
}

resource "aws_ecs_service" "app" {
  name            = local.name
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets = local.task_subnet_ids
    # A public address is how a task in a public subnet reaches PubMed and Anthropic without a
    # NAT gateway; the task security group is what keeps it unreachable from outside.
    assign_public_ip = !var.private_tasks_with_nat
    security_groups  = [aws_security_group.task.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = "app"
    container_port   = 8000
  }

  # A task that fails its migration or its health check must not be counted as a good release.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  health_check_grace_period_seconds = 120
  # At desired_count = 1 this is what makes a deploy overlap rather than go down: 200% lets a
  # second task start before the old one is drained.
  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  enable_execute_command = true # `aws ecs execute-command` for a shell, instead of a bastion

  depends_on = [aws_lb_listener.https]

  lifecycle {
    # The deploy workflow registers a new task definition per commit; Terraform should not drag
    # the service back to the tag it last knew about.
    ignore_changes = [task_definition, desired_count]
  }
}
