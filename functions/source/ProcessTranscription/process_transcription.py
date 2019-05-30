from __future__ import print_function  # Python 2/3 compatibility

import boto3
import os
import logging
import time
import json
from urllib2 import urlopen
import string
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
# Check valid languages here: https://docs.aws.amazon.com/comprehend/latest/dg/API_BatchDetectEntities.html#comprehend-BatchDetectEntities-request-LanguageCode
LANGUAGE_CODE = os.getenv('LANGUAGE_CODE', default = "en")

comprehend = boto3.client(service_name='comprehend', region_name=REGION)

commonDict = {'i': 'I'}

ENTITY_CONFIDENCE_THRESHOLD = 0.5

s3_client = boto3.client("s3")

# Pull the bucket name from the environment variable set in the cloudformation stack
bucket = os.environ['BUCKET_NAME']
print("bucket: " + bucket)


class InvalidInputError(ValueError):
    pass


def process_transcript(transcription_url):
    custom_vocabs = None

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
        detected_entities_response = comprehend.batch_detect_entities(TextList=comprehend_chunks, LanguageCode=LANGUAGE_CODE)
        round_trip = time.time() - start
        logger.info('End of batch_detect_entities. Took time {:10.4f}\n'.format(round_trip))

        entities = parse_detected_entities_response(detected_entities_response, {})

        for entity_type in entities:
            entities_as_list[entity_type] = list(entities[entity_type])

        clean_up_entity_results(entities_as_list)
        print(json.dumps(entities_as_list, indent=4))

        start = time.time()
        detected_phrase_response = comprehend.batch_detect_key_phrases(TextList=comprehend_chunks, LanguageCode=LANGUAGE_CODE)
        round_trip = time.time() - start
        logger.info('End of batch_detect_key_phrases. Took time {:10.4f}\n'.format(round_trip))

        key_phrases = parse_detected_key_phrases_response(detected_phrase_response)
        logger.debug(json.dumps(key_phrases, indent=4))

    agentTranscript = ''

    #Agent is channel 1 now...
    for item in results['channel_labels']['channels'][1]['items']:
        if item['type'] == 'punctuation':
            filler = ''
        else:
            filler = ' '
        agentTranscript += filler + item['alternatives'][0]['content']

    customerTranscript = ''

    # Customer is channel 0 now...
    for item in results['channel_labels']['channels'][0]['items']:
        if item['type'] == 'punctuation':
            filler = ''
        else:
            filler = ' '
        customerTranscript += filler + item['alternatives'][0]['content']

    agent = [agentTranscript]
    customer = [customerTranscript]
    agent_entities_as_list = {}
    detected_agent_phrase_response = ''
    agent_key_phrases = ''
    agent_sentiment = ''

    if len(agent) > 1 :
        detected_agent_entities_response = comprehend.batch_detect_entities(TextList=agent[0:24], LanguageCode=LANGUAGE_CODE)
        round_trip = time.time() - start
        logger.info('End of batch_detect_entities. Took time {:10.4f}\n'.format(round_trip))

        agent_entities = parse_detected_entities_response(detected_agent_entities_response, {})

        for entity_type in agent_entities:
            agent_entities_as_list[entity_type] = list(agent_entities[entity_type])

        clean_up_entity_results(agent_entities_as_list)
        print(json.dumps(agent_entities_as_list, indent=4))

        start = time.time()
        detected_agent_phrase_response = comprehend.batch_detect_key_phrases(TextList=agent[0:24], LanguageCode=LANGUAGE_CODE)
        round_trip = time.time() - start
        logger.info('End of batch_detect_key_phrases. Took time {:10.4f}\n'.format(round_trip))

        agent_key_phrases = parse_detected_key_phrases_response(detected_agent_phrase_response)
        logger.debug(json.dumps(key_phrases, indent=4))

        agent_sentiment = comprehend.detect_sentiment(Text=agentTranscript[0:5000], LanguageCode=LANGUAGE_CODE)['Sentiment']

        print('agent sentiment ' + agent_sentiment)

    customer_entities = {}
    customer_entities_as_list = {}
    customer_key_phrases = ''
    customer_sentiment = ''

    if len(customer) > 1 :
        logger.info("CUSTOMER " + json.dumps(customer))
        logger.info("CUSTOMER[0:24] " + json.dumps(customer[0:24]))
        detected_agent_entities_response = comprehend.batch_detect_entities(TextList=customer[0:24], LanguageCode=LANGUAGE_CODE)
        round_trip = time.time() - start
        logger.info('End of batch_detect_entities. Took time {:10.4f}\n'.format(round_trip))

        customer_entities = parse_detected_entities_response(detected_agent_entities_response, {})

        for entity_type in customer_entities:
            customer_entities_as_list[entity_type] = list(customer_entities[entity_type])

        clean_up_entity_results(agent_entities_as_list)
        print(json.dumps(agent_entities_as_list, indent=4))

        start = time.time()
        detected_agent_phrase_response = comprehend.batch_detect_key_phrases(TextList=customer[0:24], LanguageCode=LANGUAGE_CODE)
        round_trip = time.time() - start
        logger.info('End of batch_detect_key_phrases. Took time {:10.4f}\n'.format(round_trip))

        customer_key_phrases = parse_detected_key_phrases_response(detected_agent_phrase_response)
        logger.debug(json.dumps(key_phrases, indent=4))

        customer_sentiment = comprehend.detect_sentiment(Text=customerTranscript[0:5000], LanguageCode=LANGUAGE_CODE)['Sentiment']

        print('customer sentiment ' + customer_sentiment)

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
    #  "status":"Completed",
    #  "accountId":"Your AWS Account Id",
    #  "results":{
    #    "transcripts":[
    #        {
    #            "transcript":"Hello ... this is the text of the transcript"
    #        }
    #    ],
    #     "channel_labels": {
    #       "number_of_channels": 2,
    #       "channels": [
    #         {
    #           "channel_label": "ch_0"
    #           "items": [
    #             {
    #               "start_time": "23.84",
    #               "type": "pronunciation",
    #               "end_time": "24.87",
    #               "alternatives": [
    #                 {
    #                   "content": "Hello",
    #                   "confidence": "1.0000"
    #                 }
    #               ]
    #             }
    #           ]
    #         }
    #       ]
    #     },
    #     "items":[
    #        {
    #            "start_time":"0.630",
    #            "end_time":"5.620",
    #            "alternatives": [
    #                {
    #                    "confidence":"1.0000",
    #                    "content":"Hello"
    #                }
    #            ],
    #            "type":"pronunciation",
    #            "channel_label": "ch_0"
    #        }
    #     ]
    #  }


    items = results['items']
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

            if (start_time - previous_time) > 2 or (
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

def lambda_handler(event, context):
    """
        AWS Lambda handler

    """
    logger.info('Received event')
    logger.info(json.dumps(event))

    # Pull the signed URL for the payload of the transcription job
    transcription_url = event['transcribeStatus']['transcriptionUrl']

    return process_transcript(transcription_url)
