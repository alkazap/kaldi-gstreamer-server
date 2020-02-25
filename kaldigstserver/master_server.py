#!/usr/bin/env python
#
# Copyright 2013 Tanel Alumae

"""
Reads speech data via websocket requests, sends it to Redis, waits for results from Redis and
forwards to client via websocket
"""
"""
Note: Redis is an in-memory data structure store, used as a database, cache and message broker
(which also does not seem to be used here...)
-@alkazap
"""
import sys
import logging
import json
import codecs
import os.path
import uuid
import time
import threading
import functools
from Queue import Queue

import tornado.ioloop
import tornado.options
import tornado.web
import tornado.websocket
import tornado.gen
import tornado.concurrent
import concurrent.futures
import settings
import common


class Application(tornado.web.Application):
    """
    Responsible for global configuration, including the routing table that maps requests to handlers
    """
    def __init__(self):
        # Application settings:
        settings = dict(
            # Authentication and security settings:
            cookie_secret="43oETzKXQAGaYdkL5gEmGeJJFuYh7EQnp2XdTP1o/Vo=", 
            # used by RequestHandler.get_secure_cookie() and set_secure_cookie() to sign cookies
            # to generate cookie_secret value (unique, random string):
            # >>> import base64, uuid
            # >>> base64.b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes)            
            xsrf_cookies=False, # if True, Cross-site request forgery protection will be enabled
            
            # Template settings:
            autoescape=None, # controls automatic escaping for templates (raplacing &, <, > with their corresponding HTML entities)
            template_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"), # directory containing template files

            # Static file settings:
            static_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"), # directory from which static files will be served
        )

        # The routing table is a list of URLSpec objects (or tuples), each of which contains (at least) a regular expression and a handler class
        handlers = [
            (r"/", MainHandler),
            (r"/client/ws/speech", DecoderSocketHandler),
            (r"/client/ws/status", StatusSocketHandler),
            (r"/client/dynamic/reference", ReferenceHandler),
            (r"/client/dynamic/recognize", HttpChunkedRecognizeHandler),
            (r"/worker/ws/speech", WorkerSocketHandler),
            (r"/client/static/(.*)", tornado.web.StaticFileHandler, {'path': settings["static_path"]}),
            # third element supplies the initialization arguments which will be passed to RequestHandler.initialize
        ]
        tornado.web.Application.__init__(self, handlers, **settings)
        self.available_workers = set()
        self.status_listeners = set() # Client Web Sockets
        self.num_requests_processed = 0

    def send_status_update_single(self, ws):
        """
        Send number of workers available and number of requests processed to a client
        """
        status = dict(num_workers_available=len(self.available_workers), num_requests_processed=self.num_requests_processed)
        ws.write_message(json.dumps(status)) # send JSON formatted message (str) to the client of this Web Socket

    def send_status_update(self):
        """
        Send status update to each listening client web socket
        """
        for ws in self.status_listeners:
            self.send_status_update_single(ws)

    def save_reference(self, content_id, content):
        """
        Used by ReferenceHandler()
        """
        refs = {}
        try:
            with open("reference-content.json") as f: # where does reference-content.json come from?
                refs = json.load(f)
        except:
            pass
        refs[content_id] = content
        with open("reference-content.json", "w") as f:
            json.dump(refs, f, indent=2)


class MainHandler(tornado.web.RequestHandler):
    def get(self):
        current_directory = os.path.dirname(os.path.abspath(__file__))
        parent_directory = os.path.join(current_directory, os.pardir)
        readme = os.path.join(parent_directory, "README.md")
        self.render(readme) # load a Template by name and render it with the given arguments


def content_type_to_caps(content_type):
    """
    Converts MIME-style raw audio content type specifier to GStreamer CAPS (capabilities) string
    Used by HttpChunkedRecognizeHandler()
    Example: 
        input str = "audio/x-raw;rate=16000;format=S16LE;channels=1;layout=interleaved"
        output_str = "audio/x-raw, rate=16000, format=S16LE, channels=1, layout=interleaved"
    """
    default_attributes= {"rate": 16000, "format" : "S16LE", "channels" : 1, "layout" : "interleaved"}
    media_type, _, attr_string = content_type.replace(";", ",").partition(",") # replace() replaces all ";" with ","
    # media_type = str before ","; _ = ","; attr_string = str after ","
    if media_type in ["audio/x-raw", "audio/x-raw-int"]:
        media_type = "audio/x-raw"
        attributes = default_attributes
        for (key,_,value) in [p.partition("=") for p in attr_string.split(",")]: # split() turns str into a list
            attributes[key.strip()] = value.strip() # strip() removes spaces at the beginning and the end
        return "%s, %s" % (media_type, ", ".join(["%s=%s" % (key, value) for (key,value) in attributes.iteritems()]))
    else:
        return content_type


