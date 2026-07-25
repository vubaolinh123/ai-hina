export interface MicrophoneCapture {
  chunks: Float32Array[];
  sampleCount: number;
  sampleRate: number;
}

export interface MicrophoneRecorderOptions {
  maximumSeconds?: number;
  chunkNotificationMilliseconds?: number;
  onChunk?: (capture: Readonly<MicrophoneCapture>) => void;
  onMaximumDuration?: () => void;
}

export class MicrophoneRecorder {
  private readonly chunks: Float32Array[] = [];
  private sampleCount = 0;
  private stopping = false;
  private lastNotifiedSampleCount = 0;

  private constructor(
    private readonly stream: MediaStream,
    private readonly context: AudioContext,
    private readonly source: MediaStreamAudioSourceNode,
    private readonly processor: AudioWorkletNode,
    private readonly sink: GainNode,
    private readonly options: MicrophoneRecorderOptions,
  ) {}

  static async start(options: MicrophoneRecorderOptions = {}): Promise<MicrophoneRecorder> {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("E_DESKTOP_MIC_UNAVAILABLE: thiết bị không cung cấp microphone");
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });
    const context = new window.AudioContext();
    try {
      await context.audioWorklet.addModule(
        new URL("hina-audio-capture-worklet.js", document.baseURI).href,
      );
      const source = context.createMediaStreamSource(stream);
      const processor = new AudioWorkletNode(context, "hina-audio-capture", {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [1],
      });
      const sink = context.createGain();
      sink.gain.value = 0;
      const recorder = new MicrophoneRecorder(
        stream,
        context,
        source,
        processor,
        sink,
        options,
      );
      processor.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        recorder.acceptChunk(new Float32Array(event.data));
      };
      source.connect(processor);
      processor.connect(sink);
      sink.connect(context.destination);
      await context.resume();
      return recorder;
    } catch (error) {
      stream.getTracks().forEach((track) => track.stop());
      await context.close();
      throw error;
    }
  }

  private acceptChunk(chunk: Float32Array): void {
    if (this.stopping || chunk.length === 0) return;
    this.chunks.push(chunk);
    this.sampleCount += chunk.length;
    const notificationSamples = Math.max(
      1,
      Math.round(
        this.context.sampleRate
        * (this.options.chunkNotificationMilliseconds ?? 250)
        / 1_000,
      ),
    );
    if (
      this.options.onChunk
      && this.sampleCount - this.lastNotifiedSampleCount >= notificationSamples
    ) {
      this.lastNotifiedSampleCount = this.sampleCount;
      this.options.onChunk(this.snapshot());
    }
    const elapsedSeconds = this.sampleCount / this.context.sampleRate;
    const maximumSeconds = this.options.maximumSeconds ?? 30;
    if (elapsedSeconds >= maximumSeconds) {
      this.options.onMaximumDuration?.();
    }
  }

  snapshot(): MicrophoneCapture {
    return {
      chunks: [...this.chunks],
      sampleCount: this.sampleCount,
      sampleRate: this.context.sampleRate,
    };
  }

  async stop(): Promise<MicrophoneCapture> {
    if (this.stopping) return this.snapshot();
    this.stopping = true;
    this.processor.port.onmessage = null;
    this.source.disconnect();
    this.processor.disconnect();
    this.sink.disconnect();
    this.stream.getTracks().forEach((track) => track.stop());
    const capture = this.snapshot();
    await this.context.close();
    return capture;
  }
}
