from __future__ import print_function  # Python 2/3 compatibility

import boto3
import botocore
import os
import logging
import time
import json
# import urllib.request
from urllib2 import urlopen
import string
import random
from common_lib import find_duplicate_person, id_generator

# from requests_aws_sign import AWSV4Sign
# from elasticsearch import Elasticsearch, RequestsHttpConnection

# Log level
logging.basicConfig()
logger = logging.getLogger()
if os.getenv('LOG_LEVEL') == 'DEBUG':
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)
# Parameters
REGION = os.getenv('AWS_REGION', default='us-east-1')

transcribe_client = boto3.client('transcribe', region_name=REGION)
comprehend = boto3.client(service_name='comprehend', region_name=REGION)

commonDict = {'i': 'I'}

ENTITY_CONFIDENCE_THRESHOLD = 0.5

KEY_PHRASES_CONFIDENCE_THRESHOLD = 0.7

# get the Elasticsearch endpoint from the environment variables
ES_ENDPOINT = os.getenv('ES_ENDPOINT', default='search-podcasts-fux2acvdz4giniry55uf23yc2i.us-east-1.es.amazonaws.com')

# get the Elasticsearch index name from the environment variables
ES_INDEX = os.getenv('ES_INDEX', default='podcasts')

# get the Elasticsearch document type from the environment variables
ES_DOCTYPE = os.getenv('ES_DOCTYPE', default='episode')

# Establish credentials
session_var = boto3.session.Session()
credentials = session_var.get_credentials()

s3_client = boto3.client("s3")

# Pull the bucket name from the environment variable set in the cloudformation stack
bucket = os.environ['BUCKET_NAME']
print("bucket: " + bucket)


class InvalidInputError(ValueError):
    pass


def process_transcript(transcription_url, podcast_url, vocabulary_info):
    custom_vocabs = None

    # job_status_response = transcribe_client.get_transcription_job(TranscriptionJobName=transcribe_job_id)
    response = urlopen(transcription_url)
    output = response.read()
    json_data = json.loads(output)

    logger.debug(json.dumps(json_data, indent=4))
    results = json_data['results']
    # free up memory
    del json_data

    comprehend_chunks, paragraphs = chunk_up_transcript(custom_vocabs, results)

    key_phrases = ''
    entities_as_list = {}

    if comprehend_chunks is not None and len(comprehend_chunks) > 0:
        start = time.time()
        detected_entities_response = comprehend.batch_detect_entities(TextList=comprehend_chunks, LanguageCode='en')
        round_trip = time.time() - start
        logger.info('End of batch_detect_entities. Took time {:10.4f}\n'.format(round_trip))
    
        entities = parse_detected_entities_response(detected_entities_response, {})

        for entity_type in entities:
            entities_as_list[entity_type] = list(entities[entity_type])
    
        clean_up_entity_results(entities_as_list)
        print(json.dumps(entities_as_list, indent=4))
    
        start = time.time()
        detected_phrase_response = comprehend.batch_detect_key_phrases(TextList=comprehend_chunks, LanguageCode='en')
        round_trip = time.time() - start
        logger.info('End of batch_detect_key_phrases. Took time {:10.4f}\n'.format(round_trip))
    
        key_phrases = parse_detected_key_phrases_response(detected_phrase_response)
        logger.debug(json.dumps(key_phrases, indent=4))
        
