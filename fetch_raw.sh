#!/bin/bash

# --- Default Config ---
DETECTOR="H1"
RUN="O4a"
HOURS=1
OUTPUT_DIR="/sdcard/Download/gravi-signal/data/raw"
SEGMENT_DURATION=32

# Function to show usage
usage() {
    echo "Usage: $0 [-d detector] [-r run] [-h hours] [-o output_dir] [-s segment_duration]"
    echo "  -d: Detector (H1, L1, V1). Default: H1"
    echo "  -r: Run (O2, O3a, O3b, O4a). Default: O4a"
    echo "  -h: Hours to download. Default: 1"
    echo "  -o: Output directory. Default: /sdcard/Download/gravi-signal/data/raw"
    echo "  -s: Segment duration (seconds). Default: 32"
    exit 1
}

# Parse arguments
while getopts "d:r:h:o:s:" opt; do
    case ${opt} in
        d) DETECTOR=$OPTARG ;;
        r) RUN=$OPTARG ;;
        h) HOURS=$OPTARG ;;
        o) OUTPUT_DIR=$OPTARG ;;
        s) SEGMENT_DURATION=$OPTARG ;;
        *) usage ;;
    esac
done

# GPS Iniziali (Run + 6h offset)
case $RUN in
    "O2")  START_GPS=1164578417 ;;
    "O3a") START_GPS=1238187618 ;;
    "O3b") START_GPS=1256677218 ;;
    "O4a") START_GPS=1368978018 ;;
    *) echo "Run non supportata: $RUN"; exit 1 ;;
esac

mkdir -p "$OUTPUT_DIR"

# --- Resume Logic ---
LAST_FILE=$(ls -1 "$OUTPUT_DIR" | grep "^${DETECTOR}_" | sort -V | tail -n 1)
if [ -n "$LAST_FILE" ]; then
    CURRENT_START=$(echo "$LAST_FILE" | cut -d'_' -f3 | cut -d'.' -f1)
    echo "Resume found: starting from GPS $CURRENT_START"
else
    CURRENT_START=$START_GPS
    echo "Fresh start: starting from origin GPS $CURRENT_START"
fi

# Align to 4096s boundary
CURRENT_START=$(( (CURRENT_START / 4096) * 4096 ))
END_GPS=$(( CURRENT_START + (HOURS * 3600) ))

echo "=== FETCH-RAW BASH: $DETECTOR [$RUN] ==="
echo "Target: $HOURS hours (until GPS $END_GPS)"

BASE_DELAY=0.3

# --- Download Loop ---
while [ $CURRENT_START -lt $END_GPS ]; do
    BLOCK_END=$(( CURRENT_START + SEGMENT_DURATION ))
    # Ensure we don't overshoot the requested total duration
    if [ $BLOCK_END -gt $END_GPS ]; then
        BLOCK_END=$END_GPS
    fi
    
    FILENAME="${DETECTOR}_${CURRENT_START}_${BLOCK_END}.hdf5"
    
    if [ -f "$OUTPUT_DIR/$FILENAME" ]; then
        echo "Block ${CURRENT_START} to ${BLOCK_END}: Already exists."
    else
        echo -n "Block ${CURRENT_START} to ${BLOCK_END}: Fetching... "
        
        while true; do
            sleep $BASE_DELAY
            
            # Query GWOSC JSON API for the file path
            API_URL="https://gwosc.org/archive/links/$RUN/$DETECTOR/$CURRENT_START/$CURRENT_START/json/"
            
            HTTP_CODE=$(curl -s -o /tmp/gwosc_api.json -w "%{http_code}" "$API_URL")
            
            if [ "$HTTP_CODE" = "429" ]; then
                echo -n "(429 Too Many Requests, delay +300ms, wait 1s)... "
                BASE_DELAY=$(awk "BEGIN {print $BASE_DELAY + 0.3}")
                sleep 1
                continue
            fi
            
            FILE_URL=$(cat /tmp/gwosc_api.json | jq -r '.path[0]')

            if [ "$FILE_URL" != "null" ] && [ -n "$FILE_URL" ]; then
                HTTP_CODE=$(curl -L -C - -s -o "$OUTPUT_DIR/$FILENAME" -w "%{http_code}" "$FILE_URL")
                if [ "$HTTP_CODE" = "429" ]; then
                    echo -n "(429 on download, delay +300ms, wait 1s)... "
                    BASE_DELAY=$(awk "BEGIN {print $BASE_DELAY + 0.3}")
                    sleep 1
                    continue
                fi
                echo "OK"
            else
                echo "FAILED (Data not available at GWOSC)"
            fi
            break
        done
    fi

    CURRENT_START=$BLOCK_END
done

echo "Download completed."
