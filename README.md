# 🧠 Serverless Document Analytics System  
### A Complete Event-Driven Document Processing Pipeline Using AWS Serverless Architecture

---

## 📖 Table of Contents
1. [Overview](#overview)  
2. [Architecture Diagram](#architecture-diagram)  
3. [System Components](#system-components)  
4. [Data Flow](#data-flow)  
5. [AWS Services Used](#aws-services-used)  
6. [Implementation Steps](#implementation-steps)  
7. [Lambda Function Details](#lambda-function-details)  
8. [IAM Role and Permissions](#iam-role-and-permissions)  
9. [CloudFormation Template (Optional)](#cloudformation-template-optional)  
10. [Testing the System](#testing-the-system)  
11. [Example Output](#example-output)  
12. [Possible Enhancements](#possible-enhancements)  
13. [Learning Outcomes](#learning-outcomes)  
14. [License](#license)

---

## 🌐 Overview

The **Serverless Document Analytics System** automates the extraction and analysis of text from uploaded documents (e.g., PDF, TXT) without using any servers.  
It uses **AWS Lambda**, **Amazon S3**, **Amazon DynamoDB**, **Amazon SNS**, and **Amazon CloudWatch** to form a **fully event-driven architecture**.

This system can:
- Detect when a document is uploaded to S3.  
- Automatically extract and store text data in DynamoDB.  
- Periodically analyze all stored text (e.g., find frequent words).  
- Send an email summary of the analysis results via SNS.

All processing runs on-demand and scales automatically — ideal for a **serverless analytics use case**.

---

## 🧩 Architecture Diagram

```

```
            ┌────────────────────────────────┐
            │     User Uploads Document       │
            │     (PDF or TXT to S3 Bucket)   │
            └───────────────┬────────────────┘
                            │
                            ▼
             ┌──────────────────────────────┐
             │   Lambda #1: documentExtractor│
             │ - Extracts text from file     │
             │ - Saves to DynamoDB           │
             └───────────────┬──────────────┘
                             │
                             ▼
                ┌────────────────────────┐
                │   DynamoDB Table        │
                │  (DocumentTextTable)    │
                └────────────┬────────────┘
                             │
             ┌───────────────┴────────────────┐
             │  CloudWatch Scheduled Trigger   │
             │ (e.g., once daily)              │
             └───────────────┬────────────────┘
                             │
                             ▼
             ┌──────────────────────────────┐
             │ Lambda #2: documentAnalyzer   │
             │ - Analyzes stored text data   │
             │ - Publishes report to SNS     │
             └───────────────┬──────────────┘
                             │
                             ▼
               ┌────────────────────────────┐
               │  Amazon SNS Topic           │
               │  (Email Notification)       │
               └────────────────────────────┘
```

````

---

## 🧱 System Components

| Component | Description |
|------------|-------------|
| **S3 Bucket** | Stores uploaded documents that trigger the workflow. |
| **Lambda Function #1: documentExtractor** | Extracts text from new S3 objects and saves to DynamoDB. |
| **DynamoDB Table** | Stores extracted text and metadata for each document. |
| **Lambda Function #2: documentAnalyzer** | Periodically reads DynamoDB, performs analytics, sends SNS summary. |
| **SNS Topic** | Sends analytics results to email subscribers. |
| **CloudWatch Event Rule** | Triggers the analyzer Lambda on a schedule (e.g., daily). |

---

## 🔄 Data Flow

1. User uploads a file (e.g., `report.pdf`) to the **S3 bucket**.  
2. The **S3 event** triggers **Lambda #1 (documentExtractor)**.  
3. Lambda extracts the text content and metadata.  
4. The extracted text is stored in **DynamoDB** (`DocumentTextTable`).  
5. **CloudWatch Event Rule** triggers **Lambda #2 (documentAnalyzer)** daily.  
6. Lambda reads all items from DynamoDB, counts frequent words, and publishes a report to **SNS**.  
7. **SNS** sends an **email notification** with the summary.

---

## 🧰 AWS Services Used

| AWS Service | Purpose |
|--------------|----------|
| **Amazon S3** | Document storage and event trigger. |
| **AWS Lambda** | Compute logic for text extraction and analytics. |
| **Amazon DynamoDB** | Serverless NoSQL database for storing extracted text. |
| **Amazon SNS** | Notification service for report delivery. |
| **Amazon CloudWatch** | Schedules automated analytics job and logs system metrics. |
| **AWS IAM** | Controls permissions and roles for Lambda execution. |

---

## ⚙️ Implementation Steps

### Step 1: Create S3 Bucket
```bash
aws s3 mb s3://serverless-doc-analytics-bucket
````

### Step 2: Create DynamoDB Table

```bash
aws dynamodb create-table \
  --table-name DocumentTextTable \
  --attribute-definitions AttributeName=document_id,AttributeType=S \
  --key-schema AttributeName=document_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

### Step 3: Create SNS Topic

```bash
aws sns create-topic --name DocumentReportTopic
aws sns subscribe --topic-arn <TopicARN> --protocol email --notification-endpoint <your-email>
```

You’ll receive a confirmation email — click **Confirm subscription**.

---

## 🧑‍💻 Lambda Function Details

### 🔹 Lambda #1: `documentExtractor`

#### Trigger:

* Event: **S3 PUT (Object Created)**
* Source: S3 bucket containing uploaded documents.

#### Role Permissions:

* `AmazonS3ReadOnlyAccess`
* `AmazonDynamoDBFullAccess`
* `CloudWatchLogsFullAccess`

#### Example Code:

```python
import boto3, json, io
import PyPDF2

s3 = boto3.client('s3')
dynamo = boto3.resource('dynamodb')
table = dynamo.Table('DocumentTextTable')

def lambda_handler(event, context):
    # Extract event data
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = event['Records'][0]['s3']['object']['key']
    
    # Get object content
    obj = s3.get_object(Bucket=bucket, Key=key)
    file_content = obj['Body'].read()
    
    # Determine file type
    if key.endswith('.pdf'):
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_content))
        text = " ".join([page.extract_text() or "" for page in pdf_reader.pages])
    else:
        text = file_content.decode('utf-8', errors='ignore')
    
    # Save to DynamoDB
    table.put_item(Item={
        'document_id': key,
        'filename': key,
        'text': text,
        'size': obj['ContentLength'],
        'uploaded_at': obj['LastModified'].isoformat()
    })
    
    print(f"Processed file: {key}")
    return {'status': 'success', 'file': key}
```

---

### 🔹 Lambda #2: `documentAnalyzer`

#### Trigger:

* Event: **CloudWatch Scheduled Rule (cron)**
  Example: `cron(0 0 * * ? *)` → runs daily at midnight UTC

#### Role Permissions:

* `AmazonDynamoDBReadOnlyAccess`
* `AmazonSNSFullAccess`
* `CloudWatchLogsFullAccess`

#### Example Code:

```python
import boto3, re, collections

dynamo = boto3.resource('dynamodb')
sns = boto3.client('sns')
table = dynamo.Table('DocumentTextTable')

TOPIC_ARN = 'arn:aws:sns:us-east-1:123456789012:DocumentReportTopic'

def lambda_handler(event, context):
    response = table.scan()
    items = response.get('Items', [])
    
    word_counter = collections.Counter()
    for item in items:
        words = re.findall(r'\w+', item['text'].lower())
        word_counter.update(words)
    
    top_words = word_counter.most_common(10)
    report = "\n".join([f"{w}: {c}" for w, c in top_words])
    
    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject="Daily Document Analytics Report",
        Message=f"Top 10 Most Frequent Words:\n{report}"
    )
    
    print("Report sent to SNS")
    return {'status': 'report_sent', 'total_docs': len(items)}
```

---

## 🔐 IAM Role and Permissions

Create an **IAM Role** for both Lambdas with these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": ["logs:*"], "Resource": "*"},
    {"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": "arn:aws:s3:::serverless-doc-analytics-bucket/*"},
    {"Effect": "Allow", "Action": ["dynamodb:*"], "Resource": "arn:aws:dynamodb:*:*:table/DocumentTextTable"},
    {"Effect": "Allow", "Action": ["sns:Publish"], "Resource": "arn:aws:sns:*:*:DocumentReportTopic"}
  ]
}
```

---

## 🧾 CloudFormation Template (Optional)

You can deploy the entire system using this YAML (save as `serverless-doc-analytics.yaml`):

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: Serverless Document Analytics System

Resources:
  DocumentBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: serverless-doc-analytics-bucket

  DocumentTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: DocumentTextTable
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: document_id
          AttributeType: S
      KeySchema:
        - AttributeName: document_id
          KeyType: HASH

  SNSTopic:
    Type: AWS::SNS::Topic
    Properties:
      TopicName: DocumentReportTopic

  ExtractorLambda:
    Type: AWS::Lambda::Function
    Properties:
      FunctionName: documentExtractor
      Runtime: python3.9
      Handler: lambda_function.lambda_handler
      Role: !GetAtt LambdaRole.Arn
      Code:
        ZipFile: |
          import boto3
          def lambda_handler(event, context):
              print("Triggered by S3 Event")

  AnalyzerLambda:
    Type: AWS::Lambda::Function
    Properties:
      FunctionName: documentAnalyzer
      Runtime: python3.9
      Handler: lambda_function.lambda_handler
      Role: !GetAtt LambdaRole.Arn
      Code:
        ZipFile: |
          import boto3
          def lambda_handler(event, context):
              print("Analyzer triggered")

  LambdaRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: LambdaExecutionRole
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: lambda.amazonaws.com
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
        - arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess
        - arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess
        - arn:aws:iam::aws:policy/AmazonSNSFullAccess
```

---

## 🧪 Testing the System

1. Upload a `.txt` or `.pdf` file to your **S3 bucket**.
2. Wait for **Lambda #1** to process it.

   * Check **CloudWatch Logs** → confirm “Processed file: …” message.
3. Wait for the **scheduled Lambda #2** to run (or invoke manually).
4. Check your **email** for the SNS report.

You can also query DynamoDB manually:

```bash
aws dynamodb scan --table-name DocumentTextTable
```

---

## 📬 Example Output

**SNS Email Example:**

```
Subject: Daily Document Analytics Report

Top 10 Most Frequent Words:
data: 54
aws: 38
lambda: 27
system: 24
cloud: 21
dynamodb: 19
python: 15
storage: 12
document: 10
analytics: 8
```

---

## 🌟 Possible Enhancements

| Enhancement               | Description                                                                   |
| ------------------------- | ----------------------------------------------------------------------------- |
| 🔍 **Sentiment Scoring**  | Implement basic positive/negative keyword analysis.                           |
| 🧮 **Summary Statistics** | Track total documents, total words, and upload frequency.                     |
| 📊 **Visualization**      | Export reports to S3 and visualize in QuickSight or Python (Cloud9).          |
| 🗄️ **Archiving**         | Move processed files from S3 to Glacier for cost optimization.                |
| 🔔 **Custom Alerts**      | Send SNS alerts when certain keywords (e.g., “error”, “confidential”) appear. |

---

## 🎓 Learning Outcomes

By completing this project, you’ll learn how to:

* Design **event-driven serverless workflows** using AWS Lambda triggers.
* Integrate **S3**, **DynamoDB**, **SNS**, and **CloudWatch** seamlessly.
* Build and deploy **serverless ETL pipelines** in AWS Academy Sandbox.
* Apply **IAM roles and least-privilege security** for Lambda functions.
* Schedule tasks using **CloudWatch Events** for periodic processing.

---

## 📜 License

© 2025 Mohamad Ikhsan Nurulloh
For educational use within **AWS Academy Cloud Architecting Labs**.
Do not redistribute or deploy for commercial use without permission.

---

