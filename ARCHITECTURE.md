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

**SlowscanEncoder** (lines 80-207)
- Captures video frames from webcam
- Converts RGB to YCbCr color space
- Generates sync pulses for line/frame timing
- Outputs stereo audio: left=luma, right=chroma
- Handles interlaced field encoding (alternates even/odd lines)

**SlowscanDecoder** (lines 212-472)
- Processes stereo audio input sample-by-sample (in streaming chunks)
- Uses Auto-Gain Control (AGC) tracking of signal bounds across chunks to map audio levels to color values correctly
- Injects a small amount of random noise into samples during decoding to prevent zero-difference tracking issues in the AGC, faithfully matching original Python and JS reference decoders
- Detects sync pulses to determine line/frame boundaries
- Reconstructs YCbCr from audio levels
- Converts back to RGB for display
- Renders with CRT-style effects (blend mode, line width, phosphor fade)

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
- **Gradient strokes**: Each scan line rendered as a horizontal gradient
- **Screen blend mode**: Additive blending for phosphor glow effect
- **Phosphor fade**: Gradual darkening (5% per clearInterval)
- **Jitter**: Random 2px offset for analog noise aesthetic

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
