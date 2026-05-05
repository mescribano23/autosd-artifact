import os
import ast
import argparse
import re
import time
import sys
import json

from tqdm import tqdm

from evaluator import Evaluator

class ReverseMutator(object):
    def __init__(self):
        pass
    
    def _get_human_sol(self, sol_id):
        sol_task_id = f'HumanEval/{sol_id}'
        solution = self._he_data[sol_task_id]['canonical_solution']
        preamble = 'def ' + self._he_data[sol_task_id]['prompt'].split('def ')[-1]
        return preamble + solution
    
    @staticmethod
    def wrap_sol_in_eval_format(sol, sol_id):
        return {
            'task_id': f'HumanEval/{sol_id}',
            'samples': [sol],
        }
    
    def get_all_mutants(self, mut_id, mut_code):
        mutating_func_list = [
            self._int_const_changer,
            self._str_const_changer,
            self._aug_assign_changer,
            self._op_changer,
#             self._if_remover,
            self._if_negator,
#             self._binop_remover,
        ]
        for mut_func in mutating_func_list:
            for mutant in mut_func(mut_code):
                yield {
                    'mutant': mutant,
                    'mut_op': mut_func.__name__,
                    'task_id': f'ARHE/{mut_id}',
                }
    
    def _int_const_changer(self, sol):
        sol_ast = ast.parse(sol)
        for node in ast.walk(sol_ast):
            if not isinstance(node, ast.Constant):
                continue
            if node.value in (0, 1):
                node.value = 1 - node.value
                yield ast.unparse(sol_ast)
                node.value = 1 - node.value
    
    def _str_const_changer(self, sol):
        sol_ast = ast.parse(sol)
        
        existing_strs = []
        for node in ast.walk(sol_ast):
            if not isinstance(node, ast.Constant):
                continue
            if isinstance(node.value, str) and len(node.value) != 0:
                existing_strs.append(node.value)
        
        for node in ast.walk(sol_ast):
            if not isinstance(node, ast.Constant):
                continue
            if isinstance(node.value, str) and len(node.value) != 0:
                org_str_value = node.value
                
                # capitalization
                if not org_str_value.isupper():
                    node.value = org_str_value.upper()
                    yield ast.unparse(sol_ast)
                if not org_str_value.islower():
                    node.value = org_str_value.lower()
                    yield ast.unparse(sol_ast)
                
                node.value = org_str_value
            elif isinstance(node.value, str): # length zero case
                for existing_str in existing_strs:
                    node.value = existing_str
                    yield ast.unparse(sol_ast)
                node.value = ''
    
    def _aug_assign_changer(self, sol):
        sol_ast = ast.parse(sol)
        for node in ast.walk(sol_ast):
            if isinstance(node, ast.AugAssign):
                if isinstance(node.op, ast.Add):
                    node.op = ast.Sub()
                    yield ast.unparse(sol_ast)
                    node.op = ast.Add()
                elif isinstance(node.op, ast.Sub):
                    node.op = ast.Add()
                    yield ast.unparse(sol_ast)
                    node.op = ast.Sub()
                elif isinstance(node.op, ast.Mult):
                    node.op = ast.Div()
                    yield ast.unparse(sol_ast)
                    node.op = ast.Mult()
                elif isinstance(node.op, ast.Div):
                    node.op = ast.Mult()
                    yield ast.unparse(sol_ast)
                    node.op = ast.Div()
    
    def _op_changer(self, sol):
        sol_ast = ast.parse(sol)
        for node in ast.walk(sol_ast):
            if isinstance(node, ast.Compare):
                for op_idx, op in enumerate(node.ops):
                    if isinstance(op, ast.Lt):
                        node.ops[op_idx] = ast.LtE()
                        yield ast.unparse(sol_ast)
                        node.ops[op_idx] = ast.Lt()
                    elif isinstance(op, ast.LtE):
                        node.ops[op_idx] = ast.Lt()
                        yield ast.unparse(sol_ast)
                        node.ops[op_idx] = ast.LtE()
                    elif isinstance(op, ast.Gt):
                        node.ops[op_idx] = ast.GtE()
                        yield ast.unparse(sol_ast)
                        node.ops[op_idx] = ast.Gt()
                    elif isinstance(op, ast.GtE):
                        node.ops[op_idx] = ast.Gt()
                        yield ast.unparse(sol_ast)
                        node.ops[op_idx] = ast.GtE()
                    elif isinstance(op, ast.Eq):
                        node.ops[op_idx] = ast.NotEq()
                        yield ast.unparse(sol_ast)
                        node.ops[op_idx] = ast.Eq()
                    elif isinstance(op, ast.NotEq):
                        node.ops[op_idx] = ast.Eq()
                        yield ast.unparse(sol_ast)
                        node.ops[op_idx] = ast.NotEq()
            elif isinstance(node, ast.BinOp):
                if isinstance(node.op, ast.Add):
                    node.op = ast.Sub()
                    yield ast.unparse(sol_ast)
                    node.op = ast.Add()
                elif isinstance(node.op, ast.Sub):
                    node.op = ast.Add()
                    yield ast.unparse(sol_ast)
                    node.op = ast.Sub()
                elif isinstance(node.op, ast.Mult):
                    node.op = ast.Div()
                    yield ast.unparse(sol_ast)
                    node.op = ast.Mult()
                elif isinstance(node.op, ast.Div):
                    node.op = ast.Mult()
                    yield ast.unparse(sol_ast)
                    node.op = ast.Div()
    
    def _if_remover(self, sol):
        class DeleteIf_LeaveThen(ast.NodeTransformer):
            def __init__(self, change_idx, *args, **kwargs):
                self._change_idx = change_idx
                self._curr_counter = -1
                super(DeleteIf_LeaveThen, self).__init__(*args, **kwargs)

            def visit_If(self, node):
                self._curr_counter += 1
                if (self._curr_counter == self._change_idx and
                    len(node.body) == 1):
                    return self.visit(node.body[0])
                else:
                    return ast.If(
                        test = node.test,
                        body = [self.visit(e) for e in node.body],
                        orelse = [self.visit(e) for e in node.orelse] if node.orelse is not None else None
                    )

        class DeleteIf_LeaveElse(ast.NodeTransformer):
            def __init__(self, change_idx, *args, **kwargs):
                self._change_idx = change_idx
                self._curr_counter = -1
                super(DeleteIf_LeaveElse, self).__init__(*args, **kwargs)

            def visit_If(self, node):
                self._curr_counter += 1
                if (self._curr_counter == self._change_idx and 
                    node.orelse is not None and 
                    len(node.orelse) == 1):
                    return self.visit(node.orelse[0])
                else:
                    return ast.If(
                        test = node.test,
                        body = [self.visit(e) for e in node.body],
                        orelse = [self.visit(e) for e in node.orelse] if node.orelse is not None else None
                    )

        modifiers = [
            DeleteIf_LeaveThen,
            DeleteIf_LeaveElse,
        ]

        sol_ast = ast.parse(sol)
        if_count = len([n for n in ast.walk(sol_ast) if isinstance(n, ast.If)])

        for modifier_class in modifiers:
            for if_idx in range(if_count):
                sol_ast = ast.parse(sol)
                mod_ast = modifier_class(if_idx).visit(sol_ast)
                yield ast.unparse(mod_ast)

    def _if_negator(self, sol):
        sol_ast = ast.parse(sol)
        for node in ast.walk(sol_ast):
            if isinstance(node, ast.If):
                node.test = ast.UnaryOp(
                    op = ast.Not(),
                    operand = node.test
                )
                yield ast.unparse(sol_ast)
                node.test = node.test.operand
    
    def _binop_remover(self, sol):
        class DeleteBinOp_LeaveLeft(ast.NodeTransformer):
            def __init__(self, change_idx, *args, **kwargs):
                self._change_idx = change_idx
                self._curr_counter = -1
                super(DeleteBinOp_LeaveLeft, self).__init__(*args, **kwargs)

            def visit_BinOp(self, node):
                self._curr_counter += 1
                if (self._curr_counter == self._change_idx):
                    return self.visit(node.left)
                else:
                    return ast.BinOp(
                        left = self.visit(node.left),
                        op = node.op,
                        right = self.visit(node.right),
                    )

        class DeleteBinOp_LeaveRight(ast.NodeTransformer):
            def __init__(self, change_idx, *args, **kwargs):
                self._change_idx = change_idx
                self._curr_counter = -1
                super(DeleteBinOp_LeaveRight, self).__init__(*args, **kwargs)

            def visit_BinOp(self, node):
                self._curr_counter += 1
                if (self._curr_counter == self._change_idx):
                    return self.visit(node.right)
                else:
                    return ast.BinOp(
                        left = self.visit(node.left),
                        op = node.op,
                        right = self.visit(node.right),
                    )

        modifiers = [
            DeleteBinOp_LeaveLeft,
            DeleteBinOp_LeaveRight,
        ]

        sol_ast = ast.parse(sol)
        if_count = len([n for n in ast.walk(sol_ast) if isinstance(n, ast.BinOp)])

        for modifier_class in modifiers:
            for if_idx in range(if_count):
                sol_ast = ast.parse(sol)
                mod_ast = modifier_class(if_idx).visit(sol_ast)
                yield ast.unparse(mod_ast)

