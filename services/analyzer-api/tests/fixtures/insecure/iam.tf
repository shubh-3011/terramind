# Intentionally insecure fixture: wildcard principal and a long-lived access key.
data "aws_iam_policy_document" "any_principal" {
  statement {
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    actions   = ["s3:GetObject"]
    resources = ["*"]
  }
}

resource "aws_iam_access_key" "ci" {
  user = "ci-deployer"
}
