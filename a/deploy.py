import boto3, os, json, time, shutil, subprocess, sys
from zipfile import ZipFile

# -----------------------------
# CONFIGURATION
# -----------------------------
REGION = "us-east-1"
BASE_NAME = "word-analysis"
LAMBDA_RUNTIME = "python3.11"
LAMBDA_HANDLER = "lambda_word_analysis.lambda_handler"
DYNAMO_TABLE_NAME = f"{BASE_NAME}-dynamo"

# -----------------------------
# AWS CLIENTS
# -----------------------------
s3_client = boto3.client("s3", region_name=REGION)
iam_client = boto3.client("iam")
sns_client = boto3.client("sns")
lambda_client = boto3.client("lambda", region_name=REGION)
dynamodb_client = boto3.client("dynamodb")
sts_client = boto3.client("sts")
account_id = sts_client.get_caller_identity()["Account"]

# -----------------------------
# 1. PROMPT EMAILS
# -----------------------------
emails = input("Enter comma-separated emails for SNS notifications: ").split(",")
summary_email = input("Enter email for direct summary report: ").strip()

# -----------------------------
# 2. GENERATE RESOURCE NAMES
# -----------------------------
timestamp = int(time.time())
source_bucket = f"{BASE_NAME}-source-{timestamp}"
target_bucket = f"{BASE_NAME}-target-{timestamp}"
sns_topic_name = f"{BASE_NAME}-topic-{timestamp}"
lambda_name = f"{BASE_NAME}-lambda-{timestamp}"
lambda_role_name = f"{BASE_NAME}-role-{timestamp}"

print(f"Resources will be created with timestamp {timestamp}")

# -----------------------------
# 3. CREATE S3 BUCKETS
# -----------------------------
print("Creating S3 buckets...")
for bucket in [source_bucket, target_bucket]:
    if REGION == "us-east-1":
        s3_client.create_bucket(Bucket=bucket)
    else:
        s3_client.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": REGION})
    print(f"Bucket created: {bucket}")

# -----------------------------
# 4. CREATE SNS TOPIC
# -----------------------------
print("Creating SNS topic...")
sns_topic_arn = sns_client.create_topic(Name=sns_topic_name)["TopicArn"]
for email in emails:
    email = email.strip()
    if email:
        sns_client.subscribe(TopicArn=sns_topic_arn, Protocol="email", Endpoint=email)
        print(f"Subscribed {email}")

# -----------------------------
# 5. CREATE DYNAMODB TABLE
# -----------------------------
print("Creating DynamoDB table...")
try:
    dynamodb_client.create_table(
        TableName=DYNAMO_TABLE_NAME,
        KeySchema=[{'AttributeName': 'id','KeyType':'HASH'}],
        AttributeDefinitions=[{'AttributeName':'id','AttributeType':'S'}],
        BillingMode='PAY_PER_REQUEST'
    )
    waiter = dynamodb_client.get_waiter('table_exists')
    waiter.wait(TableName=DYNAMO_TABLE_NAME)
    print(f"DynamoDB table created: {DYNAMO_TABLE_NAME}")
except dynamodb_client.exceptions.ResourceInUseException:
    print(f"DynamoDB table {DYNAMO_TABLE_NAME} already exists")

# -----------------------------
# 6. CREATE IAM ROLE
# -----------------------------
print("Creating IAM role for Lambda...")
trust_policy = {
    "Version":"2012-10-17",
    "Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]
}
role = iam_client.create_role(
    RoleName=lambda_role_name,
    AssumeRolePolicyDocument=json.dumps(trust_policy)
)
time.sleep(10)  # Wait for role propagation
iam_client.attach_role_policy(
    RoleName=lambda_role_name,
    PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
)

inline_policy = {
    "Version": "2012-10-17",
    "Statement": [
        {"Effect": "Allow",
         "Action": ["s3:GetObject","s3:PutObject"],
         "Resource":[f"arn:aws:s3:::{source_bucket}/*", f"arn:aws:s3:::{target_bucket}/*"]},
        {"Effect": "Allow",
         "Action": ["dynamodb:PutItem","dynamodb:UpdateItem","dynamodb:GetItem"],
         "Resource": f"arn:aws:dynamodb:{REGION}:{account_id}:table/{DYNAMO_TABLE_NAME}"},
        {"Effect": "Allow",
         "Action": ["sns:Publish"],
         "Resource": sns_topic_arn},
        {"Effect": "Allow",
         "Action": ["ses:SendEmail","ses:SendRawEmail"],
         "Resource": "*"}
    ]
}
iam_client.put_role_policy(RoleName=lambda_role_name, PolicyName=f"{BASE_NAME}-policy", PolicyDocument=json.dumps(inline_policy))
print("IAM role and policies created.")

# -----------------------------
# 7. CREATE LAMBDA PACKAGE
# -----------------------------
print("Packaging Lambda function...")
package_dir = "lambda_package"
if os.path.exists(package_dir):
    shutil.rmtree(package_dir)
