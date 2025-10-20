import boto3, os, time, shutil, subprocess, sys, json
from datetime import datetime

def log_step(message):
    """Print message with timestamp."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")

REGION = "us-east-1"
BASE_NAME = "file-word-analysis"
LAMBDA_CODE_FILENAME = "lambda_word_analysis.py"
DYNAMO_TABLE_NAME = f"{BASE_NAME}-table"

# AWS clients
s3_client = boto3.client("s3", region_name=REGION)
iam_client = boto3.client("iam")
sns_client = boto3.client("sns")
lambda_client = boto3.client("lambda", region_name=REGION)
dynamodb_client = boto3.client("dynamodb", region_name=REGION)
sts_client = boto3.client("sts")

ACCOUNT_ID = sts_client.get_caller_identity()["Account"]

# -----------------------------
# 1. Prompt for SNS subscribers
# -----------------------------
log_step("Starting deployment process...")
emails_input = input("Enter comma-separated email addresses for notifications: ").strip()
emails = [email.strip() for email in emails_input.split(",") if email.strip()]
if not emails:
    log_step("No valid emails provided. Exiting.")
    exit(1)

# -----------------------------
# 2. Generate resource names
# -----------------------------
timestamp = int(time.time())
source_bucket = f"{BASE_NAME}-source-{timestamp}"
sns_topic_name = f"{BASE_NAME}-topic-{timestamp}"
lambda_name = f"{BASE_NAME}-lambda-{timestamp}"
lambda_role_name = f"{BASE_NAME}-role-{timestamp}"

log_step(f"Source bucket: {source_bucket}")
log_step(f"DynamoDB table: {DYNAMO_TABLE_NAME}")
log_step(f"Lambda function: {lambda_name}")
log_step(f"IAM role: {lambda_role_name}")

# -----------------------------
# 3. Create S3 bucket
# -----------------------------
log_step("Creating S3 bucket...")
try:
    if REGION == "us-east-1":
        s3_client.create_bucket(Bucket=source_bucket)
    else:
        s3_client.create_bucket(Bucket=source_bucket, CreateBucketConfiguration={"LocationConstraint": REGION})
    log_step(f"Created bucket: {source_bucket}")
except Exception as e:
    log_step(f"Bucket {source_bucket} creation skipped or failed: {e}")

# -----------------------------
# 4. Create SNS topic and subscribe emails
# -----------------------------
log_step("Creating SNS topic and subscribing emails...")
sns_topic_arn = sns_client.create_topic(Name=sns_topic_name)["TopicArn"]
for email in emails:
    sns_client.subscribe(TopicArn=sns_topic_arn, Protocol="email", Endpoint=email)
log_step("SNS topic created and subscriptions sent.")

# -----------------------------
# 5. Create DynamoDB table
# -----------------------------
log_step("Creating DynamoDB table...")
try:
    dynamodb_client.create_table(
        TableName=DYNAMO_TABLE_NAME,
        KeySchema=[{'AttributeName': 'id', 'KeyType': 'HASH'}],
        AttributeDefinitions=[{'AttributeName': 'id', 'AttributeType': 'S'}],
        BillingMode='PAY_PER_REQUEST'
    )
    log_step("DynamoDB table creating...")
    waiter = dynamodb_client.get_waiter('table_exists')
    waiter.wait(TableName=DYNAMO_TABLE_NAME)
    log_step("DynamoDB table ready.")
except dynamodb_client.exceptions.ResourceInUseException:
    log_step("DynamoDB table already exists, skipping creation.")

# -----------------------------
# 6. Create IAM role for Lambda
# -----------------------------
log_step("Creating IAM role and attaching policies for Lambda...")
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
         "Action": ["s3:GetObject"],
         "Resource":[f"arn:aws:s3:::{source_bucket}/*"]},
        {"Effect": "Allow",
         "Action":["sns:Publish"],
         "Resource":[sns_topic_arn]},
        {"Effect": "Allow",
         "Action":["dynamodb:PutItem"],
         "Resource":[f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/{DYNAMO_TABLE_NAME}"]}
    ]
}
iam_client.put_role_policy(RoleName=lambda_role_name, PolicyName=f"{BASE_NAME}-policy", PolicyDocument=json.dumps(inline_policy))
log_step("IAM role and policies created for Lambda.")

# -----------------------------
# 7. Write Lambda code
# -----------------------------
log_step("Writing Lambda code...")
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
    words = re.findall(r'\\b\\w+\\b', text.lower())
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
                sniffer = csv.Sniffer()
                dialect = sniffer.sniff(content_str[:1024])
                reader = csv.DictReader(StringIO(content_str), delimiter=dialect.delimiter)
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
                text = ""
                for page in reader.pages:
                    text += page.extract_text() + "\\n"
                analysis = analyze_text(text)
                table.put_item(Item={{'id': key, **analysis}})
                analysis_results.append(str(analysis))
            else:
                analysis_results.append("Skipped unsupported file type.")

            summary.append(f"File: {{key}}\\n" + "\\n".join(analysis_results))

        except Exception as e:
            summary.append(f"File: {{key}} - Failed: {{e}}")

    if summary:
        message = "\\n\\n".join(summary)
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"File Analysis Summary ({{len(event.get('Records', []))}} file(s))",
            Message=message
        )

    return {{'statusCode': 200, 'body': 'Processing complete and summary sent.'}}
"""

