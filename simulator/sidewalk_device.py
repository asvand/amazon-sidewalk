# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. 
# SPDX-License-Identifier: MIT-0

import argparse
from awscrt import io, mqtt, auth, http
from awsiot import mqtt_connection_builder
import sys
import threading
import time
import json
import random
from uuid import uuid4
import base64

device_id = ["AWS12345", "AWS34567", "AWS54637", "AWS98765"]
message_id = 0

# This sample uses the Message Broker for AWS IoT to send and receive messages
# through an MQTT connection. On startup, the device connects to the server,
# subscribes to a topic, and begins publishing messages to that topic.
# The device should receive those same messages back from the message broker,
# since it is subscribed to that same topic.

parser = argparse.ArgumentParser(description="Send and receive messages through and MQTT connection.")
parser.add_argument('--endpoint', required=True, help="Your AWS IoT custom endpoint, not including a port. " +
                                                      "Ex: \"abcd123456wxyz-ats.iot.us-east-1.amazonaws.com\"")
parser.add_argument('--cert', help="File path to your client certificate, in PEM format.")
parser.add_argument('--key', help="File path to your private key, in PEM format.")
parser.add_argument('--root-ca', help="File path to root certificate authority, in PEM format. " +
                                      "Necessary if MQTT server uses a certificate that's not already in " +
                                      "your trust store.")
parser.add_argument('--client-id', default="sidewalk_device", help="Client ID for MQTT connection.")
parser.add_argument('--topic', default="SidewalkSimulator/", help="Topic to subscribe to, and publish messages to.")
#parser.add_argument('--topic', default="/sidewalk/", help="Topic to subscribe to, and publish messages to.")
parser.add_argument('--message', default="Hello World!", help="Message to publish. " +
                                                              "Specify empty string to publish nothing.")
parser.add_argument('--count', default=10, type=int, help="Number of messages to publish/receive before exiting. " +
                                                          "Specify 0 to run forever.")
parser.add_argument('--use-websocket', default=False, action='store_true',
    help="To use a websocket instead of raw mqtt. If you " +
    "specify this option you must specify a region for signing, you can also enable proxy mode.")
parser.add_argument('--signing-region', default='us-east-1', help="If you specify --use-web-socket, this " +
    "is the region that will be used for computing the Sigv4 signature")
parser.add_argument('--proxy-host', help="Hostname for proxy to connect to. Note: if you use this feature, " +
    "you will likely need to set --root-ca to the ca for your proxy.")
parser.add_argument('--proxy-port', type=int, default=8080, help="Port for proxy to connect to.")
parser.add_argument('--verbosity', choices=[x.name for x in io.LogLevel], default=io.LogLevel.NoLogs.name,
    help='Logging level')

# Using globals to simplify sample code
args = parser.parse_args()

io.init_logging(getattr(io.LogLevel, args.verbosity), 'stderr')

received_count = 0
received_all_event = threading.Event()

# Callback when connection is accidentally lost.
def on_connection_interrupted(connection, error, **kwargs):
    print("Connection interrupted. error: {}".format(error))


# Callback when an interrupted connection is re-established.
def on_connection_resumed(connection, return_code, session_present, **kwargs):
    print("Connection resumed. return_code: {} session_present: {}".format(return_code, session_present))

    if return_code == mqtt.ConnectReturnCode.ACCEPTED and not session_present:
        print("Session did not persist. Resubscribing to existing topics...")
        resubscribe_future, _ = connection.resubscribe_existing_topics()

        # Cannot synchronously wait for resubscribe result because we're on the connection's event-loop thread,
        # evaluate result with a callback instead.
        resubscribe_future.add_done_callback(on_resubscribe_complete)


def on_resubscribe_complete(resubscribe_future):
    resubscribe_results = resubscribe_future.result()
    print("Resubscribe results: {}".format(resubscribe_results))

    for topic, qos in resubscribe_results['topics']:
        if qos is None:
            sys.exit("Server rejected resubscribe to topic: {}".format(topic))


# Callback when the subscribed topic receives a message
# This prints the data that comes back from IoT Core
def on_message_received(topic, payload, **kwargs):

    print("Received message from topic '{}': {} \n".format(topic, payload))
    payloadJson = json.loads(payload) #str(payload, 'utf-8')
    payload_data = int(decode_message(payloadJson["PayloadData"]))
    print("Received PayloadData :", payload_data)
    print(" ")
    
    
    global received_count
    received_count += 1
    if received_count == args.count:
        received_all_event.set()


