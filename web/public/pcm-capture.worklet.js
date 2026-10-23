// Runs on the audio rendering thread. Forwards raw channel data to the page, which
// keeps the samples until push-to-talk is released.
class PcmCapture extends AudioWorkletProcessor {
  process(inputs) {
    const channels = inputs[0];
    if (channels && channels.length > 0) {
      this.port.postMessage(channels.map((channel) => channel.slice()));
    }
    return true;
  }
}

registerProcessor("pcm-capture", PcmCapture);