@tornado.web.stream_request_body
class HttpChunkedRecognizeHandler(tornado.web.RequestHandler):
    """
    Provides a HTTP POST/PUT interface supporting chunked transfer requests, similar to that provided by
    http://github.com/alumae/ruby-pocketsphinx-server.
    """
    def prepare(self):
        self.id = str(uuid.uuid4()) # uuid4() creates a random UUID object (unique identifier)
        self.final_hyp = ""
        self.final_result_queue = Queue() # multi-producer, multi-consumer queue, useful in threaded programming
        self.user_id = self.request.headers.get("device-id", "none")
        self.content_id = self.request.headers.get("content-id", "none")
        logging.info("%s: OPEN: user='%s', content='%s'" % (self.id, self.user_id, self.content_id))
        self.worker = None
        self.error_status = 0
        self.error_message = None
        # Waiter thread for final hypothesis:
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1) # asynch (new thread) executor for get_final_hyp()
        try:
            self.worker = self.application.available_workers.pop() # remove and return an arbitrary worker
            self.application.send_status_update()
            logging.info("%s: Using worker %s" % (self.id, self.__str__()))
            self.worker.set_client_socket(self) # WorkerSocketHandler()

            content_type = self.request.headers.get("Content-Type", None) # DecoderSocketHandler()
            if content_type:
                content_type = content_type_to_caps(content_type)
                logging.info("%s: Using content type: %s" % (self.id, content_type))

            self.worker.write_message(json.dumps(dict(id=self.id, content_type=content_type, user_id=self.user_id, content_id=self.content_id)))
        except KeyError:
            logging.warn("%s: No worker available for client request" % self.id)
            self.set_status(503) # Sets reponse status to Service Unavailable Error
            self.finish("No workers available") # Finishes this response, ending the HTTP request

    def data_received(self, chunk):
        """
        Called whenever data is available
        """
        assert self.worker is not None
        logging.debug("%s: Forwarding client message of length %d to worker" % (self.id, len(chunk)))
        self.worker.write_message(chunk, binary=True)

    def post(self, *args, **kwargs):
        self.end_request(args, kwargs)

    def put(self, *args, **kwargs):
        self.end_request(args, kwargs)

    @tornado.concurrent.run_on_executor
    def get_final_hyp(self):
        logging.info("%s: Waiting for final result..." % self.id)
        return self.final_result_queue.get(block=True)
        # Remove and return an item from the queue
        # block if necessary until an item is available

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def end_request(self, *args, **kwargs):
        logging.info("%s: Handling the end of chunked recognize request" % self.id)
        assert self.worker is not None
        self.worker.write_message("EOS", binary=True)
        logging.info("%s: yielding..." % self.id)
        hyp = yield self.get_final_hyp()
        if self.error_status == 0:
            logging.info("%s: Final hyp: %s" % (self.id, hyp))
            response = {"status" : 0, "id": self.id, "hypotheses": [{"utterance" : hyp}]}
            self.write(response)
        else:
            logging.info("%s: Error (status=%d) processing HTTP request: %s" % (self.id, self.error_status, self.error_message))
            response = {"status" : self.error_status, "id": self.id, "message": self.error_message}
            self.write(response)
        self.application.num_requests_processed += 1
        self.application.send_status_update()
        self.worker.set_client_socket(None)
        self.worker.close()
        self.finish()
        logging.info("Everything done")

    def send_event(self, event):
        event_str = str(event)
        if len(event_str) > 100:
            event_str = event_str[:97] + "..."
        logging.info("%s: Receiving event %s from worker" % (self.id, event_str))
        if event["status"] == 0 and ("result" in event):
            try:
                if len(event["result"]["hypotheses"]) > 0 and event["result"]["final"]:
                    if len(self.final_hyp) > 0:
                        self.final_hyp += " "
                    self.final_hyp += event["result"]["hypotheses"][0]["transcript"]
            except:
                e = sys.exc_info()[0]
                logging.warn("Failed to extract hypothesis from recognition result:" + e)
        elif event["status"] != 0:
            self.error_status = event["status"]
            self.error_message = event.get("message", "")

    def close(self):
        logging.info("%s: Receiving 'close' from worker" % (self.id))
        self.final_result_queue.put(self.final_hyp)


class ReferenceHandler(tornado.web.RequestHandler):
    def post(self, *args, **kwargs):
        content_id = self.request.headers.get("Content-Id")
        if content_id:
            content = codecs.decode(self.request.body, "utf-8")
            user_id = self.request.headers.get("User-Id", "")
            self.application.save_reference(content_id, dict(content=content, user_id=user_id, time=time.strftime("%Y-%m-%dT%H:%M:%S")))
            logging.info("Received reference text for content %s and user %s" % (content_id, user_id))
            self.set_header('Access-Control-Allow-Origin', '*')
        else:
            self.set_status(400) # Bad Request Error
            self.finish("No Content-Id specified")

    def options(self, *args, **kwargs):
        # CORS (Cross-origin resource sharing) server response headers:
        self.set_header('Access-Control-Allow-Origin', '*') # allows all domains
        self.set_header('Access-Control-Allow-Methods', 'POST, OPTIONS') # allowed request methods
        self.set_header('Access-Control-Max-Age', 1000) # max num of secs the results can be cached
        self.set_header('Access-Control-Allow-Headers',  'origin, x-csrftoken, content-type, accept, User-Id, Content-Id') 
        # allowed request headers, '*' is not valid


