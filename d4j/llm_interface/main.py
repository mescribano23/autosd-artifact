import os
from shutil import which
import subprocess as sp
import argparse
import re
import time
import sys
import json
import requests

#import openai
import tqdm

from remote_jdb_client import RemoteJDBWrapper
# from inject_test import inject_test
import util

# openai.api_key = os.getenv("OPENAI_API_KEY")
# D4J_HOME = "/".join(which("defects4j").split("/")[:-3]) + "/"
D4J_PROMPT_INFO = './bug_prompt_info.json'
TEMPERATURE = 0.7
COMMIT_STATUS = './commit_status.csv'

def query_chatgpt_002(prompt, end_tokens=['`'], max_tokens=100):
    URI = 'http://localhost:8031/completions'
    d = {
        'prompt': prompt,
        'max_tokens': max_tokens,
        'temperature': TEMPERATURE,
        'end_tokens': end_tokens,
        'top_p': 1.0,
    }
    response = requests.post(URI, data=d)
    if response.status_code == 200:
        resp_text = json.loads(response.text)['choices'][0]['text']
        for delimiter in end_tokens:
            resp_text = resp_text.split(delimiter)[0]
        return resp_text
    if response.status_code != 200:
        raise ValueError(f'Request failed with error message {response.text}')

def query_human(prompt, end_tokens, max_tokens=100):
    return input('')

def safe_query_model(prompt, end_tokens=['`'], max_tokens=100):
    save_err = None
    for _ in range(10):
        try:
            return query_chatgpt_002(prompt, end_tokens, max_tokens)

        except Exception as e:
            print('ERR:', e)
            save_err = e
            if 'maximum context length' in str(e):
                break

            time.sleep(8)
    raise ValueError(f'Error persisted: {str(save_err)}')

def get_error_msg_from(test_file):
    working_dir = os.path.dirname(test_file)
    p = sp.run(['python', os.path.basename(test_file)], 
               cwd = working_dir, capture_output=True)
    error_msg = p.stderr.decode('utf-8')
    assert len(error_msg) != 0
    return error_msg

