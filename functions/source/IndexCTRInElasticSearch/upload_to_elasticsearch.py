from __future__ import print_function

import boto3
import certifi
import json
import os
from aws_requests_auth.aws_auth import AWSRequestsAuth
from elasticsearch import Elasticsearch, RequestsHttpConnection
from elasticsearch import helpers
import logging
import time
import base64

# Log level
logging.basicConfig()
logger = logging.getLogger()

# Parameters
REGION = os.getenv('AWS_REGION', default='us-east-1')
esendpoint = os.environ['ES_DOMAIN']
FULL_EPISODE_INDEX = os.getenv('ES_EPISODE_INDEX', default='reinvent-2018-workshop')
FULL_EPISODE_DOCTYPE = os.getenv('FULL_EPISODE_DOCTYPE', default='doc')


s3_client = boto3.client('s3')
# Create the auth token for the sigv4 signature
session = boto3.session.Session()
credentials = session.get_credentials().get_frozen_credentials()
awsauth = AWSRequestsAuth(
    aws_access_key=credentials.access_key,
    aws_secret_access_key=credentials.secret_key,
    aws_token=credentials.token,
    aws_host=esendpoint,
    aws_region=REGION,
    aws_service='es'
)

# Connect to the elasticsearch cluster using aws authentication. The lambda function
# must have access in an IAM policy to the ES cluster.
es = Elasticsearch(
    hosts=[{'host': esendpoint, 'port': 443}],
    http_auth=awsauth,
    use_ssl=True,
    verify_certs=True,
    ca_certs=certifi.where(),
    timeout=120,
    connection_class=RequestsHttpConnection
)


# Entry point into the lambda function
def lambda_handler(event, context):
    for record in event['Records']:
        # Kinesis data is base64 encoded so decode here
        payload = base64.b64decode(record['kinesis']['data'])
        print("Decoded payload: " + payload)
        index_ctr(es, json.loads(payload))
    return 'Successfully processed {} records.'.format(len(event['Records']))

def index_ctr(es, payload):
    
    contact_id = payload['ContactId']

    updateDoc = {
        'doc':payload,
        "doc_as_upsert" : True
    }

    start = time.time()
    res = es.update(index=FULL_EPISODE_INDEX, doc_type=FULL_EPISODE_DOCTYPE, body=updateDoc, id=contact_id)
    logger.info('REQUEST_TIME es_client.index {:10.4f}'.format(time.time() - start))