# Two roles, deliberately: the execution role is what ECS itself uses to pull the image and
# resolve secrets before the container exists; the task role is what the running app can do.
# Keeping them apart means the app cannot read the secrets it was given, only use them.

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secrets" {
  statement {
    sid     = "ReadTheseSecretsOnly"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.jwt_secret.arn,
      aws_secretsmanager_secret.database_url.arn,
      aws_secretsmanager_secret.anthropic_api_key.arn,
      aws_secretsmanager_secret.uspto_api_key.arn,
    ]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

resource "aws_iam_role" "task" {
  name               = "${local.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

# The same least-privilege shape the askgrey-app user was given by hand, minus the access key:
# object actions under documents/ only, no s3:List*, so a compromised task cannot enumerate
# whose papers exist; GenerateDataKey and Decrypt on the one document key.
data "aws_iam_policy_document" "task" {
  statement {
    sid       = "DocumentObjects"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]
    resources = [local.documents_prefix_arn]
  }

  statement {
    sid       = "DocumentKey"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [var.documents_kms_key_arn]
  }

  dynamic "statement" {
    for_each = var.invite_email_sender == "" ? [] : [1]
    content {
      sid       = "InvitationMail"
      actions   = ["ses:SendEmail"]
      resources = ["*"]
      condition {
        test     = "StringEquals"
        variable = "ses:FromAddress"
        values   = [var.invite_email_sender]
      }
    }
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "documents"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}
