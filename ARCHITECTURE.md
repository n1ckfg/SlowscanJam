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
- Preallocates `Float32Array` scratch and output buffers sized from the frame dimensions; `encodeFrame` writes via an index (no `push` / spread) and produces zero per-frame heap allocations
- Polyphase lowpass filter coefficients are computed once in the constructor; `resampleInto` has a fast no-mirror branch for interior samples

**SlowscanDecoder**
- Processes stereo audio input sample-by-sample (in streaming chunks)
- Uses Auto-Gain Control (AGC) tracking of signal bounds across chunks to map audio levels to color values correctly
- Injects a small amount of pseudo-noise into samples during decoding to prevent zero-difference tracking issues in the AGC, faithfully matching original Python and JS reference decoders. Noise is sourced from a precomputed 4096-sample LUT with decorrelated L/C read indices — `Math.random()` is not called in the hot loop
- Detects sync pulses to determine line/frame boundaries
- Reconstructs YCbCr from audio levels; YCbCr→RGB is inlined in the per-sample loop to avoid array allocation
- Chroma delay line is a preallocated `Float32Array`, not a growable JS array
- Per-scanline color samples are written into `Float32Array` (phase) + `Uint8Array` (RGB), and line objects are recycled through a pool so the sample loop performs no per-sample allocation
- Delegates display rendering to a pluggable renderer (WebGL preferred, Canvas 2D fallback)

**WebGLPhosphor (GLSL renderer)**
- Default renderer for the decoded display
- Each scanline is emitted as a triangle-strip quad whose two vertices carry identical per-sample RGB, so the GPU rasterizer interpolates color across each line
- A simple fragment shader writes `vec4(v_col, 1.0)`; blend mode is additive (`ONE, ONE`) when the Blend Mode checkbox is on, approximating the original `screen` phosphor glow
- Phosphor fade is implemented as a semi-transparent black quad drawn through the shader on a fixed interval
- Replaces the slow CPU path of building many-stop `createLinearGradient` strokes per line in Canvas 2D

**Canvas2DPhosphor (fallback)**
- Used only if WebGL context creation fails
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
| `sampleRate` | 96000 | Audio sample rate |
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
- **GPU scanline quads**: Each scan line is a triangle-strip quad with per-vertex RGB; the GPU interpolates color along the line
- **Additive blend**: WebGL `blendFunc(ONE, ONE)` approximates the original Canvas `screen` phosphor glow
- **Phosphor fade**: Gradual darkening via a semi-transparent black quad drawn on a fixed interval
- **Jitter**: Random sub-pixel offset per line for analog noise aesthetic

### Pipeline pluggability

The decoder selects its renderer at construction:
1. Try `WebGLPhosphor` — uses GLSL vertex + fragment shaders.
2. Fall back to `Canvas2DPhosphor` — uses `createLinearGradient` with decimated color stops.

### Why not move decoding to a shader?

The decoder's sample loop is sequential by nature: AGC bounds, sync detection, and phase tracking all carry state forward sample-to-sample. GPU parallelism doesn't help a serial feedback loop, so the CPU loop was optimized in place (typed arrays, no allocations, precomputed noise LUT) rather than ported to GLSL. Only the render step — which is embarrassingly parallel per line/pixel — was moved to shaders.

## Audio Playback Queue

Stereo samples produced by each encode pass are buffered for playback through `ScriptProcessorNode`. The queue is a **power-of-two `Float32Array` ring buffer** (262144 samples ≈ 2.7s at 96 kHz) with masked read/write indices. If the producer laps the consumer, the read head advances to drop the oldest samples rather than corrupting ordering. This replaced JS arrays that were grown with `push` and periodically `slice`-trimmed (O(n) churn on the audio thread).

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

**Browser app**: No external dependencies (vanilla JavaScript + Web Audio API)

**Python encoder**: numpy, scipy, pillow, soundfile

**Node.js encoder**: sharp, wavefile, glob, yargs
