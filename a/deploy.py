import boto3, zipfile, io, os, time, json

REGION = "us-east-1"  # Change to your preferred region
BASE_NAME = "image-compression"

# AWS clients
s3_client = boto3.client("s3", region_name=REGION)
iam_client = boto3.client("iam")
sns_client = boto3.client("sns")
lambda_client = boto3.client("lambda", region_name=REGION)
sts_client = boto3.client("sts")

ACCOUNT_ID = sts_client.get_caller_identity()["Account"]

# 1. Prompt for emails
emails = input("Enter comma-separated email addresses for SNS notifications: ").split(",")

# 2. Generate unique resource names
timestamp = int(time.time())
source_bucket = f"{BASE_NAME}-source-{timestamp}"
target_bucket = f"{BASE_NAME}-target-{timestamp}"
sns_topic_name = f"{BASE_NAME}-topic-{timestamp}"
lambda_name = f"{BASE_NAME}-lambda-{timestamp}"
lambda_role_name = f"{BASE_NAME}-role-{timestamp}"

# 3. Create S3 buckets (region-aware)
print("\nCreating S3 buckets...")
if REGION == "us-east-1":
    s3_client.create_bucket(Bucket=source_bucket)
    s3_client.create_bucket(Bucket=target_bucket)
else:
    s3_client.create_bucket(
        Bucket=source_bucket,
        CreateBucketConfiguration={"LocationConstraint": REGION}
    )
    s3_client.create_bucket(
        Bucket=target_bucket,
        CreateBucketConfiguration={"LocationConstraint": REGION}
    )
print(f"Buckets created: {source_bucket}, {target_bucket}")

# 4. Create SNS topic
sns_topic_arn = sns_client.create_topic(Name=sns_topic_name)["TopicArn"]
for email in emails:
    email = email.strip()
    if email:
        sns_client.subscribe(TopicArn=sns_topic_arn, Protocol="email", Endpoint=email)
        print(f"Subscribed {email} to SNS topic")

# 5. Create IAM role for Lambda
trust_policy = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]
}
role = iam_client.create_role(RoleName=lambda_role_name, AssumeRolePolicyDocument=json.dumps(trust_policy))
time.sleep(10)  # wait for role propagation
iam_client.attach_role_policy(RoleName=lambda_role_name, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")

# Inline policy for S3 & SNS access
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

# 6. Package Lambda function
zip_buffer = io.BytesIO()
with zipfile.ZipFile(zip_buffer, 'w') as zf:
    zf.write("lambda_function.py", arcname="lambda_function.py")
zip_buffer.seek(0)

# 7. Create Lambda function
lambda_response = lambda_client.create_function(
    FunctionName=lambda_name,
    Runtime="python3.11",
    Role=f"arn:aws:iam::{ACCOUNT_ID}:role/{lambda_role_name}",
    Handler="lambda_function.lambda_handler",
    Code={"ZipFile": zip_buffer.read()},
    Environment={"Variables":{"TARGET_BUCKET":target_bucket,"SNS_TOPIC_ARN":sns_topic_arn}},
)
lambda_arn = lambda_response["FunctionArn"]

# 8. Add S3 trigger to Lambda
notification_configuration = {
    "LambdaFunctionConfigurations":[{"LambdaFunctionArn":lambda_arn,"Events":["s3:ObjectCreated:Put"]}]
}
s3_client.put_bucket_notification_configuration(
    Bucket=source_bucket,
    NotificationConfiguration=notification_configuration
)

print("\nDeployment Complete!")
print(f"Source Bucket: {source_bucket}")
print(f"Target Bucket: {target_bucket}")
print(f"SNS Topic ARN: {sns_topic_arn}")
print(f"Lambda Function ARN: {lambda_arn}")
print("Please confirm your SNS subscriptions via email!")
