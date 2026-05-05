import signal
import json
import ast

class TimeoutException(Exception):
    pass

def handler(signum, frame):
    raise TimeoutException

signal.signal(signal.SIGALRM, handler)

def read_solutions(filename):
    sols = []
    with open(filename) as f:
        for line in f:
            sols.append(json.loads(line))
    return sols

class HEDataObject():
    def __init__(self):
        self._he_data = self._read_humaneval_data()
        self._problem_num = len(self._he_data)
    
    def _read_humaneval_data(self):
        he_data = dict()
        with open('./arhe_data/HumanEval.jsonl') as f:
            for line in f:
                line_obj = json.loads(line)
                he_data[line_obj['task_id']] = line_obj
        return he_data

class Evaluator(HEDataObject):
    def _get_exec_code(self, solution, custom_test=None, wrap_with_f=True):
        sol_task_id = solution['task_id']
        corresp_he_data = self._he_data[sol_task_id]
        
        llm_prompt = corresp_he_data['prompt']
        sample = solution['samples'][0].strip() + '\n'
        task_name = llm_prompt.split('def ')[-1].split('(')[0]
        llm_prompt = 'def '.join(llm_prompt.split('def ')[:-1])
        
        if custom_test is None:
            code_to_run = llm_prompt + sample + corresp_he_data['test']
        else:
            code_to_run = llm_prompt + sample + custom_test
        if wrap_with_f:
            code_to_run += f'\n\ncheck({task_name})'
            code_to_run = '\n'.join('    '+l for l in code_to_run.split('\n'))
            code_to_run = 'def go():\n' + code_to_run + '\ngo()'
        else:
            assert custom_test is not None
            l = custom_test.replace('candidate', task_name).strip()
            if '==' in l:
                separator = '=='
            elif '<' in l:
                separator = '<'
            elif '>' in l:
                separator = '>'
            elif ' is ' in l:
                separator = ' is '
            else:
                print('Separator unknown for', l)
                raise ValueError('Expected value extraction failed for assertion `'+l+'`')
            
            actual_value = l.split(separator)[0][6:].strip()

            r = ast.parse(l)
            r.body[0].msg = ''
            raw_assert = ast.unparse(r)
            custom_test_modified = raw_assert + ', ' + actual_value
            
            code_to_run = llm_prompt + sample + custom_test_modified
            
        return code_to_run
    
    def evaluate_sol(self, solution):
        task_id = solution['task_id']
        failing_tests = []
        for isolated_test_func in self._isolated_test_generator(task_id):
            code_to_run = self._get_exec_code(solution, isolated_test_func)
        
            try:
                signal.alarm(1)
                exec(code_to_run)
            except Exception as e:
                failing_test = isolated_test_func.split('\n')[-1]
                failing_tests.append({
                    'failing_assertion': failing_test,
                    'failing_exception': str(type(e)),
                })
            finally:
                signal.alarm(0)
                
        return failing_tests
    
    def _isolated_test_generator(self, task_id):
        org_test_func = self._he_data[task_id]['test']
        org_test_func = 'def ' + org_test_func.split('def ')[-1]
        parsed_test_func = ast.parse(org_test_func)
        for statement in parsed_test_func.body[0].body:
            if not isinstance(statement, ast.Assert):
                if ast.unparse(statement).startswith('print'):
                    continue
                raise ValueError(f'Unknown statement {ast.unparse(statement)} in {task_id}')
            new_func_ast = ast.parse(org_test_func)
            new_func_ast.body[0].body = [statement]
            yield ast.unparse(new_func_ast)
