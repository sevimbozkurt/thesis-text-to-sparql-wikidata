#!/bin/bash
# Disambiguate the combined-oracle arm on the GPU with Qwen2.5-14B, the
# disambiguation backbone of all prompt arms.
set -euo pipefail
cd "$(dirname "$0")"
source "${CONDA_SH:-$HOME/miniconda3/etc/profile.d/conda.sh}"
conda activate "${CONDA_ENV:-vllm}"
export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
# Pick the emptiest GPU unless GPU=n is set.
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
ls -la outputs/linked_both.json
