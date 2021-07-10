from test_framework import TestGroup,TestCase,FailTestCaseBody
import test_framework
import tests.inbox_tests
import tests.occasional_tests
import tests.sck_tests
import tests.shared_port
import tests.spawn_tests
import tests.test_area_server
import tests.yeshup_tests
all_tests = \
    (TestGroup(), 'all_tests', [
        (TestGroup(), 'tests.get_proc_socket_info', [
            (TestCase(), "no_tests_found", FailTestCaseBody("""no tests found in tests/get_proc_socket_info.py"""))
        ]),
        (TestGroup(), 'tests.inbox_tests', [
            (TestCase(), 'test_self_send', tests.inbox_tests.test_self_send),
            (TestCase(), 'test_send_other_process', tests.inbox_tests.test_send_other_process),
            (TestCase(), 'test_many_clients', tests.inbox_tests.test_many_clients),
            (TestCase(), 'test_xmany_clients_pipelined', tests.inbox_tests.test_xmany_clients_pipelined),
            (TestCase(), 'test_timeout0_empty', tests.inbox_tests.test_timeout0_empty),
            (TestCase(), 'test_timeout0_nonempty', tests.inbox_tests.test_timeout0_nonempty),
            (TestCase(), 'test_timeout_timesout', tests.inbox_tests.test_timeout_timesout),
            (TestCase(), 'test_timeout_explicit_infinity', tests.inbox_tests.test_timeout_explicit_infinity),
            (TestCase(), 'test_read_all_inbox', tests.inbox_tests.test_read_all_inbox),
            (TestCase(), 'test_flush_buffer', tests.inbox_tests.test_flush_buffer),
            (TestCase(), 'test_selective_receive1', tests.inbox_tests.test_selective_receive1),
            (TestCase(), 'test_selective_receive2', tests.inbox_tests.test_selective_receive2),
            (TestCase(), 'test_selective_receive3', tests.inbox_tests.test_selective_receive3),
            (TestCase(), 'test_timeout_with_unmatching_message', tests.inbox_tests.test_timeout_with_unmatching_message),
            (TestCase(), 'test_timeout_with_unmatching_message2', tests.inbox_tests.test_timeout_with_unmatching_message2),
            (TestCase(), 'test_timeout_with_delayed_unmatching_messages', tests.inbox_tests.test_timeout_with_delayed_unmatching_messages),
            (TestCase(), 'test_disconnect_notification', tests.inbox_tests.test_disconnect_notification),
            (TestCase(), 'test_non_listen_connection', tests.inbox_tests.test_non_listen_connection),
        ]),
        (TestGroup(), 'tests.occasional_tests', [
            (TestCase(), 'test_trivial_run', tests.occasional_tests.test_trivial_run),
            (TestCase(), 'test_system_exit_0', tests.occasional_tests.test_system_exit_0),
            (TestCase(), 'test_ping_cs', tests.occasional_tests.test_ping_cs),
            (TestCase(), 'test_simple_spawn', tests.occasional_tests.test_simple_spawn),
            (TestCase(), 'test_nested_occasional', tests.occasional_tests.test_nested_occasional),
            (TestCase(), 'test_check_right_exit', tests.occasional_tests.test_check_right_exit),
            (TestCase(), 'test_spawn_monitor_exit_0', tests.occasional_tests.test_spawn_monitor_exit_0),
            (TestCase(), 'test_spawn_monitor_sigterm', tests.occasional_tests.test_spawn_monitor_sigterm),
            (TestCase(), 'test_spawn_monitor_return_val', tests.occasional_tests.test_spawn_monitor_return_val),
            (TestCase(), 'test_spawn_monitor_uncaught_exception', tests.occasional_tests.test_spawn_monitor_uncaught_exception),
            (TestCase(), 'test_spawn_monitor_exit_delay', tests.occasional_tests.test_spawn_monitor_exit_delay),
            (TestCase(), 'test_monitoring_proc_exits', tests.occasional_tests.test_monitoring_proc_exits),
            (TestCase(), 'test_send_after_process_exited', tests.occasional_tests.test_send_after_process_exited),
            (TestCase(), 'test_send_to_wrong_address1', tests.occasional_tests.test_send_to_wrong_address1),
            (TestCase(), 'test_main_system_exit_nonzero', tests.occasional_tests.test_main_system_exit_nonzero),
            (TestCase(), 'test_main_signal', tests.occasional_tests.test_main_signal),
            (TestCase(), 'test_non_callable_main', tests.occasional_tests.test_non_callable_main),
            (TestCase(), 'test_non_callable_spawn', tests.occasional_tests.test_non_callable_spawn),
            (TestCase(), 'test_too_few_args_main', tests.occasional_tests.test_too_few_args_main),
            (TestCase(), 'test_too_many_args_main', tests.occasional_tests.test_too_many_args_main),
            (TestCase(), 'test_too_many_args_spawn', tests.occasional_tests.test_too_many_args_spawn),
            (TestCase(), 'test_error_no_monitor', tests.occasional_tests.test_error_no_monitor),
            (TestCase(), 'test_sub_process_killed', tests.occasional_tests.test_sub_process_killed),
            (TestCase(), 'test_implicit', tests.occasional_tests.test_implicit),
            (TestCase(), 'test_top_level', tests.occasional_tests.test_top_level),
            (TestCase(), 'test_spawn_monitor_exit_0_impl', tests.occasional_tests.test_spawn_monitor_exit_0_impl),
        ]),
        (TestGroup(), 'tests.sck_tests', [
            (TestCase(), 'test_trivial_sockets', tests.sck_tests.test_trivial_sockets),
            (TestCase(), 'test_socket_accept_exit', tests.sck_tests.test_socket_accept_exit),
            (TestCase(), 'test_server_trivial_connect', tests.sck_tests.test_server_trivial_connect),
            (TestCase(), 'test_client_trivial_connect', tests.sck_tests.test_client_trivial_connect),
            (TestCase(), 'test_send_two', tests.sck_tests.test_send_two),
            (TestCase(), 'test_connect_send_disconnect_repeat', tests.sck_tests.test_connect_send_disconnect_repeat),
            (TestCase(), 'test_server_close', tests.sck_tests.test_server_close),
            (TestCase(), 'test_client_close', tests.sck_tests.test_client_close),
            (TestCase(), 'test_server_send_after_disconnect', tests.sck_tests.test_server_send_after_disconnect),
            (TestCase(), 'test_client_send_after_disconnect', tests.sck_tests.test_client_send_after_disconnect),
            (TestCase(), 'test_send_malformed_netstring_from_client', tests.sck_tests.test_send_malformed_netstring_from_client),
            (TestCase(), 'test_send_malformed_netstring_from_server', tests.sck_tests.test_send_malformed_netstring_from_server),
            (TestCase(), 'test_client_sends_non_dill_message', tests.sck_tests.test_client_sends_non_dill_message),
            (TestCase(), 'test_server_sends_non_dill_message', tests.sck_tests.test_server_sends_non_dill_message),
            (TestCase(), 'test_server_sigkill_disconnect', tests.sck_tests.test_server_sigkill_disconnect),
            (TestCase(), 'test_client_sigkill_disconnect', tests.sck_tests.test_client_sigkill_disconnect),
            (TestCase(), 'test_split_message', tests.sck_tests.test_split_message),
            (TestCase(), 'test_client_sends_half_message_kill_client', tests.sck_tests.test_client_sends_half_message_kill_client),
            (TestCase(), 'test_client_sends_half_message_kill_server', tests.sck_tests.test_client_sends_half_message_kill_server),
            (TestCase(), 'test_server_sends_half_message_kill_server', tests.sck_tests.test_server_sends_half_message_kill_server),
            (TestCase(), 'test_server_sends_half_message_kill_client', tests.sck_tests.test_server_sends_half_message_kill_client),
            (TestCase(), 'test_connect_to_missing_server', tests.sck_tests.test_connect_to_missing_server),
        ]),
        (TestGroup(), 'tests.shared_port', [
            (TestCase(), 'test_socket_passing', tests.shared_port.test_socket_passing),
            (TestCase(), 'test_connect_list', tests.shared_port.test_connect_list),
            (TestCase(), 'test_connect_start_list', tests.shared_port.test_connect_start_list),
            (TestCase(), 'test_shared_port_server', tests.shared_port.test_shared_port_server),
            (TestCase(), 'test_shared_port_server_heavy', tests.shared_port.test_shared_port_server_heavy),
        ]),
        (TestGroup(), 'tests.spawn_tests', [
            (TestCase(), 'test_leave_function', tests.spawn_tests.test_leave_function),
            (TestCase(), 'test_python_exit_0', tests.spawn_tests.test_python_exit_0),
            (TestCase(), 'test_linux_exit_0', tests.spawn_tests.test_linux_exit_0),
            (TestCase(), 'test_python_exit_non_zero', tests.spawn_tests.test_python_exit_non_zero),
            (TestCase(), 'test_linux_exit_non_zero', tests.spawn_tests.test_linux_exit_non_zero),
            (TestCase(), 'test_sigterm', tests.spawn_tests.test_sigterm),
            (TestCase(), 'test_sigkill_0', tests.spawn_tests.test_sigkill_0),
            (TestCase(), 'test_exe_exit_0', tests.spawn_tests.test_exe_exit_0),
            (TestCase(), 'test_exe_exit_non_zero', tests.spawn_tests.test_exe_exit_non_zero),
            (TestCase(), 'test_exe_sigterm', tests.spawn_tests.test_exe_sigterm),
            (TestCase(), 'test_exe_sigkill', tests.spawn_tests.test_exe_sigkill),
            (TestCase(), 'test_return_from_function', tests.spawn_tests.test_return_from_function),
            (TestCase(), 'test_exit_value_function_0', tests.spawn_tests.test_exit_value_function_0),
            (TestCase(), 'test_exit_value_function_non_trivial', tests.spawn_tests.test_exit_value_function_non_trivial),
            (TestCase(), 'test_uncaught_exception', tests.spawn_tests.test_uncaught_exception),
            (TestCase(), 'test_error_function', tests.spawn_tests.test_error_function),
            (TestCase(), 'test_process_key_ret', tests.spawn_tests.test_process_key_ret),
            (TestCase(), 'test_process_key_exit_0', tests.spawn_tests.test_process_key_exit_0),
        ]),
        (TestGroup(), 'tests.test_area_server', [
            (TestCase(), 'test_area_server', tests.test_area_server.test_area_server),
        ]),
        (TestGroup(), 'tests.yeshup_tests', [
            (TestCase(), 'test_simple_yeshup', tests.yeshup_tests.test_simple_yeshup),
        ]),
    ])

if __name__ == "__main__":
    test_framework.run_main_with_args(all_tests)

