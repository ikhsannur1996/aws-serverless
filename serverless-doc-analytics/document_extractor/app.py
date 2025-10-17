import boto3
import json
import io
import csv
import PyPDF2
import os
from datetime import datetime
import uuid
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client('s3')
dynamo = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')

DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
ANALYZER_FUNCTION_NAME = os.environ['ANALYZER_FUNCTION_NAME']

def extract_text_from_file(bucket, key):
    obj = s3.get_object(Bucket=bucket, Key=key)
    file_content_bytes = obj['Body'].read()

    size = obj.get('ContentLength', len(file_content_bytes))
    uploaded_at = obj.get('LastModified')
    if isinstance(uploaded_at, (str,)):
        uploaded_at = uploaded_at
    elif uploaded_at is not None:
        uploaded_at = uploaded_at.isoformat()
    else:
        uploaded_at = datetime.utcnow().isoformat()

    text = ""

    if key.lower().endswith('.pdf'):
        try:
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_content_bytes))
            pages_text = [page.extract_text() or "" for page in pdf_reader.pages]
            text = " ".join(pages_text)
        except Exception as e:
            logger.warning(f"Failed to extract text from PDF {key}: {e}")
            text = ""
    elif key.lower().endswith(('.txt', '.csv')):
        # Use utf-8-sig to handle BOMs
        file_content_str = file_content_bytes.decode('utf-8-sig', errors='ignore')
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
    logger.info(f"Received event: {json.dumps(event)}")
    try:
        bucket = event['Records'][0]['s3']['bucket']['name']
        key = event['Records'][0]['s3']['object']['key']
    except (KeyError, IndexError) as e:
        logger.error(f"Invalid S3 event data: {e}")
        return {'status': 'error', 'message': 'Invalid S3 event data'}

    # Extract text and metadata
    text, size, uploaded_at = extract_text_from_file(bucket, key)

    # Generate a unique document ID
    document_id = str(uuid.uuid4())

    # Store in DynamoDB
    table = dynamo.Table(DYNAMODB_TABLE)
    try:
        table.put_item(
            Item={
                'document_id': document_id,
                'file_name': key,
                'text': text,
                'size': int(size) if size is not None else 0,
                'uploaded_at': uploaded_at
            }
        )
    except Exception as e:
        logger.exception(f"Failed to persist document {document_id}: {e}")
        return {'status': 'error', 'message': 'Failed to persist document'}

    # Invoke Analyzer Lambda asynchronously, passing the new document id
    try:
        lambda_client.invoke(
            FunctionName=ANALYZER_FUNCTION_NAME,
            InvocationType='Event',
            Payload=json.dumps({'document_id': document_id})
        )
    except Exception as e:
        logger.exception(f"Failed to invoke analyzer lambda: {e}")
        # Not a hard error for extractor — document is persisted; return success but note failure to trigger analyzer
        return {'status': 'success', 'document_id': document_id, 'analysis_triggered': False, 'message': 'Persisted but failed to trigger analyzer'}

    return {'status': 'success', 'document_id': document_id, 'analysis_triggered': True}