with open(LAMBDA_CODE_FILENAME, "w") as f:
    f.write(lambda_code)
log_step("Lambda code file written successfully.")

# -----------------------------
# 8. Package Lambda
# -----------------------------
log_step("Packaging Lambda function...")
package_dir = "lambda_package"
if os.path.exists(package_dir): shutil.rmtree(package_dir)
os.makedirs(package_dir)
shutil.copy(LAMBDA_CODE_FILENAME, package_dir)

# Install PyPDF2 locally in package_dir
subprocess.check_call([sys.executable, "-m", "pip", "install", "PyPDF2", "-t", package_dir])

zip_path = "lambda_package.zip"
shutil.make_archive("lambda_package", 'zip', package_dir)
log_step("Lambda package created.")

# -----------------------------
# 9. Deploy Lambda
# -----------------------------
log_step("Deploying Lambda function to AWS...")
with open(zip_path, 'rb') as f:
    zip_bytes = f.read()

lambda_response = lambda_client.create_function(
    FunctionName=lambda_name,
    Runtime="python3.11",
    Role=f"arn:aws:iam::{ACCOUNT_ID}:role/{lambda_role_name}",
    Handler=f"{LAMBDA_CODE_FILENAME.rsplit('.',1)[0]}.lambda_handler",
    Code={"ZipFile": zip_bytes},
    Environment={"Variables":{"SNS_TOPIC_ARN":sns_topic_arn,"DYNAMO_TABLE":DYNAMO_TABLE_NAME}}
)
lambda_arn = lambda_response["FunctionArn"]
log_step(f"Lambda function deployed: {lambda_arn}")

# -----------------------------
# 10. Add S3 permission
# -----------------------------
log_step("Adding S3 permission for Lambda invocation...")
time.sleep(15)
try:
    lambda_client.add_permission(
        FunctionName=lambda_name,
        StatementId=f"s3-invoke-{timestamp}",
        Action="lambda:InvokeFunction",
        Principal="s3.amazonaws.com",
        SourceArn=f"arn:aws:s3:::{source_bucket}"
    )
    log_step("Permission added for S3 to invoke Lambda.")
except Exception as e:
    log_step(f"Permission setup skipped or failed: {e}")

# -----------------------------
# 11. Add S3 trigger
# -----------------------------
log_step("Configuring S3 trigger for Lambda...")
notification_configuration = {
    "LambdaFunctionConfigurations":[{"LambdaFunctionArn":lambda_arn,"Events":["s3:ObjectCreated:*"]}]
}
s3_client.put_bucket_notification_configuration(
    Bucket=source_bucket,
    NotificationConfiguration=notification_configuration
)
log_step("S3 trigger configured for Lambda.")

# -----------------------------
# 12. Cleanup local files
# -----------------------------
log_step("Cleaning up local temporary files...")
shutil.rmtree(package_dir)
os.remove(zip_path)
os.remove(LAMBDA_CODE_FILENAME)
log_step("Local cleanup complete.")

# -----------------------------
# Final Summary
# -----------------------------
log_step("Deployment complete!")
print(f"Source bucket: {source_bucket}")
print(f"SNS topic: {sns_topic_arn}")
print(f"DynamoDB table: {DYNAMO_TABLE_NAME}")
print(f"Lambda function ARN: {lambda_arn}")
print("Please confirm your SNS subscription emails.")
