#!/bin/bash

PROGRAMS=("simon" "aes" "search")
RERUNS=("1" "3")
LOG=./logs

# create a log dir if not exist
if ! test -d $LOG; then
    mkdir $LOG
fi

# run weird programs with or without majority voting
for program in "${PROGRAMS[@]}"; do
    for rerun in "${RERUNS[@]}"; do
        bin="build/rerun${rerun}/${program}.elf"
        log="${LOG}/rerun${rerun}/"
        echo "[*] Running ${program} with ${rerun} rerun(s)"
        python3 tools/run_wm.py $bin -l $log
    done
done
