import os
import subprocess as sp
from distutils.version import StrictVersion
import tqdm
import argparse

TARGET_DIR = '/home/sungmin/Documents/projects_23/humaneval-debugger/buggy_functions'
OUTPUT_DIR = './output/'

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--template_file', type=str, required=True)
    parser.add_argument('--label', type=str, required=True)
    args = parser.parse_args()

    for fname in tqdm.tqdm(sorted(os.listdir(TARGET_DIR))):
        if '.py' not in fname or 'test.py' in fname:
            continue
        task_id = int(fname.removesuffix('.py').split('_')[1])

        command = ['timeout', '10m',
            'python', 'main.py',
            '--function_file', os.path.join(TARGET_DIR, f'func_{task_id}.py'),
            '--test_file', os.path.join(TARGET_DIR, f'func_{task_id}_inftest.py'),
            '--n_steps', '4',
            '--template_file', args.template_file,
            '--output_file', os.path.join(OUTPUT_DIR, f'func_{task_id}_{args.label}_process.txt'),
        ]
        proc = sp.run(command, capture_output=True)
        with open(os.path.join(OUTPUT_DIR, 'proc_out', f'{args.label}_{task_id}_stdout.txt'), 'w') as f:
            print(proc.stdout.decode('utf-8'), file=f)
        with open(os.path.join(OUTPUT_DIR, 'proc_out', f'{args.label}_{task_id}_stderr.txt'), 'w') as f:
            print(proc.stderr.decode('utf-8'), file=f)
