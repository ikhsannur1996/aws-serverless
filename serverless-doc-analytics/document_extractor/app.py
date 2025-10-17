import boto3
import json
import io
import csv
import PyPDF2
import os
import uuid
from datetime import datetime

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
    elif key.lower().endswith('.csv'):
        text_data = []
        csv_io = io.StringIO(file_content_bytes.decode('utf-8', errors='ignore'))
        reader = csv.reader(csv_io)
        for row in reader:
            text_data.append(" ".join(row))
        text = " ".join(text_data)
    elif key.lower().endswith('.txt'):
        text = file_content_bytes.decode('utf-8', errors='ignore')

    return text, size, uploaded_at

def lambda_handler(event, context):
    for record in event.get('Records', []):
        if 'Sns' in record:
            sns_message = json.loads(record['Sns']['Message'])
            bucket = sns_message.get('Records', [])[0]['s3']['bucket']['name']
            key = sns_message.get('Records', [])[0]['s3']['object']['key']
        else:
            continue

        text, size, uploaded_at = extract_text_from_file(bucket, key)
        document_id = str(uuid.uuid4())

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

        lambda_client.invoke(
            FunctionName=ANALYZER_FUNCTION_NAME,
            InvocationType='Event',
            Payload=json.dumps({'source': 'extractor', 'document_id': document_id})
        )

    return {'status': 'extraction_complete'}
