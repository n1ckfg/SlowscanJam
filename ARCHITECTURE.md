# SlowscanJam Architecture

## Overview

SlowscanJam is a **Cassette Video** encoder/decoder system that converts video frames into stereo audio signals and back. This format allows video to be stored on analog audio cassette tapes, similar to slow-scan television (SSTV) used in amateur radio.

## Core Concept

Video frames are encoded as audio by:
1. Converting RGB pixels to YCbCr color space
2. Transmitting luminance (Y) on the left audio channel
3. Transmitting chrominance (Cb/Cr alternating lines) on the right channel
4. Using sync pulses to mark line and frame boundaries
5. Using interlaced fields (even/odd lines) for smoother playback

## Project Structure

```
SlowscanJam/
├── index.html          # Main browser app (combined encoder + decoder)
├── run.bat             # Windows launcher (starts local http-server)
├── run.command         # macOS launcher
└── ref/                # Reference implementations
    ├── Cassette-Video-Encoder-py/   # Python encoder (file-based)
    ├── Cassette-Video-Encoder-js/   # Node.js encoder (file-based)
    ├── Cassette-Video-Decoder-js/   # Browser decoder (audio input)
    └── Cassette-Video-Decoder-py/   # Python decoder class
```

## Main Application (index.html)

A single-page browser application that captures webcam video, encodes it to audio in real-time, then decodes it back to video.

### Pipeline

```
Camera → SlowscanEncoder → Audio Signal → SlowscanDecoder → Canvas Display
                               ↓
                      (Optional: Speakers)
```

### Components

**SlowscanEncoder**
- Captures video frames from webcam
- Converts RGB to YCbCr color space
- Generates sync pulses for line/frame timing
- Outputs stereo audio: left=luma, right=chroma
- Handles interlaced field encoding (alternates even/odd lines)
- `encodeCanvas(canvas, ctx)` is the entry point and is async: with a `WebGLEncoder` attached (`config.gpu`) the whole encode runs in shaders; otherwise it calls `getImageData` and the CPU `encodeFrame`
- CPU path: preallocated `Float32Array` output buffers; the oversampled scratch buffers are allocated on first CPU use. `encodeFrame` writes via an index (no `push` / spread) and produces zero per-frame heap allocations
- Polyphase lowpass filter coefficients are computed once in the constructor (and uploaded as shader uniforms on the GPU path); `resampleInto` has a fast no-mirror branch for interior samples

**WebGLEncoder (GLSL encoder)**
- Default encoder backend when WebGL2 is available; a single instance (one WebGL context) is shared by every `SlowscanEncoder` that `init()` creates
- The source canvas is uploaded as a texture (no `getImageData`), then two fragment passes run:
  1. **Signal pass**: one fragment per oversampled sample. Works out whether the sample is field/line sync, quiet, or picture, and for picture samples fetches the source pixel and converts to Y / Cb / Cr
  2. **Filter pass**: one fragment per output sample. Applies the lowpass + decimation (with edge mirroring identical to `resampleInto`) over the signal texture. Taps are unrolled at shader-build time with constant uniform indices
- Both render targets are `RG32UI` holding `floatBitsToUint(left, right)`, so values stay full float32. Output matches `encodeFrame` to ~2e-7
- Readback is asynchronous: `readPixels` into a pixel-pack buffer, `fenceSync`, poll the fence on a timer, then `getBufferSubData` into a buffer reinterpreted as `Float32Array`. The main thread is free while the GPU works. A result is discarded (resolves `null`) if the encoder was reconfigured meanwhile

**SlowscanDecoder**
- Processes stereo audio input sample-by-sample (in streaming chunks)
- Uses Auto-Gain Control (AGC) tracking of signal bounds across chunks to map audio levels to color values correctly
- Injects a small amount of pseudo-noise into samples during decoding to prevent zero-difference tracking issues in the AGC, faithfully matching original Python and JS reference decoders. Noise is sourced from a precomputed 4096-sample LUT with decorrelated L/C read indices — `Math.random()` is not called in the hot loop
- Detects sync pulses to determine line/frame boundaries
- Reconstructs YCbCr from audio levels and stores the AGC-normalized values per sample. YCbCr→RGB, brightness and saturation are applied by the renderer at draw time (in the vertex shader with WebGL)
- Chroma delay line is a preallocated `Float32Array`, not a growable JS array
- Per-scanline samples are written into `Float32Array` (phase) + `Float32Array` (Y, Cb, Cr), and line objects are recycled through a pool so the sample loop performs no per-sample allocation
- Delegates display rendering to a pluggable renderer (WebGL2 preferred, Canvas 2D fallback); `destroy()` frees the renderer's GPU resources when `init()` replaces the decoder

