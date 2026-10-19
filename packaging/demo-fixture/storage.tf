# Demo bucket with no encryption, no versioning and no public-access block.
resource "aws_s3_bucket" "reports" {
  bucket = "terramind-demo-reports"
}

resource "aws_s3_bucket_acl" "reports" {
  bucket = aws_s3_bucket.reports.id
  acl    = "public-read" # BAD
}
