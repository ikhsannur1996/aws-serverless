#!/usr/bin/env python3
"""
AWS Deployment Script: File Word Analysis System
------------------------------------------------
✅ Creates: Source Bucket, DynamoDB Table, SNS Topic, IAM Role, Lambda, S3 Trigger
🚫 Skips: Target Bucket
🕒 Logs: Start / Finish / Duration / Details for every step
"""

import boto3, os, time, shutil, subprocess, sys, json
from datetime import datetime, timezone

# -----------------------------
# Configurations
# -----------------------------
REGION = "us-east-1"
BASE_NAME = "file-word-analysis"
LAMBDA_CODE_FILENAME = "lambda_word_analysis.py"
DYNAMO_TABLE_NAME = f"{BASE_NAME}-table"

# -----------------------------
# Helper Logging Functions
# -----------------------------
def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

def elapsed(start_ts):
    return f"{(time.time() - start_ts):.2f}s"

def log_start(step):
    print(f"\n[START] {step}")
    print(f"  Time : {now_iso()}")
    return time.time()

def log_finish(step, start_time, detail=""):
    print(f"[FINISH] {step}")
    print(f"  Time : {now_iso()}")
    print(f"  Duration : {elapsed(start_time)}")
    if detail:
        print(f"  Detail : {detail}")

# -----------------------------
# Initialize AWS Clients
# -----------------------------
step = "Initialize AWS Clients"
t0 = log_start(step)
s3_client = boto3.client("s3", region_name=REGION)
iam_client = boto3.client("iam")
sns_client = boto3.client("sns")
lambda_client = boto3.client("lambda", region_name=REGION)
dynamodb_client = boto3.client("dynamodb", region_name=REGION)
sts_client = boto3.client("sts")
ACCOUNT_ID = sts_client.get_caller_identity()["Account"]
log_finish(step, t0, f"AWS Region={REGION}, AccountID={ACCOUNT_ID}")

# -----------------------------
# 1. Prompt for SNS Subscribers
# -----------------------------
step = "Prompt for SNS Subscribers"
t1 = log_start(step)
emails_input = input("Enter comma-separated email addresses for notifications: ").strip()
emails = [e.strip() for e in emails_input.split(",") if e.strip()]
if not emails:
    print("❌ No valid emails provided. Exiting.")
    sys.exit(1)
log_finish(step, t1, f"Subscribers: {emails}")

# -----------------------------
# 2. Generate Resource Names
# -----------------------------
step = "Generate Resource Names"
t2 = log_start(step)
timestamp = int(time.time())
source_bucket = f"{BASE_NAME}-source-{timestamp}"
sns_topic_name = f"{BASE_NAME}-topic-{timestamp}"
lambda_name = f"{BASE_NAME}-lambda-{timestamp}"
lambda_role_name = f"{BASE_NAME}-role-{timestamp}"
log_finish(step, t2, f"SourceBucket={source_bucket}, SNSTopic={sns_topic_name}, Lambda={lambda_name}, Role={lambda_role_name}")

# -----------------------------
# 3. Create Source S3 Bucket
# -----------------------------
step = "Create Source S3 Bucket"
t3 = log_start(step)
try:
    if REGION == "us-east-1":
        s3_client.create_bucket(Bucket=source_bucket)
    else:
        s3_client.create_bucket(
            Bucket=source_bucket,
            CreateBucketConfiguration={"LocationConstraint": REGION}
        )
    log_finish(step, t3, f"Created bucket {source_bucket}")
except Exception as e:
    log_finish(step, t3, f"⚠️ Bucket creation failed or already exists: {e}")

# -----------------------------
# 4. Create SNS Topic & Subscribe Emails
# -----------------------------
step = "Create SNS Topic and Subscriptions"
t4 = log_start(step)
sns_topic_arn = sns_client.create_topic(Name=sns_topic_name)["TopicArn"]
for email in emails:
    sns_client.subscribe(TopicArn=sns_topic_arn, Protocol="email", Endpoint=email)
log_finish(step, t4, f"Created SNS Topic={sns_topic_arn} and sent subscriptions to {emails}")

