# Info about Kaldi's GStreamer plugin

## Make sure that the GST plugin path includes Kaldi's `/src/gst-plugin` dir

`$ export GST_PLUGIN_PATH=~/kaldi/src/gst-plugin`

## Print info

`$ gst-inspect-1.0 onlinegmmdecodefaster`

```
Factory Details:
  Rank                     none (0)
  Long-name                OnlineGmmDecodeFaster
  Klass                    Speech/Audio
  Description              Convert speech to text
  Author                   Tanel Alumae <tanel.alumae@phon.ioc.ee>

Plugin Details:
  Name                     onlinegmmdecodefaster
  Description              Online speech recognizer based on the Kaldi toolkit
  Filename                 /home/alena/kaldi/src/gst-plugin/libgstonlinegmmdecodefaster.so
  Version                  1.0
  License                  LGPL
  Source module            myfirstonlinegmmdecodefaster
  Binary package           Kaldi
  Origin URL               http://kaldi.sourceforge.net/

GObject
 +----GInitiallyUnowned
       +----GstObject
             +----GstElement
                   +----GstOnlineGmmDecodeFaster

Pad Templates:
  SINK template: 'sink'
    Availability: Always
    Capabilities:
      audio/x-raw
                 format: S16LE
               channels: 1
                   rate: 16000

  SRC template: 'src'
    Availability: Always
    Capabilities:
      text/x-raw
                 format: { utf8 }


Element Flags:
  no flags set

Element Implementation:
  Has change_state() function: 0x7f5a2cbf3200

Element has no clocking capabilities.
Element has no URI handling capabilities.

Pads:
  SINK: 'sink'
    Pad Template: 'sink'
  SRC: 'src'
    Pad Template: 'src'

Element Properties:
  name                : The name of the object
                        flags: readable, writable
                        String. Default: "onlinegmmdecodefaster0"
  parent              : The parent of the object
                        flags: readable, writable
                        Object of type "GstObject"
  silent              : Determines whether incoming audio is sent to the decoder or not
                        flags: readable, writable
                        Boolean. Default: false
  model               : Filename of the acoustic model
                        flags: readable, writable
                        String. Default: "final.mdl"
  fst                 : Filename of the HCLG FST
                        flags: readable, writable
                        String. Default: "HCLG.fst"
  word-syms           : Name of word symbols file (typically words.txt)
                        flags: readable, writable
                        String. Default: "words.txt"
  silence-phones      : Colon-separated IDs of silence phones, e.g. '1:2:3:4:5'
                        flags: readable, writable
                        String. Default: "1:2:3:4:5"
  lda-mat             : Filename of the LDA transform data
                        flags: readable, writable
                        String. Default: ""
  beam                : Decoding beam.  Larger->slower, more accurate.
                        flags: readable, writable
                        Float. Range:    1.175494e-38 -    3.402823e+38 Default:              16 
  max-active          : Decoder max active states.  Larger->slower; more accurate
                        flags: readable, writable
                        Integer. Range: -2147483648 - 2147483647 Default: 2147483647 
  min-active          : Decoder min active states (don't prune if #active less than this).
                        flags: readable, writable
                        Integer. Range: -2147483648 - 2147483647 Default: 20 
  beam-delta          : Increment used in decoder [obscure setting]
                        flags: readable, writable
                        Float. Range:    1.175494e-38 -    3.402823e+38 Default:             0.5 
  hash-ratio          : Setting used in decoder to control hash behavior
                        flags: readable, writable
                        Float. Range:    1.175494e-38 -    3.402823e+38 Default:               2 
  rt-min              : Approximate minimum decoding run time factor
                        flags: readable, writable
                        Float. Range:    1.175494e-38 -    3.402823e+38 Default:             0.7 
  rt-max              : Approximate maximum decoding run time factor
                        flags: readable, writable
                        Float. Range:    1.175494e-38 -    3.402823e+38 Default:            0.75 
  update-interval     : Beam update interval in frames
                        flags: readable, writable
                        Integer. Range: -2147483648 - 2147483647 Default: 3 
  beam-update         : Beam update rate
                        flags: readable, writable
                        Float. Range:    1.175494e-38 -    3.402823e+38 Default:            0.01 
  max-beam-update     : Max beam update rate
                        flags: readable, writable
                        Float. Range:    1.175494e-38 -    3.402823e+38 Default:            0.05 
  inter-utt-sil       : Maximum # of silence frames to trigger new utterance
                        flags: readable, writable
                        Integer. Range: -2147483648 - 2147483647 Default: 50 
  max-utt-length      : If the utterance becomes longer than this number of frames, shorter silence is acceptable as an utterance separator
                        flags: readable, writable
                        Integer. Range: -2147483648 - 2147483647 Default: 1500 
  batch-size          : Number of feature vectors processed w/o interruption
                        flags: readable, writable
                        Integer. Range: -2147483648 - 2147483647 Default: 27 
  num-tries           : Number of successive repetitions of timeout before we terminate stream
                        flags: readable, writable
                        Integer. Range: -2147483648 - 2147483647 Default: 5 
  left-context        : Number of frames of left context
                        flags: readable, writable
                        Integer. Range: -2147483648 - 2147483647 Default: 4 
  right-context       : Number of frames of right context
                        flags: readable, writable
                        Integer. Range: -2147483648 - 2147483647 Default: 4 
  acoustic-scale      : Scaling factor for acoustic likelihoods
                        flags: readable, writable
                        Float. Range:    1.175494e-38 -    3.402823e+38 Default:      0.07692308 
  cmn-window          : Number of feat. vectors used in the running average CMN calculation
                        flags: readable, writable
                        Integer. Range: -2147483648 - 2147483647 Default: 600 
  min-cmn-window      : Minumum CMN window used at start of decoding (adds latency only at start)
                        flags: readable, writable
                        Integer. Range: -2147483648 - 2147483647 Default: 100 

Element Signals:
  "hyp-word" :  void user_function (GstElement* object,
                                    gchararray arg0,
                                    gpointer user_data);
```