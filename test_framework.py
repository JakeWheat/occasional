#!/usr/bin/env python3

"""x

A test framework which supports test results from multiple concurrent
processes

Planned:
run tests concurrently, distributed
logging and reports
profiling support
timeout support
support for running tests written in other frameworks using adaptors
  (the adaptors run the other tests' executables and get the results
   either from stdout/stderr or the log produced from the test runs)

usage guide TODO:

running tests from command line

writing tests


"""

import traceback
import functools
import sys
import traceback

def sysinfo_to_value(e):
    return ("".join(traceback.format_exception(*e, 0)),
            f"{type(e[0])}: {str(e[0])}",
            traceback.extract_tb(e[2]))

def get_process_name(f):
    if isinstance(f, functools.partial):
        return f.func.__name__
    else:
        return f.__name__

def test_server(address_sock):
    # create the status/results queue
    # todo: do this without queues?
    res_queue = multiprocessing.Queue()

    finished_queue = multiprocessing.Queue()

    def summarize():
        # read from res queue
        # run through the notifies and check they each have a corresponding
        # results
        # summarize the results
        logged_suites = []
        suite_results = []
        try:
            while True:
                x = res_queue.get(timeout=0)
                match x:
                    case ("start_suite", nm):
                        logged_suites.append(nm)
                    case ("suite_results", nm, res):
                        if nm not in logged_suites:
                            print(f"error: suite results without start suite: {nm}")
                        suite_results.append(res)
                        logged_suites.remove(nm)
        except queue.Empty:
            pass
        if len(logged_suites) > 0:
            print(f"error: suites not finished: {logged_suites}")

        total_suites = 0
        suites_passed = 0
        total_tests = 0
        tests_passed = 0
        for i in suite_results:
            total_tests += i[0]
            tests_passed += i[1]
            total_suites += 1
            if i[0] == i[1]:
                suites_passed += 1

        print(f"{tests_passed} / {total_tests} passed, {suites_passed} / {total_suites} suites passed")
        # exit the test server
        finished_queue.put(True)

    def handle_suite(client_sock, nm):
        res_queue.put(("start_suite", nm))
        print(nm)
        test_results = []
        while True:
            match client_sock.receive_value():
                case ("pass", msg):
                    print(f"  PASS {msg}")
                    test_results.append(("pass", msg))
                case ("fail", msg):
                    print(f"  FAIL {msg}")
                    test_results.append(("fail", msg))
                case ("finish",):
                    total_tests = 0
                    tests_passed = 0
                    for i in test_results:
                        total_tests += 1
                        if i[0] == "pass":
                            tests_passed += 1
                    print(f"  {tests_passed} / {total_tests} passed")
                    res_queue.put(("suite_results", nm, (total_tests,tests_passed)))
                    client_sock.send_value(("ok",))
                case None:
                    break
                case x:
                    print(f"error: unexpected message in handle suite: {x}")

    # accept a suite: ...
    def accept_handler(cs, _):
        client_sock = socket_wrapper.ValueSocket(cs)
        match client_sock.receive_value():
            case ("summarize",):
                summarize()
            case ("new_suite", nm):
                handle_suite(client_sock, nm)
            case x:
                print(f"unrecognised handshake to test server {x}")
        
    # start server
    srv = socket_wrapper.SocketServer(accept_handler)
    
    # send the address back on the pipe
    address_sock.send_value(srv.addr)

    # wait until summarize is completed then exit
    finished_queue.get()
    srv.close()

def run_suite(addr, f):
    if type(addr) is TestLocal:
        addr.run_suite(f)
    else:
        ts = TestSuiteHandle(addr, f)
        ts.run()
        ts.finish()

    
class TestServer():

    def __init__(self):
        (p0, p1) = socket_wrapper.value_socketpair()
        self.server_process = multiprocessing.Process(target=test_server, args=[p1])
        self.server_process.start()
        self.addr = p0.receive_value()
        p0.close()

    def run_suite(self, f):
        ts = TestSuiteHandle(self.addr, f)
        ts.run()
        ts.finish()
        

    def finish_tests(self):
        cs = socket_wrapper.ValueSocket()
        cs.connect(self.addr)
        cs.send_value(("summarize",))
        self.server_process.join()


        
class TestSuiteHandle():
    def __init__(self, addr, f):
        self.connection_sock = socket_wrapper.ValueSocket() #socket_type=socket_type)
        self.connection_sock.connect(addr)
        self.connection_sock.send_value(("new_suite", get_process_name(f)))
        self.f = f

    def run(self):
        try:
            self.f(self)
        except:
            x = sysinfo_to_value(sys.exc_info())
            self.fail(f"test suite threw exception {x}")
        
    def finish(self):
        self.connection_sock.send_value(("finish",))
        # don't return until the test suite processing is finished
        # so that everything lines up by the time
        # finish tests is called
        self.connection_sock.receive_value()
        self.connection_sock.close()

    def tpass(self, msg):
        self.connection_sock.send_value(("pass", msg))

    def fail(self, msg):
        self.connection_sock.send_value(("fail", msg))

    def assert_equal(self, msg, exp, got):
        if exp == got:
            self.tpass(msg)
        else:
            self.fail(f"{msg} expected {exp} got {got}")

    def assert_true(self, msg, b):
        if b:
            self.tpass(msg)
        else:
            self.fail(msg)

    def assert_pred(self, msg, pred, v):
        if pred(v):
            self.tpass(msg)
        else:
            self.fail(f"{msg} failed predicate: {v}")


