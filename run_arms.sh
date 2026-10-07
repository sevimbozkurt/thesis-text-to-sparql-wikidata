#!/bin/bash
# Disambiguates the construct-profile and constrained-vocabulary arms on a GPU
# with Qwen2.5-14B, the disambiguation backbone of all prompt arms (vLLM).
# Set CONDA_SH, CONDA_ENV and HF_HOME if your installation differs from the defaults.
set -euo pipefail
cd "$(dirname "$0")"
source "${CONDA_SH:-$HOME/miniconda3/etc/profile.d/conda.sh}"
conda activate "${CONDA_ENV:-vllm}"
export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
export CUDA_VISIBLE_DEVICES=${GPU:-0}

echo "=== environment ==="
python -c "import vllm,sys;print('vllm',vllm.__version__,'| python',sys.version.split()[0])"
echo "HF_HOME=$HF_HOME"
echo "CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv,noheader

echo
echo "=== X10: construct-profile arm ==="
python disamb_any.py --gen profile_generated.json --split working \
       --tag profile --model Qwen/Qwen2.5-14B-Instruct

echo
echo "=== X14: constrained-vocabulary arm ==="
python disamb_any.py --gen constrained_generated.json --split working \
       --tag constrained --model Qwen/Qwen2.5-14B-Instruct

echo
echo "=== DONE ==="
ls -la outputs/linked_profile.json outputs/linked_constrained.json
