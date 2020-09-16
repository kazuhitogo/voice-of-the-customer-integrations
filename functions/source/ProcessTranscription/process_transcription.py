import boto3
import os
import logging
import time
import json
from urllib.request import urlopen
import string
from common_lib import find_duplicate_person, id_generator

# Log level
logging.basicConfig()
logger = logging.getLogger()
if os.getenv('LOG_LEVEL') == 'DEBUG':
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)

# Parameters
REGION = os.getenv('AWS_REGION')
# Check valid languages here: https://docs.aws.amazon.com/comprehend/latest/dg/API_BatchDetectEntities.html#comprehend-BatchDetectEntities-request-LanguageCode
LANGUAGE_CODE = os.getenv('LANGUAGE_CODE', default="ja")

comprehend = boto3.client(service_name='comprehend', region_name=REGION)

commonDict = {'i': 'I'}

s3_client = boto3.client("s3")

# Pull the bucket name from the environment variable set in the cloudformation stack
bucket = os.environ['BUCKET_NAME']


def process_transcript(transcription_url,agent_name='',agent_arn=''):
    custom_vocabs = None

    response = urlopen(transcription_url)
    output = response.read()
    json_data = json.loads(output)
    logger.info(json_data)

    # customer
    customer_transcriptions = []
    # センテンスを作成する
    # 1 秒未満に続いた単語は同じセンテンスとし、1 秒以上空いた音声は別センテンスとする
    for d in json_data['results']['channel_labels']['channels'][0]['items']:
        if 'start_time' not in d:
            pass
        elif customer_transcriptions == [] or float(d['start_time']) - float(customer_transcriptions[-1]['end_time']) >= 1:
            customer_transcriptions.append({
                'job_name':json_data['jobName'],
                'person':'customer',
                'start_time':d['start_time'],
                'end_time':d['end_time'],
                'content':d['alternatives'][0]['content'],
                'detail_flag':True
            })
        elif float(d['start_time']) - float(customer_transcriptions[-1]['end_time']) < 1: # 1秒未満
            customer_transcriptions[-1]['end_time'] = d['end_time']
            customer_transcriptions[-1]['content'] += d['alternatives'][0]['content']
    
    for customer_transcription in customer_transcriptions:
        customer_transcription['start_time'] = int(float(customer_transcription['start_time'])*1000)
        customer_transcription['end_time'] = int(float(customer_transcription['end_time'])*1000)
    for i,customer_transcription in enumerate(customer_transcriptions):
        res = comprehend.detect_sentiment(Text=customer_transcription['content'],LanguageCode=LANGUAGE_CODE)
        customer_transcriptions[i]['Positive'] = res['SentimentScore']['Positive']
        customer_transcriptions[i]['Negative'] = res['SentimentScore']['Negative']
        customer_transcriptions[i]['Neutral'] = res['SentimentScore']['Neutral']
        customer_transcriptions[i]['Mixed'] = res['SentimentScore']['Mixed']
        res = comprehend.detect_key_phrases(Text=customer_transcription['content'],LanguageCode=LANGUAGE_CODE)
        customer_transcriptions[i]['KeyPhrases'] = []
        if res['KeyPhrases'] == []:
            pass
        else:
            for r in res['KeyPhrases']:
                customer_transcriptions[i]['KeyPhrases'].append(r['Text'])
        customer_transcriptions[i]['Entities'] = []
        res = comprehend.detect_entities(Text=customer_transcription['content'],LanguageCode=LANGUAGE_CODE)
        if res['Entities']==[]:
            pass
        else:
            for r in res['Entities']:
                customer_transcriptions[i]['Entities'].append(r['Text'])
    # 全体のtranscription
    customer_transcriptions.append({
        'content': json_data['results']['transcripts'][0]['transcript'].replace(' ',''),
        'job_name':json_data['jobName'],
        'person':'customer',
        'detail_flag':False
    })
    # 全体の感情分析
    res = comprehend.detect_sentiment(Text=customer_transcriptions[-1]['content'],LanguageCode=LANGUAGE_CODE)
    customer_transcriptions[-1]['Positive'] = res['SentimentScore']['Positive']
    customer_transcriptions[-1]['Negative'] = res['SentimentScore']['Negative']
    customer_transcriptions[-1]['Neutral'] = res['SentimentScore']['Neutral']
    customer_transcriptions[-1]['Mixed'] = res['SentimentScore']['Mixed']
    # 全体のキーフレーズ分析
    res = comprehend.detect_key_phrases(Text=customer_transcriptions[-1]['content'],LanguageCode=LANGUAGE_CODE)
    print('all transcription key phrases:')
    print(res)
    customer_transcriptions[-1]['KeyPhrases'] = []
    if res['KeyPhrases'] == []:
        pass
    else:
        for r in res['KeyPhrases']:
            customer_transcriptions[-1]['KeyPhrases'].append(r['Text'])
    # 全体のエンティティ分析
    res = comprehend.detect_entities(Text=customer_transcriptions[-1]['content'],LanguageCode=LANGUAGE_CODE)
    customer_transcriptions[-1]['Entities'] = []
    if res['Entities'] == []:
        pass
    else:
        for r in res['Entities']:
            customer_transcriptions[-1]['Entities'].append(r['Text'])
    




    # agent
    agent_transcriptions = []
    # センテンスを作成する
    # 1 秒未満に続いた単語は同じセンテンスとし、1 秒以上空いた音声は別センテンスとする
    for d in json_data['results']['channel_labels']['channels'][1]['items']:
        if 'start_time' not in d:
            pass
        elif agent_transcriptions == [] or float(d['start_time']) - float(agent_transcriptions[-1]['end_time']) >= 1:
            agent_transcriptions.append({
                'job_name':json_data['jobName'],
                'person':'agent',
                'start_time':d['start_time'],
                'end_time':d['end_time'],
                'content':d['alternatives'][0]['content'],
                'agent_arn':agent_arn,
                'agent_name':agent_name,
                'detail_flag':True
            })
        elif float(d['end_time']) - float(agent_transcriptions[-1]['end_time']) < 1:
            agent_transcriptions[-1]['end_time'] = d['end_time']
            agent_transcriptions[-1]['content'] += d['alternatives'][0]['content']
    for agent_transcription in agent_transcriptions:
        agent_transcription['start_time'] = int(float(agent_transcription['start_time'])*1000)
        agent_transcription['end_time'] = int(float(agent_transcription['end_time'])*1000)
    for i,agent_transcription in enumerate(agent_transcriptions):
        res = comprehend.detect_sentiment(Text=agent_transcription['content'],LanguageCode=LANGUAGE_CODE)
        agent_transcriptions[i]['Positive'] = res['SentimentScore']['Positive']
        agent_transcriptions[i]['Negative'] = res['SentimentScore']['Negative']
        agent_transcriptions[i]['Neutral'] = res['SentimentScore']['Neutral']
        agent_transcriptions[i]['Mixed'] = res['SentimentScore']['Mixed']
        res = comprehend.detect_key_phrases(Text=agent_transcription['content'],LanguageCode=LANGUAGE_CODE)
        agent_transcriptions[i]['KeyPhrases'] = []
        if res['KeyPhrases'] == []:
            pass
        else:
            for r in res['KeyPhrases']:
                agent_transcriptions[i]['KeyPhrases'].append(r['Text'])
        agent_transcriptions[i]['Entities'] = []
        res = comprehend.detect_entities(Text=agent_transcription['content'],LanguageCode=LANGUAGE_CODE)
        if res['Entities']==[]:
            pass
        else:
            for r in res['Entities']:
                agent_transcriptions[i]['Entities'].append(r['Text'])
    
    # 全体のtranscription
    agent_transcriptions.append({
        'content': json_data['results']['transcripts'][0]['transcript'].replace(' ',''),
        'job_name':json_data['jobName'],
        'person':'agent',
        'agent_arn':agent_arn,
        'agent_name':agent_name,
        'detail_flag':False,
    })
    # 全体の感情分析
    res = comprehend.detect_sentiment(Text=agent_transcriptions[-1]['content'],LanguageCode=LANGUAGE_CODE)
    agent_transcriptions[-1]['Positive'] = res['SentimentScore']['Positive']
    agent_transcriptions[-1]['Negative'] = res['SentimentScore']['Negative']
    agent_transcriptions[-1]['Neutral'] = res['SentimentScore']['Neutral']
    agent_transcriptions[-1]['Mixed'] = res['SentimentScore']['Mixed']
    # 全体のキーフレーズ分析
    res = comprehend.detect_key_phrases(Text=agent_transcriptions[-1]['content'],LanguageCode=LANGUAGE_CODE)
    print('all transcription key phrases:')
    print(res)
    agent_transcriptions[-1]['KeyPhrases'] = []
    if res['KeyPhrases'] == []:
        pass
    else:
        for r in res['KeyPhrases']:
            agent_transcriptions[-1]['KeyPhrases'].append(r['Text'])
    # 全体のエンティティ分析
    res = comprehend.detect_entities(Text=agent_transcriptions[-1]['content'],LanguageCode=LANGUAGE_CODE)
    agent_transcriptions[-1]['Entities'] = []
    if res['Entities'] == []:
        pass
    else:
        for r in res['Entities']:
            agent_transcriptions[-1]['Entities'].append(r['Text'])
    
    
    # s3upload

    transcript_locations = []

    # customer
    for customer_transcription in customer_transcriptions:
        key = 'callrecords/transcript/sentence/customer/' + id_generator() + '.json'
        response = s3_client.put_object(Body=json.dumps(customer_transcription, indent=2), Bucket=bucket, Key=key)
        logger.info(json.dumps(response, indent=2))
        logger.info("successfully written transcript to s3://" + bucket + "/" + key)
    
        # Return the bucket and key of the transcription / comprehend result.
        transcript_locations.append({"bucket": bucket, "key": key})
    # agent
    for agent_transcription in agent_transcriptions:
        key = 'callrecords/transcript/sentence/agent/' + id_generator() + '.json'
        response = s3_client.put_object(Body=json.dumps(agent_transcription, indent=2), Bucket=bucket, Key=key)
        logger.info(json.dumps(response, indent=2))
        logger.info("successfully written transcript to s3://" + bucket + "/" + key)
    
        # Return the bucket and key of the transcription / comprehend result.
        transcript_locations.append({"bucket": bucket, "key": key})

    logger.info('return value:')
    logger.info(transcript_locations)
    return transcript_locations

def lambda_handler(event, context):
    """
        AWS Lambda handler
    """
    logger.info('Received event')
    logger.info(json.dumps(event))

    # Pull the signed URL for the payload of the transcription job
    transcription_url = event['transcribeStatus']['transcriptionUrl']
    agent_name = event['transcribeStatus']['Username']
    agent_arn = event['transcribeStatus']['ARN']

    return process_transcript(transcription_url,agent_name,agent_arn)
