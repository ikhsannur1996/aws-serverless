Serverless Document Analytics System (SAM)
This project deploys an automated, event-driven pipeline on AWS using the Serverless Application Model (SAM) to process documents and generate analytics reports. The workflow is sequential: S3 Upload \rightarrow Extractor \rightarrow Analyzer \rightarrow SNS Notification.
✨ Features
 * File Support: Processes PDF, TXT, and CSV files.
 * Automation: Automatically triggered by S3 object creation.
 * Sequential Workflow: The Extractor Lambda invokes the Analyzer Lambda immediately upon successful data persistence.
 * Analytics: Performs basic word frequency analysis on all extracted text.
 * Notification: Sends a final report via Amazon SNS email.
🛠️ Prerequisites
 * AWS CLI configured with appropriate permissions.
 * SAM CLI installed.
 * Docker running (required for sam build and local testing).
 * Python 3.9+ installed.
📂 Project Structure
serverless-doc-analytics/
├── template.yaml               # SAM Configuration (Infrastructure as Code)
├── requirements.txt            # Python dependencies
├── document_extractor/         # Lambda #1: Extracts and Persists Data
│   └── app.py
└── document_analyzer/          # Lambda #2: Analyzes Data and Reports
    └── app.py

⚙️ Configuration Files
1. template.yaml
Defines all AWS resources. Note the S3 trigger filters and the LambdaInvokePolicy enabling the sequential flow.
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Description: Sequential Document Analytics System (PDF, TXT, CSV) deployed via AWS SAM.

Parameters:
  SnsEmail:
    Type: String
    Description: Email address to subscribe to the SNS topic for report notifications.

Resources:
  # --- Core Infrastructure ---
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

  # ----------------------------------------------------------------------
  # 1. DocumentExtractorFunction (S3 Trigger -> Saves to DB -> Invokes #2)
  # ----------------------------------------------------------------------
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
        - LambdaInvokePolicy: # Permission to invoke the Analyzer
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
                    
  # ----------------------------------------------------------------------
  # 2. DocumentAnalyzerFunction (Invoked by #1 -> Reads DB -> Sends Report)
  # ----------------------------------------------------------------------
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

2. requirements.txt
PyPDF2

🐍 Application Code
1. document_extractor/app.py
Handles the logic for reading PDF (using PyPDF2), TXT, and CSV (using Python's csv module), then stores the data and invokes the next Lambda.
import boto3, json, io, csv
import PyPDF2 
import os
from datetime import datetime

s3 = boto3.client('s3')
dynamo = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')

# ... (Environment variable setup)

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
    # ... (S3 event processing, error handling, DynamoDB write)

    # Sequentially Invoke the Analyzer Function
    lambda_client.invoke(
        FunctionName=ANALYZER_FUNCTION_NAME,
        InvocationType='Event',
        Payload=json.dumps({'source_event': 'document_extraction_complete'})
    )
    return {'status': 'success', 'document_id': document_id, 'analysis_triggered': True}

2. document_analyzer/app.py
Scans the DynamoDB table, performs word frequency analysis, and publishes the report via SNS.
import boto3, re, collections
import os
from datetime import datetime

dynamo = boto3.resource('dynamodb')
sns = boto3.client('sns')

# ... (Environment variable setup)

def perform_analysis(items):
    # ... (Analysis logic)
    
    message = (
        f"Document Analytics Report\n"
        f"Analysis Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        # ... (Report details)
    )
    return message

def lambda_handler(event, context):
    # 1. Scan DynamoDB for all data
    # ... (Scan logic)
    
    # 2. Perform Analysis
    # ... (Analysis logic)

    # 3. Publish report to SNS
    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject=subject,
        Message=message
    )
    return {'status': 'report_sent', 'total_docs': len(items)}

(Note: The full content of the Python files is shortened here for brevity, as the complete code was provided in the previous response and the logic remains unchanged.)
🚀 Deployment Guide
Follow these steps from the root serverless-doc-analytics/ directory to deploy your stack.
Step 1: Build the Project
The sam build command downloads dependencies (like PyPDF2) and prepares the deployment artifacts.
sam build

Step 2: Deploy to AWS
The sam deploy --guided command is interactive and creates the CloudFormation stack.
sam deploy --guided

You will be prompted for:
| Prompt | Value |
|---|---|
| Stack Name | ServerlessDocAnalyticsStack (or similar) |
| AWS Region | us-east-1 (or your preferred region) |
| Parameter SnsEmail | Your Email Address (e.g., user@example.com) |
| Confirm changes before deploy | Y |
| Allow SAM CLI to create IAM roles | Y |
| Save arguments to samconfig.toml | Y |
Step 3: Confirmation
Check the email address you provided for a message from AWS SNS and click the Confirm subscription link.
🧪 Usage and Testing
 * Retrieve the S3 Bucket Name from the Stack Outputs in the AWS console or the deployment terminal output.
 * Upload a document (report.pdf, data.csv, or notes.txt) to that S3 bucket.
 * The pipeline will execute automatically:
   * documentExtractor runs, saves text to DynamoDB, and invokes the Analyzer.
   * documentAnalyzer runs, performs analysis on all saved data, and sends a report.
 * Check your email for the Immediate Document Analytics Report.