class PromptBuilder():
    def __init__(self, proj, bug_id, template_file, verbose=True):
        self._proj = proj
        self._bug_id = bug_id
        with open(D4J_PROMPT_INFO) as f:
            self._prompt_info = json.load(f)
        self._bug_info = self._check_bug_known()
        self._prompt = self._construct_prompt(template_file)
        with open(COMMIT_STATUS) as f:
            use_minimized = False
            for line in f:
                line_bug_name, commit_msg = line.split(',')
                if line_bug_name == f'{proj}_{bug_id}':
                    use_minimized = 'automatic commit' in commit_msg
                    break
        self._test_name = self._bug_info['test_name']+('Minimized' if use_minimized else '')
        
        if verbose:
            print(self._prompt, end='')
        self._verbose = verbose
        self._interaction_done = False
    
    def _inject_minimized_test(self):
        inject_test(util.ROOT_DIR+f'/{self._proj}_{self._bug_id}/',
                    util.d4j_test_path_prefix(self._proj, self._bug_id),
                    self._bug_info['test_name'],
                    self._bug_info['test_method'])
    
    def _check_bug_known(self):
        input_bug_name = self._proj + '_' + str(self._bug_id)
        for elem in self._prompt_info:
            if elem['bug_name'] == input_bug_name:
                return elem
        raise ValueError(f'The bug {input_bug_name} is unknown, sorry.')
    
    def _construct_prompt(self, template_file):
        with open(template_file) as f:
            prompt_template = f.read()
        replace_keys = ['report_text', 'test_method', 'error_message', 'buggy_method', 'bm_classpath']
        for key in replace_keys:
            prev_prompt_template = prompt_template
            prompt_template = prompt_template.replace('{{'+key+'}}', self._bug_info[key])
            assert prev_prompt_template != prompt_template, key
        return prompt_template
    
    def _simulated_print(self, text):
        for c in text:
            sys.stdout.write(c)
            sys.stdout.flush()
            time.sleep(0.03)

    def _add_to_prompt(self, text):
        self._prompt += text
        if self._verbose:
            self._simulated_print(text)

    def _file_numberer(self, file):
        with open(file) as f:
            lines = f.readlines()
        numbered_lines = []
        for i, line in enumerate(lines):
            numbered_lines.append(f'{i+1} {line}')
        return ''.join(numbered_lines).strip()
    
    def start_interaction(self):
        self._add_to_prompt('''Using the scientific method as described previously, I debugged the issue as follows.

Attempt 1.
Hypothesis: Given that''')
    
    def _start_jdb(self):
        self._jdbw = RemoteJDBWrapper(self._proj, self._bug_id, self._test_name)
    
    def _terminate_jdb(self):
        self._jdbw.terminate()

    def _handle_jdb_command(self, cmd):
        try:
            return self._jdbw._relay_command(cmd)
        except BrokenPipeError:
            return '[The breakpoint was not covered.]'
        
    def single_step(self, is_final=False):
        nl_plan = safe_query_model(self._prompt, end_tokens=['Experiment:'], max_tokens=512)
        self._add_to_prompt(nl_plan + 'Experiment: `')
        debugger_cmd = safe_query_model(self._prompt, end_tokens=['`'])
        self._add_to_prompt(debugger_cmd + '`\nObservation: `')
        
        self._start_jdb()
        process_result = self._handle_jdb_command(debugger_cmd)
        if type(process_result) != str:
            print(f'Warning: process result was non-string {process_result}')
            process_result = str(process_result)
        self._terminate_jdb()
        
        self._add_to_prompt(process_result + '`\nConclusion:')
        conclusion_str = safe_query_model(self._prompt, end_tokens=['Attempt', '```\n', '```java'], max_tokens=100)
        if '<DEBUGGING DONE>' in conclusion_str:
            self._add_to_prompt(conclusion_str.split('<DEBUGGING DONE>')[0] + '<DEBUGGING DONE>\n\n')
            self.final_step()
            self._interaction_done = True
        else:
            self._add_to_prompt(conclusion_str)
            if not is_final:
                self._add_to_prompt('Attempt')
    
    def _redact_failures(self, split_token = '## Analysis'):
        assert self._prompt.count(split_token) == 1
        attempt_str = self._prompt.split(split_token)[-1]
        attempt_lines = attempt_str.split('\n')
        conclusion_strings = [e for e in attempt_lines if 'Conclusion:' in e]
        failed_attempts = [i+1 for i, e in enumerate(conclusion_strings) if 'is supported' not in e]
        failed_attempt_string_indexes = [f'Attempt {i}.' for i in failed_attempts]
        failed_attempt_starts = [i for i, e in enumerate(attempt_lines) if e in failed_attempt_string_indexes]
        failed_attempt_ends = [i+1 for i, e in enumerate(attempt_lines) if 'Conclusion: The hypothesis is rejected' in e]
        failed_attempt_ends = [0] + failed_attempt_ends
        failed_attempt_starts = failed_attempt_starts + [-1]
        
        new_str = self._prompt.split(split_token)[0] + split_token
        for prev_end, new_start in zip(failed_attempt_ends, failed_attempt_starts):
            new_str += '\n'.join(attempt_lines[prev_end:new_start]) + '\n'
        if len(failed_attempts) == 3:
            new_str = '\n'.join(e for e in new_str.split('\n') if 'Using the scientific method' not in e)
        return new_str    

    def final_step(self):
        self._trace = self._prompt
        self._prompt = self._redact_failures()
        if self._verbose:
            print('====')
            print(self._prompt)
            print('====')
        self._add_to_prompt('The repaired code (full method, without comments) is:\n\n```java\n')
        patch = safe_query_model(self._prompt, end_tokens=['```\n'], max_tokens=1024)
        self._add_to_prompt(patch + '```\n')

    def take_steps(self, n_steps=10):
        if n_steps > 0:
            self.start_interaction()
        for i in range(n_steps):
            self.single_step(is_final = (i == n_steps-1))
            if self._interaction_done:
                break
        
        if not self._interaction_done:
            self.final_step()
            self._interaction_done = True
    
    def export(self, fname):
        with open(fname, 'w') as f:
            print(self._prompt, file=f)
    
    def get_solution(self):
        assert self._interaction_done
        generated_sol = self._prompt.split('```java')[-1].split('```')[0]
        generated_sol = '\n'.join([
            re.sub('^\d+ ', '', e)
            for e in generated_sol.split('\n') 
            if not (e.isnumeric() or 'assert' in e)])
        return generated_sol
    

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=str)
    parser.add_argument('--bug_id', type=int)
    parser.add_argument('--prompt_file', type=str, required=True)
    parser.add_argument('--n_steps', type=int, default=10)
    parser.add_argument('--output_file', type=str)
    parser.add_argument('--verbose', type=int, default=0)
    parser.add_argument('--all', type=int, default=0)
    parser.add_argument('--repeats', type=int, default=1)

    args = parser.parse_args()
    assert (args.all != 0) != (args.project is not None), 'Specify a single project, or use the --all command.'

    if args.all == 0:
        prompt_builder = PromptBuilder(args.project, args.bug_id, args.prompt_file,
                                       verbose=(args.verbose==1))
        prompt_builder.take_steps(args.n_steps)
        if args.output_file is not None:
            prompt_builder.export(args.output_file)
    else:
        with open(D4J_PROMPT_INFO) as f:
            all_bug_info = json.load(f)
        
        for r_idx in range(5, args.repeats+5):
            all_traces = []
            save_fname = args.output_file if args.repeats == 1 else args.output_file.split('.')[0]+f'_{r_idx}_T{TEMPERATURE}.json'
            print('Will save to file:', save_fname)
            for bug_info in tqdm.tqdm(all_bug_info):
                project, bug_id = bug_info['bug_name'].split('_')
                bug_id = int(bug_id)
                try:
                    prompt_builder = PromptBuilder(project, bug_id, args.prompt_file,
                                               verbose=(args.verbose==1))
                    prompt_builder.take_steps(args.n_steps)
                    all_traces.append({
                        'task_id': 'Defects4J-APR/'+bug_info['bug_name'],
                        'samples': [prompt_builder.get_solution()],
                        'trace': prompt_builder._trace,
                        'prompt_at_repair': prompt_builder._prompt
                    })
                except ValueError as e:
                    print('ValueError, likely length too long:', e)
                    continue
                except Exception as e:
                    print(f'Outer-loop exception ignored: {type(e)} {e}')
                    continue
                with open(save_fname, 'w') as f:
                    json.dump(all_traces, f)
            print(f'Iter {r_idx+1}/{args.repeats} Complete.')
