(function exposeAudioViseme(root, factory) {
  const api = Object.freeze(factory());
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.HinaAudioViseme = api;
}(typeof globalThis === "object" ? globalThis : this, () => {
  const VISEMES = Object.freeze(["sil", "A", "I", "U", "E", "O"]);
  const SILENCE_RMS = 0.018;

  function classifyAudioViseme(timeDomain, frequency, sampleRate, fftSize) {
    if (
      !(timeDomain instanceof Uint8Array)
      || !(frequency instanceof Uint8Array)
      || !Number.isFinite(sampleRate)
      || sampleRate < 8_000
      || !Number.isInteger(fftSize)
      || fftSize < 32
      || frequency.length !== fftSize / 2
      || timeDomain.length < 32
    ) {
      throw new TypeError("E_AUDIO_VISEME_INPUT: analyser inputs are invalid");
    }

    let energy = 0;
    for (const sample of timeDomain) {
      const normalized = (sample - 128) / 128;
      energy += normalized * normalized;
    }
    const rms = Math.sqrt(energy / timeDomain.length);
    const intensity = clamp((rms - 0.006) * 5.4);
    if (rms < SILENCE_RMS) {
      return Object.freeze({
        viseme: "sil",
        intensity: 0,
        accuracy: "audio_spectral_heuristic",
      });
    }

    const low = bandEnergy(frequency, sampleRate, fftSize, 180, 700);
    const mid = bandEnergy(frequency, sampleRate, fftSize, 700, 1_800);
    const high = bandEnergy(frequency, sampleRate, fftSize, 1_800, 4_000);
    let viseme = "A";
    if (high > mid * 1.22 && high > low * 1.1) {
      viseme = "I";
    } else if (low > mid * 1.35 && low > high * 1.6) {
      viseme = "U";
    } else if (mid > low * 1.28 && mid > high * 1.15) {
      viseme = "E";
    } else if (
      low > mid * 1.2
      && low > high * 1.35
      && mid > high * 1.15
    ) {
      viseme = "O";
    }
    return Object.freeze({
      viseme,
      intensity: Number(intensity.toFixed(4)),
      accuracy: "audio_spectral_heuristic",
    });
  }

  function createVisemeStabilizer(requiredFrames = 2) {
    if (!Number.isInteger(requiredFrames) || requiredFrames < 1 || requiredFrames > 8) {
      throw new TypeError("E_AUDIO_VISEME_STABILIZER: requiredFrames is invalid");
    }
    let current = "sil";
    let candidate = "sil";
    let count = 0;
    return Object.freeze({
      push(result) {
        if (!result || !VISEMES.includes(result.viseme)) {
          throw new TypeError("E_AUDIO_VISEME_RESULT: result is invalid");
        }
        if (result.viseme === "sil") {
          current = "sil";
          candidate = "sil";
          count = 0;
          return Object.freeze({ ...result, viseme: "sil" });
        }
        if (result.viseme === current) {
          candidate = current;
          count = 0;
          return Object.freeze({ ...result });
        }
        if (result.viseme !== candidate) {
          candidate = result.viseme;
          count = 1;
        } else {
          count += 1;
        }
        if (count >= requiredFrames) {
          current = candidate;
          count = 0;
        }
        return Object.freeze({
          ...result,
          viseme: current,
          intensity: current === "sil" ? 0 : result.intensity,
        });
      },
      reset() {
        current = "sil";
        candidate = "sil";
        count = 0;
      },
    });
  }

  function bandEnergy(frequency, sampleRate, fftSize, fromHz, toHz) {
    const binHz = sampleRate / fftSize;
    const start = Math.max(1, Math.floor(fromHz / binHz));
    const end = Math.min(frequency.length, Math.ceil(toHz / binHz));
    if (end <= start) return 0;
    let energy = 0;
    for (let index = start; index < end; index += 1) {
      const normalized = frequency[index] / 255;
      energy += normalized * normalized;
    }
    return energy / (end - start);
  }

  function clamp(value) {
    return Math.min(1, Math.max(0, Number(value) || 0));
  }

  return {
    VISEMES,
    SILENCE_RMS,
    classifyAudioViseme,
    createVisemeStabilizer,
  };
}));
