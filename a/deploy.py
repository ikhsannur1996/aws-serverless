import boto3
import os
import shutil
import subprocess
import sys
import time
import json

# -----------------------------
# Configuration
# -----------------------------
REGION = "us-east-1"
BASE_NAME = "image-compression"

# -----------------------------
# Initialize AWS clients
# -----------------------------
s3 = boto3.client("s3", region_name=REGION)
iam = boto3.client("iam")
sns = boto3.client("sns")
lam = boto3.client("lambda", region_name=REGION)
sts = boto3.client("sts")

ACCOUNT_ID = sts.get_caller_identity()["Account"]
timestamp = int(time.time())
print(f"Deployment timestamp: {timestamp}, Account: {ACCOUNT_ID}")

# -----------------------------
# Prompt for SNS emails
# -----------------------------
emails = input("Enter comma-separated SNS emails: ").split(",")

# -----------------------------
# Resource names
# -----------------------------
source_bucket = f"{BASE_NAME}-source-{timestamp}"
target_bucket = f"{BASE_NAME}-target-{timestamp}"
sns_topic_name = f"{BASE_NAME}-topic-{timestamp}"
lambda_name = f"{BASE_NAME}-lambda-{timestamp}"
lambda_role_name = f"{BASE_NAME}-role-{timestamp}"

# -----------------------------
# 1. Create S3 buckets
# -----------------------------
for b in [source_bucket, target_bucket]:
    if REGION == "us-east-1":
        s3.create_bucket(Bucket=b)
    else:
        s3.create_bucket(Bucket=b, CreateBucketConfiguration={"LocationConstraint": REGION})
    print(f"Created bucket: {b}")

# -----------------------------
# 2. Create SNS topic and subscribe emails
# -----------------------------
sns_arn = sns.create_topic(Name=sns_topic_name)["TopicArn"]
for e in emails:
    e = e.strip()
    if e:
        sns.subscribe(TopicArn=sns_arn, Protocol="email", Endpoint=e)
        print(f"Subscribed {e}")
print(f"SNS Topic ARN: {sns_arn}")

# -----------------------------
# 3. Create IAM role for Lambda
# -----------------------------
trust_policy = {
    "Version":"2012-10-17",
    "Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]
}
role = iam.create_role(RoleName=lambda_role_name, AssumeRolePolicyDocument=json.dumps(trust_policy))
time.sleep(10)  # Wait for role propagation
iam.attach_role_policy(RoleName=lambda_role_name, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")

inline_policy = {
    "Version":"2012-10-17",
    "Statement":[
        {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject"],"Resource":[f"arn:aws:s3:::{source_bucket}/*", f"arn:aws:s3:::{target_bucket}/*"]},
        {"Effect":"Allow","Action":["sns:Publish"],"Resource":[sns_arn]}
    ]
}
iam.put_role_policy(RoleName=lambda_role_name, PolicyName=f"{BASE_NAME}-policy", PolicyDocument=json.dumps(inline_policy))
print(f"IAM role {lambda_role_name} created with policies.")

# -----------------------------
# 4. Prepare Lambda package
# -----------------------------
package_dir = "lambda_package"
if os.path.exists(package_dir):
    shutil.rmtree(package_dir)
os.makedirs(package_dir)

# Write lambda_function.py
lambda_code = f"""
import boto3
import io
import os
import imageio.v3 as iio

TARGET_BUCKET = os.environ['TARGET_BUCKET']
SNS_TOPIC_ARN = os.environ['SNS_TOPIC_ARN']

s3 = boto3.client("s3")
sns = boto3.client("sns")

def lambda_handler(event, context):
    summary_lines = []

    for record in event.get("Records", []):
        source_bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        try:
            response = s3.get_object(Bucket=source_bucket, Key=key)
            img_data = response['Body'].read()
            img = iio.imread(img_data)

            out_buffer = io.BytesIO()
            ext = key.split('.')[-1].lower()
            if ext in ["jpg","jpeg"]:
                iio.imwrite(out_buffer, img, format="JPEG", quality=60)
            elif ext == "png":
                iio.imwrite(out_buffer, img, format="PNG", compression=6)
            else:
                iio.imwrite(out_buffer, img, format=ext.upper())

            out_buffer.seek(0)
            s3.put_object(Bucket=TARGET_BUCKET, Key=key, Body=out_buffer)
            summary_lines.append(f"{{key}}: compressed successfully")
        except Exception as e:
            summary_lines.append(f"{{key}}: error - {{e}}")

    if summary_lines:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"Image Compression Summary ({{len(summary_lines)}} file(s))",
            Message="\\n".join(summary_lines)
        )

    return {{"statusCode":200,"body":"Images processed and notification sent."}}
"""

with open(os.path.join(package_dir,"lambda_function.py"), "w") as f:
    f.write(lambda_code)

# Install dependencies
subprocess.check_call([sys.executable,"-m","pip","install","boto3","imageio","-t", package_dir])

# Zip package
shutil.make_archive("lambda_package","zip",package_dir)
with open("lambda_package.zip","rb") as f:
    zip_bytes = f.read()
shutil.rmtree(package_dir)
os.remove("lambda_package.zip")

# -----------------------------
# 5. Create Lambda function
# -----------------------------
lambda_resp = lam.create_function(
    FunctionName=lambda_name,
    Runtime="python3.11",
    Role=f"arn:aws:iam::{ACCOUNT_ID}:role/{lambda_role_name}",
    Handler="lambda_function.lambda_handler",
    Code={"ZipFile": zip_bytes},
    Environment={"Variables":{"TARGET_BUCKET":target_bucket,"SNS_TOPIC_ARN":sns_arn}}
)
lambda_arn = lambda_resp["FunctionArn"]
print(f"Lambda function {lambda_name} created: {lambda_arn}")

# -----------------------------
# 6. Add S3 trigger
# -----------------------------
time.sleep(10)  # Wait for Lambda propagation

lam.add_permission(
    FunctionName=lambda_name,
    StatementId=f"s3-invoke-{timestamp}",
    Action="lambda:InvokeFunction",
    Principal="s3.amazonaws.com",
    SourceArn=f"arn:aws:s3:::{source_bucket}"
)

time.sleep(5)

s3.put_bucket_notification_configuration(
    Bucket=source_bucket,
    NotificationConfiguration={
        "LambdaFunctionConfigurations":[
            {"LambdaFunctionArn": lambda_arn, "Events": ["s3:ObjectCreated:Put"]}
        ]
    }
)
print(f"S3 trigger added for bucket {source_bucket}")

# -----------------------------
# Deployment complete
# -----------------------------
print("=== DEPLOYMENT COMPLETE ===")
print(f"Source Bucket: {source_bucket}")
print(f"Target Bucket: {target_bucket}")
print(f"SNS Topic ARN: {sns_arn}")
print(f"Lambda Function ARN: {lambda_arn}")
print("Please confirm your SNS subscriptions via email!")
