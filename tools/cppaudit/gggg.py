

# Gradescope-Googletest Grading Glue (gggg)
#
# This file contains a Python library for creating an autograder
# script in a declarative style.
#
# See template-example/grade.py for a usage example.

# Test:
#  - README.md contributors: missing, starter, good
#  - Missing required files
#  - File unmmodified that shouldn't be
#  - File modified that shouldn't be
#  - Does not compile
#  - TODO present, missing
#  - gtest tests: all pass, none pass, some pass

import hashlib, json, pathlib, subprocess, xml.etree.ElementTree, yaml, difflib, os

DEFAULT_TIMEOUT = 60

DEFAULT_CONTRIBUTORS_PATH = 'README.md'
DEFAULT_STARTER_CONTRIBUTORS = ['Ada Lovelace adalovelace@csu.fullerton.edu',
                                'Charles Babbage charlesbab@csu.fullerton.edu']
DEFAULT_REJECTED_TEST_MESSAGE = 'submission was rejected, so test was skipped'
DEFAULT_GTEST_XML_FILENAME = 'gtest.xml'
DEFAULT_GRADESCOPE_JSON_FILENAME = 'results.json'
COMPILE_COMMAND_JSON_FILENAME = "compile_commands.json"
CLANG_TIDY_YAML_FILENAME = "style.yaml"
DEFAULT_INDENT = ' ' * 4

class Assignment:
    def __init__(self,
                 max_score,
                 rejected_score,
                 contributors_path = DEFAULT_CONTRIBUTORS_PATH,
                 starter_contributors = DEFAULT_STARTER_CONTRIBUTORS,
                 rejected_test_message = DEFAULT_REJECTED_TEST_MESSAGE,
                 gtest_xml_filename = DEFAULT_GTEST_XML_FILENAME,
                 gradescope_json_filename = DEFAULT_GRADESCOPE_JSON_FILENAME,
                 indent = DEFAULT_INDENT):

        if not (isinstance(max_score, int) and
                isinstance(rejected_score, int) and
                isinstance(contributors_path, str) and
                isinstance(starter_contributors, list) and
                all([isinstance(x, str) for x in starter_contributors]) and
                isinstance(rejected_test_message, str) and
                isinstance(gtest_xml_filename, str) and
                isinstance(gradescope_json_filename, str) and
                isinstance(indent, str)):
            raise TypeError
        
        if not ((max_score > 0) and
                (rejected_score >= 0) and
                (rejected_score < max_score) and
                (all(ch == ' ' for ch in indent))):
            raise ValueError
        
        self.max_score = max_score
        self.rejected_score = rejected_score
        self.contributors_path = contributors_path
        self.starter_contributors = starter_contributors
        self.rejected_test_message = rejected_test_message
        self.gtest_xml_filename = gtest_xml_filename
        self.gradescope_json_filename = gradescope_json_filename
        self.indent = indent

    def contributors(self):
        lines = []
        with open(self.contributors_path, 'r') as f:
            for line in f.readlines():
                i = line.find('@')
                if i not in [-1, 0, len(line)-1]:
                    lines.append(line.strip())
        return lines

    def indent_multiline(self, message):
        
        if not isinstance(message, str):
            raise TypeError
        
        result = ''
        for line in message.splitlines():
            result += self.indent + line + '\n'
        return result
    
class Test:
    def __init__(self, name, max_score, score, message):

        if not (isinstance(name, str) and
                isinstance(max_score, int) and
                isinstance(score, int) and
                isinstance(message, str)):
            raise TypeError

        if not (len(name) > 0 and
                max_score > 0 and
                score >= 0 and
                score <= max_score):
            raise ValueError
        
        self.name = name
        self.max_score = max_score
        self.score = score
        self.message = message

# Result of executing a shell command.
class Execution:

    RESULTS = SUCCESS, FAILURE, TIMEOUT = range(3)
    
    def __init__(self, result, exit_code, output):
        if not ((result in Execution.RESULTS) and
                isinstance(exit_code, int) and
                isinstance(output, str)):
            raise TypeError
        self.result = result
        self.exit_code = exit_code
        self.output = output

# Return true if obj is a non-empty list of argv strings.
def is_args(obj):
    return (isinstance(obj, list) and
            len(obj) > 0 and
            all([isinstance(x, str) and len(x) > 0 for x in obj]))

