from datetime import datetime, timezone

import boto3

_dynamodb = None


def _get_dynamodb():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource('dynamodb')
    return _dynamodb


def check_if_seen(table_name, key, value):
    """Check if a job ID has already been processed."""
    table = _get_dynamodb().Table(table_name)
    response = table.get_item(Key={key: value})
    return 'Item' in response


def batch_check_seen(table_name, key, values):
    """Check many job IDs at once. Returns the set of values already seen."""
    dynamodb = _get_dynamodb()
    seen = set()
    unique_values = list(dict.fromkeys(values))
    for i in range(0, len(unique_values), 100):
        chunk = unique_values[i:i + 100]
        request = {
            table_name: {
                'Keys': [{key: v} for v in chunk],
                'ProjectionExpression': '#k',
                'ExpressionAttributeNames': {'#k': key},
            }
        }
        while request:
            response = dynamodb.batch_get_item(RequestItems=request)
            for item in response.get('Responses', {}).get(table_name, []):
                seen.add(item[key])
            unprocessed = response.get('UnprocessedKeys') or {}
            request = unprocessed if unprocessed.get(table_name, {}).get('Keys') else None
    return seen


def mark_as_seen(table_name, key, value):
    """Record a job ID as processed."""
    table = _get_dynamodb().Table(table_name)
    table.put_item(Item={
        key: value,
        'seen_at': datetime.now(timezone.utc).isoformat(),
    })