# Lets figure out the individual speakers...
    agent = []
    customer = []
    for x in paragraphs.split('spk_') :
    	if len(x) > 2:
    		if x[0:1] == '0':
    			agent.append(x[2:])
    		else:
    			customer.append(x[2:])
    			
    agentTranscript = '\n\n'.join(agent)
    customerTranscript = '\n\n'.join(customer)
    agent_entities_as_list = {}
    detected_agent_phrase_response = ''
    agent_key_phrases = ''
    agent_sentiment = ''
    
    if len(agent) > 0 :
        detected_agent_entities_response = comprehend.batch_detect_entities(TextList=agent[0:24], LanguageCode='en')
        round_trip = time.time() - start
        logger.info('End of batch_detect_entities. Took time {:10.4f}\n'.format(round_trip))
    
        agent_entities = parse_detected_entities_response(detected_agent_entities_response, {})

        for entity_type in agent_entities:
            agent_entities_as_list[entity_type] = list(agent_entities[entity_type])
    
        clean_up_entity_results(agent_entities_as_list)
        print(json.dumps(agent_entities_as_list, indent=4))
    
        start = time.time()
        detected_agent_phrase_response = comprehend.batch_detect_key_phrases(TextList=agent[0:24], LanguageCode='en')
        round_trip = time.time() - start
        logger.info('End of batch_detect_key_phrases. Took time {:10.4f}\n'.format(round_trip))
    
        agent_key_phrases = parse_detected_key_phrases_response(detected_agent_phrase_response)
        logger.debug(json.dumps(key_phrases, indent=4))
        
        agent_sentiment = comprehend.detect_sentiment(Text=agentTranscript[0:5000], LanguageCode='en')['Sentiment']
        
        
       
    customer_entities = {}
    customer_entities_as_list = {}
    customer_key_phrases = ''
    customer_sentiment = ''
    
    if len(customer) > 0 :
        detected_agent_entities_response = comprehend.batch_detect_entities(TextList=customer[0:24], LanguageCode='en')
        round_trip = time.time() - start
        logger.info('End of batch_detect_entities. Took time {:10.4f}\n'.format(round_trip))
    
        customer_entities = parse_detected_entities_response(detected_agent_entities_response, {})

        for entity_type in customer_entities:
            customer_entities_as_list[entity_type] = list(customer_entities[entity_type])
    
        clean_up_entity_results(agent_entities_as_list)
        print(json.dumps(agent_entities_as_list, indent=4))
    
        start = time.time()
        detected_agent_phrase_response = comprehend.batch_detect_key_phrases(TextList=customer[0:24], LanguageCode='en')
        round_trip = time.time() - start
        logger.info('End of batch_detect_key_phrases. Took time {:10.4f}\n'.format(round_trip))
    
        customer_key_phrases = parse_detected_key_phrases_response(detected_agent_phrase_response)
        logger.debug(json.dumps(key_phrases, indent=4))
        
        customer_sentiment = comprehend.detect_sentiment(Text=customerTranscript[0:5000], LanguageCode='en')['Sentiment']


    doc_to_update = {'transcript': paragraphs}
    doc_to_update['agent'] = agentTranscript
    doc_to_update['customer'] = customerTranscript
    doc_to_update['transcript_entities'] = entities_as_list
    doc_to_update['key_phrases'] = key_phrases
    doc_to_update['agent_key_phrases'] = agent_key_phrases
    doc_to_update['agent_entities'] = agent_entities_as_list
    doc_to_update['customer_phrases'] = customer_key_phrases
    doc_to_update['customer_entities'] = customer_entities_as_list
    doc_to_update['agent_sentiment'] = agent_sentiment
    doc_to_update['customer_sentiment'] = customer_sentiment
    key = 'callrecords/transcript/' + id_generator() + '.json'

    response = s3_client.put_object(Body=json.dumps(doc_to_update, indent=2), Bucket=bucket, Key=key)
    logger.info(json.dumps(response, indent=2))

    logger.info("successfully written transcript to s3://" + bucket + "/" + key)
    # Return the bucket and key of the transcription / comprehend result.
    transcript_location = {"bucket": bucket, "key": key}
    return transcript_location



def chunk_up_transcript(custom_vocabs, results):
    # Here is the JSON returned by the Amazon Transcription SDK
    # {
    #  "jobName":"JobName",
    #  "accountId":"Your AWS Account Id",
    #  "results":{
    #    "transcripts":[
    #        {
    #            "transcript":"ah ... this is the text of the transcript"
    #        }
    #    ],
    #     "speaker_labels": {
    #       "speakers": 2,
    #       "segments": [
    #         {
    #           "start_time": "0.0",
    #           "speaker_label": "spk_1",
    #           "end_time": "23.84",
    #           "items": [
    #               {
    #                   "start_time": "23.84",
    #                   "speaker_label": "spk_0",
    #                   "end_time": "24.87",
    #                   "items": [
    #                       {
    #                           "start_time": "24.063",
    #                           "speaker_label": "spk_0",
    #                           "end_time": "24.273"
    #                       },
    #                       {
    #                           "start_time": "24.763",
    #                           "speaker_label": "spk_0",
    #                           "end_time": "25.023"
    #                       }
    #                   ]
    #               }
    #           ]
    #         ]
    #      },
    #    "items":[
    #        {
    #            "start_time":"0.630",
    #            "end_time":"5.620",
    #            "alternatives": [
    #                {
    #                    "confidence":"0.7417",
    #                    "content":"ah"
    #                }
    #            ],
    #            "type":"pronunciation"
    #        }
    #     ]
    #  }


    speaker_label_exist = False
    speaker_segments = None
    if 'speaker_labels' in results:
        speaker_label_exist = True
        speaker_segments = parse_speaker_segments(results)

    items = results['items']
    last_speaker = None
    paragraphs = []
    current_paragraph = ""
    comprehend_chunks = []
    current_comprehend_chunk = ""
    previous_time = 0
    last_pause = 0
    last_item_was_sentence_end = False
    for item in items:
        if item["type"] == "pronunciation":
            start_time = float(item['start_time'])

            if speaker_label_exist:
                current_speaker = get_speaker_label(speaker_segments, float(item['start_time']))
                if last_speaker is None or current_speaker != last_speaker:
                    if current_paragraph is not None:
                        paragraphs.append(current_paragraph)
                    current_paragraph = current_speaker + " :"
                    last_pause = start_time
                last_speaker = current_speaker

            elif (start_time - previous_time) > 2 or (
                            (start_time - last_pause) > 15 and last_item_was_sentence_end):
                last_pause = start_time
                if current_paragraph is not None or current_paragraph != "":
                    paragraphs.append(current_paragraph)
                current_paragraph = ""

            phrase = item['alternatives'][0]['content']
            if custom_vocabs is not None:
                if phrase in custom_vocabs:
                    phrase = custom_vocabs[phrase]
                    logger.info("replaced custom vocab: " + phrase)
            if phrase in commonDict:
                phrase = commonDict[phrase]
            current_paragraph += " " + phrase

            # add chunking
            current_comprehend_chunk += " " + phrase

            last_item_was_sentence_end = False

        elif item["type"] == "punctuation":
            current_paragraph += item['alternatives'][0]['content']
            current_comprehend_chunk += item['alternatives'][0]['content']
            if item['alternatives'][0]['content'] in (".", "!", "?"):
                last_item_was_sentence_end = True
            else:
                last_item_was_sentence_end = False

        if (item["type"] == "punctuation" and len(current_comprehend_chunk) >= 4500) \
                or len(current_comprehend_chunk) > 4900:
            comprehend_chunks.append(current_comprehend_chunk)
            current_comprehend_chunk = ""

        if 'end_time' in item:
            previous_time = float(item['end_time'])

    if not current_comprehend_chunk == "":
        comprehend_chunks.append(current_comprehend_chunk)
    if not current_paragraph == "":
        paragraphs.append(current_paragraph)

    logger.debug(json.dumps(paragraphs, indent=4))
    logger.debug(json.dumps(comprehend_chunks, indent=4))

    return comprehend_chunks, "\n\n".join(paragraphs)


