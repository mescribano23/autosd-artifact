import subprocess as sp
import time
import signal
import os
import re
from util import *

DEBUG = False

class JDBWrapper(object):
    def __init__(self, d4j_home, proj, bug_num, target_test = None, port=31313):
        self._d4j_home = d4j_home
        curr_dir = os.getcwd()
        self._server_proc = self.start_server(proj, bug_num, target_test, port)
        time.sleep(0.1) # allow server process to properly initialize
        self._client_proc = self.start_client(port)
        client_preamble = self._read_stdout_to_prompt()
        self._client_terminated = False
        signal.signal(signal.SIGALRM, self._timeout_handler) 

    def start_server(self, proj, bug_num, target_test = None, port=31313):
        if target_test is not None:
            target_test_class, target_test_name = target_test.split('::')
        server_cmd = 'java -Xdebug '
        server_cmd += f'-agentlib:jdwp=transport=dt_socket,address=localhost:{port},server=y,suspend=y ' # jdb-activating
        server_cmd += '-XX:ReservedCodeCacheSize=256M -XX:MaxPermSize=1G -Djava.awt.headless=true ' # parameters
        server_cmd += f'-Xbootclasspath/a:{self._d4j_home}/major/bin/../config/config.jar -jar {self._d4j_home}/major/bin/../lib/ant-launcher.jar ' # d4j common 1
        server_cmd += f'-f {self._d4j_home}/framework/projects/defects4j.build.xml -Dd4j.home={self._d4j_home} -Dd4j.dir.projects={self._d4j_home}/framework/projects ' # d4j common 2
        server_cmd += f'-Dbasedir={ROOT_DIR}/{proj}_{bug_num} ' # specify buggy project path
        server_cmd += f'-DOUTFILE={ROOT_DIR}/{proj}_{bug_num}/failing_tests ' # location to log failing test information
        server_cmd += 'run.dev.tests '
        if target_test is not None:
            server_cmd += f'-Dtest.entry.class={target_test_class} '
            server_cmd += f'-Dtest.entry.method={target_test_name}'
        if (DEBUG): print("server_cmd: " + server_cmd)
        repo_dir = repo_path(proj, bug_num)
        serv_proc = sp.Popen(server_cmd.split(), stdout=sp.DEVNULL, stderr=sp.DEVNULL, cwd=repo_dir)
        return serv_proc
    
    def start_client(self, port):
        client_cmd = f'java -cp java_analyzer/sane_jdb/sane-jdb.jar com.sun.tools.example.debug.tty.TTY -attach localhost:{port}'
        if (DEBUG): print("client_cmd: " + client_cmd)
        return sp.Popen(client_cmd.split(), stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE)
    
    def _timeout_handler(self, signum, frame):
        raise TimeoutException()

    def _read_stdout_to_prompt(self, timeout=30):
        stdout_read = ''
        next_line = 'a' # dummy value
        signal.alarm(timeout)
        try:
            while ((re.search('^\S+\[1\]', next_line) is None) and next_line):
                next_line = self._client_proc.stdout.readline().decode()
                stdout_read += next_line
            if not next_line:
                self._client_terminated = True
        except TimeoutException:
            raise TimeoutException(f'Reading timeout; content from process up to now is `{stdout_read}`')
        finally:
            signal.alarm(0)
        stdout_read = stdout_read.strip()
        if (DEBUG): print('response:', stdout_read)
        return '\n'.join(stdout_read.split('\n')[:-1])

    def _relay_command(self, jdb_cmd:str, timeout=30, response_expected=True, retries=3):
        '''returns jdb response to jdb_cmd'''
        if (DEBUG): print("jdb_cmd: " + jdb_cmd)
        jdb_response = ''
        retry_counter = 0
        if not response_expected:
            retries = 1
        try:
            while len(jdb_response) == 0 and retry_counter < retries:
                if retry_counter > 0:
                    if (DEBUG):
                        print(f'Retrying jdb command that expected output: {jdb_cmd}')
                    time.sleep(0.1)
                    self._client_proc.stdin.write(b'\n')
                else:
                    self._client_proc.stdin.write(jdb_cmd.encode()+b'\n')
                self._client_proc.stdin.flush()
                jdb_response = self._read_stdout_to_prompt(timeout)
                if retry_counter > 0: # clean spurious next line
                    _ = self._read_stdout_to_prompt(timeout)
                retry_counter += 1
            if response_expected and retry_counter == retries:
                raise TimeoutException
        except TimeoutException as e:
            if (DEBUG):
                print(e)
            raise TimeoutException(f'Timeout while executing command {jdb_cmd}')
        return jdb_response

    def get_which_test(self):
        '''accesses which defects4j test is being executed.'''
        TEST_INVOKER = 'sun.reflect.NativeMethodAccessorImpl.invoke0'
        stack_trace = self.where('0x1')
        stack_lines = stack_trace.split('\n')
        test_invoking_line = [i for i, l in enumerate(stack_lines) if TEST_INVOKER in l][-1]
        test_line = stack_lines[test_invoking_line-1]
        test_name = test_line.strip().split()[1]
        test_name_comps = test_name.split('.')
        test_class, test_method = '.'.join(test_name_comps[:-1]), test_name_comps[-1]
        return f'{test_class}::{test_method}'

    def set_breakpoint(self, classpath, line):
        stop_cmd = f'stop at {classpath}:{line}'
        response = self._relay_command(stop_cmd)
        return ('Set defferred breakpoint' in response or 'Deferring breakpoint' in response
                or 'Set breakpoint' in response)
    
    def run_process(self):
        response = self._relay_command('run')
        return 'error' not in response
    
    def evaluate_expr(self, expr:str, timeout=5):
        response = self._relay_command(f'print {expr}', timeout=timeout)
        if 'Exception' in response or 'Error:' in response or len(response.strip()) == 0:
            return None # unevaluatable expression
        else:
            return response.strip().removeprefix(f'{expr} = ')
    
    def get_curr_line(self):
        stack_trace = self.where()
        latest_elem = stack_trace.split('\n')[0].split()[-1].strip('()')
        curr_file, curr_line = latest_elem.split(':')
        return curr_file, int(curr_line)

    def where(self, target_thread=''):
        response = self._relay_command('where '+target_thread)
        return response

    def get_var_type(self, var):
        response = self._relay_command(f'print {var}.getClass()')
        ptype_det_str = 'name getClass in'
        if not ('Exception' in response or 'Error' in response or len(response.strip()) == 0):
            new_response = self.evaluate_expr(f'{var}.getClass()')
            return new_response.strip('"').removeprefix('class ')
        elif ptype_det_str in response:
            # when the variable has primitive type, getClass() fails, but type exists
            first_line = response.split('\n')[0]
            det_str_idx = response.index(ptype_det_str)
            true_type = first_line[det_str_idx+len(ptype_det_str):].strip()
            return true_type
        else:
            # unknown identifier
            if 'primitive type' in response:
                if 'type: null' in response:
                    return 'null'
                else:
                    return 'primitive_type'
            else:
                raise ValueError('please query valid variables.')
    
    def get_fields_of_class(self, classname, static=False):
        response = self._relay_command(f'fields {classname}')
        if 'not a valid' in response:
            return None
        else:
            field_info = response.split('\n')[1:]
            field_tokens = [e.split() for e in field_info] # (public static type fieldname)
            return field_tokens

    def get_var_fields(self, var, static=False):
        if static:
            var_class = "*." + var
        else:
            var_class = self.get_var_type(var)
        class_fields = self.get_fields_of_class(var_class, static)
        return class_fields

    def get_methods_of_class(self, classname, static=False):
        response = self._relay_command(f'methods {classname}')
        if 'not a valid' in response:
            return None
        else:
            method_info = response.split('\n')[1:]
            # (public static class-defined-in ret-type methodname)
            method_tokens = [e.replace(', ', ',').split() for e in method_info]
            return method_tokens

    def get_var_methods(self, var, static=False):
        if static:
            var_class = "*." + var
        else:
            var_class = self.get_var_type(var)
        class_methods = self.get_methods_of_class(var_class, static)
        return class_methods

    
    def get_class_resolution(self, classname):
        response = self._relay_command(f'class {classname} all')
        if 'not a valid' in response:
            return None
        else:
            related_types = response.split('\n')[1:]
            return [e.split() for e in related_types] # (relationship, classname)

    def dump_var(self, var):
        return self._relay_command(f'dump {var}')

    def move_on(self):
        response = self._relay_command('cont')
        return 'Breakpoint hit' in response
    
    def force_load_class(self, classpath):
        response = self._relay_command(f'print Class.forName("{classpath}")')
        return (not ('Exception' in response or 'Error' in response))
    
    def exit(self):
        self._relay_command(f'exit', response_expected=False)
        self._client_terminated = True
    
    def terminate(self):
        self._server_proc.terminate()
        self._client_proc.terminate()
        self._client_terminated = True
    
    @staticmethod
    def get_valid_breakpoint(abs_jpath, target_lineno):
        import javalang
        import java_analyzer.var_scope as jvs
        with open(abs_jpath) as f:
            target_code = f.read()
            code_lines = target_code.split('\n')
        break_lineno = target_lineno
        # while finds first executable line after target_lineno (inclusive)
        sja = jvs.StaticJavaAnalyzer(target_code)
        if_analysis = jvs.parse_if_condition(sja, target_lineno)
        if if_analysis is not None:
            return if_analysis[0].line
        if 'else' in code_lines[break_lineno-1]:
            # else_analysis = jvs.parse_if_condition_from_else(sja, target_lineno)
            # return else_analysis[0].line
            break_lineno += 1
        # not currently in if condition
        while True:
            ## condition complicated so included in while body
            # escaping empty lines / comments
            curr_line = code_lines[break_lineno-1]
            try:
                curr_tokens = list(javalang.tokenizer.tokenize(curr_line))
                if len(curr_tokens) != 0:
                    break
            except javalang.tokenizer.LexerError:
                pass
            break_lineno += 1
        return break_lineno


    