class BaselineEvaluator(Evaluator):
    def __init__(self, mutant_file):
        with open(mutant_file) as f:
            self._mutant_info = json.load(f)
        self._rm = ReverseMutator()
        self._generated_prompts = []
        super(BaselineEvaluator, self).__init__()
    
    def get_solutions(self, N=1):
        '''Get N solutions from the LLM.'''
        for idx, mut_info in tqdm(enumerate(self._mutant_info)):
            buggy_code = mut_info['mutant']
            possible_sols = [e['mutant'] for e in self._rm.get_all_mutants(idx, buggy_code)]
            self._generated_prompts.append({
                'samples': possible_sols
            })
    
    def evaluate_all_solutions(self):
        import random
        assert len(self._mutant_info) == len(self._generated_prompts)
        overall_stats = []
        for _ in range(100):
            total_passed = 0
            for mut_info, prompt_obj in tqdm(list(zip(self._mutant_info, self._generated_prompts))):
                evaluation_object = {
                    'task_id': mut_info['task_id'],
                    'samples': random.sample(prompt_obj['samples'], k=min(10, len(prompt_obj['samples'])))
                }
                failing_tests = self.evaluate_sol(evaluation_object)
                prompt_obj['passed'] = (len(failing_tests) == 0)
                total_passed += int(len(failing_tests) == 0)
            print(total_passed)
            overall_stats.append(total_passed)
        print(overall_stats)
            
    
    def save_to(self, file_name):
        with open(file_name, 'w') as f:
            json.dump(self._generated_prompts, f)
            
    

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mutant_file', type=str, required=True)
    parser.add_argument('--output_file', type=str)

    args = parser.parse_args()

    baseline_evaluator = BaselineEvaluator(
        args.mutant_file
    )
    baseline_evaluator.get_solutions()
    baseline_evaluator.evaluate_all_solutions()
    if args.output_file is not None:
        baseline_evaluator.save_to(args.output_file)
