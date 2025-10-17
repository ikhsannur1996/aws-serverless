# Serverless Document Analytics System (SAM)

This project deploys an automated, event-driven pipeline on AWS using the Serverless Application Model (SAM) to process documents and generate analytics reports. The workflow is sequential: **S3 Upload → Extractor → Analyzer → SNS Notification**.

## ✨ Features

- **File Support:** Processes PDF, TXT, and CSV files.
- **Automation:** Automatically triggered by S3 object creation.
- **Sequential Workflow:** The Extractor Lambda invokes the Analyzer Lambda immediately after successful data persistence.
- **Analytics:** Performs document language detection and word frequency analysis on all extracted text.
- **Notification:** Sends a final report via Amazon SNS email.

## 🛠️ Prerequisites

- AWS CLI configured with appropriate permissions.
- SAM CLI installed.
- Python 3.9+ installed.

## 📂 Project Structure

```
serverless-doc-analytics/
├── template.yaml               # SAM Configuration (Infrastructure as Code)
├── requirements.txt            # Python dependencies
├── document_extractor/         # Lambda #1: Extracts and Persists Data
│   └── app.py
└── document_analyzer/          # Lambda #2: Analyzes Data and Reports
    └── app.py
```

## ⚙️ Configuration Files

### template.yaml

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Description: Complete Document Analytics System (PDF, TXT, CSV) deployed via AWS SAM

Parameters:
  SnsEmail:
    Type: String
    Description: Email address to subscribe to report notifications

Resources:
  # S3 bucket to upload documents
  DocumentBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub "sam-doc-analytics-bucket-${AWS::AccountId}"

  # DynamoDB table to store processed text
  DocumentTable:
    Type: AWS::Serverless::SimpleTable
    Properties:
      TableName: DocumentTextTable
      PrimaryKey:
        Name: document_id
        Type: String

  # SNS Topic for notifications
  SNSTopic:
    Type: AWS::SNS::Topic
    Properties:
      TopicName: DocumentReportTopic

  # Email subscription to SNS Topic
  SNSEmailSubscription:
    Type: AWS::SNS::Subscription
    Properties:
      Endpoint: !Ref SnsEmail
      Protocol: email
      TopicArn: !Ref SNSTopic

  # Lambda function to extract text from documents
  DocumentExtractorFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: documentExtractor
      CodeUri: document_extractor/
      Handler: app.lambda_handler
      Runtime: python3.9
      Timeout: 60
      MemorySize: 512
      Policies:
        - S3ReadPolicy:
            BucketName: !Ref DocumentBucket
        - DynamoDBWritePolicy:
            TableName: !Ref DocumentTable
        - LambdaInvokePolicy:
            FunctionName: !Ref DocumentAnalyzerFunction
      Environment:
        Variables:
          DYNAMODB_TABLE: !Ref DocumentTable
          ANALYZER_FUNCTION_NAME: !Ref DocumentAnalyzerFunction
      Events:
        S3Event:
          Type: S3
          Properties:
            Bucket: !Ref DocumentBucket
            Events: s3:ObjectCreated:*
            Filter:
              S3Key:
                Rules:
                  - Name: suffix
                    Value: .pdf
                  - Name: suffix
                    Value: .txt
                  - Name: suffix
                    Value: .csv

  # Lambda function for analyzing documents
  DocumentAnalyzerFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: documentAnalyzer
      CodeUri: document_analyzer/
      Handler: app.lambda_handler
      Runtime: python3.9
      Timeout: 30
      Policies:
        - DynamoDBReadPolicy:
            TableName: !Ref DocumentTable
        - SNSPublishMessagePolicy:
            TopicName: !Ref SNSTopic
      Environment:
        Variables:
          DYNAMODB_TABLE: !Ref DocumentTable
          TOPIC_NAME: !Ref SNSTopic

Outputs:
  S3UploadBucketName:
    Description: S3 bucket where documents should be uploaded
    Value: !Ref DocumentBucket

  SNSTopicARN:
    Description: ARN of the SNS Topic
    Value: !Ref SNSTopic
```

### requirements.txt

```
PyPDF2
langdetect
```

## 🐍 Application Code

### document_extractor/app.py

```python
import boto3
import json
import io
import csv
import PyPDF2 
import os
from datetime import datetime
import uuid

s3 = boto3.client('s3')
dynamo = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')

DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
ANALYZER_FUNCTION_NAME = os.environ['ANALYZER_FUNCTION_NAME']

