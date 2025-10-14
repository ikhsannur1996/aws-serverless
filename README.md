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
- Docker running (required for `sam build` and local testing).
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
Description: Sequential Document Analytics System (PDF, TXT, CSV) deployed via AWS SAM.

Parameters:
  SnsEmail:
    Type: String
    Description: Email address to subscribe to the SNS topic for report notifications.

Resources:
  DocumentBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub "sam-doc-analytics-bucket-${AWS::AccountId}"

  DocumentTable:
    Type: AWS::Serverless::SimpleTable
    Properties:
      TableName: DocumentTextTable
      PrimaryKey:
        Name: document_id
        Type: String

  SNSTopic:
    Type: AWS::SNS::Topic
    Properties:
      TopicName: DocumentReportTopic

  SNSEmailSubscription:
    Type: AWS::SNS::Subscription
    Properties:
      Endpoint: !Ref SnsEmail
      Protocol: email
      TopicArn: !Ref SNSTopic

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
            TopicArn: !Ref SNSTopic
      Environment:
        Variables:
          DYNAMODB_TABLE: !Ref DocumentTable
          TOPIC_ARN: !Ref SNSTopic

Outputs:
  S3UploadBucketName:
    Description: S3 Bucket where documents should be uploaded to start the workflow.
    Value: !Ref DocumentBucket

  SNSTopicARN:
    Description: ARN of the SNS Topic. Confirm subscription via email after deployment.
    Value: !Ref SNSTopic
```

### requirements.txt

```
PyPDF2
langdetect
```

## 🐍 Application Code

### 1. document_extractor/app.py

- Extracts text from PDF, TXT, and CSV files uploaded to S3.
- Uses PyPDF2 for PDF extraction and Python’s csv module for CSV parsing.
- Stores extracted text along with metadata in DynamoDB.
- Invokes the `documentAnalyzer` Lambda asynchronously after saving.

### 2. document_analyzer/app.py

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

Fill the interactive prompts:

| Prompt                     | Example / Description                   |
|----------------------------|----------------------------------------|
| Stack Name                 | ServerlessDocAnalyticsStack             |
| AWS Region                 | us-east-1 (or your preferred region)   |
| Parameter SnsEmail         | Your Email (e.g., user@example.com)    |
| Confirm changes before deploy | Y                                    |
| Allow SAM CLI to create IAM roles | Y                              |
| Save arguments to samconfig.toml | Y                                |

### Step 3: Confirm SNS Subscription

Check your email inbox and confirm the subscription message sent by AWS SNS to start receiving notification emails.

## 🧪 Usage and Testing

- Retrieve the S3 bucket name from the stack outputs.
- Upload supported document files (`.pdf`, `.csv`, `.txt`) to the bucket.
- The Extractor Lambda will automatically trigger, extract text, save to DynamoDB, and invoke the Analyzer Lambda.
- The Analyzer Lambda performs language detection and word frequency analysis on all stored text data.
- Receive the analytics report immediately via the subscribed email.
