#!/usr/bin/env python3

import argparse
import os
import math
import numpy as np
import soundfile
from PIL import Image, ImageDraw
import random
import sys

def hPhaseToX(hPhase, hOffset, overScan, width):
    return ((hPhase - hOffset) / overScan) * width

def vPhaseToY(vPhase, field, hFreq, vFreq, height):
    return (vPhase + (field / vFreq) * hFreq * 0.5) * height

def YCbCrToRGB(y, cb, cr):
    r = y + 45 * cr / 32.0
    g = y - (11 * cb + 23 * cr) / 32.0
    b = y + 113 * cb / 64.0
    return r, g, b

def process_audio(input_file, out_dir):
    print(f"Loading {input_file}...")
    data, sample_rate = soundfile.read(input_file)
    if len(data.shape) == 1:
        print("Error: Expected stereo audio for Luma (left) and Chroma (right).")
        return
        
    lSamples = data[:, 0]
    cSamples = data[:, 1]
    
    width = 1280
    height = 720
    
    overScan = 0.82
    hOffset = 0.06525
    pulseLength = 0.2 / 1000.0
    brightness = 1.0
    saturation = 1.0
    lineWidth = 2.5
    
    hFreqConfig = 225.0
    vFreqConfig = 3.0
    
    LMin, LMax = 0.0, 1.0
    CMin, CMax = -1.0, 1.0
    
    hPhase = 0.0
    vPhase = 0.0
    
    p_time = 0.0
    p_timeout = 0.0
    p_luma = 0
    p_lumaPrev = 0
    p_chroma = 0
    p_chromaPrev = 0
    p_changed = False
    p_ready = False
    
    timing_time = 0
    timing_lastV = 0
    timing_lastH = 0
    
    field = 0
    chromaField = 0
    
    chromaDelay = [0.0] * int(sample_rate / 10.0 + 100)
    chromaDelayIndex = 0
    
    lines = []
    currLine_x1 = 0.0
    currLine_y = 0.0
    currLine_maxPhase = 0.0
    currLine_colors = []
    
    hFreqTarget = 1.0 / hFreqConfig * sample_rate
    vFreqTarget = 1.0 / vFreqConfig * sample_rate
    hFreq = hFreqTarget
    vFreq = vFreqTarget
    
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(canvas, "RGBA")
    
    frame_count = 0
    total_samples = len(lSamples)
    
    os.makedirs(out_dir, exist_ok=True)
    
    print("Decoding...")
    
    for i in range(total_samples):
        if i % (sample_rate * 2) == 0:
            print(f"\rProgress: {i / total_samples * 100:.1f}% ({i}/{total_samples} samples)", end="")
            sys.stdout.flush()
            
        timing_time += 1
        
        # Add small noise to prevent zero differences
        lSample = lSamples[i] + random.random() * 0.01 - 0.005
        cSample = cSamples[i] + random.random() * 0.01 - 0.005
        
        if lSample < LMin: LMin = lSample
        if lSample > LMax: LMax = lSample
        
        LMin *= 1.0 - (1.0 / sample_rate)
        LMax *= 1.0 - (1.0 / sample_rate)
        
        if LMin > -0.025: LMin = -0.025
        if LMax < 0.025: LMax = 0.025
        
        if cSample < CMin: CMin = cSample
        if cSample > CMax: CMax = cSample
        
        CMin *= 1.0 - (1.0 / sample_rate)
        CMax *= 1.0 - (1.0 / sample_rate)
        
        if CMin > -0.05: CMin = -0.05
        if CMax < 0.05: CMax = 0.05
        
        luma = (lSample * 2.0 - LMin) / (LMax - LMin) * brightness * 255.0
        chroma = (cSample * 2.0 - CMin) / (CMax - CMin) * saturation * 255.0
        
        chromaLast = chromaDelay[chromaDelayIndex] if chromaDelayIndex < len(chromaDelay) else 0.0
        
        if chromaDelayIndex < int(sample_rate / 10.0):
            chromaDelay[chromaDelayIndex] = chroma
            chromaDelayIndex += 1
            
        chroma -= 128.0
        chromaLast -= 128.0
        
        if chromaField == 0:
            r, g, b = YCbCrToRGB(luma, chromaLast, chroma)
        else:
            r, g, b = YCbCrToRGB(luma, chroma, chromaLast)
            
        if len(currLine_colors) < 1024:
            currLine_colors.append({
                'phase': hPhase,
                'r': max(min(round(r), 255), 0),
                'g': max(min(round(g), 255), 0),
                'b': max(min(round(b), 255), 0)
            })
            
        currLine_maxPhase = hPhase
        
        hPhase += 1.0 / hFreq
        vPhase += 1.0 / vFreq
        
        currLine_x2 = hPhaseToX(hPhase, hOffset, overScan, width)
        
        blank = False
        
        if (LMax - LMin) > 0.1 and (CMax - CMin) > 0.1:
            if lSample < LMin * 0.5:
                p_luma = -1
            elif lSample > LMax * 0.5:
                p_luma = 1
            else:
                p_luma = 0
                
            if cSample < CMin * 0.5:
                p_chroma = -1
            elif cSample > CMax * 0.5:
                p_chroma = 1
            else:
                p_chroma = 0
                
            if p_luma != p_lumaPrev or p_chroma != p_chromaPrev:
                p_time = 0
                p_lumaPrev = p_luma
                p_chromaPrev = p_chroma
                p_changed = True
                
            if p_luma != 0 and p_chroma != 0:
                p_time += 1.0 / sample_rate
                
                if p_time > pulseLength * 0.5 and p_changed:
                    p_changed = False
                    
                    if not p_ready:
                        p_ready = True
                        p_timeout = pulseLength * 1.25
                    else:
                        p_ready = False
                        blank = True
                        
                        if (timing_time - timing_lastH < hFreqTarget * 1.5) and (timing_time - timing_lastH > hFreqTarget * 0.5):
                            hFreq = hFreq * 0.9 + (timing_time - timing_lastH) * 0.1
                            
                        timing_lastH = timing_time
                        
                        hPhase = 0
                        chromaDelayIndex = 0
                        
                        if p_luma > 0:
                            chromaField = 0
                        else:
                            chromaField = 1
                            
                        if p_luma != p_chroma:
                            if (timing_time - timing_lastV < vFreqTarget * 1.5) and (timing_time - timing_lastV > vFreqTarget * 0.5):
                                vFreq = vFreq * 0.75 + (timing_time - timing_lastV) * 0.25
                                
                            timing_lastV = timing_time
                            
                            vPhase = 0
                            chromaField = 1
                            
                            if p_luma > 0:
                                field = 0
                            else:
                                field = 1
                                
            if p_ready:
                p_timeout -= 1.0 / sample_rate
                if p_timeout <= 0:
                    p_ready = False
        else:
            p_luma = p_lumaPrev = 0
            p_chroma = p_chromaPrev = 0
            p_changed = False
            p_ready = False
            
        hFreq = hFreq * (1.0 - 1.0 / sample_rate) + hFreqTarget * (1.0 / sample_rate)
        vFreq = vFreq * (1.0 - 1.0 / sample_rate) + vFreqTarget * (1.0 / sample_rate)
        
        if hPhase >= 1.0:
            blank = True
            hPhase -= 1.0
            chromaDelayIndex = 0
            chromaField = 0 if chromaField == 1 else 1
            
        if vPhase >= 1.0:
            blank = True
            vPhase -= 1.0
            field = 1 if field == 0 else 0
            
            # Save frame at the end of every field
            out_path = os.path.join(out_dir, f"frame_{frame_count:05d}.png")
            canvas.save(out_path)
            frame_count += 1
            
            # Fade canvas to simulate phosphor decay / screen blending
            # Using Image.eval to multiply each channel by 0.85
            canvas = Image.eval(canvas, lambda p: int(p * 0.85))
            draw = ImageDraw.Draw(canvas, "RGBA")
            
        if blank:
            if len(lines) < 1024 and len(currLine_colors) > 5 and currLine_maxPhase > 0:
                lines.append({
                    'x1': currLine_x1,
                    'x2': currLine_x2,
                    'y': currLine_y,
                    'maxPhase': currLine_maxPhase,
                    'colors': currLine_colors
                })
                
                # Draw lines accumulated so far
                for line in lines:
                    colors = line['colors']
                    if len(colors) > 1:
                        y_start = line['y'] + random.random() * 2.0 - 1.0
                        y_end = line['y'] + random.random() * 2.0 - 1.0
                        
                        for j in range(len(colors) - 1):
                            c1 = colors[j]
                            c2 = colors[j+1]
                            
                            f1 = c1['phase'] / line['maxPhase']
                            f2 = c2['phase'] / line['maxPhase']
                            
                            px1 = line['x1'] + (line['x2'] - line['x1']) * f1
                            px2 = line['x1'] + (line['x2'] - line['x1']) * f2
                            
                            py1 = y_start + (y_end - y_start) * f1
                            py2 = y_start + (y_end - y_start) * f2
                            
                            color = (c1['r'], c1['g'], c1['b'], 255)
                            draw.line([(px1, py1), (px2, py2)], fill=color, width=int(lineWidth))
                
                lines = []
                
            currLine_x1 = hPhaseToX(hPhase, hOffset, overScan, width)
            currLine_y = vPhaseToY(vPhase, field, hFreq, vFreq, height)
            currLine_maxPhase = 0
            currLine_colors = []
            
            blank = False
            
    print("\nDone!")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--input', required=True, help='input audio file (wav)')
    parser.add_argument('-o', '--output', required=True, help='output directory for frames')
    args = parser.parse_args()
    
    process_audio(args.input, args.output)
