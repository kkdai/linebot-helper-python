/**
 * Audio Worklet Processor for capturing and processing audio
 */

class AudioCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.bufferSize = 512; // 32ms at 16kHz — per Gemini best practices (20-40ms chunks)
    this.buffer = new Float32Array(this.bufferSize);
    this.bufferIndex = 0;
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];

    if (input && input.length > 0) {
      const inputChannel = input[0];

      for (let i = 0; i < inputChannel.length; i++) {
        this.buffer[this.bufferIndex++] = inputChannel[i];

        if (this.bufferIndex >= this.bufferSize) {
          this.port.postMessage({
            type: 'audio',
            data: this.buffer.slice(),
          });
          this.bufferIndex = 0;
        }
      }
    }

    return true;
  }
}

registerProcessor('audio-capture-processor', AudioCaptureProcessor);