def parse_detected_key_phrases_response(detected_phrase_response):
    if 'ErrorList' in detected_phrase_response and len(detected_phrase_response['ErrorList']) > 0:
        logger.error("encountered error during batch_detect_key_phrases")
        logger.error(json.dumps(detected_phrase_response['ErrorList'], indent=4))

    if 'ResultList' in detected_phrase_response:
        result_list = detected_phrase_response["ResultList"]
        phrases_set = set()
        for result in result_list:
            phrases = result['KeyPhrases']
            for detected_phrase in phrases:
                if float(detected_phrase["Score"]) >= ENTITY_CONFIDENCE_THRESHOLD:
                    phrase = detected_phrase["Text"]
                    phrases_set.add(phrase)
        key_phrases = list(phrases_set)
        return key_phrases
    else:
        return []


def clean_up_entity_results(entities_as_list):
    if 'PERSON' in entities_as_list:
        try:
            people = entities_as_list['PERSON']
            duplicates = find_duplicate_person(people)
            for d in duplicates:
                people.remove(d)
            entities_as_list['PERSON'] = people
        except Exception as e:
            logger.error(e)
    if 'COMMERCIAL_ITEM' in entities_as_list:
        entities_as_list['Products_and_Titles'] = entities_as_list['COMMERCIAL_ITEM']
        del entities_as_list['COMMERCIAL_ITEM']
    if 'TITLE' in entities_as_list:
        if 'PRODUCTS / TTTLES' in entities_as_list:
            entities_as_list['Products_and_Titles'].append(entities_as_list['TITLE'])
        else:
            entities_as_list['Products_and_Titles'] = entities_as_list['TITLE']
        del entities_as_list['TITLE']


def parse_detected_entities_response(detected_entities_response, entities):
    if 'ErrorList' in detected_entities_response and len(detected_entities_response['ErrorList']) > 0:
        logger.error("encountered error during batch_detect_entities")
        logger.error("error:" + json.dumps(detected_entities_response['ErrorList'], indent=4))

    if 'ResultList' in detected_entities_response:
        result_list = detected_entities_response["ResultList"]
        # entities = {}
        for result in result_list:
            detected_entities = result["Entities"]
            for detected_entity in detected_entities:
                if float(detected_entity["Score"]) >= ENTITY_CONFIDENCE_THRESHOLD:

                    entity_type = detected_entity["Type"]

                    if entity_type != 'QUANTITY':
                        text = detected_entity["Text"]

                        if entity_type == 'LOCATION' or entity_type == 'PERSON' or entity_type == 'ORGANIZATION':
                            if not text.isupper():
                                text = string.capwords(text)

                        if entity_type in entities:
                            entities[entity_type].add(text)
                        else:
                            entities[entity_type] = set([text])
        return entities
    else:
        return {}


def get_speaker_label(speaker_segments, start_time):
    for segment in speaker_segments:
        if segment['start_time'] <= start_time < segment['end_time']:
            return segment['speaker']
    return None


def parse_speaker_segments(results):
    speaker_labels = results['speaker_labels']['segments']
    speaker_segments = []
    for label in speaker_labels:
        segment = dict()
        segment["start_time"] = float(label["start_time"])
        segment["end_time"] = float(label["end_time"])
        segment["speaker"] = label["speaker_label"]
        speaker_segments.append(segment)
    return speaker_segments


def lambda_handler(event, context):
    """
        AWS Lambda handler

    """
    logger.info('Received event')
    logger.info(json.dumps(event))

    # Pull the signed URL for the payload of the transcription job
    transcription_url = event['transcribeStatus']['transcriptionUrl']

    vocab_info = None
    if 'vocabularyInfo' in event:
        vocab_info = event['vocabularyInfo']
    return process_transcript(transcription_url, None, None) #event['podcastUrl'], vocab_info)
