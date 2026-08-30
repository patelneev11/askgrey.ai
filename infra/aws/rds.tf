# --- database --------------------------------------------------------------------------------

resource "aws_db_subnet_group" "this" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "random_password" "db" {
  length  = 40
  special = false # a URL-safe password keeps DATABASE_URL from needing percent-encoding
}

resource "aws_db_instance" "this" {
  identifier     = local.name
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_allocated_storage * 5 # autoscale rather than fill up silently
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "askgrey"
  username = "askgrey"
  password = random_password.db.result
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false

  backup_retention_period    = var.db_backup_retention_days
  backup_window              = "07:00-07:30"
  maintenance_window         = "sun:08:00-sun:08:30"
  auto_minor_version_upgrade = true

  # Real user workspaces: a destroy must leave a copy behind and a delete must be deliberate.
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.name}-final"

  performance_insights_enabled = false # not free on t4g.micro-class usage patterns worth paying for yet
  copy_tags_to_snapshot        = true
  apply_immediately            = false
}
