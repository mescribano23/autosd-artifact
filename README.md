# Artifact for AutoSD

This repository contains the code and result files for AutoSD, a novel explainable APR technique.

## Structure

 * The directory `arhe/` contains the results using the ARHE dataset; one can look to the `ARHEAnalysis.ipynb` file to reproduce the numbers from the result files. Along with this, `main.py` implements the AutoSD technique in conjunction with the other Python files within the directory.
 * The directory `d4j/` contains the results using the Defects4J v1.2 and v2.0 datasets; one can look to the `CombinationAnalysis.ipynb` file to reproduce the numbers in the paper from the result files. The technique implementation for Java is found in the `llm_interface/` subdirectory, along with the prompts used. We maintained a separate debugger server that the LLM could query, so the implementation for that is provided in `debugger_server/`.
 * The directory `human_study/` contains the results of the human study. The figures from RQ4 and RQ5 of the paper can be redrawn using the `AnswerAnalyzer.ipynb` script. Names have been anonymized; we only distinguish between students and developers. We also provide the HTML files containing the explanations that were used in the human study for reference.

