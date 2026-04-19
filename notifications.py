import os
import mimetypes
import boto3
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart


def send_email(mail_from, mail_to, mail_subject, mail_body, attachment=None):
    """Send an email via AWS SES, optionally with an attachment."""
    ses = boto3.client('ses')
    msg = MIMEMultipart()
    recipients = mail_to if isinstance(mail_to, list) else [mail_to]
    msg['Subject'] = mail_subject
    msg['From'] = mail_from
    if isinstance(mail_to, list):
        msg['To'] = ', '.join(mail_to)
    else:
        msg['To'] = mail_to

    msg.attach(MIMEText(mail_body))

    if attachment:
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