def encode_message(message):
    message_bytes = message.encode('ascii')
    base64_bytes = base64.b64encode(message_bytes)
    base64_message = base64_bytes.decode('ascii')
    return base64_message
    
def decode_message(base64_message):          
    base64_bytes = base64_message.encode('ascii')
    message_bytes = base64.b64decode(base64_bytes)
    message = message_bytes.decode('ascii')
    return message    

# Message to be published. The device and payload are chosen at random
def publish_message():
    global message_id
    
    random_val_d = random.randint(0, 3)

    temp = {}
    temp["Seq"] = random.randint(0, 5096)
    message_id = message_id + 1
    device_message = {}
    device_message["MessageId"] = str(message_id) 
    device_message["WirelessDeviceId"] = device_id[random_val_d]
    device_data = str(random.randint(10,25))
    print ("Publishing Payload data :", device_data)
    device_message["PayloadData"] = encode_message(device_data)
    device_message["WirelessMetaData"] = temp
    
    print('publishing on {}: {}'.format(args.topic, json.dumps(device_message)))

    mqtt_connection.publish(
        topic=args.topic,
        payload=json.dumps(device_message),
        qos=mqtt.QoS.AT_LEAST_ONCE)     


if __name__ == '__main__':
    # Spin up resources
    event_loop_group = io.EventLoopGroup(1)
    host_resolver = io.DefaultHostResolver(event_loop_group)
    client_bootstrap = io.ClientBootstrap(event_loop_group, host_resolver)

    if args.use_websocket == True:
        proxy_options = None
        if (args.proxy_host):
            proxy_options = http.HttpProxyOptions(host_name=args.proxy_host, port=args.proxy_port)

        credentials_provider = auth.AwsCredentialsProvider.new_default_chain(client_bootstrap)
        mqtt_connection = mqtt_connection_builder.websockets_with_default_aws_signing(
            endpoint=args.endpoint,
            client_bootstrap=client_bootstrap,
            region=args.signing_region,
            credentials_provider=credentials_provider,
            websocket_proxy_options=proxy_options,
            ca_filepath=args.root_ca,
            on_connection_interrupted=on_connection_interrupted,
            on_connection_resumed=on_connection_resumed,
            client_id=args.client_id,
            clean_session=False,
            keep_alive_secs=6)

    else:
        mqtt_connection = mqtt_connection_builder.mtls_from_path(
            endpoint=args.endpoint,
            cert_filepath=args.cert,
            pri_key_filepath=args.key,
            client_bootstrap=client_bootstrap,
            ca_filepath=args.root_ca,
            on_connection_interrupted=on_connection_interrupted,
            on_connection_resumed=on_connection_resumed,
            client_id=args.client_id,
            clean_session=False,
            keep_alive_secs=6)

    print("Connecting to {} with client ID '{}'...".format(
        args.endpoint, args.client_id))

    connect_future = mqtt_connection.connect()

    # Future.result() waits until a result is available
    connect_future.result()
    print("Connected!")

    # Subscribe
    responseTopic = "/SidewalkSimulatorRule/response/"
    print("Subscribing to topic '{}'...".format(responseTopic))
    subscribe_future, packet_id = mqtt_connection.subscribe(
        topic=responseTopic,
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=on_message_received)

    subscribe_result = subscribe_future.result()
    print("Subscribed with {}".format(str(subscribe_result['qos'])))

    # Publish message to server desired number of times.
    # This step is skipped if message is blank.
    # This step loops forever if count was set to 0.
    if args.message:
        if args.count == 0:
            print ("Sending messages until program killed")
        else:
            print ("Sending {} message(s)".format(args.count))

        publish_count = 1
        while (publish_count <= args.count) or (args.count == 0):
            publish_message()
            time.sleep(2)
            publish_count += 1

    # Wait for all messages to be received.
    # This waits forever if count was set to 0.
    if args.count != 0 and not received_all_event.is_set():
        print("Waiting for all messages to be received...")

    received_all_event.wait()
    print("{} message(s) received.".format(received_count))

    # Disconnect
    print("Disconnecting...")
    disconnect_future = mqtt_connection.disconnect()
    disconnect_future.result()
    print("Disconnected!")