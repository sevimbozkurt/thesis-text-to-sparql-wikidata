#!/bin/bash
# Disambiguate the combined-oracle arm on the GPU with Qwen2.5-14B, the
# disambiguation backbone of all prompt arms.
set -euo pipefail
cd /data/sevim/gpu_bundle
source /data/sevim/miniconda3/etc/profile.d/conda.sh
conda activate vllm
export HF_HOME=/home/sevim/.cache/huggingface
# Pick the emptiest GPU rather than assuming 0. Two reasons, both learned the
# hard way: a crashed vLLM run leaves an orphaned EngineCore holding ~42GB, and
# this is a shared machine (another user was on GPU 2). Overriding with GPU=n
# still works.
if [ -z "${GPU:-}" ]; then
  GPU=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
        | sort -t, -k2 -n | head -1 | cut -d, -f1 | tr -d ' ')
fi
export CUDA_VISIBLE_DEVICES=$GPU
echo "selected GPU $GPU (emptiest of $(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l))"
python -c "import vllm;print('vllm',vllm.__version__)"
python disamb_any.py --gen both_generated.json --split working \
       --tag both --model Qwen/Qwen2.5-14B-Instruct
echo "=== DONE ==="
ls -la linked_both.json
