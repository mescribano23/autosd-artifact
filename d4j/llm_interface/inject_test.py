import codecs
import os

import javalang

import util

def inject_test(repo_path, test_dir, test_name, gen_test, dry=False):
    classpath = test_name.split('::')[0]
    test_file = os.path.join(repo_path, test_dir, classpath.replace('.', '/')+'.java')
    with codecs.open(test_file, 'r', encoding='utf-8', errors='ignore') as f:
        testf_lines = f.readlines()
        testf_content = ''.join(testf_lines)
        needs_assert_imports = '@Test' in testf_content

    
    new_file_content, new_gen_test = inject_with_imports(
        testf_lines, gen_test)

    with open(test_file, 'w') as f:
        print(new_file_content, file=f)

def inject_with_imports(testf_lines, gen_test):
    new_test_lines = testf_lines[:]

    # Adding test at the very end
    # change test name to avoid collision
    org_test_name = parse_method(gen_test).name
    new_test_name = org_test_name + 'Minimized'
    gen_test = gen_test.replace(
        'void ' + org_test_name,
        'void ' + new_test_name)
    # add @Test decorator if necessary
    if '@Test' in ''.join(testf_lines) and '@Test' not in gen_test:
        gen_test = '@Test\n' + gen_test.strip()

    final_paren_loc = 0
    for idx in range(1, len(testf_lines)+1):
        if '}' in testf_lines[-idx]:
            final_paren_loc = -idx
            break
    assert final_paren_loc != 0
    new_test_lines = (
        new_test_lines[:final_paren_loc] +
        [e+'\n' for e in gen_test.split('\n')] +
        new_test_lines[final_paren_loc:]
    )
    new_file_content = ''.join(new_test_lines)

    return new_file_content, gen_test

def parse_method(gen_test):
    tokens = javalang.tokenizer.tokenize(gen_test)
    parser = javalang.parser.Parser(tokens)
    tree = parser.parse_member_declaration()
    return tree