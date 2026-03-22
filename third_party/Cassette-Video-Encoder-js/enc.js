#!/usr/bin/env node

const yargs = require('yargs/yargs');
const { hideBin } = require('yargs/helpers');
const glob = require('glob');
const fs = require('fs');
const sharp = require('sharp');
const { WaveFile } = require('wavefile');

const argv = yargs(hideBin(process.argv))
    .option('input', {
        alias: 'i',
        type: 'array',
        demandOption: true,
        describe: 'input file pattern(s)'
    })
    .option('rate', {
        alias: 'r',
        type: 'number',
        default: 96000,
        describe: 'sample rate'
    })
    .option('fps', {
        alias: 'f',
        type: 'number',
        default: 3.0,
        describe: 'frames per second'
    })
    .option('lines', {
        alias: 'l',
        type: 'number',
        default: 150,
        describe: 'lines of resolution'
    })
    .option('pulselength', {
        alias: 'p',
        type: 'number',
        default: 0.2,
        describe: 'length of sync pulses in ms'
    })
    .option('oversample', {
        alias: 'o',
        type: 'number',
        default: 10,
        describe: 'oversampling amount'
    })
    .help()
    .parse();

const outfile = argv._[0];
if (!outfile) {
    console.error("Output file is required. Please provide it as the last positional argument.");
    process.exit(1);
}

const sample_rate = argv.rate;
const oversample = argv.oversample;
const pulse_length = argv.pulselength / 1000.0;
const fps = argv.fps;
const lines = argv.lines;
const h_time = (1 / fps / lines) * 2;
let width_samples = h_time - (pulse_length * 4);

if (width_samples <= 0) {
    console.error("Not time for image data, try reducing frame rate, lines, or pulse length.");
    process.exit(1);
}

console.log(`hFreq: ${1.0 / h_time},`);
console.log(`vFreq: ${fps},`);
console.log(`overScan: ${width_samples / h_time},`);
console.log(`hOffset: ${(pulse_length * 1.45) / h_time},`);
console.log(`pulseLength: ${pulse_length}`);

width_samples *= sample_rate;
const width_pixels = Math.round(width_samples * oversample);

const pulseLengthSamples = Math.round(pulse_length * sample_rate * oversample);
const pulse = new Float64Array(pulseLengthSamples).fill(1.0);
const negPulse = new Float64Array(pulseLengthSamples).fill(-1.0);
const quiet = new Float64Array(pulseLengthSamples).fill(0.0);

let images = [];
for (const pattern of argv.input) {
    const files = glob.sync(pattern);
    files.sort();
    images.push(...files);
}

if (images.length === 0) {
    console.error("No input images found.");
    process.exit(1);
}

function rgbToYcbcr(r, g, b) {
    let y = 0.299 * r + 0.587 * g + 0.114 * b;
    let cb = -0.168736 * r - 0.331264 * g + 0.5 * b + 128;
    let cr = 0.5 * r - 0.418688 * g - 0.081312 * b + 128;
    return [y, cb, cr];
}

class FloatArrayBuilder {
    constructor() {
        this.chunks = [];
        this.length = 0;
    }
    append(arr) {
        this.chunks.push(arr);
        this.length += arr.length;
    }
    build() {
        const out = new Float64Array(this.length);
        let offset = 0;
        for (const chunk of this.chunks) {
            out.set(chunk, offset);
            offset += chunk.length;
        }
        return out;
    }
}

function resample_poly(arr, up, down) {
    const factor = down;
    const out = new Float64Array(Math.ceil(arr.length / factor));
    
    // Simple FIR lowpass filter
    const taps = factor * 4 + 1; 
    const filter = new Float64Array(taps);
    let sum = 0;
    for (let i = 0; i < taps; i++) {
        let n = i - (taps - 1) / 2;
        if (n === 0) {
            filter[i] = 1.0;
        } else {
            filter[i] = Math.sin(Math.PI * n / factor) / (Math.PI * n);
        }
        // Hamming window
        filter[i] *= 0.54 - 0.46 * Math.cos(2 * Math.PI * i / (taps - 1));
        sum += filter[i];
    }
    for (let i = 0; i < taps; i++) filter[i] /= sum;

    // Convolve and decimate
    for (let i = 0; i < out.length; i++) {
        let val = 0;
        let center = i * factor;
        for (let j = 0; j < taps; j++) {
            let idx = center + j - (taps - 1) / 2;
            if (idx >= 0 && idx < arr.length) {
                val += arr[idx] * filter[j];
            } else if (idx < 0) {
                // mirror padding for left edge
                let mirrorIdx = -idx;
                if (mirrorIdx >= arr.length) mirrorIdx = arr.length - 1;
                val += arr[mirrorIdx] * filter[j];
            } else if (idx >= arr.length) {
                // mirror padding for right edge
                let mirrorIdx = arr.length - 1 - (idx - arr.length + 1);
                if (mirrorIdx < 0) mirrorIdx = 0;
                val += arr[mirrorIdx] * filter[j];
            }
        }
        out[i] = val;
    }
    return out;
}

