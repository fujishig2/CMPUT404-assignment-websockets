#!/usr/bin/env python
# coding: utf-8
# Copyright (c) 2013-2014 Abram Hindle
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import flask
from flask import Flask, request
from flask_sockets import Sockets
import gevent
from gevent import queue
import time
import json
import os

app = Flask(__name__)
sockets = Sockets(app)
app.debug = True

# Setup a client class with a queue. If the queue has any data put into it, it will be sent to
# the client.
class Client:
    def __init__(self):
        self.queue = queue.Queue()

    def put(self, v):
        self.queue.put_nowait(v)

    def get(self):
        return self.queue.get()

# Setup a global list of clients
clients = list()

class World:
    def __init__(self):
        self.clear()
        # we've got listeners now!
        self.listeners = list()
        
    def add_set_listener(self, listener):
        self.listeners.append( listener )

    def update(self, entity, key, value):
        entry = self.space.get(entity,dict())
        entry[key] = value
        self.space[entity] = entry
        self.update_listeners( entity )

    def set(self, entity, data):
        self.space[entity] = data
        self.update_listeners( entity )

    def update_listeners(self, entity):
        '''update the set listeners'''
        for listener in self.listeners:
            listener(entity, self.get(entity))

    def clear(self):
        for client in clients:
            client.put("clear world")
        self.space = dict()

    def get(self, entity):
        return self.space.get(entity,dict())
    
    def world(self):
        return self.space

myWorld = World()        

# Put the entity being listened to into the client queue
def set_listener( entity, data ):
    for client in clients:
        client.put(json.dumps({entity: data}))

# Initialize the add_set_listener to be a function called
# whenever a listener is being updated.
myWorld.add_set_listener( set_listener )
     
# Home page. This is the usable draw board
@app.route("/")
def index():
    return flask.send_from_directory('static','index.html')

# Websocket client message handler.
def read_ws(ws,client):
    try:
        while True:
            # Receive the message from the client
            msg = ws.receive()
            if (msg is not None):
                # Check to see if the message is a get world command
                if msg != "get world":
                    # Parse the message and add it to the world.
                    parsed = json.loads(msg)
                    for key in parsed:
                        # Make sure we aren't adding any duplicates. It could potentially happen
                        # if many different clients are making requests at the exact same time.
                        if myWorld.get(key):
                            myWorld.set("X" + str(len(myWorld.world())), parsed[key])
                        else:
                            myWorld.set(key, parsed[key])
                # If this is a get world command, simply return the world to the
                # client which sent the request in.
                else:
                    client.put(json.dumps(myWorld.world()))
            else:
                break
    except:
        '''Done'''

# Websocket subscribe handler. Also the server to client message handler.
@sockets.route('/subscribe')
def subscribe_socket(ws):
    # Create new client and add it to the greenlet
    client = Client()
    clients.append(client)
    g = gevent.spawn( read_ws, ws, client )    
    try:
        # Send messages to the client by popping from the queue of
        # entities and sending those entities to the client.
        while True:
            # block here
            msg = client.get()
            ws.send(msg)
    except Exception as e:# WebSocketError as e:
        print("WS Error %s" % e)
    finally:
        clients.remove(client)
        gevent.kill(g)
    return None


# I give this to you, this is how you get the raw body/data portion of a post in flask
# this should come with flask but whatever, it's not my project.
def flask_post_json():
    '''Ah the joys of frameworks! They do so much work for you
       that they get in the way of sane operation!'''
    if (request.json != None):
        return request.json
    elif (request.data != None and request.data.decode("utf8") != u''):
        return json.loads(request.data.decode("utf8"))
    else:
        return json.loads(request.form.keys()[0])

# Entity API (Post/Put only). This is the API which handles entity calls.
@app.route("/entity/<entity>", methods=['POST','PUT'])
def update(entity):
    try:
        # Post handler. Create a new entity
        if request.method == "POST":
            req_json = flask_post_json()
            # Check to see if the entity already exists. If it does exist, 
            # create a new entity with name X(length).
            if myWorld.get(entity) != {}:
                entity = "X" + str(len(myWorld.world()))
            myWorld.set(entity, req_json)
            # Return the entity using a direct call to the world to ensure that we are sending
            # the worlds data.
            return app.response_class(response=json.dumps(myWorld.get(entity)), mimetype='application/json')

        # Put handler. Update an existing entity
        elif request.method == "PUT":
            req_json = flask_post_json()
            # Update the entitys attributes given in the update request
            for key in req_json:
                myWorld.update(entity, key, req_json[key])
            # Return the entity using a direct call to the world to ensure that we are sending
            # the worlds data.
            return app.response_class(response=json.dumps(myWorld.get(entity)), mimetype='application/json')
        else:
            return "Method not handled.", 405

    # Error handler
    except:
        return "Cannot update entity.", 400
    return None

# World API (Post/Get only). This API handles all calls to the world.
@app.route("/world", methods=['POST','GET'])    
def world():
    # Get handler. Returns the current world
    if request.method == 'GET':
        return app.response_class(response=json.dumps(myWorld.world()), mimetype='application/json')

    # Post handler. Sets the world to be the world given in the post body
    elif request.method == 'POST':
        try:
            req_json = flask_post_json()
            # Clear the world
            world.clear()
            # Set the world to be the world found in the post request
            for key in req_json:
                world.set(key, req_json[key])
            # Return the new world
            return app.response_class(response=json.dumps(myWorld.world()), mimetype='application/json')
        # Error handler
        except:
            return "Cannot update world.", 400
        
    else:
        return "Method not handled.", 405

# Entity Get handler. Gets a given entity's information
@app.route("/entity/<entity>")    
def get_entity(entity):
    if request.method == 'GET':
        return app.response_class(response=json.dumps(myWorld.get(entity)), mimetype='application/json')
    return "Method not handled.", 405

# Clear Post/Get API. Clears the world of all its contents.
@app.route("/clear", methods=['POST','GET'])
def clear():
    '''Clear the world out!'''
    if request.method == 'GET' or request.method == 'POST':
        try:
            # Clear the world
            myWorld.clear()
            # Return the cleared world
            return app.response_class(response=json.dumps(myWorld.world()), mimetype='application/json')
        except:
            return "Cannot clear world.", 400
    return "Method not handled.", 405



if __name__ == "__main__":
    ''' This doesn't work well anymore:
        pip install gunicorn
        and run
        gunicorn -k flask_sockets.worker sockets:app
    '''
    app.run()
