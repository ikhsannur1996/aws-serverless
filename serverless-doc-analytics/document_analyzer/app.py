import boto3
import re
import collections
from langdetect import detect, DetectorFactory
import os
from datetime import datetime

DetectorFactory.seed = 0

dynamo = boto3.resource('dynamodb')
sns = boto3.client('sns')

DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
TOPIC_ARN = os.environ['TOPIC_ARN']

def perform_analysis(items):
    full_text = " ".join(item.get('text', '') for item in items)
    try:
        language = detect(full_text)
    except Exception:
        language = "unknown"

    words = re.findall(r'\b\w+\b', full_text.lower())
    word_freq = collections.Counter(words)
    top_words = word_freq.most_common(10)

    summary = "\n".join(f"{w}: {c}" for w, c in top_words)
    return language, summary

def lambda_handler(event, context):
    table = dynamo.Table(DYNAMODB_TABLE)
    response = table.scan()
    items = response.get('Items', [])

    language, summary = perform_analysis(items)

    report = (
        f"📊 Document Analytics Report\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Documents analyzed: {len(items)}\n"
        f"Detected language: {language}\n\n"
        f"Top 10 Words:\n{summary}"
    )

    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject="✅ Document Analysis Completed",
        Message=report
    )

    return {'status': 'report_sent', 'documents_analyzed': len(items)}
