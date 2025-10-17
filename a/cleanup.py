import boto3
import time

REGION = "us-east-1"
BASE_NAME = "image-compression"

# AWS clients
s3_client = boto3.client("s3", region_name=REGION)
lambda_client = boto3.client("lambda", region_name=REGION)
sns_client = boto3.client("sns")
iam_client = boto3.client("iam")
sts_client = boto3.client("sts")

ACCOUNT_ID = sts_client.get_caller_identity()["Account"]

# Prompt for timestamp used in deployment
timestamp = input("Enter the timestamp of deployment to clean up (from bucket/function names): ").strip()

# Resource names
source_bucket = f"{BASE_NAME}-source-{timestamp}"
target_bucket = f"{BASE_NAME}-target-{timestamp}"
lambda_name = f"{BASE_NAME}-lambda-{timestamp}"
lambda_role_name = f"{BASE_NAME}-role-{timestamp}"
sns_topic_name = f"{BASE_NAME}-topic-{timestamp}"

print("\nCleaning up resources...")

# 1. Delete Lambda function
try:
    lambda_client.delete_function(FunctionName=lambda_name)
    print(f"Deleted Lambda function: {lambda_name}")
except Exception as e:
    print(f"Lambda deletion skipped: {e}")

# 2. Delete S3 buckets (must delete all objects first)
for bucket in [source_bucket, target_bucket]:
    try:
        # Delete all objects
        response = s3_client.list_objects_v2(Bucket=bucket)
        if 'Contents' in response:
            for obj in response['Contents']:
                s3_client.delete_object(Bucket=bucket, Key=obj['Key'])
        # Delete the bucket
        s3_client.delete_bucket(Bucket=bucket)
        print(f"Deleted bucket: {bucket}")
    except Exception as e:
        print(f"Bucket deletion skipped ({bucket}): {e}")

# 3. Delete SNS topic
try:
    topic_arn = sns_client.create_topic(Name=sns_topic_name)["TopicArn"]
    sns_client.delete_topic(TopicArn=topic_arn)
    print(f"Deleted SNS topic: {sns_topic_name}")
except Exception as e:
    print(f"SNS deletion skipped: {e}")

# 4. Delete IAM role
try:
    # Detach managed policy
    iam_client.detach_role_policy(RoleName=lambda_role_name, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")
    # Delete inline policy
    inline_policies = iam_client.list_role_policies(RoleName=lambda_role_name)['PolicyNames']
    for policy in inline_policies:
        iam_client.delete_role_policy(RoleName=lambda_role_name, PolicyName=policy)
    # Delete the role
    iam_client.delete_role(RoleName=lambda_role_name)
    print(f"Deleted IAM role: {lambda_role_name}")
except Exception as e:
    print(f"IAM role deletion skipped: {e}")

print("\nCleanup complete!")