**WebGLPhosphor (GLSL renderer, WebGL2)**
- Default renderer for the decoded display
- Each batch of scanlines is uploaded as one `RGB32F` texture (one row per line, normalized Y/Cb/Cr per sample) plus a small per-line instance buffer (x start, x end, y + jitter, row, last sample index)
- The whole batch is one `drawArraysInstanced` call: a triangle strip per line, two vertices per sample. The vertex shader pulls its sample from the texture by vertex index (from a static index buffer) and converts YCbCr→RGB with brightness/saturation. Lines shorter than the batch's longest collapse their spare vertices onto the last sample
- The CPU builds no vertices; per batch it copies sample rows and writes 5 floats per line
- The fragment shader writes the interpolated `vec4(v_col, 1.0)`; blend mode is additive (`ONE, ONE`) when the Blend Mode checkbox is on, approximating the original `screen` phosphor glow
- Phosphor fade is implemented as a semi-transparent black quad drawn through the shader on a fixed interval

**Canvas2DPhosphor (fallback)**
- Used only if WebGL2 context creation fails
- Converts YCbCr→RGB on the CPU for each gradient stop
- Decimates gradient stops to a small maximum so `createLinearGradient` stays fast even at high per-line sample counts

### Synchronization and Dynamic Parameters

The system computes critical timing parameters dynamically whenever the `fps` or `lines` settings are updated, injecting these values into the decoder to maintain a perfectly faithful signal-lock. This logic calculates parameters matching the original `enc.js` reference outputs:
- `hTime` = `(1 / fps / lines) * 2`
- `widthSamples` = `hTime - (pulseLength * 4)`
- `overScan` = `widthSamples / hTime`
- `hOffset` = `(pulseLength * 1.45) / hTime`

### Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `fps` | 3 | Frames per second |
| `lines` | 150 | Vertical resolution |
| `sampleRate` | 96000 | Audio sample rate (`SAMPLE_RATE`; shared by encoder, decoder and playback) |
| `pulseLength` | 0.2ms | Sync pulse duration |
| `oversample` | 10 | Oversampling factor for timing accuracy |
| `hFreq` | 225 Hz | Horizontal line frequency |
| `vFreq` | 3 Hz | Vertical frame frequency |

## Signal Format

### Audio Encoding

**Left Channel (Luma):**
- Carries brightness information (Y component)
- Values range from -0.5 to +0.5

**Right Channel (Chroma):**
- Carries color information
- Even lines: Cb (blue-difference)
- Odd lines: Cr (red-difference)

### Sync Pulses

Sync pulses are full-amplitude (+1.0 or -1.0) signals that mark timing:

**Field Sync (start of frame):**
- Field 0: L=[-pulse, +pulse], R=[+pulse, -pulse]
- Field 1: L=[+pulse, -pulse], R=[-pulse, +pulse]

**Line Sync (between lines):**
- Even lines: L=[+pulse, -pulse], R=[+pulse, -pulse]
- Odd lines: L=[-pulse, +pulse], R=[-pulse, +pulse]

### Interlacing

Uses 2:1 interlacing for smoother motion:
- Field 0: Even lines (0, 2, 4, ...)
- Field 1: Odd lines (1, 3, 5, ...)
- Each frame alternates between fields

## Reference Implementations

### Python Encoder (ref/Cassette-Video-Encoder-py/enc.py)

Batch encoder for converting image sequences to WAV files.

```bash
./enc.py -i "frames/*.jpg" -f 3 -l 150 output.wav
```

Uses NumPy/SciPy for signal processing and PIL for image handling.

### Node.js Encoder (ref/Cassette-Video-Encoder-js/enc.js)

Equivalent batch encoder using Sharp for images and wavefile for audio.

```bash
node enc.js -i "frames/*.jpg" output.wav
```

### Browser Decoder (ref/Cassette-Video-Decoder-js/cv.js)

Standalone decoder class that takes stereo audio input (from line-in or microphone) and renders to a canvas. Used for playing back cassette video from physical tapes.

## Color Space Conversion

**RGB to YCbCr (encoder):**
```
Y  =  0.299*R + 0.587*G + 0.114*B
Cb = -0.169*R - 0.331*G + 0.500*B + 128
Cr =  0.500*R - 0.419*G - 0.081*B + 128
```

**YCbCr to RGB (decoder):**
```
R = Y + 1.406*Cr
G = Y - 0.344*Cb - 0.719*Cr
B = Y + 1.766*Cb
```

## Display Rendering

The decoder renders with CRT-style effects:
- **GPU scanlines**: Each scan line is an instanced triangle strip whose vertices pull and convert their own samples; the GPU interpolates color along the line
- **Additive blend**: WebGL `blendFunc(ONE, ONE)` approximates the original Canvas `screen` phosphor glow
- **Phosphor fade**: Gradual darkening via a semi-transparent black quad drawn on a fixed interval
- **Jitter**: Random sub-pixel offset per line for analog noise aesthetic

### Pipeline pluggability

The decoder selects its renderer at construction:
1. Try `WebGLPhosphor` — WebGL2, GLSL ES 3.00 vertex + fragment shaders.
2. Fall back to `Canvas2DPhosphor` — uses `createLinearGradient` with decimated color stops.

