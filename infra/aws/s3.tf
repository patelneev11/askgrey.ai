# --- document bucket policy ------------------------------------------------------------------

# The bucket itself predates this stack and is not managed here; only its policy is, so the
# rule below can be read and reviewed alongside the rest of the infrastructure.
#
# Public access is already blocked at the account and bucket level. What the block does not
# cover is a request from an authorized principal arriving over plain HTTP, where the object
# and its presigned URL cross the network in the clear. Deny beats allow, so this holds
# whatever an IAM policy grants.
data "aws_iam_policy_document" "documents" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      "arn:aws:s3:::${var.documents_bucket}",
      "arn:aws:s3:::${var.documents_bucket}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "documents" {
  bucket = var.documents_bucket
  policy = data.aws_iam_policy_document.documents.json
}
