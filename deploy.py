import boto3
import json
import os
import time
import shutil
import subprocess
import sys
from zipfile import ZipFile

REGION = "us-east-1"
BASE_NAME = "word-analysis"

print("Step 0: Initializing AWS clients...")
s3_client = boto3.client("s3", region_name=REGION)
iam_client = boto3.client("iam")
sns_client = boto3.client("sns")
lambda_client = boto3.client("lambda", region_name=REGION)
dynamodb_client = boto3.client("dynamodb", region_name=REGION)
sts_client = boto3.client("sts")

ACCOUNT_ID = sts_client.get_caller_identity()["Account"]
print(f"Account ID: {ACCOUNT_ID}\n")

# -----------------------------
# 1. Prompt for SNS emails
# -----------------------------
print("Step 1: Enter SNS email subscribers (comma-separated):")
emails = input().split(",")

# -----------------------------
# 2. Generate unique resource names
# -----------------------------
timestamp = int(time.time())
source_bucket = f"{BASE_NAME}-source-{timestamp}"
target_bucket = f"{BASE_NAME}-target-{timestamp}"
sns_topic_name = f"{BASE_NAME}-topic-{timestamp}"
lambda_name = f"{BASE_NAME}-lambda-{timestamp}"
lambda_role_name = f"{BASE_NAME}-role-{timestamp}"
dynamo_table = f"{BASE_NAME}-table-{timestamp}"

print(f"Buckets: {source_bucket}, {target_bucket}")
print(f"SNS topic: {sns_topic_name}")
print(f"Lambda function: {lambda_name}")
print(f"DynamoDB table: {dynamo_table}\n")

# -----------------------------
# 3. Create S3 buckets
# -----------------------------
print("Step 3: Creating S3 buckets...")
for bucket in [source_bucket, target_bucket]:
    if REGION == "us-east-1":
        s3_client.create_bucket(Bucket=bucket)
    else:
        s3_client.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": REGION})
print("S3 buckets created.\n")

# -----------------------------
# 4. Create SNS topic and subscribe emails
# -----------------------------
sns_topic_arn = sns_client.create_topic(Name=sns_topic_name)["TopicArn"]
for email in emails:
    email = email.strip()
    if email:
        sns_client.subscribe(TopicArn=sns_topic_arn, Protocol="email", Endpoint=email)
        print(f"Subscribed {email} to SNS topic")
print("SNS topic and subscriptions created.\n")

# -----------------------------
# 5. Create IAM role for Lambda
# -----------------------------
print("Step 5: Creating IAM role for Lambda...")
trust_policy = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]
}
role = iam_client.create_role(RoleName=lambda_role_name, AssumeRolePolicyDocument=json.dumps(trust_policy))
print("IAM role created. Waiting 10s for propagation...")
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
         "Resource":[sns_topic_arn]},
        {"Effect": "Allow",
         "Action":["dynamodb:PutItem","dynamodb:UpdateItem"],
         "Resource":[f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/{dynamo_table}"]}
    ]
}
iam_client.put_role_policy(RoleName=lambda_role_name, PolicyName=f"{BASE_NAME}-policy", PolicyDocument=json.dumps(inline_policy))
print("Attached inline policy.\n")

# -----------------------------
# 6. Create DynamoDB table
# -----------------------------
print("Step 6: Creating DynamoDB table...")
dynamodb_client.create_table(
    TableName=dynamo_table,
    KeySchema=[{"AttributeName": "FileName", "KeyType": "HASH"}],
    AttributeDefinitions=[{"AttributeName": "FileName", "AttributeType": "S"}],
    BillingMode="PAY_PER_REQUEST"
)
print("DynamoDB table created.\n")