# same test interface without the seperate process
# this will only work if your test code is all in the same
# process
class TestLocal:
    def __init__(self):
        self.results = []
        self.current_suite = None
        self.current_suite_results = []
        self.addr = self

        
    def finish_tests(self):
        self.finish_current_suite()
        num_tests = 0
        num_test_passes = 0
        num_suites = 0 #len(self.results)
        num_suite_passes = 0
        for i in self.results:
            #print(i)
            num_suites += 1
            stests = 0
            spasses = 0
            for j in i[1]:
                stests += 1
                #print(j)
                if j[0] == "PASS":
                    spasses += 1
            if spasses == stests:
                num_suite_passes += 1
            #print(f"{stests} {spasses}")
            num_tests += stests
            num_test_passes += spasses
            
        print(f"{num_test_passes} / {num_tests} passed, {num_suite_passes} / {num_suites} suites passed")
        return num_test_passes == num_tests


    def finish_current_suite(self):
        if self.current_suite is not None:
            num_tests = 0
            num_passes = 0
            for i in self.current_suite_results:
                num_tests += 1
                if i[0] == "PASS":
                    num_passes += 1
            print(f"  {num_passes} / {num_tests} passed")
            self.results.append((self.current_suite, self.current_suite_results))
            self.current_suite = None
            self.current_suite_results = []
        
    def tpass(self, msg):
        print(f"  PASS {msg}")
        self.current_suite_results.append(("PASS", msg))
    def fail(self, msg):
        print(f"  FAIL {msg}")
        self.current_suite_results.append(("FAIL", msg))

    def assert_equal(self, msg, exp, got):
        if exp == got:
            self.tpass(msg)
        else:
            self.fail(f"{msg} expected {exp} got {got}")

    def assert_true(self, msg, b):
        if b:
            self.tpass(msg)
        else:
            self.fail(msg)

    def assert_pred(self, msg, pred, v):
        if pred(v):
            self.tpass(msg)
        else:
            self.fail(f"{msg} failed predicate: {v}")

    def run_suite(self, f):
        self.finish_current_suite()
        self.current_suite = f.__name__
        print(f.__name__)
        try:
            f(self)
        except:
            x = sysinfo_to_value(sys.exc_info())
            self.fail(f"test suite threw exception {x}")



            
if __name__ == "__main__":

    ##############
    # parse comment line
    import argparse
    import re
    import importlib
    import glob
    import os

    parser = argparse.ArgumentParser()
    # write module names on command line:
    # test.py module1 module2
    # or if you specify no modules, it searches all the modules
    # test.py
    # set the search path for modules (todo)
    # test.py -I.:tests
    # test.py -I.:tests my_mod1 my_mod2
    # patterns to match:
    # test.py -t pat1 -t pat2
    parser.add_argument('modules_to_test', nargs='*', default=[])
    parser.add_argument('--test-pattern', '-t', nargs='+', default=[])
    parser.add_argument("--use-local", type=bool, default=False)


    args = parser.parse_args()

    #modules_to_test = ["socket_wrapper_tests",
    #                   "sockets_passing_demo"]
    modules_to_test = args.modules_to_test
    # affects error messages
    auto_mode = False
    if modules_to_test == []:
        auto_mode = True
        for i in glob.glob("*.py"):
            modules_to_test.append(os.path.splitext(i)[0])

    print(args.test_pattern)
    
    # test_patterns = [] #"sockets_passing_demo"]
    test_patterns_re = []
    for i in args.test_pattern:
        test_patterns_re.append(re.compile(i))

    ###########
    # execute tests
    if args.use_local:
        t = TestLocal()
    else:
        import socket_wrapper
        import multiprocessing
        import queue
        t = TestServer()

    for moduleName in modules_to_test:
        try:
            run_module = False
            if test_patterns_re == []:
                run_module = True
            else:
                for r in test_patterns_re:
                    if r.match(moduleName):
                        run_module = True
                        break
            mod = importlib.import_module(moduleName)
            ts = getattr(mod, "all_tests")
            print(moduleName)
            print("------")
            try:
                for f in ts:
                    if run_module:
                        t.run_suite(f)
                    else:
                        for r in test_patterns_re:
                            if r.match(f.__name__):
                                t.run_suite(f)
            except:
                # todo: turn this into a test case failure also or something
                print(sys.exc_info()[0])
                traceback.print_exc()
        except:
            if auto_mode:
                pass
            else:
                # todo: turn this into a test case failure also or something
                print(sys.exc_info()[0])
                traceback.print_exc()
    if not t.finish_tests():
        sys.exit(-1)

