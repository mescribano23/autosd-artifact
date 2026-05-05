# Artifact for AutoSD

This repository contains the code and result files for AutoSD, a novel explainable APR technique.

## Structure

 * The directory `arhe/` contains the results using the ARHE dataset; one can look to the `ARHEAnalysis.ipynb` file to reproduce the numbers from the result files. Along with this, `main.py` implements the AutoSD technique in conjunction with the other Python files within the directory.
 * The directory `d4j/` contains the results using the Defects4J v1.2 and v2.0 datasets; one can look to the `CombinationAnalysis.ipynb` file to reproduce the numbers in the paper from the result files. The technique implementation for Java is found in the `llm_interface/` subdirectory, along with the prompts used. We maintained a separate debugger server that the LLM could query, so the implementation for that is provided in `debugger_server/`.
 * The directory `human_study/` contains the results of the human study. The figures from RQ4 and RQ5 of the paper can be redrawn using the `AnswerAnalyzer.ipynb` script. Names have been anonymized; we only distinguish between students and developers. We also provide the HTML files containing the explanations that were used in the human study for reference.

## Running AutoSD on one Defects4J task

The Defects4J runner in `d4j/llm_interface/main.py` can call OpenAI models
directly. Set `OPENAI_API_KEY`, optionally set `OPENAI_MODEL`, and pass the same
model with `--model`.

Example prompt-only smoke test for `Chart-1`:

```bash
cd /home/mescribano/repos/autosd-artifact/d4j/llm_interface

export OPENAI_API_KEY="your_key_here"
export OPENAI_MODEL="gpt-4o-mini"
export AUTOSD_USAGE_PATH=/home/mescribano/repos/autosd-artifact/results/autosd-d4j-smoke/direct_Chart_1_usage.json

python main.py \
  --project Chart \
  --bug_id 1 \
  --prompt_file zsV3_prompt.txt \
  --n_steps 0 \
  --output_file /home/mescribano/repos/autosd-artifact/results/autosd-d4j-smoke/direct_Chart_1_trace.txt \
  --verbose 1 \
  --model gpt-4o-mini
```

`--output_file` stores the full AutoSD trace and generated repaired method.
`AUTOSD_USAGE_PATH` is optional; when set, AutoSD writes OpenAI usage such as
`prompt_tokens`, `completion_tokens`, `requests`, and `model` to that JSON file.
This is the same usage format consumed by the thesis orchestrator for cost
comparison.
