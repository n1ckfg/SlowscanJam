DIR=output

mkdir $DIR
IMAGE_OUTPUT_PATH=$DIR/image-%05d.jpg

ffmpeg -y -i $1 $IMAGE_OUTPUT_PATH

# Encode all jpeg images from the intro directory into an intro.wav file with the default settings of 3fps, 150 lines, and 0.2ms sync pulses.
#python3 enc.py -i "$DIR/*.jpg" $DIR.wav

# Encode the same frames but at 10 frames per second, 100 lines of resolution and 0.1ms sync pulses.
python3 enc.py -i "$DIR/*.jpg" -f 10 -l 100 -p 0.1 $DIR.wav