# -----------------------------
# 5. Create DynamoDB Table
# -----------------------------
step = "Create DynamoDB Table"
t5 = log_start(step)
try:
    dynamodb_client.create_table(
        TableName=DYNAMO_TABLE_NAME,
        KeySchema=[{'AttributeName': 'id', 'KeyType': 'HASH'}],
        AttributeDefinitions=[{'AttributeName': 'id', 'AttributeType': 'S'}],
        BillingMode='PAY_PER_REQUEST'
    )
    print("⏳ Waiting for DynamoDB table to be active...")
    waiter = dynamodb_client.get_waiter('table_exists')
    waiter.wait(TableName=DYNAMO_TABLE_NAME)
    log_finish(step, t5, f"DynamoDB table {DYNAMO_TABLE_NAME} ready.")
except dynamodb_client.exceptions.ResourceInUseException:
    log_finish(step, t5, "Table already exists. Skipped creation.")

# -----------------------------
# 6. Create IAM Role for Lambda
# -----------------------------
step = "Create IAM Role and Policies"
t6 = log_start(step)
trust_policy = {
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"},
        "Action": "sts:AssumeRole"
    }]
}
role = iam_client.create_role(
    RoleName=lambda_role_name,
    AssumeRolePolicyDocument=json.dumps(trust_policy)
)
time.sleep(10)
iam_client.attach_role_policy(
    RoleName=lambda_role_name,
    PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
)
inline_policy = {
    "Version": "2012-10-17",
    "Statement": [
        {"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": [f"arn:aws:s3:::{source_bucket}/*"]},
        {"Effect": "Allow", "Action": ["sns:Publish"], "Resource": [sns_topic_arn]},
        {"Effect": "Allow", "Action": ["dynamodb:PutItem"], "Resource": [f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/{DYNAMO_TABLE_NAME}"]}
    ]
}
iam_client.put_role_policy(
    RoleName=lambda_role_name,
    PolicyName=f"{BASE_NAME}-policy",
    PolicyDocument=json.dumps(inline_policy)
)
log_finish(step, t6, f"IAM Role created: {lambda_role_name}")

# -----------------------------
# 7. Write Lambda Code
# -----------------------------
step = "Write Lambda Code File"
t7 = log_start(step)
lambda_code = f"""
import boto3, csv, re
from io import StringIO, BytesIO
from collections import Counter
from PyPDF2 import PdfReader
import os

SNS_TOPIC_ARN = os.environ['SNS_TOPIC_ARN']
DYNAMO_TABLE = os.environ['DYNAMO_TABLE']

s3 = boto3.client('s3')
sns = boto3.client('sns')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(DYNAMO_TABLE)

def analyze_text(text):
    words = re.findall(r'\\\\b\\\\w+\\\\b', text.lower())
    total_words = len(words)
    unique_words = len(set(words))
    top_words = Counter(words).most_common(5)
    lines = text.splitlines()
    return {{
        'total_words': total_words,
        'unique_words': unique_words,
        'top_words': top_words,
        'total_lines': len(lines)
    }}

def lambda_handler(event, context):
    summary = []
    for record in event.get("Records", []):
        src_bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        try:
            obj = s3.get_object(Bucket=src_bucket, Key=key)
            content_bytes = obj['Body'].read()
            file_lower = key.lower()
            analysis_results = []

            if file_lower.endswith(".csv"):
                content_str = content_bytes.decode('utf-8')
                reader = csv.DictReader(StringIO(content_str))
                for i, row in enumerate(reader):
                    row_text = ' '.join(row.values())
                    analysis = analyze_text(row_text)
                    analysis['row_number'] = i + 1
                    table.put_item(Item={{'id': f"{{key}}_row{{i+1}}", **analysis}})
                    analysis_results.append(f"Row {{i+1}}: {{analysis}}")
            elif file_lower.endswith(".txt"):
                content_str = content_bytes.decode('utf-8')
                analysis = analyze_text(content_str)
                table.put_item(Item={{'id': key, **analysis}})
                analysis_results.append(str(analysis))
            elif file_lower.endswith(".pdf"):
                reader = PdfReader(BytesIO(content_bytes))
                text = "".join([page.extract_text() + "\\n" for page in reader.pages])
                analysis = analyze_text(text)
                table.put_item(Item={{'id': key, **analysis}})
                analysis_results.append(str(analysis))
            else:
                analysis_results.append("Skipped unsupported file type.")
            summary.append(f"File: {{key}}\\n" + "\\n".join(analysis_results))
        except Exception as e:
            summary.append(f"File: {{key}} - Failed: {{e}}")
    if summary:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"File Analysis Summary ({{len(event.get('Records', []))}} file(s))",
            Message="\\n\\n".join(summary)
        )
    return {{'statusCode': 200, 'body': 'Processing complete.'}}
"""
with open(LAMBDA_CODE_FILENAME, "w") as f:
    f.write(lambda_code)
log_finish(step, t7, f"Wrote {LAMBDA_CODE_FILENAME}")

# -----------------------------
# 8. Package Lambda Function
# -----------------------------
step = "Package Lambda Function"
t8 = log_start(step)
package_dir = "lambda_package"
if os.path.exists(package_dir): shutil.rmtree(package_dir)
os.makedirs(package_dir)
shutil.copy(LAMBDA_CODE_FILENAME, package_dir)
subprocess.check_call([sys.executable, "-m", "pip", "install", "PyPDF2", "-t", package_dir])
zip_path = "lambda_package.zip"
shutil.make_archive("lambda_package", 'zip', package_dir)
log_finish(step, t8, f"Lambda package ready: {zip_path}")

# -----------------------------
# 9. Deploy Lambda
# -----------------------------
step = "Deploy Lambda Function"
t9 = log_start(step)
with open(zip_path, 'rb') as f:
    zip_bytes = f.read()
lambda_response = lambda_client.create_function(
    FunctionName=lambda_name,
    Runtime="python3.11",
    Role=f"arn:aws:iam::{ACCOUNT_ID}:role/{lambda_role_name}",
    Handler=f"{LAMBDA_CODE_FILENAME.rsplit('.',1)[0]}.lambda_handler",
    Code={"ZipFile": zip_bytes},
    Environment={"Variables": {"SNS_TOPIC_ARN": sns_topic_arn, "DYNAMO_TABLE": DYNAMO_TABLE_NAME}}
)
lambda_arn = lambda_response["FunctionArn"]
log_finish(step, t9, f"Lambda Deployed: {lambda_arn}")

# -----------------------------
# 10. Add Permission for S3 Trigger
# -----------------------------
step = "Add S3 Invoke Permission for Lambda"
t10 = log_start(step)
time.sleep(15)
try:
    lambda_client.add_permission(
        FunctionName=lambda_name,
        StatementId=f"s3-invoke-{timestamp}",
        Action="lambda:InvokeFunction",
        Principal="s3.amazonaws.com",
        SourceArn=f"arn:aws:s3:::{source_bucket}"
    )
    log_finish(step, t10, "Permission added successfully.")
except Exception as e:
    log_finish(step, t10, f"Permission setup failed: {e}")

# -----------------------------
# 11. Configure S3 Trigger
# -----------------------------
step = "Configure S3 Trigger for Lambda"
t11 = log_start(step)
notification_configuration = {
    "LambdaFunctionConfigurations": [
        {"LambdaFunctionArn": lambda_arn, "Events": ["s3:ObjectCreated:*"]}
    ]
}
s3_client.put_bucket_notification_configuration(
    Bucket=source_bucket,
    NotificationConfiguration=notification_configuration
)
log_finish(step, t11, "S3 trigger configured.")

# -----------------------------
# 12. Cleanup Local Files
# -----------------------------
step = "Cleanup Local Files"
t12 = log_start(step)
shutil.rmtree(package_dir)
os.remove(zip_path)
os.remove(LAMBDA_CODE_FILENAME)
log_finish(step, t12, "Temporary files deleted.")

# -----------------------------
# ✅ Summary
# -----------------------------
print("\n✅ DEPLOYMENT COMPLETE")
print(f"Source Bucket : {source_bucket}")
print(f"SNS Topic ARN : {sns_topic_arn}")
print(f"DynamoDB Table: {DYNAMO_TABLE_NAME}")
print(f"Lambda ARN    : {lambda_arn}")
print("📧 Please confirm your SNS subscription emails.")
