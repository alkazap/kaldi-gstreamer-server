"""
Created on May 17, 2013

@author: tanel
"""

"""
Annotated on Jan 22, 2019

@author: alkazap

Using Kaldi's OnlineGmmDecodeFaster decoder
"""

import gi

gi.require_version('Gst', '1.0')
from gi.repository import GObject, Gst

GObject.threads_init() # initialize thread support in PyGObject
Gst.init(None) # initialize GStreamer
import logging
import thread
import os

logger = logging.getLogger(__name__)

import pdb

class DecoderPipeline(object):
    def __init__(self, conf={}):
        logger.info("Creating decoder using conf: %s" % conf)
        self.use_cutter = conf.get("use-vad", False) # VAD - Voice Activity Detection
        # if true, uses energy-based VAD to apply frame weights for i-vector stats extraction
        self.create_pipeline(conf)
        self.outdir = conf.get("out-dir", None)
        if self.outdir:
            if not os.path.exists(self.outdir):
                os.mkdir(self.outdir)
            elif not os.path.isdir(self.outdir):
                raise Exception("Output directory %s already exists as a file" % self.outdir)

        # Will be assigned by worker.py:
        self.word_handler = None
        self.eos_handler = None
        self.request_id = "<undefined>"


    def create_pipeline(self, conf):
        """
        PIPELINE:
            if use_cutter:
                [appsrc]->[decodebin]->[cutter]->[audioconvert]->[audioresample]->[tee(src1)]->[queue1]->[filesink]
                                                                                [tee(src2)]->[queue2]->[asr]->[fakesink]
            else:
                [appsrc]->[decodebin]->[audioconvert]->[audioresample]->[tee(src1)]->[queue1]->[filesink]
                                                                        [tee(src2)]->[queue2]->[asr]->[fakesink]
        """
        # Create new GStreamer elements 
        # Gst.ElementFactory.make(type of element to create, unique instance name)
        self.appsrc = Gst.ElementFactory.make("appsrc", "appsrc") # used by app to insert data into pipeline
        self.decodebin = Gst.ElementFactory.make("decodebin", "decodebin") # constructs a decoding pipeline
        self.audioconvert = Gst.ElementFactory.make("audioconvert", "audioconvert") # converts raw audio buffers between various possible formats
        self.audioresample = Gst.ElementFactory.make("audioresample", "audioresample")  # resamples raw audio buffers to different sample rates
        # using a configurable windowing function to enhance quality
        self.tee = Gst.ElementFactory.make("tee", "tee") # split data to multiple pads (branchcning the data flow)
        self.queue1 = Gst.ElementFactory.make("queue", "queue1") # queue data to provide separate threads for each branch
        self.filesink = Gst.ElementFactory.make("filesink", "filesink") # write incoming data to a file in the local file system
        self.queue2 = Gst.ElementFactory.make("queue", "queue2")
        self.cutter = Gst.ElementFactory.make("cutter", "cutter") # analyses the audio signal for periods of silence
        # the start and end of silence is signalled by bus messages named "cutter" that contain two fields:
        # "timestamp": the timestamp of the buffer that triggered the message
        # "above": TRUE for begin of silence and FALSE for end of silence
        self.asr = Gst.ElementFactory.make("onlinegmmdecodefaster", "asr") # plugin that acts as a filter, 
        # taking raw audio as input and producing recognized word as output
        self.fakesink = Gst.ElementFactory.make("fakesink", "fakesink") # dummy sink that swallows everything

        if not self.asr:
            print >> sys.stderr, "ERROR: Couldn't create the onlinegmmdecodefaster element!"
            gst_plugin_path = os.environ.get("GST_PLUGIN_PATH")
            if gst_plugin_path:
                print >> sys.stderr, \
                    "Couldn't find onlinegmmdecodefaster element at %s. " \
                    "If it's not the right path, try to set GST_PLUGIN_PATH to the right one, and retry. " \
                    "You can also try to run the following command: " \
                    "'GST_PLUGIN_PATH=%s gst-inspect-1.0 onlinegmmdecodefaster'." \
                    % (gst_plugin_path, gst_plugin_path)
            else:
                print >> sys.stderr, \
                    "The environment variable GST_PLUGIN_PATH wasn't set or it's empty. " \
                    "Try to set GST_PLUGIN_PATH environment variable, and retry."
            sys.exit(-1);

        # Customize properties 
        # set_property(property-name, property-value)
        for (key, val) in conf.get("decoder", {}).iteritems():
            logger.info("Setting decoder property: %s = %s" % (key, val))
            self.asr.set_property(key, val) # set onlinegmmdecodefaster properties from conf.yaml
            # run 'gst-inspect-1.0 onlinegmmdecodefaster' for details

        self.appsrc.set_property("is-live", True) # whether to act as a live source (default: false)
        self.filesink.set_property("location", "/dev/null") # location of the file to write (default: null)
        self.cutter.set_property("leaky", False) # do we leak buffers when below threshold? (default: false)
        self.cutter.set_property("pre-length", 1000 * 1000000) # length of pre-recording buffer (default: 200*1000*1000 nanosecs)
        self.cutter.set_property("run-length", 1000 * 1000000) # length of drop below threshold before cut_stop (default: 500*1000*1000 nanosecs)
        self.cutter.set_property("threshold", 0.01) # volume threshold before trigger (default: 0.1)
        if self.use_cutter:
            self.asr.set_property("silent", True) # determines whether incoming audio is sent to the decoder or not (default: false)
        logger.info('Created GStreamer elements')

        # Create the empty pipeline
        self.pipeline = Gst.Pipeline()
        # Build the pipeline (add elements to the pipeline)
        for element in [self.appsrc, self.decodebin, self.audioconvert, self.audioresample, self.tee,
                        self.queue1, self.filesink,
                        self.queue2, self.cutter, self.asr, self.fakesink]:
            logger.debug("Adding %s to the pipeline" % element)
            self.pipeline.add(element)

        # Link elements with each other, following the data flow (src to dst)
        logger.info('Linking GStreamer elements')
        self.appsrc.link(self.decodebin)
        ##self.appsrc.link(self.audioconvert)
        self.decodebin.connect('pad-added', self._connect_decoder)
        if self.use_cutter:
            self.cutter.link(self.audioconvert)
        self.audioconvert.link(self.audioresample)
        self.audioresample.link(self.tee)
        ##self.audioresample.link(self.cutter)
        ##self.cutter.link(self.tee)
        self.tee.link(self.queue1)
        self.queue1.link(self.filesink)
        self.tee.link(self.queue2)
        self.queue2.link(self.asr)
        self.asr.link(self.fakesink)

        # Create bus and connect several handlers
        self.bus = self.pipeline.get_bus() # listen to the bus
        self.bus.add_signal_watch() # adds a bus signal watch to the default main context with the default priority
        # after calling this statement, the bus will emit the 'message' signal for each message posted on the bus
        self.bus.enable_sync_message_emission()# instructs GStreamer to emit the 'sync-message" signal after running the bus's sync handler
        # 'sync-message' signal comes from the thread of whatever object posted the message

        # If the default GLib mainloop integration is used, it is possible 
        # to connect to the 'message' signal on the bus in form of 'message::<type>'
        self.bus.connect('message::eos', self._on_eos)
        self.bus.connect('message::error', self._on_error)
        ##self.bus.connect('message::cutter', self._on_cutter)

        cutter_type = 'sync'
        if cutter_type == 'async': # never enters here...
            self.bus.connect('message::element', self._on_element_message)
        else:
            ##self.bus.set_sync_handler(self.bus.sync_signal_handler)
            self.bus.connect('sync-message::element',  self._on_element_message)
            # calls '_on_element_message' method every time a new message is posted on the bus

        self.asr.connect('hyp-word', self._on_word) # calls '_on_word' method whenever decoding plugin produces a new recognized word

        logger.info("Setting pipeline to READY")
        self.pipeline.set_state(Gst.State.READY)
        logger.info("Set pipeline to READY")

    def _connect_decoder(self, element, pad):
        """
        'pad-added' signal callback
        """
        logger.info("%s: Connecting audio decoder" % self.request_id)
        if self.use_cutter: 
            pad.link(self.cutter.get_static_pad("sink"))
            # link decodebin's src pad to cutter's sink
        else:
            pad.link(self.audioconvert.get_static_pad("sink"))
            # link decodebin's src pad to audioconvert's sink

        logger.info("%s: Connected audio decoder" % self.request_id)

    def _on_element_message(self, bus, message):
        """
        'sync-message::element' signal callback
        """
        if message.has_name("cutter"):
            if message.get_structure().get_value('above'): # for begin of silence
                logger.info("LEVEL ABOVE")
                self.asr.set_property("silent", False) # don't send incoming audio to the decoder
            else: # for end of silence
                logger.info("LEVEL BELOW")
                self.asr.set_property("silent", True) # send incoming audio to the decoder

    def _on_word(self, asr, word):
        """
        'hyp-word' signal callback
        """
        logger.info("%s: Got word: %s" % (self.request_id, word.decode('utf8')))
        if self.word_handler: # from worker.py
            self.word_handler(word)

    def _on_error(self, bus, msg):
        """
        'message::error' signal callback
        """
        self.error = msg.parse_error()
        logger.error(self.error)
        self.finish_request()
        if self.error_handler: # from worker.py
            self.error_handler(self.error[0].message)

    def _on_eos(self, bus, msg):
        """
        'message::eos' signal callback
        """
        logger.info('%s: Pipeline received eos signal' % self.request_id)
        self.finish_request()
        if self.eos_handler:
            self.eos_handler[0](self.eos_handler[1])

    def finish_request(self): # called from worker.py
        """
        Called by '_on_error' and '_on_eos' methods
        """
        logger.info('%s: Finishing request' % self.request_id)
        if self.outdir:
            self.filesink.set_state(Gst.State.NULL)
            self.filesink.set_property('location', "/dev/null")
            self.filesink.set_state(Gst.State.PLAYING)
        self.pipeline.set_state(Gst.State.NULL)
        self.request_id = "<undefined>"

    def init_request(self, id, caps_str): # called from worker.py
        self.request_id = id
        if caps_str and len(caps_str) > 0:
            logger.info("%s: Setting caps to %s" % (self.request_id, caps_str))
            caps = Gst.caps_from_string(caps_str)
            self.appsrc.set_property("caps", caps)
        else:
            ##caps = Gst.caps_from_string(None)
            self.appsrc.set_property("caps", None)
            ##self.pipeline.set_state(Gst.State.READY)
            pass
        ##self.appsrc.set_state(Gst.State.PAUSED)

        if self.outdir:
            self.pipeline.set_state(Gst.State.PAUSED)
            self.filesink.set_state(Gst.State.NULL)
            self.filesink.set_property('location', "%s/%s.raw" % (self.outdir, id))
            self.filesink.set_state(Gst.State.PLAYING)

        ##self.filesink.set_state(Gst.State.PLAYING)
        ##self.decodebin.set_state(Gst.State.PLAYING)
        self.pipeline.set_state(Gst.State.PLAYING)
        self.filesink.set_state(Gst.State.PLAYING)
        # Create a new empty bugger
        buf = Gst.Buffer.new_allocate(None, 0, None)
        # Push empty buffer into the appsrc (to avoid hang on client diconnect)
        self.appsrc.emit("push-buffer", buf)
        logger.info('%s: Pipeline initialized' % (self.request_id))

    def process_data(self, data): # called from worker.py
        """
        Passes data to9 appsrc with the "push-buffer" action signal.
        """
        logger.debug('%s: Pushing buffer of size %d to pipeline' % (self.request_id, len(data)))
        # Create a new empty bugger
        buf = Gst.Buffer.new_allocate(None, len(data), None)
        # Copy data to buffer at 0 offset
        buf.fill(0, data)
        # Push the buffer into the appsrc
        self.appsrc.emit("push-buffer", buf)

    def end_request(self): # called from worker.py
        """
        Emits "end-of-stream" action signal after the app has finished putting data into appsrc.
        After this call, no more buffers can be pushed into appsrc until a flushing seek occurs 
        or the state of the appsrc has gone through READY.
        """
        logger.info("%s: Pushing EOS to pipeline" % self.request_id)
        self.appsrc.emit("end-of-stream")

    def set_word_handler(self, handler): # called from worker.py
        self.word_handler = handler

    def set_eos_handler(self, handler, user_data=None): # called from worker.py
        self.eos_handler = (handler, user_data)

    def set_error_handler(self, handler): # called from worker.py
        self.error_handler = handler

    def cancel(self): # called from worker.py
        """
        Sends EOS (downstream) event to the pipeline. No more data is to be expected to follow 
        without either a STREAM_START event, or a FLUSH_STOP and a SEGMENT event.
        """
        logger.info("%s: Cancelling pipeline" % self.request_id)
        self.pipeline.send_event(Gst.Event.new_eos())
        ##self.asr.set_property("silent", True)
        ##self.pipeline.set_state(Gst.State.NULL)

        ##if (self.pipeline.get_state() == Gst.State.PLAYING):
        ##logger.debug("Sending EOS to pipeline")
        ##self.pipeline.send_event(Gst.Event.new_eos())
        ##self.pipeline.set_state(Gst.State.READY)
        logger.info("%s: Cancelled pipeline" % self.request_id)