#!/bin/bash
# usage: sweep.sh OUTDIR "seeds"   (resumable: seeds already scored are skipped)
OUT=$1; SEEDS=$2
cd "$(dirname "$0")/../.."
for s in $SEEDS; do
  while [ $(jobs -r | wc -l) -ge 6 ]; do sleep 2; done
  OMP_NUM_THREADS=1 python3 -u authoring/methods/run_seed.py $s $OUT >> $OUT.log 2>&1 &
done
wait
echo SWEEP_DONE >> $OUT.log
