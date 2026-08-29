"""Run the frozen three-model comparison for replication round R002."""

from pathlib import Path

from analysis import compare_wp1_models as comparison


comparison.ANALYSIS_ID = "wp1-r002-xai-nvidia-deepseek-20260828-v1"
comparison.OUTPUT = (
    comparison.RESULTS / "model_comparison" / comparison.ANALYSIS_ID
)
comparison.CAMPAIGNS = {
    "xAI Grok Build 0.1": ["EXP-R002-XAI-GROK-BUILD01-FULL-001"],
    "NVIDIA Nemotron 3 Super": [
        "EXP-R002-OPENROUTER-NVIDIA-NEMOTRON3-SUPER-FULL-001"
    ],
    "DeepSeek V4 Flash 0731": [
        "EXP-R002-OPENROUTER-DEEPSEEK-V4-FLASH-0731-FULL-001"
    ],
}


if __name__ == "__main__":
    comparison.main()
