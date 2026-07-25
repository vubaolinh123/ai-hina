class HinaAudioCaptureProcessor extends AudioWorkletProcessor {
  process(inputs, outputs) {
    const input = inputs[0]?.[0];
    if (input?.length) {
      const chunk = input.slice().buffer;
      this.port.postMessage(chunk, [chunk]);
    }
    const output = outputs[0]?.[0];
    if (output) {
      output.fill(0);
    }
    return true;
  }
}

registerProcessor("hina-audio-capture", HinaAudioCaptureProcessor);