os.makedirs(package_dir)

# Write Lambda function code
LAMBDA_CODE_FILENAME = os.path.join(package_dir, "lambda_word_analysis.py")
with open(LAMBDA_CODE_FILENAME, "w") as f:
    f.write(f"""
import boto3, csv, re
from io import StringIO, BytesIO
from collections import Counter
from PyPDF2 import PdfReader
import os

TARGET_BUCKET = os.environ['TARGET_BUCKET']
SNS_TOPIC_ARN = os.environ['SNS_TOPIC_ARN']
DYNAMO_TABLE = os.environ['DYNAMO_TABLE']
SUMMARY_EMAIL = os.environ.get('SUMMARY_EMAIL')

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
            if file_lower.endswith('.csv'):
                content_str = content_bytes.decode('utf-8')
                sniffer = csv.Sniffer()
                dialect = sniffer.sniff(content_str[:1024])
                reader = csv.DictReader(StringIO(content_str), delimiter=dialect.delimiter)
                for i,row in enumerate(reader):
                    row_text = ' '.join(row.values())
                    analysis = analyze_text(row_text)
                    analysis['row_number'] = i+1
                    table.put_item(Item={{'id': f'{{key}}_row{{i+1}}', **analysis}})
                    analysis_results.append(f"Row {{i+1}}: {{analysis}}")
            elif file_lower.endswith('.txt'):
                content_str = content_bytes.decode('utf-8')
                analysis = analyze_text(content_str)
                table.put_item(Item={{'id': key, **analysis}})
                analysis_results.append(str(analysis))
            elif file_lower.endswith('.pdf'):
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
        if SUMMARY_EMAIL:
            ses = boto3.client('ses')
            ses.send_email(
                Source=SUMMARY_EMAIL,
                Destination={{"ToAddresses":[SUMMARY_EMAIL]}},
                Message={{
                    "Subject":{{"Data":f"File Analysis Summary ({{len(event.get('Records', []))}} file(s))"}},
                    "Body":{{"Text":{{"Data":message}}}}
                }}
            )
    return {{'statusCode': 200, 'body': 'Processing complete and summary sent.'}}
""")

# Install dependencies
subprocess.check_call([sys.executable, "-m", "pip", "install", "PyPDF2", "-t", package_dir])

# Create zip
zip_path = "lambda_word_analysis.zip"
shutil.make_archive("lambda_word_analysis", 'zip', package_dir)

# -----------------------------
# 8. CREATE LAMBDA FUNCTION
# -----------------------------
print("Creating Lambda function...")
with open(zip_path, 'rb') as f:
    zip_bytes = f.read()

lambda_response = lambda_client.create_function(
    FunctionName=lambda_name,
    Runtime=LAMBDA_RUNTIME,
    Role=f"arn:aws:iam::{account_id}:role/{lambda_role_name}",
    Handler=LAMBDA_HANDLER,
    Code={"ZipFile": zip_bytes},
    Timeout=300,
    MemorySize=256,
    Environment={
        "Variables":{
            "TARGET_BUCKET": target_bucket,
            "SNS_TOPIC_ARN": sns_topic_arn,
            "DYNAMO_TABLE": DYNAMO_TABLE_NAME,
            "SUMMARY_EMAIL": summary_email
        }
    }
)
lambda_arn = lambda_response['FunctionArn']
print(f"Lambda function created: {lambda_arn}")

# -----------------------------
# 9. ADD S3 TRIGGER
# -----------------------------
try:
    lambda_client.add_permission(
        FunctionName=lambda_name,
        StatementId=f"s3-invoke-{timestamp}",
        Action="lambda:InvokeFunction",
        Principal="s3.amazonaws.com",
        SourceArn=f"arn:aws:s3:::{source_bucket}"
    )
except Exception as e:
    print(f"Lambda S3 permission skipped: {e}")

notification_configuration = {
    "LambdaFunctionConfigurations":[{"LambdaFunctionArn":lambda_arn,"Events":["s3:ObjectCreated:*"]}]
}
s3_client.put_bucket_notification_configuration(
    Bucket=source_bucket,
    NotificationConfiguration=notification_configuration
)
print("S3 trigger added to Lambda.")

# -----------------------------
# 10. CLEANUP LOCAL FILES
# -----------------------------
shutil.rmtree(package_dir)
os.remove(zip_path)
print("Local packaging files cleaned up.")

# -----------------------------
# DEPLOY COMPLETE
# -----------------------------
print("\nDEPLOYMENT COMPLETE!")
print(f"Source Bucket: {source_bucket}")
print(f"Target Bucket: {target_bucket}")
print(f"SNS Topic ARN: {sns_topic_arn}")
print(f"DynamoDB Table: {DYNAMO_TABLE_NAME}")
print(f"Lambda ARN: {lambda_arn}")
print("Please confirm SNS subscriptions and SES verification email for summary email.")