The encoder backend is chosen once at page load: `WebGLEncoder` if a WebGL2 context can be created, otherwise the CPU path. The source canvas's 2D context is created with `willReadFrequently` only in the CPU case. That flag keeps the backing store CPU-side for `getImageData`, but the GPU path uploads the canvas as a texture, which is cheaper from a GPU-backed canvas.

### What runs where

| Stage | Where | Why |
|-------|-------|-----|
| RGB→YCbCr, sync generation, lowpass + decimation (encoder) | GPU (`WebGLEncoder`) | Every output sample is independent |
| AGC, sync detection, phase tracking (decoder sample loop) | CPU | Sequential: each sample's state feeds the next |
| YCbCr→RGB, brightness, saturation (decoder output) | GPU (`WebGLPhosphor` vertex shader) | Per sample, independent |
| Scanline geometry + rasterization | GPU (`WebGLPhosphor`) | Per line / per pixel |

The decoder's sample loop stays on the CPU: AGC bounds, sync detection, and phase tracking all carry state forward sample-to-sample, so GPU parallelism doesn't help. It was optimized in place (typed arrays, no allocations, precomputed noise LUT).

### GPU notes (measured on Raspberry Pi 4, V3D 4.2, Chromium)

- **8-bit textures return fp16 on V3D.** The signal pass rounds fetched texels back to exact bytes (`floor(c * 255.0 + 0.5)`). Without that the output drifts ~2.4e-4 from the CPU encoder.
- **Loops over uniform arrays are slow on V3D.** A dynamically indexed `u_filter[j]` is fetched through the texture unit, so a 41-tap loop ran at half speed (and the compiler won't unroll it even with a constant bound). The filter pass is unrolled in JS with constant indices.
- **A single-pass encoder was slower than the CPU.** One fragment per output sample rebuilding all 41 oversampled taps (with integer divisions and branching) took ~10 ms on V3D. As a separate signal pass plus an unrolled filter pass the GPU work is ~3 ms.
- **Readback has a fixed ~2 ms round trip in Chrome**, even for a few bytes, so it is done asynchronously. The pixel-pack buffer gets fresh storage (`bufferData`) every frame; reusing it makes Chrome discard its readback shadow copy and log a performance warning.
- **Fragment-heavy colour conversion was slower than per-vertex.** Converting YCbCr in the fragment shader (two float texel fetches per pixel) doubled the renderer's GPU time on V3D. Doing it per sample in the vertex shader keeps fragment work trivial.

Per field at 6 fps / 200 lines (16,000 samples), Pi 4:

| | Before (CPU encode, per-line draw calls) | After |
|--|--|--|
| Encoder, main-thread time | ~12–14 ms (blocking) | ~2.5–3 ms typical (submit + readback); GPU work runs async |
| Renderer, CPU time per batch | ~1.7–2.4 ms | ~0.6–1.1 ms |
| Renderer, GPU time per batch | ~2.6–3.3 ms | ~3.2–3.8 ms (vertex texture fetches; one draw call instead of ~100) |
| Main-thread tasks > 10 ms (8 s of running app) | 42–43 | 3–8 |

## Audio Playback Queue

Stereo samples produced by each encode pass are buffered for playback through `ScriptProcessorNode`. The queue is a **power-of-two `Float32Array` ring buffer** (262144 samples ≈ 2.7s at 96 kHz) with masked read/write indices. If the producer laps the consumer, the read head advances to drop the oldest samples rather than corrupting ordering. This replaced JS arrays that were grown with `push` and periodically `slice`-trimmed (O(n) churn on the audio thread).

### Sample rate

The encoder always produces `SAMPLE_RATE` (96 kHz) samples, and two other places have to agree with it:
- **Decoder**: `init()` passes `sampleRate: SAMPLE_RATE`, which sets its line/frame timing targets, AGC decay and chroma delay length. Without it the decoder falls back to `audioCtx.sampleRate` (meant for live line-in input). On 48 kHz hardware that halves the expected line length and the picture breaks into horizontal stripes.
- **Playback**: the `AudioContext` is created with `{ sampleRate: SAMPLE_RATE }` so the `ScriptProcessorNode` drains the queue as fast as the encoder fills it; the browser resamples to the output device. A browser that ignores the option still decodes correctly, but playback runs slow and the queue drops samples.

## Layout

The browser UI arranges the three canvases in two columns:
- **Left column**: SOURCE (camera) on top, DECODED (output) below
- **Right column**: ENCODED (audio signal preview)
- Controls panel is fixed top-right

## Running the Application

1. Start a local HTTP server (required for camera access):
   - Windows: Run `run.bat`
   - macOS: Run `run.command`
2. Click "Start Camera" to begin
3. Adjust parameters with the on-screen controls

## Dependencies

**Browser app**: No external dependencies (vanilla JavaScript + Web Audio API + WebGL2, with CPU / Canvas 2D fallbacks)

**Python encoder**: numpy, scipy, pillow, soundfile

**Node.js encoder**: sharp, wavefile, glob, yargs
