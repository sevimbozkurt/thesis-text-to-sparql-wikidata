#!/bin/bash
# Disambiguate one prompt arm on the GPU with Qwen2.5-14B.
# Usage: ./run_arm.sh <gen-file> <tag>
set -euo pipefail
cd /data/sevim/gpu_bundle
source /data/sevim/miniconda3/etc/profile.d/conda.sh
conda activate vllm
export HF_HOME=/home/sevim/.cache/huggingface
if [ -z "${GPU:-}" ]; then
  GPU=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
        | sort -t, -k2 -n | head -1 | cut -d, -f1 | tr -d ' ')
fi
export CUDA_VISIBLE_DEVICES=$GPU
echo "GPU $GPU | vllm $(python -c 'import vllm;print(vllm.__version__)')"
python disamb_any.py --gen "$1" --split working --tag "$2" \
       --model Qwen/Qwen2.5-14B-Instruct
echo "=== DONE ==="
ls -la "linked_$2.json"
