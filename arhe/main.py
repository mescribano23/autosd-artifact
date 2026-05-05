import os
import subprocess as sp
import argparse
import re
import time
import sys
import json
import requests
import csv
import ast

from tqdm import tqdm
import openai

from evaluator import Evaluator

DEBUG = False
EPHEMERAL_FILE = 'debugging.py'

class CommentRemover(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        node.body = [e for e in node.body if not (isinstance(e, ast.Expr) and isinstance(e.value, ast.Constant))]
        self.generic_visit(node)
        return node

def query_model(prompt, end_tokens=['`'], max_tokens=100):
    response = openai.Completion.create(
        model='gpt-3.5-turbo-instruct',
        prompt=prompt,
        temperature=0.0,
        max_tokens=max_tokens,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0,
        stop=end_tokens
    )
    return_text = response['choices'][0]['text']
    return return_text

def safe_query_model(prompt, end_tokens=['`'], max_tokens=100):
    save_err = None
    for _ in range(5):
        try:
            return query_model(prompt, end_tokens, max_tokens)
        except Exception as e:
            print('ERR:', e)
            save_err = e
            time.sleep(8)
    return f'Error persisted: {str(save_err)}'

def get_error_msg_from(test_file):
    working_dir = os.path.dirname(test_file)
    p = sp.run(['python3.9', os.path.basename(test_file)], 
               capture_output=True)
    error_msg = p.stderr.decode('utf-8').strip()
    assert len(error_msg) != 0
    return error_msg

class PDBWrapper():
    def __init__(self, start_cmd):
        self._start_cmd = start_cmd
        self._pdb = sp.Popen(start_cmd.split(), stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE,
                             cwd=os.getcwd())
        self.client_preamble = self._read_stdout_to_prompt() + '\n(Pdb)'
        self._client_terminated = False
    
    def _read_stdout_to_prompt(self):
        stdout_read = ''
        next_char = 'a' # dummy value
        while ((re.search('\(Pdb\)', stdout_read) is None) and next_char):
            next_char = self._pdb.stdout.read(1).decode()
            stdout_read += next_char
        if not next_char:
            self._client_terminated = True
        stdout_read = stdout_read.strip()
        return '\n'.join(stdout_read.split('\n')[:-1])
    
    def _send_command(self, cmd):
        self._pdb.stdin.write(cmd.encode())
        self._pdb.stdin.write(b'\n')
        self._pdb.stdin.flush()
        out = self._read_stdout_to_prompt()
        return out
    
    def execute_command(self, cmd, with_unroll=False):
        if not with_unroll or 'p ' != cmd.split(';;')[-1].strip()[:2]:
            stdout_read = self._send_command(cmd)
            return stdout_read
        else:
            cmd_blocks = cmd.split(';;')
            cmd_blocks = cmd_blocks[:2] + ['globals().update(locals())'] + cmd_blocks[2:]
            cmd = ';;'.join(cmd_blocks)
            first_output = self._send_command(cmd)
            output_list = [first_output.split('\n')[-1]]
            if 'Uncaught exception.' in first_output:
                return '[The breakpoint line was not covered by the test.]'
            cmd_without_breakpoint = ';;'.join(cmd.split(';;')[1:])
            next_output = self._send_command('c')
            while 'Uncaught exception.' not in next_output:
                next_output = self._send_command(cmd.split(';;')[-1])
                output_list.append(next_output.split('\n')[-1])
                next_output = self._send_command('c')
            
            # error output handling
            if all('***' in e for e in output_list):
                return output_list[0]
            else:
                return [e for e in output_list if '***' not in e]
                
    
    def terminate(self):
        self._pdb.terminate()
    
    @property
    def terminated(self):
        return self._client_terminated

class PromptBuilder():
    def __init__(self, function_file, template_file = 'initial_template.txt', verbose=True):
        with open(template_file) as f:
            prompt_template = f.read().strip()
        self._error_msg = get_error_msg_from(function_file)
        self._prompt = prompt_template.format(
            function_file = function_file,
            function_code = self._file_numberer(function_file),
            error_msg = self._error_msg
        )
        self._function_file = function_file
        if verbose:
            print(self._prompt, end='')
        self._verbose = verbose
        self._interaction_done = False
        self._cr = CommentRemover()
    
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
    
    def start_interaction(self, append_start = True):
        prehandling = safe_query_model(self._prompt, end_tokens=['Attempt'], max_tokens=300)
        self._add_to_prompt(prehandling)
        if append_start:
            self._add_to_prompt('Attempt')
    
    def _start_pdb(self):
        cmd = f'python3.9 -m pdb {self._function_file}'

        self._pdbw = PDBWrapper(cmd)
        process_result = self._pdbw.client_preamble
    
    def _terminate_pdb(self):
        self._pdbw.terminate()

    def _replace_in_file(self, replace_line, org_expr, new_expr):
        replace_line = int(replace_line)
        with open(self._function_file) as f:
            org_lines = f.readlines()
        new_line = org_lines[replace_line-1].replace(org_expr, new_expr)
        if new_line == org_lines[replace_line-1]:
            raise ValueError(f'expr {org_expr} not found in line {replace_line}')
        org_lines[replace_line-1] = new_line
        with open(self._function_file, 'w') as f:
            f.write(''.join(org_lines))
        
    def _exec_pdb_command(self, debugger_cmd, with_unroll=True):
        if 'AND RUN' in debugger_cmd:
            if 'REPLACE' not in debugger_cmd:
                return 'Unknown command; please use REPLACE.'
            replace_cmd = debugger_cmd.removesuffix(') AND RUN').removeprefix('REPLACE(')
            try:
                replace_line, org_expr, new_expr = list(csv.reader([replace_cmd], skipinitialspace=True))[0]
            except ValueError:
                print(f'FAILURE ON {replace_cmd} ;;')
                return 'Could not parse {replace_cmd}; please specify three arguments.'
            try:
                self._replace_in_file(replace_line, org_expr, new_expr)
                error_msg = get_error_msg_from(self._function_file)
                self._replace_in_file(replace_line, new_expr, org_expr)
                return error_msg.strip().split('\n')[-1]
            except ValueError as e:
                return str(e)
            except AssertionError:
                self._replace_in_file(replace_line, new_expr, org_expr)
                return '[No exception triggered]'
            except Exception as e:
                print('Unfamiliar exception', e)
                self._replace_in_file(replace_line, new_expr, org_expr)
                return str(e)
        
        output_obj = self._pdbw.execute_command(debugger_cmd, with_unroll=with_unroll)
        if not with_unroll or 'p ' != debugger_cmd.split(';;')[-1].strip()[:2]:
            return output_obj.split('\n')[-1]
        else:
            if isinstance(output_obj, str):
                return output_obj
            else:
                assert type(output_obj) == list
                output_list = output_obj

            if 'AssertionError' in self._error_msg:
                true_debugger_output = output_list[:len(output_list)//2]
            else:
                true_debugger_output = output_list

            if len(true_debugger_output) == 1:
                return str(true_debugger_output[0])
            else:
                return 'At each loop execution, the expression was: ' + '['+', '.join(true_debugger_output)+']'
            
        
    def single_step(self, is_final=False):
        nl_plan = safe_query_model(self._prompt, end_tokens=['Experiment:'], max_tokens=300)
        self._add_to_prompt(nl_plan + 'Experiment: `')
        debugger_cmd = safe_query_model(self._prompt, end_tokens=['`'])
        debugger_cmd = debugger_cmd.replace(' n ;', ' c ;')
        debugger_cmd = debugger_cmd.replace(' ; ', ' ;; ')
        self._add_to_prompt(debugger_cmd + '`\nObservation: `')
        
        self._start_pdb()
        process_result = self._exec_pdb_command(debugger_cmd)
        self._terminate_pdb()
        
        self._add_to_prompt(process_result + '`\nConclusion:')
        conclusion_str = safe_query_model(self._prompt, end_tokens=['Attempt', '```\n', '```python'], max_tokens=512)
        
        if '<DEBUGGING DONE>' in conclusion_str:
            self._add_to_prompt(conclusion_str.split('<DEBUGGING DONE>')[0] + '<DEBUGGING DONE>\n\n')
            self.final_step()
            self._interaction_done = True
        else:
            self._add_to_prompt(conclusion_str)
            if not is_final:
                self._add_to_prompt('Attempt')
        
    def _content_without_comments(self, fname):
        with open(fname) as f:
            root = ast.parse(f.read())
            last_function_node = [e for e in root.body if isinstance(e, ast.FunctionDef)][-1]
            return ast.unparse(self._cr.visit(last_function_node))
        
    def final_step(self):
        self._trace = self._prompt
        self._prompt = self._redact_failures()
        self._add_to_prompt('The repaired code (full method, without comments) is:\n\n```python\ndef')
        patch = safe_query_model(self._prompt, end_tokens=['```\n'], max_tokens=512)
        self._add_to_prompt(patch + '```\n')

    def take_steps(self, n_steps=10):
        for i in range(n_steps):
            self.single_step(is_final = (i == n_steps-1))
            if self._interaction_done:
                break
        
        if not self._interaction_done:
            self.final_step()
            self._interaction_done = True
    
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
        return new_str
    
    def get_solution(self):
        assert self._interaction_done
        generated_sol = self._prompt.split('```python')[-1].split('```')[0]
        generated_sol = '\n'.join([
            re.sub('^\d+ ', '', e)
            for e in generated_sol.split('\n') 
            if not (e.isnumeric() or 'assert' in e)])
        return generated_sol
        

class ASDEvaluator(Evaluator):
    def __init__(self, mutant_file, template_file):
        with open(mutant_file) as f:
            self._mutant_info = json.load(f)
        self._template_file = template_file
        super(ASDEvaluator, self).__init__()
    
    def get_solutions(self, N=1, steps=3, ephemeral_file=EPHEMERAL_FILE):
        if N != 1:
            raise NotImplementedError
        for mutant_instance in tqdm(self._mutant_info):
            custom_test = mutant_instance['failed_tests'][0]['failing_assertion'].strip()
            try:
                exec_code = self._get_exec_code(
                    solution = {
                        'task_id': mutant_instance['task_id'],
                        'samples': [mutant_instance['mutant']],
                    }, 
                    custom_test = custom_test,
                    wrap_with_f = False
                )
            except ValueError as e:
                print('Warning:', type(e), e)
                mutant_instance['samples'] = [mutant_instance['mutant']]
                continue
            
            with open(ephemeral_file, 'w') as f:
                f.write(exec_code)
            
            try:
                prompt_builder = PromptBuilder(ephemeral_file, self._template_file, verbose=DEBUG)
                prompt_builder.take_steps(n_steps=steps)
                proposed_sol = prompt_builder.get_solution()
            except Exception as e:
                print('Warning@PromptBuilder:', type(e), e)
                mutant_instance['samples'] = ['']
                continue
            if DEBUG:
                print(proposed_sol)
                print('a-ok')
                exit(0)
            mutant_instance['samples'] = [proposed_sol]
            mutant_instance['trace'] = prompt_builder._trace
            mutant_instance['prompt_at_repair'] = prompt_builder._prompt
    
    def evaluate_all_solutions(self):
        for idx, mut_info in enumerate(self._mutant_info):
            evaluation_object = {
                'task_id': mut_info['task_id'],
                'samples': mut_info['samples']
            }
            failing_tests = self.evaluate_sol(evaluation_object)
            mut_info['passed'] = (len(failing_tests) == 0)
            mut_info['fail_tests'] = failing_tests
            mut_info['ARHE_id'] = idx
    
    def save_to(self, file_name):
        with open(file_name, 'w') as f:
            json.dump(self._mutant_info, f)

    
            
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mutant_file', type=str, required=True)
    parser.add_argument('--template_file', type=str, required=True)
    parser.add_argument('--output_file', type=str)
    parser.add_argument('--steps', type=int, default=3)
    parser.add_argument('--repeats', type=int, default=1)

    args = parser.parse_args()

    for r_idx in range(args.repeats):
        asd_evaluator = ASDEvaluator(
            args.mutant_file, args.template_file
        )
        asd_evaluator.get_solutions(steps=args.steps)
        asd_evaluator.evaluate_all_solutions()
        if args.output_file is not None:
            num_out_file = args.output_file if args.repeats == 1 else args.output_file.split('.')[0]+f'_{r_idx}.json'
            asd_evaluator.save_to(num_out_file)
            print(f'Iter {r_idx+1}/{args.repeats} saved')
