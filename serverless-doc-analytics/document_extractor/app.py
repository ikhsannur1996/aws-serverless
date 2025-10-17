import boto3
import json
import io
import csv
import PyPDF2
import os
import uuid

s3 = boto3.client('s3')
dynamo = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')

DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
ANALYZER_FUNCTION_NAME = os.environ['ANALYZER_FUNCTION_NAME']

def extract_text_from_file(bucket, key):
    obj = s3.get_object(Bucket=bucket, Key=key)
    content = obj['Body'].read()
    size = obj['ContentLength']
    uploaded_at = obj['LastModified'].isoformat()

    text = ""
    if key.lower().endswith('.pdf'):
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(content))
        text = " ".join([page.extract_text() or "" for page in pdf_reader.pages])
    elif key.lower().endswith('.csv'):
        decoded = content.decode('utf-8', errors='ignore')
        text = " ".join([" ".join(row) for row in csv.reader(io.StringIO(decoded))])
    elif key.lower().endswith('.txt'):
        text = content.decode('utf-8', errors='ignore')

    return text, size, uploaded_at

def lambda_handler(event, context):
    print("SNS Event:", json.dumps(event))

    record = event['Records'][0]
    sns_message = json.loads(record['Sns']['Message'])
    s3_record = sns_message['Records'][0]
    bucket = s3_record['s3']['bucket']['name']
    key = s3_record['s3']['object']['key']

    print(f"Processing {key} from bucket {bucket}")

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
        Payload=json.dumps({'document_id': document_id})
    )

    return {'status': 'extracted', 'document_id': document_id, 'file': key}