async function encode(imageFile, field) {
    const { data, info } = await sharp(imageFile)
        .resize(width_pixels, lines, { fit: 'fill' })
        .toColorspace('srgb')
        .removeAlpha()
        .raw()
        .toBuffer({ resolveWithObject: true });
        
    let left = new FloatArrayBuilder();
    let right = new FloatArrayBuilder();

    if (field === 0) {
        left.append(negPulse);
        right.append(pulse);
        left.append(pulse);
        right.append(negPulse);
    } else {
        left.append(pulse);
        right.append(negPulse);
        left.append(negPulse);
        right.append(pulse);
    }

    left.append(quiet);
    right.append(quiet);

    const halfLines = Math.floor(lines / 2);
    
    for (let line = 0; line < halfLines; line++) {
        if (line !== 0) {
            if (line % 2 === 0) {
                left.append(pulse);
                right.append(pulse);
                left.append(negPulse);
                right.append(negPulse);
            } else {
                left.append(negPulse);
                right.append(negPulse);
                left.append(pulse);
                right.append(pulse);
            }
            left.append(quiet);
            right.append(quiet);
        }

        const row = line * 2 + field;
        const rowStart = row * width_pixels * 3;
        
        const yArr = new Float64Array(width_pixels);
        const cArr = new Float64Array(width_pixels);
        
        for (let x = 0; x < width_pixels; x++) {
            const idx = rowStart + x * 3;
            const r = data[idx];
            const g = data[idx + 1];
            const b = data[idx + 2];
            
            const [y, cb, cr] = rgbToYcbcr(r, g, b);
            
            yArr[x] = y / 255.0 - 0.5;
            if (line % 2 === 0) {
                cArr[x] = cb / 255.0 - 0.5;
            } else {
                cArr[x] = cr / 255.0 - 0.5;
            }
        }
        
        left.append(yArr);
        right.append(cArr);
        
        left.append(quiet);
        right.append(quiet);
    }

    let leftBuilt = left.build();
    let rightBuilt = right.build();

    leftBuilt = resample_poly(leftBuilt, 1, oversample);
    rightBuilt = resample_poly(rightBuilt, 1, oversample);

    return { left: leftBuilt, right: rightBuilt };
}

async function main() {
    console.log("Encoding...");

    let allLeft = new FloatArrayBuilder();
    let allRight = new FloatArrayBuilder();

    const initialSilence = new Float64Array(sample_rate).fill(0.0);
    allLeft.append(initialSilence);
    allRight.append(initialSilence);

    for (let count = 0; count < images.length; count++) {
        const imageFile = images[count];
        process.stdout.write(`\rProcessing ${count + 1}/${images.length} frames`);
        
        const field = (count % 2 === 0) ? 0 : 1;
        const { left, right } = await encode(imageFile, field);
        
        const scaledLeft = new Float64Array(left.length);
        const scaledRight = new Float64Array(right.length);
        for (let i = 0; i < left.length; i++) {
            scaledLeft[i] = left[i] * 0.5;
            scaledRight[i] = right[i] * 0.5;
        }
        
        allLeft.append(scaledLeft);
        allRight.append(scaledRight);
    }
    console.log("\nDone!");

    allLeft.append(initialSilence);
    allRight.append(initialSilence);

    const finalLeft = allLeft.build();
    const finalRight = allRight.build();

    const float32Left = new Float32Array(finalLeft);
    const float32Right = new Float32Array(finalRight);

    const wav = new WaveFile();
    wav.fromScratch(2, sample_rate, '32f', [float32Left, float32Right]);
    
    fs.writeFileSync(outfile, wav.toBuffer());
}

main().catch(err => {
    console.error(err);
    process.exit(1);
});
