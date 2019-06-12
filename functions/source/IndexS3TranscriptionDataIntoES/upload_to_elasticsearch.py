from __future__ import print_function

import boto3
import certifi
import json
import os
from aws_requests_auth.aws_auth import AWSRequestsAuth
from elasticsearch import Elasticsearch, RequestsHttpConnection
import logging

# Log level
logging.basicConfig()
logger = logging.getLogger()

# Parameters
REGION = os.getenv('AWS_REGION', default='us-east-1')
esendpoint = os.environ['ES_DOMAIN']
FULL_EPISODE_INDEX = os.getenv('ES_EPISODE_INDEX', default='call-transcript')
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
    print("Received event" + json.dumps(event, indent=4))

    fullEpisodeS3Location = event["processedTranscription"][0]
    index_episode(es, event, fullEpisodeS3Location)
    return


def index_episode(es, event, fullEpisodeS3Location):
    response = s3_client.get_object(Bucket=fullEpisodeS3Location['bucket'], Key=fullEpisodeS3Location['key'])
    file_content = response['Body'].read().decode('utf-8')
    fullepisode = json.loads(file_content)

    s3_location = "s3://" + event['bucket'] + "/" + event['key']

    s = event['key'].split('_')[1]

    contact_id = event['key'].split('/')[-1].split('_')[0]

    updateDoc = {
        'doc':{
            'audio_type': event['audio_type'],
            'audio_s3_location': s3_location,
            'contact_id': contact_id,
            'LastUpdateTimestamp': s[0:4] + '-' + s[4:6] + '-' + s[6:8] + 'T' + s.split('T')[1] + 'Z',
            'transcript': fullepisode['transcript'],
            'agent_transcript': fullepisode['agent'],
            'customer_transcript': fullepisode['customer'],
            'transcript_keyphrases': fullepisode['key_phrases'],
            'transcript_entities': fullepisode['transcript_entities'],
            'customer_keyphrases': fullepisode['customer_phrases'],
            'customer_entities': fullepisode['customer_entities'],
            'agent_keyphrases': fullepisode['agent_key_phrases'],
            'agent_entities': fullepisode['agent_entities'],
            'agent_sentiment': fullepisode['agent_sentiment'],
            'customer_sentiment': fullepisode['customer_sentiment'],
            'type': 'CallRecord'
        },
        "doc_as_upsert" : True
    }

    es.update(index=FULL_EPISODE_INDEX, doc_type=FULL_EPISODE_DOCTYPE, body=updateDoc, id=contact_id)
