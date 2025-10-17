import boto3
import json
import os
from collections import Counter
from langdetect import detect

dynamo = boto3.resource('dynamodb')
sns = boto3.client('sns')

DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
TOPIC_ARN = os.environ['TOPIC_ARN']

def analyze_text(text):
    words = text.split()
    word_count = len(words)
    language = detect(text) if text.strip() else "unknown"
    freq = Counter(words).most_common(5)
    return word_count, language, freq

def lambda_handler(event, context):
    print("Analyzer received:", json.dumps(event))
    document_id = event.get('document_id')
    if not document_id:
        return {'error': 'Missing document_id'}

    table = dynamo.Table(DYNAMODB_TABLE)
    response = table.get_item(Key={'document_id': document_id})
    item = response.get('Item')

    if not item:
        return {'error': f"Document ID {document_id} not found"}

    text = item['text']
    word_count, language, freq = analyze_text(text)

    report = (
        f"📄 Document Analysis Report\n"
        f"File Name: {item['file_name']}\n"
        f"Language: {language}\n"
        f"Word Count: {word_count}\n"
        f"Top 5 Words: {freq}\n"
    )

    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject=f"Document Analysis: {item['file_name']}",
        Message=report
    )

    print("Report sent to SNS.")
    return {'status': 'analyzed', 'document_id': document_id}