def extract_text_from_file(bucket, key):
    obj = s3.get_object(Bucket=bucket, Key=key)
    file_content_bytes = obj['Body'].read()
    
    size = obj['ContentLength']
    uploaded_at = obj['LastModified'].isoformat()
    text = ""
    
    if key.lower().endswith('.pdf'):
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_content_bytes))
        text = " ".join([page.extract_text() or "" for page in pdf_reader.pages])
    elif key.lower().endswith(('.txt', '.csv')):
        file_content_str = file_content_bytes.decode('utf-8', errors='ignore')
        if key.lower().endswith('.csv'):
            text_data = []
            csv_io = io.StringIO(file_content_str)
            reader = csv.reader(csv_io)
            for row in reader:
                text_data.append(" ".join(row))
            text = " ".join(text_data)
        else:
            text = file_content_str
        
    return text, size, uploaded_at

def lambda_handler(event, context):
    try:
        bucket = event['Records'][0]['s3']['bucket']['name']
        key = event['Records'][0]['s3']['object']['key']
    except (KeyError, IndexError) as e:
        return {'status': 'error', 'message': 'Invalid S3 event data'}

    # Extract text and metadata
    text, size, uploaded_at = extract_text_from_file(bucket, key)
    
    # Generate a unique document ID
    document_id = str(uuid.uuid4())
    
    # Store in DynamoDB
    table = dynamo.Table(DYNAMODB_TABLE)
    table.put_item(
        Item={
            'document_id': document_id,
            'file_name': key,
            'text': text,
            'size': size,
            'uploaded_at': uploaded_at
        }
    )
    
    # Invoke Analyzer Lambda asynchronously
    lambda_client.invoke(
        FunctionName=ANALYZER_FUNCTION_NAME,
        InvocationType='Event',
        Payload=json.dumps({'source_event': 'document_extraction_complete'})
    )
    
    return {'status': 'success', 'document_id': document_id, 'analysis_triggered': True}
```

### document_analyzer/app.py

```python
import boto3
import re
import collections
from langdetect import detect, DetectorFactory
import os
from datetime import datetime

# For consistent language detection results
DetectorFactory.seed = 0

dynamo = boto3.resource('dynamodb')
sns = boto3.client('sns')

DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
TOPIC_ARN = os.environ['TOPIC_ARN']

def perform_analysis(items):
    # Concatenate all texts from DynamoDB items
    full_text = " ".join(item['text'] for item in items if 'text' in item)
    
    # Detect dominant language of the entire text corpus
    try:
        language = detect(full_text)
    except Exception:
        language = "unknown"
    
    # Tokenize and count word frequency (case-insensitive, words only)
    words = re.findall(r'\b\w+\b', full_text.lower())
    word_freq = collections.Counter(words)
    
    # Extract top 10 most frequent words
    top_words = word_freq.most_common(10)
    top_words_str = "\n".join(f"{word}: {count}" for word, count in top_words)
    
    message = (
        f"Document Analytics Report\n"
        f"Analysis Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Total Documents Analyzed: {len(items)}\n"
        f"Detected Language: {language}\n"
        f"Top 10 Word Frequencies:\n{top_words_str}\n"
    )
    return message

def lambda_handler(event, context):
    table = dynamo.Table(DYNAMODB_TABLE)
    response = table.scan()
    items = response.get('Items', [])
    
    report_message = perform_analysis(items)
    
    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject="Document Analytics Report",
        Message=report_message
    )
    
    return {'status': 'report_sent', 'total_docs': len(items)}
```

## 🚀 Deployment Guide

From the root `serverless-doc-analytics/` directory:

### Step 1: Build the Project

```bash
sam build
```

This downloads dependencies (`PyPDF2`, `langdetect`) and prepares deployment artifacts.

### Step 2: Deploy to AWS

```bash
sam deploy --guided
```

Complete the interactive prompts as follows:

| Prompt                     | Example / Description                   |
|----------------------------|----------------------------------------|
| Stack Name                 | ServerlessDocAnalyticsStack             |
| AWS Region                 | us-east-1 (or your preferred region)   |
| Parameter SnsEmail         | Your Email (e.g., user@example.com)    |
| Confirm changes before deploy | Y                                    |
| Allow SAM CLI to create IAM roles | Y                              |
| Save arguments to samconfig.toml | Y                                |

### Step 3: Confirm SNS Subscription

Check your email and click the confirmation link sent by AWS SNS to activate notifications.

## 🧪 Usage and Testing

- Obtain the S3 bucket name from the deployed stack outputs.
- Upload supported files (`.pdf`, `.csv`, `.txt`) into the bucket.
- The documentExtractor Lambda triggers automatically, extracting and saving text.
- The documentAnalyzer Lambda then analyzes all documents and sends a report email.
- Check the provided email address for the Document Analytics Report.