def execute(args, timeout=DEFAULT_TIMEOUT, stdin_string=None):

    if not (is_args(args) and
            isinstance(timeout, int) and
            stdin_string is None or isinstance(stdin_string, str)):
        raise TypeError
    
    if not (timeout > 0):
        raise ValueError
    print(' '.join(args))    
    try:
        proc = subprocess.run(args,
                              stdout=subprocess.PIPE,   # capture stdout
                              stderr=subprocess.STDOUT, # merge stderr into stdout
                              text=True,                # stdout is text not binary
                              input=stdin_string,
                              timeout=timeout)
        # if we got here, there was no timeout
        exit_code = proc.returncode
        return Execution(Execution.SUCCESS if exit_code == 0 else Execution.FAILURE,
                         exit_code,
                         proc.stdout)
    except subprocess.TimeoutExpired:
        # timeout exception
        return Execution(Execution.TIMEOUT, 128, '')

class GTestSuiteResult:
    def __init__(self, name, passed, message):
        if not (isinstance(name, str) and
                isinstance(passed, bool) and
                isinstance(message, str)):
            raise TypeError
        self.name = name
        self.passed = passed
        self.message = message

class ClangTidyResult:
    def __init__(self, passed, message):
        if not (isinstance(passed, bool) and
                isinstance(message, str)):
            raise TypeError
        self.passed = passed
        self.message = message

class ClangFormatResult:
    def __init__(self, passed, message):
        if not (isinstance(passed, bool) and
                isinstance(message, str)):
            raise TypeError
        self.passed = passed
        self.message = message

