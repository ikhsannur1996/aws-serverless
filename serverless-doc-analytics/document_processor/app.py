import os
import boto3
from urllib.parse import unquote_plus
from collections import Counter
import string

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
sns_client = boto3.client('sns')
table_name = os.environ['DYNAMODB_TABLE']
sns_topic_arn = os.environ['SNS_TOPIC_ARN']

table = dynamodb.Table(table_name)

def lambda_handler(event, context):
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = unquote_plus(event['Records'][0]['s3']['object']['key'])
    
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')
        
        cleaned_text = content.lower().translate(str.maketrans('', '', string.punctuation))
        words = cleaned_text.split()
        word_count = len(words)
        
        word_freq = Counter(words)
        top_words = word_freq.most_common(5)
        
        item = {
            'file_key': key,
            'word_count': word_count,
            'top_words': dict(top_words)
        }
        
        table.put_item(Item=item)
        
        message = f"Text analysis completed for file: {key}\nWord count: {word_count}\nTop words: {dict(top_words)}"
        sns_client.publish(
            TopicArn=sns_topic_arn,
            Message=message,
            Subject="Text Analysis Notification"
        )
        
        return {
            'statusCode': 200,
            'body': f'Successfully analyzed {key}, stored results in DynamoDB, and sent notification'
        }
    
    except Exception as e:
        return {
            'statusCode': 500,
            'body': f'Error processing file: {str(e)}'
        }
