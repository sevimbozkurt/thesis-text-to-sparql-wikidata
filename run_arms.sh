#!/bin/bash
# Runs on the GPU server (aixsrv1). Disambiguates the two new arms with
# Qwen2.5-14B, the disambiguation backbone of all prompt arms.
#
# Uses the EXISTING 'vllm' conda env (vLLM 0.26.0) and the EXISTING model cache
# in /home/sevim/.cache, where Qwen2.5-14B-Instruct is already downloaded (28G).
# HF_HOME in .bashrc points at /data/sevim/cache, which has only 1.5B and 7B —
# overriding it here avoids a pointless 28G re-download.
set -euo pipefail
cd /data/sevim/gpu_bundle

source /data/sevim/miniconda3/etc/profile.d/conda.sh
conda activate vllm
export HF_HOME=/home/sevim/.cache/huggingface
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
ls -la linked_profile.json linked_constrained.json