class State:
    def __init__(self, assignment, rejected=False, rejected_message='', score=0, tests=[]):

        if not (isinstance(assignment, Assignment) and
                isinstance(rejected, bool) and
                isinstance(rejected_message, str) and
                isinstance(score, int) and
                isinstance(tests, list) and
                all([isinstance(x, Test) for x in tests])):
            raise TypeError

        if not (score >= 0):
            raise ValueError

        self.assignment = assignment
        self.rejected = rejected
        self.rejected_message = rejected_message
        self.score = score
        self.tests = list(tests)
        self.clang_formatted = {}

    # Member functions are in roughly the chronological order they
    # will be used.
        
    def reject(self, message):
        print('REJECTED: ' + message)
        self.rejected = True
        self.rejected_message = message

    def reject_unless_file_exists(self, path):
        if not isinstance(path, str):
            raise TypeError
        if self.rejected:
            return
        if not pathlib.Path(path).exists():
            self.reject('required file "' + filename + '" does not exist')

    def reject_unless_files_exist(self, path_list):
        if not (isinstance(path_list, list) and
                all([isinstance(x, str) for x in path_list])):
            raise TypeError
        if self.rejected:
            return
        for path in path_list:
            self.reject_unless_file_exists(path)        
            
    def reject_if_file_changed(self, path, original_sha256_hex):
        if not (isinstance(path, str) and
                isinstance(original_sha256_hex, str)):
            raise TypeError
        if self.rejected:
            return
        if sha256(path) != original_sha256_hex:
            self.reject('file "' + path + '" is changed')

    def reject_if_file_unchanged(self, path, original_sha256_hex):
        if not (isinstance(path, str) and
                isinstance(original_sha256_hex, str)):
            raise TypeError
        if self.rejected:
            return
        if sha256(path) == original_sha256_hex:
            self.reject('file "' + path + '" is unchanged')

    def reject_if_missing_contributors(self):
        if self.rejected:
            return
        if len(self.assignment.contributors()) == 0:
            self.reject('no names and emails in ' + self.assignment.contributors_path)

    def reject_if_starter_contributors(self):
        if self.rejected:
            return
        # Convert each list to a set, so we do set equality, which is
        # insensitive to ordering.
        if set(self.assignment.contributors()) == set(self.assignment.starter_contributors):
            self.reject('names and emails in ' +
                        self.assignment.contributors_path +
                        ' are still the placeholders:\n' +
                        '\n'.join(self.assignment.starter_contributors))

    def reject_unless_command_succeeds(self, args, timeout=DEFAULT_TIMEOUT, stdin_string=None):
        
        if not (is_args(args) and
                isinstance(timeout, int) and
                stdin_string is None or isinstance(stdin_string, str)):
            raise TypeError
        
        if not (timeout > 0):
            raise ValueError

        if self.rejected:
            return

        ex = execute(args, timeout, stdin_string)
        if ex.result == Execution.FAILURE:
            self.reject('command "' +
                        ' '.join(args) +
                        '" failed with exit code ' +
                        str(ex.exit_code))
        elif ex.result == Execution.TIMEOUT:
            self.reject('command "' +
                        ' '.join(args) +
                        '" timed out after ' +
                        str(timeout) +
                        ' seconds')
            
    def add_test(self, display_name, max_score, score, message):
        
        if not (isinstance(display_name, str) and
                isinstance(max_score, int) and
                isinstance(score, int) and
                isinstance(message, str)):
            raise TypeError

        if ((sum([test.max_score for test in self.tests]) + max_score)
             > self.assignment.max_score):
            raise ValueError
        
        if self.rejected:
            return

        self.tests.append(Test(display_name, max_score, score, message))

    def string_removed_test(self, name, max_score, taboo_string, filenames):
        
        if not (isinstance(max_score, int) and
                isinstance(taboo_string, str) and
                isinstance(filenames, list) and
                all([isinstance(x, str) for x in filenames])):
            raise TypeError

        if self.rejected:
            return

        passed = True
        message = ''
        for filename in filenames:
            line_numbers = []
            with open(filename, 'rt') as f:
                lines = f.readlines()
                for i in range(len(lines)):
                    if lines[i].find(taboo_string) != -1:
                        line_numbers.append(i+1)
                    
            if len(line_numbers) > 0:
                passed = False
                message += (filename +
                            ' still contains "' + taboo_string + '"' +
                            ' on lines ' +
                            ', '.join([str(n) for n in line_numbers]))
        self.add_test(name,
                      max_score,
                      max_score if passed else 0,
                      message)
        
    def gtest_run(self,
                  executable_filename,
                  timeout=DEFAULT_TIMEOUT):
        
        if not (isinstance(executable_filename, str) and
                isinstance(timeout, int)):
            raise TypeError
    
        if self.rejected:
            return

        try:
            os.remove(self.assignment.gtest_xml_filename)
        except OSError:
            pass
        ex = execute(['./' + executable_filename,
                      '--gtest_output=xml:' + self.assignment.gtest_xml_filename],
                     timeout=timeout)

        if ex.result == Execution.TIMEOUT:
            self.reject('unittest program "' + executable_filename + '" ' +
                        'timed out after ' + str(timeout) + ' seconds')

        # bitmask 128 indicates abnormal termination (segfault)
        if (ex.result == Execution.FAILURE) and ((ex.exit_code & 128) != 0):
            self.reject('unittest program "' + executable_filename + '" ' +
                   'terminated abnormally (crashed):\n\n' + ex.output)

    def gtest_suite_test(self, name, max_score):
        
        if not (isinstance(name, str) and
                isinstance(max_score, int)):
            raise TypeError

        if not (max_score > 0):
            raise ValueError
        
        if self.rejected:
            return

        suites = self._parse_gtest_results()
        
        if name not in suites:
            raise ValueError('no such suite name "' + suite_name + '" in "' + xml_filename + '"')
        suite = suites[name]
        passed = suite.passed

        self.add_test(name,
                      max_score,
                      max_score if passed else 0,
                      '' if passed else suite.message)
        
    # Returns a dict d such that d[name] = GTestSuiteResult
    def _parse_gtest_results(self):

        result = {}
    
        tree = xml.etree.ElementTree.parse(self.assignment.gtest_xml_filename)
        root = tree.getroot()
        for testsuite in root:

            name = testsuite.get('name')
            failures = int(testsuite.get('failures'))
            skips = int(testsuite.get('skipped'))

            message = ''
            for testcase in testsuite:
                for failure in testcase:
                    message += failure.text
        
            passed = (failures == 0 and skips == 0)
        
            result[name] = GTestSuiteResult(name, passed, message)

        return result

    def clang_tidy_run(self,
                  executable_filename,
                  executable_name,
                  implementation_file_names=None,
                  timeout=DEFAULT_TIMEOUT):
        
        if not (isinstance(executable_filename, str) and
                isinstance(executable_name, str) and
                (isinstance(implementation_file_names, list) or
                implementation_file_names is None) and
                isinstance(timeout, int)):
            raise TypeError
    
        if self.rejected:
            return
        
        # Creates a compilation database for clang-tidy
        # documentation found here: https://clang.llvm.org/docs/JSONCompilationDatabase.html
        # Seems faster to generate the database than use cmake or other tools
        compile_commands_json = [
            {
             "directory": str(pathlib.Path().resolve()),
             "command": "clang++ -std=c++17 {} -o {}".format(executable_filename, executable_name),
             "file": "{}".format( str(pathlib.Path().resolve()) + '/' + executable_filename)
            }
        ]
        for file in implementation_file_names or []:
            compile_commands_json.append({
                "directory": str(pathlib.Path().resolve()),
                "command": "clang++ -std=c++17 {} -o {}".format(file, executable_name),
                "file": "{}".format(str(pathlib.Path().resolve()) + '/' + file)
            })
        with open(COMPILE_COMMAND_JSON_FILENAME, 'wt') as f:
            json.dump(compile_commands_json, f)
        
        try:
            os.remove(CLANG_TIDY_YAML_FILENAME)
        except OSError:
            pass
        # Run clang-tidy and store results in style.yaml
        exec_command = ['clang-tidy', '-p=' + COMPILE_COMMAND_JSON_FILENAME, '-quiet', '-header-filter=^crow_all.h', '-export-fixes={}'.format(CLANG_TIDY_YAML_FILENAME)] +  [executable_filename]
        if implementation_file_names is not None:
            exec_command + implementation_file_names

        ex = execute(exec_command, timeout=timeout)

        if ex.result == Execution.TIMEOUT:
            self.reject('clang-tidy timed out after ' + str(timeout) + ' seconds')

        # bitmask 128 indicates abnormal termination (segfault)
        if (ex.result == Execution.FAILURE) and ((ex.exit_code & 128) != 0):
            self.reject('clang-tidy terminated abnormally (crashed):\n\n' + ex.output)

    def clang_tidy_check(self, max_score):
        
        if not (isinstance(max_score, int)):
            raise TypeError

        if not (max_score > 0):
            raise ValueError
        
        if self.rejected:
            return

        # Set style check to max score if no warnings
        # otherwise set to 0 and add message retrieved from linter
        result = self._parse_clang_tidy_results()
        self.add_test("Style check",
                      max_score,
                      max_score if result.passed else 0,
                      '' if result.passed else result.message)

    def _parse_clang_tidy_results(self):
        message = ""
        passed = False
        
        try:
            with open(CLANG_TIDY_YAML_FILENAME, 'r') as file:
                style_checks = yaml.safe_load(file)
                warnings = 0
                errors = 0

                # Each Diagnostic is a warning from clang-tidy
                for diagnostic in style_checks['Diagnostics']:
                    # For now, only consider warnings
                    if diagnostic['Level'] == "Warning":
                        warnings += 1
                    elif diagnostic['Level'] == "Error":
                        errors += 1

                    # Format display using data from YAML file using clang-tidy's structure
                    if  len(diagnostic['DiagnosticMessage']['Replacements']) > 0:   
                        output = "{}/{}: {}: {} [{}]\nSuggested change: {}\n\n".format(
                                diagnostic['BuildDirectory'],
                                diagnostic['DiagnosticMessage']['Replacements'][0]['FilePath'],
                                diagnostic['Level'],
                                diagnostic['DiagnosticMessage']['Message'],
                                diagnostic['DiagnosticName'],
                                diagnostic['DiagnosticMessage']['Replacements'][0]['ReplacementText'])
                    else:
                        output = "{}/{}: {}: {} [{}]\n\n".format(
                                diagnostic['BuildDirectory'],
                                diagnostic['DiagnosticMessage']['FilePath'],
                                diagnostic['Level'],
                                diagnostic['DiagnosticMessage']['Message'],
                                diagnostic['DiagnosticName'])
                    message += output

                passed = (warnings == 0 and errors == 0)
        except FileNotFoundError:
            passed = True
        
        return ClangTidyResult(passed, message)


    def clang_format_run(self,
                  file_names,
                  timeout=DEFAULT_TIMEOUT):
        
        if not (isinstance(file_names, list) and
                isinstance(timeout, int)):
            raise TypeError
        
        if len(file_names) == 0:
            raise ValueError
    
        if self.rejected:
            return
        
        if self.clang_formatted:
            self.clang_formatted = {}
        
        # run clang-format on all files

        for file in file_names or []:
            ex = execute(['clang-format', file],
                     timeout=timeout)
            if ex.result == Execution.TIMEOUT:
                self.reject('clang-format ' + file + 'timed out after ' + str(timeout) + ' seconds')
            
            # bitmask 128 indicates abnormal termination (segfault)
            if (ex.result == Execution.FAILURE) and ((ex.exit_code & 128) != 0):
                self.reject('clang-format ' + file + 'terminated abnormally (crashed):\n\n' + ex.output)
            self.clang_formatted[file] = ex.output

    def clang_format_check(self, max_score):
        
        if not (isinstance(max_score, int)):
            raise TypeError

        if not (max_score > 0):
            raise ValueError
        
        if self.rejected:
            return

        # Set style check to max score if no warnings
        # otherwise set to 0 and add message retrieved from linter
        result = self._parse_clang_format_results()
        self.add_test("Format check",
                      max_score,
                      max_score if result.passed else 0,
                      '' if result.passed else result.message)
    
    def _parse_clang_format_results(self):
        # Shoult not be empty if clang-format ran previously
        if not self.clang_formatted:
            raise LookupError
        
        message = ""
        files_need_changing = 0

        for filename in self.clang_formatted.keys():
            with open(filename, 'r') as file:
                message += "[" + filename + "]\n"
                diff = difflib.unified_diff(file.read().splitlines(),
                                            self.clang_formatted[filename].splitlines(),
                                            lineterm='')
                diff_result = list(diff)
                message += '\n'.join(diff_result) + "\n\n"
                
                if len(diff_result) > 0:
                    files_need_changing += 1
                    
        passed = (files_need_changing == 0)
        return ClangFormatResult(passed, message)

    def total_score(self):
        if self.rejected:
            return self.assignment.rejected_score
        else:
            return sum([test.score for test in self.tests])

    def print_summary(self):
        horizontal_rule()
        print('CONTRIBUTORS:')
        for c in self.assignment.contributors():
            print(self.assignment.indent_multiline(c))
        print('')

        horizontal_rule()
        print('SCORE:\n')
    
        if self.rejected:
            print('TOTAL SCORE = ' + str(self.total_score()) +
                  ' / ' + str(self.assignment.max_score) +
                  ' (SUBMISSION REJECTED)')
        else:
            name_width = max([len(test.name) for test in self.tests])
            point_width = max([len(str(test.max_score)) for test in self.tests])
        
            for test in self.tests:
                print(test.name.ljust(name_width) + self.assignment.indent + ': ' +
                      str(test.score).rjust(point_width) + ' / ' +
                      str(test.max_score).rjust(point_width))
                if len(test.message) > 0:
                    print(self.assignment.indent_multiline(test.message))

            print('\nTOTAL SCORE = ' +
                  str(self.total_score()) +
                  ' / ' +
                  str(self.assignment.max_score))

        horizontal_rule()

    def gradescope_summary(self):
        d = {'visibility': 'visible',
             'stdout_visibility': 'visible'}
    
        if self.rejected:
            d['score'] = self.total_score()
            d['output'] = self.rejected_message
        else:
            d['tests'] = [ { 'score': test.score,
                             'max_score': test.max_score,
                             'name': test.name,
                             'output': test.message,
                             'visibility': 'visible'}
                           for test in self.tests]

        with open(self.assignment.gradescope_json_filename, 'wt') as f:
            json.dump(d, f)

    def summarize(self):
        self.print_summary()
        self.gradescope_summary()

def horizontal_rule(char='-', width=79):
    
    if not (isinstance(char, str) and
            isinstance(width, int)):
        raise TypeError

    if not (len(char) == 1 and
            width > 0):
        raise ValueError

    print(char * width)

# Returns a hex digest as a string.
def sha256(path):
    if not (isinstance(path, str)):
        raise TypeError
    
    hash = hashlib.sha256()
    with open(path, 'rb') as f:
        hash.update(f.read())
    return hash.hexdigest()
