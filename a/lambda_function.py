import boto3, zipfile, io, os, time, json, subprocess, shutil, sys

REGION = "us-east-1"
BASE_NAME = "image-compression"

# AWS clients
s3_client = boto3.client("s3", region_name=REGION)
iam_client = boto3.client("iam")
sns_client = boto3.client("sns")
lambda_client = boto3.client("lambda", region_name=REGION)
sts_client = boto3.client("sts")

ACCOUNT_ID = sts_client.get_caller_identity()["Account"]

# -----------------------------
# 1. Prompt for SNS emails
# -----------------------------
emails = input("Enter comma-separated email addresses for SNS notifications: ").split(",")

# -----------------------------
# 2. Generate unique resource names
# -----------------------------
timestamp = int(time.time())
source_bucket = f"{BASE_NAME}-source-{timestamp}"
target_bucket = f"{BASE_NAME}-target-{timestamp}"
sns_topic_name = f"{BASE_NAME}-topic-{timestamp}"
lambda_name = f"{BASE_NAME}-lambda-{timestamp}"
lambda_role_name = f"{BASE_NAME}-role-{timestamp}"

# -----------------------------
# 3. Create S3 buckets (region-aware)
# -----------------------------
print("\nCreating S3 buckets...")
if REGION == "us-east-1":
    s3_client.create_bucket(Bucket=source_bucket)
    s3_client.create_bucket(Bucket=target_bucket)
else:
    s3_client.create_bucket(Bucket=source_bucket, CreateBucketConfiguration={"LocationConstraint": REGION})
    s3_client.create_bucket(Bucket=target_bucket, CreateBucketConfiguration={"LocationConstraint": REGION})
print(f"Buckets created: {source_bucket}, {target_bucket}")

# -----------------------------
# 4. Create SNS topic and subscribe emails
# -----------------------------
sns_topic_arn = sns_client.create_topic(Name=sns_topic_name)["TopicArn"]
for email in emails:
    email = email.strip()
    if email:
        sns_client.subscribe(TopicArn=sns_topic_arn, Protocol="email", Endpoint=email)
        print(f"Subscribed {email} to SNS topic")

# -----------------------------
# 5. Create IAM role for Lambda
# -----------------------------
trust_policy = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]
}
role = iam_client.create_role(RoleName=lambda_role_name, AssumeRolePolicyDocument=json.dumps(trust_policy))
time.sleep(10)
iam_client.attach_role_policy(RoleName=lambda_role_name, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")

# Inline policy for S3 and SNS
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

# -----------------------------
# 6. Prepare Lambda package with dependencies
# -----------------------------
print("Installing dependencies and creating Lambda package...")
package_dir = "package_temp"
if os.path.exists(package_dir):
    shutil.rmtree(package_dir)
os.makedirs(package_dir)

# Install dependencies locally into package_dir
subprocess.check_call([sys.executable, "-m", "pip", "install", "boto3", "Pillow", "-t", package_dir])

# Copy lambda_function.py into package_dir
shutil.copy("lambda_function.py", package_dir)

# Create zip
zip_path = "lambda_package.zip"
shutil.make_archive("lambda_package", 'zip', package_dir)

# -----------------------------
# 7. Create Lambda function
# -----------------------------
with open(zip_path, 'rb') as f:
    zip_bytes = f.read()

lambda_response = lambda_client.create_function(
    FunctionName=lambda_name,
    Runtime="python3.11",
    Role=f"arn:aws:iam::{ACCOUNT_ID}:role/{lambda_role_name}",
    Handler="lambda_function.lambda_handler",
    Code={"ZipFile": zip_bytes},
    Environment={"Variables":{"TARGET_BUCKET":target_bucket,"SNS_TOPIC_ARN":sns_topic_arn}},
)
lambda_arn = lambda_response["FunctionArn"]

# -----------------------------
# 8. Wait for propagation and add S3 permission
# -----------------------------
print("Waiting 10 seconds for Lambda propagation...")
time.sleep(10)

lambda_client.add_permission(
    FunctionName=lambda_name,
    StatementId=f"s3-invoke-{timestamp}",
    Action="lambda:InvokeFunction",
    Principal="s3.amazonaws.com",
    SourceArn=f"arn:aws:s3:::{source_bucket}"
)

time.sleep(5)

# -----------------------------
# 9. Add S3 trigger
# -----------------------------
notification_configuration = {
    "LambdaFunctionConfigurations":[{"LambdaFunctionArn":lambda_arn,"Events":["s3:ObjectCreated:Put"]}]
}
s3_client.put_bucket_notification_configuration(
    Bucket=source_bucket,
    NotificationConfiguration=notification_configuration
)

# Cleanup local temp files
shutil.rmtree(package_dir)
os.remove(zip_path)

# -----------------------------
# 10. Deployment complete
# -----------------------------
print("\nDeployment Complete!")
print(f"Source Bucket: {source_bucket}")
print(f"Target Bucket: {target_bucket}")
print(f"SNS Topic ARN: {sns_topic_arn}")
print(f"Lambda Function ARN: {lambda_arn}")
print("Please confirm your SNS subscriptions via email!")
