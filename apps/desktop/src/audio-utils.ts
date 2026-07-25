export function mergeAudioChunks(chunks: Float32Array[], sampleCount: number): Float32Array {
  const merged = new Float32Array(sampleCount);
  let offset = 0;
  for (const chunk of chunks) {
    const remaining = Math.max(0, sampleCount - offset);
    merged.set(chunk.subarray(0, remaining), offset);
    offset += chunk.length;
    if (offset >= sampleCount) break;
  }
  return merged;
}

export function resampleAudio(
  samples: Float32Array,
  sourceRate: number,
  targetRate: number,
): Float32Array {
  if (sourceRate === targetRate) return samples;
  const targetLength = Math.max(1, Math.round(samples.length * targetRate / sourceRate));
  const result = new Float32Array(targetLength);
  for (let index = 0; index < targetLength; index += 1) {
    const sourcePosition = index * (samples.length - 1) / Math.max(1, targetLength - 1);
    const lower = Math.floor(sourcePosition);
    const upper = Math.min(samples.length - 1, lower + 1);
    const weight = sourcePosition - lower;
    const lowerSample = samples[lower] ?? 0;
    const upperSample = samples[upper] ?? 0;
    result[index] = lowerSample * (1 - weight) + upperSample * weight;
  }
  return result;
}

export function encodePcmWav(samples: Float32Array, sampleRate: number): Uint8Array {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeAscii = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index += 1) {
      view.setUint8(offset + index, value.charCodeAt(index));
    }
  };
  writeAscii(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeAscii(8, "WAVE");
  writeAscii(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let index = 0; index < samples.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, samples[index] ?? 0));
    view.setInt16(44 + index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return new Uint8Array(buffer);
}
