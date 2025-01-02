from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
import mimetypes
import os, sys
import boto3
from botocore.exceptions import ClientError

def s3_upload_file(source_file, bucket, destination_file):
    session = boto3.Session()

    s3_client = session.client('s3')
    s3_client.upload_file(source_file, bucket, destination_file)

def s3_get_file(source_file, bucket, destination_file):
    session = boto3.Session()

    s3_client = session.client('s3')
    s3_client.download_file(bucket, source_file, destination_file)

def s3_list_objects(bucket, folder=None):
    session = boto3.Session()
    s3_client = session.client('s3')
    response = s3_client.list_objects_v2(Bucket=bucket, Prefix=folder)
    files = []
    for content in response.get('Contents', []):
        files.append(content['Key'])
    return files

def s3_delete_object(bucket, object):
    session = boto3.Session()
    s3_client = session.client('s3')
    s3_client.delete_object(Bucket=bucket, Key=object)

def route53_get_records(domain):
    session = boto3.Session()
    client = boto3.client('route53')
    # First get the list of domains, passing our domain as a value so it's first in the result
    domains = response = client.list_hosted_zones_by_name(DNSName=domain)
    # Then we can get the zoneid for our domain
    zoneid = response['HostedZones'][0]['Id']
    # And use that to get the records
    records = client.list_resource_record_sets(HostedZoneId=zoneid)
    return records

def route53_update_record(zoneid, record, address):
    session = boto3.Session()
    client = boto3.client('route53')
    response = client.change_resource_record_sets(
        HostedZoneId=zoneid,
        ChangeBatch={
            "Comment": "Update record to reflect new IP address for a system ",
            "Changes": [
                {
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Name": record,
                        "Type": "A",
                        "TTL": 60,
                        "ResourceRecords": [
                            {
                                "Value": address
                            }
                        ]
                    }
                } 
            ]
        }
    )
    return response

def cloudwatch_put_metric_data(namespace, metricname, value):
    session = boto3.Session()
    client = boto3.client('cloudwatch')
    response = client.put_metric_data(
	Namespace=f"{namespace}",
	MetricData = [
		{
			'MetricName': f"{metricname}",
			'Value': value
		}
	]
    )

def ecs_list_tasks(cluster):
    session = boto3.Session()
    client = boto3.client('ecs')
    tasks = client.list_tasks(
        cluster = cluster
    )
    return tasks

def ecs_describe_task(cluster,task):
    session = boto3.Session()
    client = boto3.client('ecs')
    info = client.describe_tasks(
        cluster = cluster,
        tasks = [ task ]
    )
    return info

def ecs_stop_task(cluster,task):
    session = boto3.Session()
    client = boto3.client('ecs')
    info = client.stop_task(
        cluster = cluster,
        task = task
    )

def send_email(mail_from, mail_to, mail_subject, mail_body, attachment=None):
    ses = boto3.client('ses')
    msg = MIMEMultipart()
    recipients = mail_to if isinstance(mail_to, list) else [mail_to]
    msg['Subject'] = mail_subject
    msg['From'] = mail_from
    # If multiple recipients, build them from a list
    if isinstance(mail_to, list):
        msg['To'] = ', '.join(mail_to)
    else:
        msg['To'] = mail_to
    # Add body
    msg.attach(MIMEText(mail_body))
    # If there is an attachment
    if attachment:
        # Try to figure out the MIME type by the filename
        ctype, encoding = mimetypes.guess_type(attachment)
        if ctype is None or encoding is not None:
            ctype = 'application/octet-stream'
        maintype, subtype = ctype.split('/', 1)
        with open(attachment, "rb") as file:
            part = MIMEApplication(file.read(), _subtype=subtype)
            part.add_header('Content-Disposition', 'attachment',
                          filename=os.path.basename(attachment))
            msg.attach(part)
    try:
        response = ses.send_raw_email(
            Source=mail_from,
            Destinations=recipients,
            RawMessage={'Data': msg.as_string()}
        )
        return response
    except Exception as e:
        print(f"Error sending email: {str(e)}")
        raise

def dynamodb_put_item(dynamo_table, key, value):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(dynamo_table)
    table.put_item(
        Item={
            key: value
        }
    )

def dynamodb_check_if_value_exists(dynamo_table, key, value):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(dynamo_table)
    response = table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key(key).eq(value)
    )
    if len(response['Items']) > 0:
        return True
    else:
        return False
