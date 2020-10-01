from aws_requests_auth.aws_auth import AWSRequestsAuth
from elasticsearch import Elasticsearch, RequestsHttpConnection
import os,boto3,certifi,boto3,json
from time import sleep

REGION = os.getenv('AWS_REGION')
esendpoint = os.environ['ES_DOMAIN']
FULL_EPISODE_INDEX = os.getenv('ES_EPISODE_INDEX', default='ctr') + '*'
FULL_EPISODE_DOCTYPE = os.getenv('FULL_EPISODE_DOCTYPE', default='doc')
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
es = Elasticsearch(
    hosts=[{'host': esendpoint, 'port': 443}],
    http_auth=awsauth,
    use_ssl=True,
    verify_certs=True,
    ca_certs=certifi.where(),
    timeout=120,
    connection_class=RequestsHttpConnection
)
def es_make_body(contact_id):
    esbody = {
        "_source": ["Agent"],
        "query": {
            "term":{"_id":{"value":contact_id}}}
    }
    return esbody

# The entry point for the lambda function
def lambda_handler(event, context):
    print("Received event: " + json.dumps(event, indent=2))

    transcribeJob = event['transcribeJob']
    client = boto3.client('transcribe')

    # Call the AWS SDK to get the status of the transcription job
    transcribe_response = client.get_transcription_job(TranscriptionJobName=transcribeJob)

    # Pull the transcribe job status
    transcribe_job_status = transcribe_response['TranscriptionJob']['TranscriptionJobStatus']

    retval = {
        "status": transcribe_job_status
    }

    # If the status is completed, return the transcription file url. This will be a signed url
    # that will provide the full details on the transcription
    if transcribe_job_status == 'COMPLETED':
        # Pull the contact-id
        contact_id = transcribe_response['TranscriptionJob']['Media']['MediaFileUri'].split('/')[-1].split('_')[0]
        try:
            es_response = es.search(index=FULL_EPISODE_INDEX, body=es_make_body(contact_id))
        except:
            # when first exececution, index is not exists yet
            sleep(60)
            es_response = es.search(index=FULL_EPISODE_INDEX, body=es_make_body(contact_id))
        if es_response['hits']['hits'] == []:
            retval["status"] = 'agent-id not yet'
        else:
            # pull agent_name and agent_arn
            retval["Username"] = es_response['hits']['hits'][0]['_source']['Agent']['Username']
            retval["ARN"] = es_response['hits']['hits'][0]['_source']['Agent']['ARN']
            retval["transcriptionUrl"] = transcribe_response['TranscriptionJob']['Transcript']['TranscriptFileUri']

    print(retval)

    return retval
