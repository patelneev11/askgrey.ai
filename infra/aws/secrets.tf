# --- secrets ---------------------------------------------------------------------------------

# The app never reads a committed file: every value below is injected by ECS as an environment
# variable resolved from Secrets Manager at task start, so rotation is a redeploy.

resource "random_password" "jwt_secret" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "jwt_secret" {
  name        = "${local.name}/jwt-secret"
  description = "Signs access tokens. Rotating it signs everybody out, which is the intended blast radius."
}

resource "aws_secretsmanager_secret_version" "jwt_secret" {
  secret_id     = aws_secretsmanager_secret.jwt_secret.id
  secret_string = random_password.jwt_secret.result
}

resource "aws_secretsmanager_secret" "database_url" {
  name        = "${local.name}/database-url"
  description = "Postgres URL for the app and for alembic."
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id = aws_secretsmanager_secret.database_url.id
  secret_string = format(
    "postgresql+psycopg://%s:%s@%s:%s/%s",
    aws_db_instance.this.username,
    random_password.db.result,
    aws_db_instance.this.address,
    aws_db_instance.this.port,
    aws_db_instance.this.db_name,
  )
}

# Placeholders Terraform creates but never writes a value into: the Anthropic key is yours to
# paste (console, or `aws secretsmanager put-secret-value`), and a key in state is a key in a
# file. `ignore_changes` keeps a later apply from reverting what you put there.
resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name        = "${local.name}/anthropic-api-key"
  description = "Set by hand. Without it the app falls back to its rule-based translator."
}

resource "aws_secretsmanager_secret_version" "anthropic_api_key" {
  secret_id     = aws_secretsmanager_secret.anthropic_api_key.id
  secret_string = "unset"

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "uspto_api_key" {
  name        = "${local.name}/uspto-odp-api-key"
  description = "Set by hand. Without it the patent landscape reports its source unavailable."
}

resource "aws_secretsmanager_secret_version" "uspto_api_key" {
  secret_id     = aws_secretsmanager_secret.uspto_api_key.id
  secret_string = "unset"

  lifecycle {
    ignore_changes = [secret_string]
  }
}
