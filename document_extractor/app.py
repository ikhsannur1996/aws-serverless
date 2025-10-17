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
