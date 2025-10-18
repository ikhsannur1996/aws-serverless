import boto3
import os
import shutil
import zipfile
import time
import json

REGION = "us-east-1"
BASE_NAME = "csv-to-json"
LAMBDA_CODE_FILENAME = "lambda_csv_to_json.py"

# AWS clients
s3_client = boto3.client("s3", region_name=REGION)
iam_client = boto3.client("iam")
sns_client = boto3.client("sns")
lambda_client = boto3.client("lambda", region_name=REGION)
sts_client = boto3.client("sts")

ACCOUNT_ID = sts_client.get_caller_identity()["Account"]

# -----------------------------
# 1. Prompt for SNS subscribers
# -----------------------------
emails_input = input("Enter comma-separated email addresses to receive notifications: ").strip()
emails = [email.strip() for email in emails_input.split(",") if email.strip()]

if not emails:
    print("No valid email addresses provided. Exiting.")
    exit(1)

print(f"Subscribing the following emails to SNS topic: {', '.join(emails)}")

# -----------------------------
# 2. Generate resource names
# -----------------------------
timestamp = int(time.time())
source_bucket = f"{BASE_NAME}-source-{timestamp}"
target_bucket = f"{BASE_NAME}-target-{timestamp}"
sns_topic_name = f"{BASE_NAME}-topic-{timestamp}"
lambda_name = f"{BASE_NAME}-lambda-{timestamp}"
lambda_role_name = f"{BASE_NAME}-role-{timestamp}"

# -----------------------------
# 3. Create S3 buckets
# -----------------------------
for bucket in [source_bucket, target_bucket]:
    if REGION == "us-east-1":
        s3_client.create_bucket(Bucket=bucket)
    else:
        s3_client.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": REGION})
print(f"S3 buckets created: {source_bucket}, {target_bucket}")

# -----------------------------
# 4. Create SNS topic and subscribe emails
# -----------------------------
sns_topic_arn = sns_client.create_topic(Name=sns_topic_name)["TopicArn"]
for email in emails:
    sns_client.subscribe(
        TopicArn=sns_topic_arn,
        Protocol="email",
        Endpoint=email
    )
    print(f"Subscribed {email} to SNS topic. Please check inbox to confirm subscription.")

# -----------------------------
# 5. Create IAM role for Lambda
# -----------------------------
trust_policy = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]
}
role = iam_client.create_role(RoleName=lambda_role_name, AssumeRolePolicyDocument=json.dumps(trust_policy))
print("IAM role created, waiting for propagation...")
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
print("Attached inline policy for S3 and SNS access.")

# -----------------------------
# 6. Write Lambda code
# -----------------------------
lambda_code = f"""
import boto3, os, csv, json
from io import StringIO

TARGET_BUCKET = os.environ['TARGET_BUCKET']
SNS_TOPIC_ARN = os.environ['SNS_TOPIC_ARN']
s3 = boto3.client('s3')
sns = boto3.client('sns')

def lambda_handler(event, context):
    messages = []

    for record in event.get("Records", []):
        src_bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        try:
            obj = s3.get_object(Bucket=src_bucket, Key=key)
            csv_content = obj['Body'].read().decode('utf-8')
            reader = csv.DictReader(StringIO(csv_content))
            json_data = list(reader)
            json_key = key.rsplit('.',1)[0]+'.json'
            s3.put_object(Bucket=TARGET_BUCKET, Key=json_key, Body=json.dumps(json_data, indent=2).encode('utf-8'))
            presigned_url = s3.generate_presigned_url('get_object', Params={{'Bucket':TARGET_BUCKET,'Key':json_key}}, ExpiresIn=3600)
            messages.append(f"Converted '{{key}}' -> '{{json_key}}', Preview: {{presigned_url}}")
        except Exception as e:
            messages.append(f"Failed '{{key}}': {{e}}")
    if messages:
        sns.publish(TopicArn=SNS_TOPIC_ARN, Subject=f"CSV to JSON Conversion", Message='\\n'.join(messages))
    return {{'statusCode':200,'body':'Done'}}
"""

with open(LAMBDA_CODE_FILENAME, "w") as f:
    f.write(lambda_code)

# -----------------------------
# 7. Package Lambda
# -----------------------------
package_dir = "lambda_package"
if os.path.exists(package_dir): shutil.rmtree(package_dir)
os.makedirs(package_dir)
shutil.copy(LAMBDA_CODE_FILENAME, package_dir)
zip_path = "lambda_package.zip"
shutil.make_archive("lambda_package", 'zip', package_dir)

# -----------------------------
# 8. Deploy Lambda
# -----------------------------
with open(zip_path, 'rb') as f:
    zip_bytes = f.read()

lambda_response = lambda_client.create_function(
    FunctionName=lambda_name,
    Runtime="python3.11",
    Role=f"arn:aws:iam::{ACCOUNT_ID}:role/{lambda_role_name}",
    Handler=f"{LAMBDA_CODE_FILENAME.rsplit('.',1)[0]}.lambda_handler",
    Code={"ZipFile": zip_bytes},
    Environment={"Variables":{"TARGET_BUCKET":target_bucket,"SNS_TOPIC_ARN":sns_topic_arn}}
)
lambda_arn = lambda_response["FunctionArn"]
time.sleep(10)
print(f"Lambda function deployed: {lambda_arn}")

# -----------------------------
# 9. Add S3 permission
# -----------------------------
lambda_client.add_permission(
    FunctionName=lambda_name,
    StatementId=f"s3-invoke-{timestamp}",
    Action="lambda:InvokeFunction",
    Principal="s3.amazonaws.com",
    SourceArn=f"arn:aws:s3:::{source_bucket}"
)

# -----------------------------
# 10. Add S3 trigger
# -----------------------------
notification_configuration = {
    "LambdaFunctionConfigurations":[{"LambdaFunctionArn":lambda_arn,"Events":["s3:ObjectCreated:*"]}]
}
s3_client.put_bucket_notification_configuration(
    Bucket=source_bucket,
    NotificationConfiguration=notification_configuration
)

# -----------------------------
# 11. Cleanup local files
# -----------------------------
shutil.rmtree(package_dir)
os.remove(zip_path)
os.remove(LAMBDA_CODE_FILENAME)

# -----------------------------
# Deployment Complete
# -----------------------------
print("\nDeployment complete!")
print(f"Source Bucket: {source_bucket}")
print(f"Target Bucket: {target_bucket}")
print(f"SNS Topic ARN: {sns_topic_arn}")
print(f"Lambda Function ARN: {lambda_arn}")
print("Upload CSV files manually to the source bucket to test conversion.")