class StatusSocketHandler(tornado.websocket.WebSocketHandler):
    # needed for Tornado 4.0
    def check_origin(self, origin):
        return True

    def open(self):
        logging.info("New status listener")
        self.application.status_listeners.add(self)
        self.application.send_status_update_single(self)

    def on_close(self):
        logging.info("Status listener left")
        self.application.status_listeners.remove(self)


class WorkerSocketHandler(tornado.websocket.WebSocketHandler):
    """
    Handles worker connection
    """
    def __init__(self, application, request, **kwargs):
        tornado.websocket.WebSocketHandler.__init__(self, application, request, **kwargs)
        self.client_socket = None

    # needed for Tornado 4.0
    def check_origin(self, origin):
        return True

    def open(self):
        """
        Adds new worker
        """
        self.client_socket = None
        self.application.available_workers.add(self)
        logging.info("New worker available " + self.__str__())
        self.application.send_status_update()

    def on_close(self):
        """
        Removes a worker
        """
        logging.info("Worker " + self.__str__() + " leaving")
        self.application.available_workers.discard(self)
        if self.client_socket:
            self.client_socket.close()
        self.application.send_status_update()

    def on_message(self, message):
        """
        Send event to decoder client
        """
        assert self.client_socket is not None
        event = json.loads(message)
        self.client_socket.send_event(event)

    def set_client_socket(self, client_socket):
        """
        Adds decoder client socket
        """
        self.client_socket = client_socket


class DecoderSocketHandler(tornado.websocket.WebSocketHandler):
    """
    Handles client connection
    """
    # needed for Tornado 4.0
    def check_origin(self, origin):
        """
        Accept all cross-origin traffic
        """
        return True

    def send_event(self, event):
        event["id"] = self.id
        event_str = str(event)
        if len(event_str) > 100:
            event_str = event_str[:97] + "..."
        logging.info("%s: Sending event %s to client" % (self.id, event_str))
        self.write_message(json.dumps(event))

    def open(self):
        """
        Connects to available worker
        """
        self.id = str(uuid.uuid4())
        logging.info("%s: OPEN" % (self.id))
        logging.info("%s: Request arguments: %s" % (self.id, " ".join(["%s=\"%s\"" % (a, self.get_argument(a)) for a in self.request.arguments])))
        # self.request.arguments - GET/POST args, names - strs, args - byte strs
        # self.get_atgument(a) - return arg vals (a is arg name) as unicode str
        self.user_id = self.get_argument("user-id", "none", True)
        self.content_id = self.get_argument("content-id", "none", True)
        self.worker = None
        try:
            self.worker = self.application.available_workers.pop()
            self.application.send_status_update()
            logging.info("%s: Using worker %s" % (self.id, self.__str__()))
            self.worker.set_client_socket(self)

            content_type = self.get_argument("content-type", None, True)
            if content_type:
                logging.info("%s: Using content type: %s" % (self.id, content_type))

            self.worker.write_message(json.dumps(dict(id=self.id, content_type=content_type, user_id=self.user_id, content_id=self.content_id)))
        except KeyError:
            logging.warn("%s: No worker available for client request" % self.id)
            event = dict(status=common.STATUS_NOT_AVAILABLE, message="No decoder available, try again later")
            self.send_event(event)
            self.close()

    def on_connection_close(self):
        """
        Increments number of processed requests
        Closes worker connection
        """
        logging.info("%s: Handling on_connection_close()" % self.id)
        self.application.num_requests_processed += 1
        self.application.send_status_update()
        if self.worker:
            try:
                self.worker.set_client_socket(None)
                logging.info("%s: Closing worker connection" % self.id)
                self.worker.close()
            except:
                pass

    def on_message(self, message):
        """
        Sends message to worker
        """
        assert self.worker is not None
        logging.info("%s: Forwarding client message (%s) of length %d to worker" % (self.id, type(message), len(message)))
        if isinstance(message, unicode):
            self.worker.write_message(message, binary=False)
        else:
            self.worker.write_message(message, binary=True)


def main():
    # Logging:
    # %(levelname)8s - text logging level for the message: 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'
    # %(asctime)s - human-readable time
    # %(message)s - the logged message
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)8s %(asctime)s %(message)s ")
    logging.debug('Starting up server')
    
    # Parses global options from the command line
    from tornado.options import define, options
    # The following line is in settings.py and not here... why?
    # define("port", default=8888, help="run on the given port", type=int)
    define("certfile", default="", help="certificate file for secured SSL connection") # "mydomain.crt"
    define("keyfile", default="", help="key file for secured SSL connection") # "mydomain.key"

    tornado.options.parse_command_line()

    # Initializes web application (request handlers)
    app = Application()
    if options.certfile and options.keyfile:
        ssl_options = {
          "certfile": options.certfile,
          "keyfile": options.keyfile,
        }
        logging.info("Using SSL for serving requests") 
        app.listen(options.port, ssl_options=ssl_options) # Starts an HTTP server for this app
    else:
        app.listen(options.port)
    
    #I/O event loop for non-blocking sockets
    tornado.ioloop.IOLoop.instance().start()


if __name__ == "__main__":
    main()
