import boto3, time, json

REGION = "us-east-1"
BASE_NAME = "image-compression"

# AWS clients
s3 = boto3.client("s3", region_name=REGION)
lambda_client = boto3.client("lambda", region_name=REGION)
iam = boto3.client("iam")
sns = boto3.client("sns")
sts = boto3.client("sts")
ACCOUNT_ID = sts.get_caller_identity()["Account"]

# List all resources created in this timestamped deploy
timestamp = input("Enter the timestamp used in deployment (e.g., 1697501234): ").strip()
SOURCE_BUCKET = f"{BASE_NAME}-source-{timestamp}"
TARGET_BUCKET = f"{BASE_NAME}-target-{timestamp}"
SNS_TOPIC_NAME = f"{BASE_NAME}-topic-{timestamp}"
LAMBDA_NAME = f"{BASE_NAME}-lambda-{timestamp}"
ROLE_NAME = f"{BASE_NAME}-role-{timestamp}"
POLICY_NAME = f"{BASE_NAME}-policy"

# -----------------------------
# 1. Delete S3 buckets
# -----------------------------
for bucket in [SOURCE_BUCKET, TARGET_BUCKET]:
    try:
        print(f"Deleting all objects in {bucket}...")
        # Delete all objects
        objects = s3.list_objects_v2(Bucket=bucket)
        if "Contents" in objects:
            for obj in objects["Contents"]:
                s3.delete_object(Bucket=bucket, Key=obj["Key"])
        # Delete bucket
        s3.delete_bucket(Bucket=bucket)
        print(f"Deleted bucket: {bucket}")
    except Exception as e:
        print(f"Error deleting bucket {bucket}: {e}")

# -----------------------------
# 2. Delete Lambda function
# -----------------------------
try:
    lambda_client.delete_function(FunctionName=LAMBDA_NAME)
    print(f"Deleted Lambda function: {LAMBDA_NAME}")
except Exception as e:
    print(f"Error deleting Lambda: {e}")

# -----------------------------
# 3. Delete IAM inline policy
# -----------------------------
try:
    iam.delete_role_policy(RoleName=ROLE_NAME, PolicyName=POLICY_NAME)
    print(f"Deleted inline policy: {POLICY_NAME}")
except Exception as e:
    print(f"Error deleting inline policy: {e}")

# -----------------------------
# 4. Detach and delete IAM role
# -----------------------------
try:
    iam.detach_role_policy(RoleName=ROLE_NAME, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")
    iam.delete_role(RoleName=ROLE_NAME)
    print(f"Deleted IAM role: {ROLE_NAME}")
except Exception as e:
    print(f"Error deleting IAM role: {e}")

# -----------------------------
# 5. Delete SNS topic
# -----------------------------
try:
    topic_arn = f"arn:aws:sns:{REGION}:{ACCOUNT_ID}:{SNS_TOPIC_NAME}"
    sns.delete_topic(TopicArn=topic_arn)
    print(f"Deleted SNS topic: {SNS_TOPIC_NAME}")
except Exception as e:
    print(f"Error deleting SNS topic: {e}")

print("\nCleanup complete!")
