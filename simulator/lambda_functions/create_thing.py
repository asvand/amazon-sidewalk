# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. 
# SPDX-License-Identifier: MIT-0

from __future__ import print_function
from botocore.exceptions import ClientError
import sys
import json
import logging
import boto3
import urllib3

SUCCESS = "SUCCESS"
FAILED = "FAILED"

logger = logging.getLogger()
logger.setLevel(logging.INFO)

policyDocument = {
    "Version": "2012-10-17",
    "Statement": [
        {"Effect": "Allow", "Action": ["iot:Connect", "iot:Receive", "iot:Publish","iot:Subscribe"], "Resource": "*"},
    ],
}

http = urllib3.PoolManager()


def send(event, context, responseStatus, physicalResourceId=None, noEcho=False, reason=None):
    responseUrl = event['ResponseURL']

    print(responseUrl)

    responseBody = {
        'Status' : responseStatus,
        'Reason' : reason or "See the details in CloudWatch Log Stream: {}".format(context.log_stream_name),
        'PhysicalResourceId' : physicalResourceId or context.log_stream_name,
        'StackId' : event['StackId'],
        'RequestId' : event['RequestId'],
        'LogicalResourceId' : event['LogicalResourceId'],
        'NoEcho' : noEcho,
        'Data' : {}
    }

    json_responseBody = json.dumps(responseBody)

    print("Response body:")
    print(json_responseBody)

    headers = {
        'content-type' : '',
        'content-length' : str(len(json_responseBody))
    }

    try:
        response = http.request('PUT', responseUrl, headers=headers, body=json_responseBody)
        print("Status code:", response.status)


    except Exception as e:

        print("send(..) failed executing http.request(..):", e)        
        
def handler(event, context):

    try:
        logger.info("Received event: {}".format(json.dumps(event)))
        result = FAILED
        client = boto3.client("iot")
        thingName = event["ResourceProperties"]["ThingName"]
        certArn = event["ResourceProperties"]["CertificateArn"]
        if event["RequestType"] == "Create":
            # Verify certificate is valid and correct region
            client.describe_certificate(certificateId=certArn.split("/")[-1])
            thing = client.create_thing(thingName=thingName)
            client.create_policy(
                policyName="{}-recv-pub".format(thingName),
                policyDocument=json.dumps(policyDocument),
            )
            response = client.attach_policy(
                policyName="{}-recv-pub".format(thingName), target=certArn
            )
            response = client.attach_thing_principal(
                thingName=thingName, principal=certArn
            )
            logger.info(
                "Created thing: %s and policy: %s"
                % (thingName, "{}-recv-pub".format(thingName))
            )
            result = SUCCESS
        elif event["RequestType"] == "Update":
            logger.info("Updating thing: %s" % thingName)
            result = SUCCESS
        elif event["RequestType"] == "Delete":
            logger.info("Deleting thing: %s and policy" % thingName)
            response = client.list_thing_principals(thingName=thingName)
            for i in response["principals"]:
                response = client.detach_thing_principal(
                    thingName=thingName, principal=i
                )
                response = client.detach_policy(
                    policyName="{}-recv-pub".format(thingName), target=i
                )
                response = client.delete_policy(
                    policyName="{}-recv-pub".format(thingName)
                )
                response = client.delete_thing(thingName=thingName)
            result = SUCCESS
    except ClientError as e:
        logger.error("Error: {}".format(e))
        result = FAILED
    logger.info(
        "Returning response with result of: {}".format(result)
    )
    sys.stdout.flush()
    
    send(event, context, result)
