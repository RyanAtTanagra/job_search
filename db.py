import boto3
import boto3.dynamodb.conditions


def check_if_seen(table_name, key, value):
    """Check if a job ID has already been processed."""
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(table_name)
    response = table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key(key).eq(value)
    )
    return len(response['Items']) > 0


def mark_as_seen(table_name, key, value):
    """Record a job ID as processed."""
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(table_name)
    table.put_item(Item={key: value})
