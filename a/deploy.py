import boto3
import os
import zipfile
import shutil
import subprocess
import sys
import time
import json

REGION = "us-east-1"
BASE_NAME = "csv-to-json"
LAMBDA_FILENAME = "lambda_csv_to_json.py"

# -----------------------------
# Step 0: Initialize AWS clients
# -----------------------------
print("Initializing AWS clients...")
s3_client = boto3.client("s3", region_name=REGION)
iam_client = boto3.client("iam")
sns_client = boto3.client("sns")
lambda_client = boto3.client("lambda", region_name=REGION)
sts_client = boto3.client("sts")

ACCOUNT_ID = sts_client.get_caller_identity()["Account"]
print(f"AWS Account: {ACCOUNT_ID}\n")

# -----------------------------
# Step 1: Prompt for SNS subscribers
# -----------------------------
emails = input("Enter comma-separated email addresses for SNS notifications: ").split(",")

# -----------------------------
# Step 2: Generate unique resource names
# -----------------------------
timestamp = int(time.time())
source_bucket = f"{BASE_NAME}-source-{timestamp}"
target_bucket = f"{BASE_NAME}-target-{timestamp}"
sns_topic_name = f"{BASE_NAME}-topic-{timestamp}"
lambda_name = f"{BASE_NAME}-lambda-{timestamp}"
lambda_role_name = f"{BASE_NAME}-role-{timestamp}"

print("Resource names:")
print(f"Source Bucket: {source_bucket}")
print(f"Target Bucket: {target_bucket}")
print(f"SNS Topic: {sns_topic_name}")
print(f"Lambda Function: {lambda_name}")
print(f"IAM Role: {lambda_role_name}\n")

# -----------------------------
# Step 3: Create S3 buckets
# -----------------------------
print("Creating S3 buckets...")
for bucket in [source_bucket, target_bucket]:
    if REGION == "us-east-1":
        s3_client.create_bucket(Bucket=bucket)
    else:
        s3_client.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": REGION})
    print(f"Created bucket: {bucket}")
print("S3 buckets created.\n")

# -----------------------------
# Step 4: Create SNS topic and subscribe emails
# -----------------------------
print("Creating SNS topic...")
sns_topic_arn = sns_client.create_topic(Name=sns_topic_name)["TopicArn"]
for email in emails:
    email = email.strip()
    if email:
        sns_client.subscribe(TopicArn=sns_topic_arn, Protocol="email", Endpoint=email)
        print(f"Subscribed {email} to SNS topic")
print("SNS topic created.\n")

# -----------------------------
# Step 5: Create IAM role for Lambda
# -----------------------------
print("Creating IAM role for Lambda...")
trust_policy = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]
}
role = iam_client.create_role(RoleName=lambda_role_name, AssumeRolePolicyDocument=json.dumps(trust_policy))
time.sleep(10)
iam_client.attach_role_policy(RoleName=lambda_role_name, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")

inline_policy = {
    "Version": "2012-10-17",
    "Statement": [
        {"Effect": "Allow",
         "Action": ["s3:GetObject","s3:PutObject"],
         "Resource":[f"arn:aws:s3:::{source_bucket}/*", f"arn:aws:s3:::{target_bucket}/*"]},
        {"Effect": "Allow",
         "Action":["sns:Publish"],
         "Resource":[sns_topic_arn]}
    ]
}
iam_client.put_role_policy(RoleName=lambda_role_name, PolicyName=f"{BASE_NAME}-policy", PolicyDocument=json.dumps(inline_policy))
print("IAM role created and policies attached.\n")

# -----------------------------
# Step 6: Prepare Lambda package
# -----------------------------
print("Packaging Lambda function...")
package_dir = "lambda_package"
if os.path.exists(package_dir):
    shutil.rmtree(package_dir)
os.makedirs(package_dir)

# Copy Lambda code
shutil.copy(LAMBDA_FILENAME, package_dir)

# Create zip package
zip_path = "lambda_package.zip"
shutil.make_archive("lambda_package", 'zip', package_dir)
print("Lambda package created.\n")

# -----------------------------
# Step 7: Create Lambda function
# -----------------------------
with open(zip_path, 'rb') as f:
    zip_bytes = f.read()

lambda_response = lambda_client.create_function(
    FunctionName=lambda_name,
    Runtime="python3.11",
    Role=f"arn:aws:iam::{ACCOUNT_ID}:role/{lambda_role_name}",
    Handler=f"{LAMBDA_FILENAME.rsplit('.',1)[0]}.lambda_handler",
    Code={"ZipFile": zip_bytes},
    Environment={"Variables":{"TARGET_BUCKET":target_bucket,"SNS_TOPIC_ARN":sns_topic_arn}}
)
lambda_arn = lambda_response["FunctionArn"]
print(f"Lambda function created: {lambda_arn}\n")

# -----------------------------
# Step 8: Wait for Lambda propagation
# -----------------------------
print("Waiting 10 seconds for Lambda propagation...")
time.sleep(10)

# -----------------------------
# Step 9: Add S3 invoke permission
# -----------------------------
lambda_client.add_permission(
    FunctionName=lambda_name,
    StatementId=f"s3-invoke-{timestamp}",
    Action="lambda:InvokeFunction",
    Principal="s3.amazonaws.com",
    SourceArn=f"arn:aws:s3:::{source_bucket}"
)
print("S3 permission added to Lambda.\n")

# -----------------------------
# Step 10: Add S3 trigger
# -----------------------------
notification_configuration = {
    "LambdaFunctionConfigurations":[{"LambdaFunctionArn":lambda_arn,"Events":["s3:ObjectCreated:*"]}]
}
s3_client.put_bucket_notification_configuration(
    Bucket=source_bucket,
    NotificationConfiguration=notification_configuration
)
print("S3 trigger configured.\n")

# -----------------------------
# Step 11: Cleanup local files
# -----------------------------
shutil.rmtree(package_dir)
os.remove(zip_path)
print("Local temporary files cleaned up.\n")

# -----------------------------
# Step 12: Deployment Complete
# -----------------------------
print("Deployment complete!")
print(f"Source Bucket: {source_bucket}")
print(f"Target Bucket: {target_bucket}")
print(f"SNS Topic ARN: {sns_topic_arn}")
print(f"Lambda Function ARN: {lambda_arn}")
print("Please confirm your SNS subscriptions via email!")