# -----------------------------
# 7. Prepare Lambda function code
# -----------------------------
print("Step 7: Preparing Lambda package...")
lambda_code = f"""
import boto3
import os

TARGET_BUCKET = os.environ['TARGET_BUCKET']
SNS_TOPIC_ARN = os.environ['SNS_TOPIC_ARN']
DYNAMO_TABLE = os.environ['DYNAMO_TABLE']

s3 = boto3.client('s3')
sns = boto3.client('sns')
dynamodb = boto3.client('dynamodb')

def lambda_handler(event, context):
    summary_lines = []
    for record in event.get('Records', []):
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        try:
            response = s3.get_object(Bucket=bucket, Key=key)
            content = response['Body'].read().decode('utf-8')
            words = content.split()
            total_words = len(words)
            unique_words = len(set(words))
            top_word = max(set(words), key=words.count) if words else ''
            dynamodb.put_item(
                TableName=DYNAMO_TABLE,
                Item={{'FileName': {{'S': key}}, 'TotalWords': {{'N': str(total_words)}},
                      'UniqueWords': {{'N': str(unique_words)}}, 'TopWord': {{'S': top_word}}}}
            )
            summary_lines.append(f"{{key}}: total={{total_words}}, unique={{unique_words}}, top='{{top_word}}'")
        except Exception as e:
            summary_lines.append(f"{{key}}: error - {{e}}")
    if summary_lines:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"Word Analysis Summary ({{len(summary_lines)}} file(s))",
            Message='\\n'.join(summary_lines)
        )
    return {{'statusCode': 200, 'body': 'Processed and notified.'}}
"""

# -----------------------------
# 8. Package Lambda function
# -----------------------------
package_dir = "lambda_package_temp"
if os.path.exists(package_dir):
    shutil.rmtree(package_dir)
os.makedirs(package_dir)

with open(os.path.join(package_dir, "lambda_word_analysis.py"), "w") as f:
    f.write(lambda_code)

zip_path = "lambda_package.zip"
shutil.make_archive("lambda_package", 'zip', package_dir)
print("Lambda package created.\n")

# -----------------------------
# 9. Deploy Lambda function
# -----------------------------
print("Step 9: Deploying Lambda function...")
with open(zip_path, 'rb') as f:
    zip_bytes = f.read()

lambda_response = lambda_client.create_function(
    FunctionName=lambda_name,
    Runtime="python3.11",
    Role=f"arn:aws:iam::{ACCOUNT_ID}:role/{lambda_role_name}",
    Handler="lambda_word_analysis.lambda_handler",
    Code={"ZipFile": zip_bytes},
    Environment={
        "Variables": {
            "TARGET_BUCKET": target_bucket,
            "SNS_TOPIC_ARN": sns_topic_arn,
            "DYNAMO_TABLE": dynamo_table
        }
    },
    Timeout=60
)
lambda_arn = lambda_response["FunctionArn"]
print(f"Lambda deployed: {lambda_arn}\n")

# -----------------------------
# 10. Add S3 trigger
# -----------------------------
lambda_client.add_permission(
    FunctionName=lambda_name,
    StatementId=f"s3-invoke-{timestamp}",
    Action="lambda:InvokeFunction",
    Principal="s3.amazonaws.com",
    SourceArn=f"arn:aws:s3:::{source_bucket}"
)

notification_configuration = {
    "LambdaFunctionConfigurations":[{"LambdaFunctionArn":lambda_arn,"Events":["s3:ObjectCreated:Put"]}]
}
s3_client.put_bucket_notification_configuration(
    Bucket=source_bucket,
    NotificationConfiguration=notification_configuration
)
print("S3 trigger configured.\n")

# -----------------------------
# 11. Cleanup local files
# -----------------------------
shutil.rmtree(package_dir)
os.remove(zip_path)

# -----------------------------
# 12. Deployment complete
# -----------------------------
print("Deployment complete!")
print(f"Source Bucket: {source_bucket}")
print(f"Target Bucket: {target_bucket}")
print(f"SNS Topic ARN: {sns_topic_arn}")
print(f"Lambda Function ARN: {lambda_arn}")
print(f"DynamoDB Table: {dynamo_table}")
print("Please confirm your SNS subscriptions via email.")
