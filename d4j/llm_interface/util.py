# parent of defects4j repo directories
import os
from shutil import which
from datetime import datetime
import subprocess as sp

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))+'/data/defects4j-buggy-projects/'
# defects4j home directory
# D4J_HOME = "/".join(which("defects4j").split("/")[:-3]) + "/"
# BPE info
BPE_OP_FILE = './etc_data/CasePreserved_varpairs_BPE.pkl'
BPE_VOCAB_FILE = 'etc_data/CasePreserved_vocab_BPE.pkl'
# where perfect fl information can be fetched
BUG_INFO_JSON = './etc_data/defects4j-fullv2-bugs.json'
# where candidate patch files are generated
PATCH_DIR = os.path.dirname(os.path.abspath(__file__))+'/generated_patches/'
# where FL-sorted statement locations are
FL_INFO_DIR = './etc_data/ochiai_ranks/'
# which cased representation to use (True for lower only, False for cap+low)
LOWER = False
# random seed
RAND_SEED=1234

def git_reset(repo_dir_path):
    sp.run(['git', 'reset', '--hard', 'HEAD'],
           cwd=repo_dir_path, stdout=sp.DEVNULL, stderr=sp.DEVNULL)


def git_clean(repo_dir_path):
    sp.run(['git', 'clean', '-df'],
           cwd=repo_dir_path, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
    

def compile_repo(repo_dir_path):
    # actual compiling
    compile_proc = sp.run(
        ['defects4j', 'compile'],
        stdout=sp.PIPE, stderr=sp.PIPE, cwd=repo_dir_path)

def run_test(repo_dir_path, test_name):
    '''Returns failing test number.'''
    test_process = sp.run(['timeout', '1m', 'defects4j', 'test', '-t', test_name],
                          capture_output=True, cwd=repo_dir_path)
    captured_stdout = test_process.stdout.decode()
    if len(captured_stdout) == 0:
        return -1, []  # likely compile error, all tests failed
    else:
        stdout_lines = captured_stdout.split('\n')
        failed_test_num = int(stdout_lines[0].removeprefix('Failing tests: '))
        failed_tests = [e.strip(' - ') for e in stdout_lines[1:] if len(e) > 1]
        # reported failing test number and actual number of collected failing tests should match
        assert len(failed_tests) == failed_test_num

        return 0, failed_tests

def run_all_tests(repo_dir_path):
    test_process = sp.run(['timeout', '1m', 'defects4j', 'test'],
                          capture_output=True, cwd=repo_dir_path)
    captured_stdout = test_process.stdout.decode()
    if len(captured_stdout) == 0:
        return -1, []  # likely compile error, all tests failed
    else:
        stdout_lines = captured_stdout.split('\n')
        failed_test_num = int(stdout_lines[0].removeprefix('Failing tests: '))
        failed_tests = [e.strip(' - ') for e in stdout_lines[1:] if len(e) > 1]
        # reported failing test number and actual number of collected failing tests should match
        assert len(failed_tests) == failed_test_num
        return 0, failed_tests
    

def repo_path(proj, bugid):
    return ROOT_DIR + f'{proj}_{bugid}/'

class TimeoutException(Exception):
    pass

def d4j_path_prefix(proj, bug_num):
    if proj == 'Chart':
        return 'source/'
    elif proj == 'Closure':
        return 'src/'
    elif proj == 'Lang':
        if bug_num <= 35:
            return 'src/main/java/'
        else:
            return 'src/java/'
    elif proj == 'Math':
        if bug_num <= 84:
            return 'src/main/java/'
        else:
            return 'src/java/'
    elif proj == 'Mockito':
        return 'src/'
    elif proj == 'Time':
        return 'src/main/java/'
    elif proj == 'Cli':
        if bug_num <= 29:
            return 'src/java/'
        else:
            return 'src/main/java/'
    elif proj == 'Codec':
        if bug_num <= 10:
            return 'src/java/'
        else:
            return 'src/main/java/'
    elif proj == 'Collections':
        return 'src/main/java/'
    elif proj == 'Compress':
        return 'src/main/java/'
    elif proj == 'Csv':
        return 'src/main/java/'
    elif proj == 'Gson':
        return 'gson/src/main/java/'
    elif proj in ('JacksonCore', 'JacksonDatabind', 'JacksonXml'):
        return 'src/main/java/'
    elif proj == 'Jsoup':
        return 'src/main/java/'
    elif proj == 'JxPath':
        return 'src/java/'
    else:
        raise ValueError(f'Unrecognized project {proj}')

def d4j_test_path_prefix(proj, bug_num):
    if proj == 'Chart':
        return 'tests/'
    elif proj == 'Closure':
        return 'test/'
    elif proj == 'Lang':
        if bug_num <= 35:
            return 'src/test/java/'
        else:
            return 'src/test/'
    elif proj == "Math":
        if bug_num <= 84:
            return 'src/test/java/'
        else:
            return 'src/test/'
    elif proj == 'Mockito':
        return 'test/'
    elif proj == "Time":
        return 'src/test/java/'
    elif proj == 'Cli':
        if bug_num <= 29:
            return 'src/test/'
        else:
            return 'src/test/java/'
    elif proj == 'Codec':
        if bug_num <= 10:
            return 'src/test/'
        else:
            return 'src/test/java/'
    elif proj == 'Collections':
        return 'src/test/java/'
    elif proj == 'Compress':
        return 'src/test/java/'
    elif proj == 'Csv':
        return 'src/test/java/'
    elif proj == 'Gson':
        return 'gson/src/test/java/'
    elif proj in ('JacksonCore', 'JacksonDatabind', 'JacksonXml'):
        return 'src/test/java/'
    elif proj == 'Jsoup':
        return 'src/test/java/'
    elif proj == 'JxPath':
        return 'src/test/'
    else:
        raise ValueError(f'Cannot find test path prefix for {proj}{bug_num}')

def parse_abs_path(jfile):
    repo_dir_name = jfile.removeprefix(ROOT_DIR).split('/')[0]
    repo_dir_path = ROOT_DIR + repo_dir_name + '/'
    rel_jfile_path = jfile.removeprefix(repo_dir_path)
    return repo_dir_path, rel_jfile_path

def log(*args):
    '''Used only when flush is desired'''
    now = datetime.now()
    now_str = now.strftime(r'%Y-%m-%d %H:%M:%S.%f')
    print(f'[{now_str}]', *args, flush=True)