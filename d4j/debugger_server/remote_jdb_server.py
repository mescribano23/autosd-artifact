import socket
import subprocess as sp
from shutil import which
import json, os, csv
from collections import Counter, defaultdict

from jdb_interface import JDBWrapper

import util

HOST = ''
PORT = 13377
MAX_LOOP = 100
MAX_SHOW_LEN = 50
D4J_HOME = "/".join(which("defects4j").split("/")[:-3]) + "/"

def local_handle_jdb_request(inbound_data):
    inbound_bug_name = inbound_data['proj'] + '_' + str(inbound_data['bug_id'])
    repo_dir_path = os.path.join(util.ROOT_DIR, inbound_bug_name)
    jdbw = JDBWrapper(
        D4J_HOME, 
        inbound_data['proj'], 
        inbound_data['bug_id'],
        inbound_data['test_name'],
    )
    debugger_cmd = inbound_data['jdb_cmd'].strip().rstrip(';')
    known_results = []
    try:
        last_command = None
        last_result = None
        for debugger_indiv_cmd in debugger_cmd.split(';'):
            if 'print ' in debugger_indiv_cmd.strip():
                target_expr = debugger_indiv_cmd.strip().removeprefix('print ')
                last_result = jdbw.evaluate_expr(target_expr)
            else:
                jdbw._relay_command(debugger_indiv_cmd)
            last_command = debugger_indiv_cmd
        known_results.append(last_result)
        assert last_command is not None
        if 'print ' in last_command.strip():
            target_expr = last_command.strip().removeprefix('print ')
            for _ in range(MAX_LOOP):
                jdbw.move_on()
                if jdbw._client_terminated:
                    break
                known_results.append(jdbw.evaluate_expr(target_expr))
            known_results = [(e if len(e) < MAX_SHOW_LEN else e[:MAX_SHOW_LEN]+'...') if e is not None else '[error]'
                             for e in known_results]
        if len(known_results) == 1:
            return known_results[0]
        else:
            count_results = ', '.join(f'[{k}]:{v}' for k, v in Counter(known_results).items())
            count_results = 'The values at loop execution were: [' + count_results + ']'
            return count_results
    except BrokenPipeError:
        return '[The breakpoint was not covered.]'
    finally:
        jdbw.terminate()

def modify_code(replace_command, abs_path):
    with open(abs_path) as f:
        org_code = f.read()
        code_lines = [e+'\n' for e in org_code.split('\n')]
    
    sub_cmds = replace_command.split('AND')
    sub_cmds = [e for e in sub_cmds if 'REPLACE' in e] +\
               [e for e in sub_cmds if 'ADD' in e] +\
               [e for e in sub_cmds if 'DEL' in e]
    add_lines = []
    del_lines = []
    for sub_cmd in sub_cmds:
        sub_cmd = sub_cmd.strip()
        if 'REPLACE' in sub_cmd:
            replace_cmd = sub_cmd.removesuffix(')').removeprefix('REPLACE(')
            try:
                replace_cmd = replace_cmd.replace('\\\"', '""')
                replace_line, org_expr, new_expr = list(csv.reader([replace_cmd], skipinitialspace=True))[0]
                replace_line = int(replace_line)
                code_lines[replace_line-1] = code_lines[replace_line-1].replace(org_expr, new_expr)
            except ValueError:
                print(f'Warning: the expression {sub_cmd} will not be used.')
        elif 'ADD' in sub_cmd:
            add_cmd = sub_cmd.removesuffix(')').removeprefix('ADD(')
            try:
                add_cmd = add_cmd.replace('\\\"', '""')
                add_line, new_expr = list(csv.reader([add_cmd], skipinitialspace=True))[0]
                add_line = int(add_line)
                total_shift = len([e for e in add_lines if e < add_line])
                real_idx = add_line-1+total_shift
                code_lines.insert(real_idx, new_expr + '\n' if new_expr[-1] != '\n' else '')
                add_lines.append(add_line)
            except ValueError:
                print(f'Warning: the expression {sub_cmd} will not be used.')
        elif 'DEL' in sub_cmd:
            del_line = int(sub_cmd.removesuffix(')').removeprefix('DEL('))
            total_shift = len([e for e in add_lines if e < del_line]) - \
                          len([e for e in del_lines if e < del_line])
            real_idx = del_line-1+total_shift
            del code_lines[real_idx]
            del_lines.append(del_line)
    
    with open(abs_path, 'w') as f:
        f.write(''.join(code_lines))

def local_handle_modNrun_req(inbound_data):
    with open('./bug_prompt_info.json') as f:
        bug_info = json.load(f)
    inbound_bug_name = inbound_data['proj'] + '_' + str(inbound_data['bug_id'])
    this_bug_info = [e for e in bug_info if e['bug_name'] == inbound_bug_name][0]
    buggy_classpath = this_bug_info['bm_classpath']
    buggy_relpath = os.path.join(
        util.d4j_path_prefix(inbound_data['proj'], inbound_data['bug_id']),
        buggy_classpath.split('$')[0].replace('.', '/') + '.java'
    )
    repo_dir_path = os.path.join(util.ROOT_DIR, inbound_bug_name)
    buggy_file_path = os.path.join(repo_dir_path, buggy_relpath)
    
    util.git_clean(repo_dir_path)
    modify_code(inbound_data['jdb_cmd'], buggy_file_path)
    util.compile_repo(repo_dir_path)
    compile_succ, fail_tests = util.run_test(repo_dir_path, inbound_data['test_name'])
    util.git_reset(repo_dir_path)
    util.git_clean(repo_dir_path)
    util.compile_repo(repo_dir_path)
    if compile_succ == -1:
        return '[The code failed to compile.]'
    elif len(fail_tests) == 0:
        return '[The failing test now passes.]'
    else:
        return '[The failing test still fails after the change.]'
        
def local_handle_request(inbound_data):
    if 'AND RUN' in inbound_data['jdb_cmd']:
        try:
            return local_handle_modNrun_req(inbound_data)
        except Exception as e:
            return '[There was an error while executing the test.]'
    elif ('REPLACE' in inbound_data['jdb_cmd'] or
          'ADD' in inbound_data['jdb_cmd'] or
          'DEL' in inbound_data['jdb_cmd']):
        return '[Your command appears malformed; if you want to run a test, make sure AND RUN is added.]'
    else:
        try:
            return local_handle_jdb_request(inbound_data)
        except Exception as e:
            print(type(e), e)
            return '[There was an error while handling a debugger command.]'

def recvall(sock):
    BUFF_SIZE = 1024 # 4 KiB
    data = b''
    while True:
        part = sock.recv(BUFF_SIZE)
        data += part
        if len(part) < BUFF_SIZE:
            # either 0 or end of data
            break
    return data
        
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind((HOST, PORT))
    s.listen(1)
    print('Listening...')
    while True:
        conn, addr = s.accept()
        with conn:
            print('Connected by', addr)
            while True:
                try:
                    data = recvall(conn)
                    if not data: break
                    parsed_data = json.loads(data.decode('utf-8'))
                    jdb_value = local_handle_request(parsed_data)
                    conn.send(json.dumps({
                        'response': jdb_value
                    }).encode())
                except Exception as e:
                    print(f'Exception triggered, exiting: {e}')
                    break
                
